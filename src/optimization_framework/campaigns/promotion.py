"""The fidelity gate on promotion (roadmap V3, decisions 15 and 16).

A problem declares the checks a score must pass before it counts for promotion (`ProblemDefinition.promotion_validation`).
Choosing a finalist (`hypothesis.nominate`, `hypothesis.status` finalist, `finalist.set`) and `library.publish` read the
state of those checks on the proposal's best run: `passed`, `waived` (by the researcher), `failed`, `not_checked`, or
`not_required` when the problem declares none. Agents need passed, waived or not required; the researcher's own choice of
a finalist passes with a recorded warning; a library entry needs passed, not required, or the researcher's waiver.
"""
import json

from optimization_framework.evaluation.policy import ValidationService
from optimization_framework.storage.sqlite import now

# Worst first: the state of several checks is the worst of theirs.
RANK = ("failed", "not_checked", "waived", "passed")
OPEN = {"passed", "waived", "not_required"}
PROTECTED_SPLITS = {"test", "heldout", "confirmation"}


def score_of(trial):
    for source in (trial.get("result") or {}, trial.get("progress") or {}):
        for key in ("best_objective", "best_efficiency", "best_score"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _direction(trial):
    """As the ledger ranks it (A2): the result's objective, else the problem's; records that say none were maximized."""
    sources = [((trial.get(key) or {}).get("objective_definition") or {}) for key in ("result", "progress")]
    sources.append((trial.get("problem") or {}).get("primary_objective") or {})
    return next((source["direction"] for source in sources if source.get("direction") in {"minimize", "maximize"}), "maximize")


def best_trial(store, hypothesis):
    """The proposal's best measured development run, by its objective's direction; diagnostics and locked cells never count."""
    best, best_utility = None, None
    for trial in store.list("trial", hypothesis["campaign_id"]):
        if trial.get("hypothesis_id") != hypothesis["id"] or trial.get("recipe") or trial.get("algorithm") in {"recipe", "validate"}:
            continue
        if trial.get("locked") or trial.get("confirmation_protocol_id") or trial.get("split", trial.get("task_split")) in PROTECTED_SPLITS:
            continue
        value = score_of(trial)
        if value is None:
            continue
        utility = value if _direction(trial) == "maximize" else -value
        if best_utility is None or utility > best_utility:
            best, best_utility = trial, utility
    return best


def declared(workspace, campaign_id, trial=None):
    """The promotion checks of the problem a run used, or of every current task of the campaign when there is no run."""
    store = workspace.store
    tasks = [store.get(trial["task_id"], "task")] if trial is not None else [t for t in store.list("task", campaign_id) if not t.get("archived")]
    checks = []
    for task in tasks:
        definition = workspace.evaluators.describe_task(workspace.evaluators.task_view(task))
        for check in definition.promotion_validation:
            value = check.model_dump(mode="json", exclude={"schema_version"})
            if value not in checks:
                checks.append(value)
    return checks


def _check_state(workspace, trial, check):
    store = workspace.store
    validations = ValidationService(store)
    result = trial.get("result") or trial.get("progress") or {}
    best_candidate = result.get("best_candidate", result.get("best_design"))
    latest = None
    for requirement in store.list("validation_requirement", trial["campaign_id"]):
        scope = requirement.get("scope") or {}
        if scope.get("parent_trial_id") != trial["id"] or requirement["recipe_id"] != check["recipe_id"]:
            continue
        parameters = scope.get("parameters") or {}
        if any(parameters.get(key) != value for key, value in check["parameters"].items()):
            continue
        if best_candidate is not None:
            try:
                subject = store.get(requirement["subject_id"])
            except KeyError:
                continue
            if (subject.get("payload") or {}).get("candidate") != best_candidate:
                continue
        elif scope.get("subject_index", 0) != 0:
            continue
        assessment = validations.assess(requirement["id"])
        waivers = [row for row in assessment["waivers"] if row["id"] in assessment["active_waiver_ids"]
                   and row.get("authority_kind") == "researcher"]
        results = assessment["results"]
        verdict = results[-1]["verdict"] if results else None
        if assessment["status"] == "passed":
            state = "passed"
        elif assessment["status"] != "stale" and waivers:
            state = "waived"   # only the researcher's waiver counts (decision 16)
        elif assessment["status"] != "stale" and verdict in {"failed", "error"}:
            state = "failed"
        else:
            state = "not_checked"
        records = [row["id"] for row in [*results, *assessment["waivers"]]]
        position = max([store.record_position(identity) for identity in records] or [0])
        if latest is None or position >= latest[0]:
            latest = (position, {"recipe_id": check["recipe_id"], "parameters": check["parameters"], "state": state,
                                 "requirement_id": requirement["id"], "validation_result_id": results[-1]["id"] if results else None,
                                 "waiver_id": waivers[-1]["id"] if waivers else None})
    return latest[1] if latest else {"recipe_id": check["recipe_id"], "parameters": check["parameters"], "state": "not_checked",
                                     "requirement_id": None, "validation_result_id": None, "waiver_id": None}


def trial_state(workspace, trial, checks=None):
    """The fidelity state of one run's best score."""
    checks = declared(workspace, trial["campaign_id"], trial) if checks is None else checks
    if not checks:
        return {"state": "not_required", "trial_id": trial["id"], "score": score_of(trial), "checks": []}
    rows = [_check_state(workspace, trial, check) for check in checks]
    state = min((row["state"] for row in rows), key=RANK.index)
    return {"state": state, "trial_id": trial["id"], "score": score_of(trial), "checks": rows}


def fidelity_state(workspace, hypothesis):
    """The fidelity state of the proposal's best score."""
    trial = best_trial(workspace.store, hypothesis)
    if trial is None:
        checks = declared(workspace, hypothesis["campaign_id"])
        return {"state": "not_checked" if checks else "not_required", "trial_id": None, "score": None,
                "checks": [{"recipe_id": c["recipe_id"], "parameters": c["parameters"], "state": "not_checked", "requirement_id": None,
                            "validation_result_id": None, "waiver_id": None} for c in checks]}
    return trial_state(workspace, trial)


def explain(state, *, agent=True):
    """Why the gate is closed and what opens it, in words an agent (or the researcher) can act on."""
    if state["trial_id"] is None:
        names = ", ".join(check["recipe_id"] for check in state["checks"])
        return f"The proposal has no measured run whose score could be checked ({names}). Run it first."
    parts = []
    for check in state["checks"]:
        if check["state"] in OPEN:
            continue
        run = json.dumps({"trial_id": state["trial_id"], "recipe_id": check["recipe_id"], "parameters": check["parameters"]})
        if check["state"] == "failed":
            parts.append(f"{check['recipe_id']} failed on run {state['trial_id']} (validation result {check['validation_result_id']}): "
                         "its score does not hold at higher fidelity.")
        else:
            parts.append(f"{check['recipe_id']} has not been checked on run {state['trial_id']}, the best score ({state['score']}). "
                         f"Run it with validation.run {run}.")
        parts.append("Only the researcher may waive it: an agent creates the requirement with validation.require "
                     f"{run} and asks with approval.request kind waiver and that requirement_id." if agent else
                     "To accept the score without it, waive that requirement (validation.require, then validation.waive).")
    return " ".join(parts)


def record(state):
    """The fidelity state as a promotion or a library entry records it, with the result or waiver each check rests on."""
    return {"state": state["state"], "trial_id": state["trial_id"], "score": state["score"],
            "checks": [{key: check[key] for key in ("recipe_id", "state", "requirement_id", "validation_result_id", "waiver_id")}
                       for check in state["checks"]]}


def summary(state, *, actor, warning=None):
    """What a promotion records about the check it passed through."""
    return {**record(state), "warning": warning, "by": actor, "at": now()}


def gate(state, actor, *, action):
    """None when the gate is open; the warning text when the researcher goes through a closed gate; refused for an agent."""
    if state["state"] in OPEN:
        return None
    text = explain(state)
    if actor != "researcher":
        raise ValueError(f"{action} needs the problem's fidelity check on the best score first. {text}")
    return f"Promoted by the researcher with the fidelity check {state['state'].replace('_', ' ')}. {text}"


def promotion_recipe(workspace, requirement):
    """Whether a validation requirement is one of its problem's promotion checks (only the researcher waives those)."""
    try:
        trial = workspace.store.get((requirement.get("scope") or {}).get("parent_trial_id"), "trial")
    except (KeyError, TypeError):
        return False
    return any(check["recipe_id"] == requirement["recipe_id"] for check in declared(workspace, trial["campaign_id"], trial))
