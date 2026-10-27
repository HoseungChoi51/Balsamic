"""Adequate assessment before a performance stop (roadmap V2, decisions 14 and 16).

Before an agent stops a proposal as inferior (`configuration_unpromising`, `adequately_assessed_deprioritized`), the
proposal must have been tried as the experiment rules' `assessment` asks: `min_configurations` distinct configurations
(the canonical hash of `algorithm_config`), each run to the informative horizon, with `min_seeds` seeds each when the
method or the task's evaluator is stochastic, else one run each. A run reaches the horizon when it completed
scientifically or ran at least the campaign's `short_run_seconds`, and reached `min_evaluations` when that is set.
Fewer needs the researcher's waiver of the proposal's `tuning` requirement, which an agent asks for with
`approval.request` kind waiver and `tuning_hypothesis_id`. Otherwise the honest outcome is `under_evaluated`, or
`unaffordable_within_allocation` when the campaign's remaining compute cannot cover the missing runs.
"""
from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

from .experiment_rules import check_trial_ids, current as current_rules

# Stops that conclude a proposal is worse than the others; they need an adequate assessment.
PERFORMANCE = {"configuration_unpromising", "adequately_assessed_deprioritized"}
KIND, RECIPE = "tuning", "assessment_minimums:v1"
PROTECTED_SPLITS = {"test", "heldout", "confirmation"}


def _measured(trial):
    return {**(trial.get("result") or {}), **(trial.get("progress") or {})}


def _counts(trial, probes):
    """A run of the proposal itself: not a check, a diagnostic or a locked confirmation cell, and not failed."""
    if trial.get("recipe") or trial.get("algorithm") in {"recipe", "validate"} or trial.get("diagnostic_grant_id") or trial["id"] in probes:
        return False
    if trial.get("locked") or trial.get("confirmation_protocol_id") or trial.get("split", trial.get("task_split")) in PROTECTED_SPLITS:
        return False
    return trial.get("status") not in {"failed", "cancelled", "queued"}


def reached_horizon(trial, short_run_seconds, min_evaluations=None):
    """Whether a run is informative: completed scientifically or ran at least the short-run threshold, and reached
    min_evaluations when the researcher set one."""
    measured = _measured(trial)
    complete = trial.get("status") == "completed" and bool((trial.get("result") or {}).get("scientific_complete"))
    elapsed = max(float(measured.get("elapsed_seconds") or 0), float(trial.get("execution_seconds") or 0))
    if not complete and elapsed < short_run_seconds:
        return False
    return min_evaluations is None or int(measured.get("evaluations") or 0) >= min_evaluations


def evaluator_stochastic(workspace, task):
    """Whether a task's evaluator gives another value for the same candidate: its manifest's `deterministic`, true by default."""
    if task is None:
        return False
    if task.get("evaluator_manifest"):
        return task["evaluator_manifest"].get("deterministic", True) is False
    try:
        adapter = workspace.evaluators.registry_for(task).get(((task.get("problem") or {}).get("definition_id")))
    except Exception:   # a problem this server cannot resolve declares nothing
        return False
    manifest = getattr(adapter, "manifest", None)
    manifest = manifest() if callable(manifest) else manifest
    return getattr(manifest, "deterministic", True) is False


def method_stochastic(algorithm):
    """A method's declaration (optimizers/registry.py stochastic()); an implementation package declares none, so it is."""
    from optimization_framework.optimizers.registry import stochastic
    return algorithm == "package" or not algorithm or stochastic(algorithm)


def adequacy(workspace, hypothesis, *, trials=None, rules=None, tasks=None, probes=None):
    """How the proposal was tried, against the campaign's assessment minimums.

    Returns {adequate, configurations, required_configurations, seeds_per_configuration, required_seeds, stochastic,
    short_runs, missing, words}: configurations counts those with a run at the horizon; seeds_per_configuration is the
    fewest seeds among the best-covered required configurations."""
    store, campaign_id = workspace.store, hypothesis["campaign_id"]
    rules = rules or current_rules(store, campaign_id)
    minimums = rules.get("assessment") or {}
    min_configurations, min_seeds = minimums.get("min_configurations", 3), minimums.get("min_seeds", 2)
    min_evaluations, threshold = minimums.get("min_evaluations"), rules.get("short_run_seconds") or 600
    trials = store.list("trial", campaign_id) if trials is None else trials
    tasks = {task["id"]: task for task in store.list("task", campaign_id)} if tasks is None else tasks
    probes = check_trial_ids(store, campaign_id) if probes is None else probes
    own = [trial for trial in trials if trial.get("hypothesis_id") == hypothesis["id"] and _counts(trial, probes)]
    algorithms = {trial.get("algorithm") for trial in own} or {hypothesis.get("algorithm")}
    stochastic = (any(method_stochastic(algorithm) for algorithm in algorithms)
                  or any(evaluator_stochastic(workspace, tasks.get(task_id)) for task_id in {trial.get("task_id") for trial in own}))
    needed = min_seeds if stochastic else 1
    seeds, short = {}, 0
    for trial in own:
        if not reached_horizon(trial, threshold, min_evaluations):
            short += 1
            continue
        seeds.setdefault(content_hash(trial.get("algorithm_config") or {}), set()).add(trial.get("seed", 0))
    covered = sorted((len(values) for values in seeds.values()), reverse=True)
    assessed = sum(count >= needed for count in covered)
    fewest = min(covered[:min_configurations]) if covered else 0
    missing = []
    if len(covered) < min_configurations:
        missing.append(f"{len(covered)} of {min_configurations} configurations")
    if stochastic and fewest < needed:
        missing.append(f"{fewest} of {needed} seeds")
    if short and missing:
        horizon = f"{threshold:g} s or completed" + (f", and {min_evaluations} evaluations" if min_evaluations else "")
        missing.append(f"{short} run{'s' if short != 1 else ''} short of the horizon ({horizon})")
    configurations = f"{len(covered)} of {min_configurations} configurations"
    words = f"{configurations}, {fewest} seed{'s' if fewest != 1 else ''} each" if stochastic else f"{configurations}, deterministic"
    return {"adequate": assessed >= min_configurations, "configurations": len(covered), "required_configurations": min_configurations,
            "seeds_per_configuration": fewest, "required_seeds": needed, "stochastic": stochastic, "short_runs": short,
            "missing": missing, "words": words,
            "missing_runs": sum(max(0, needed - count) for count in (covered + [0] * min_configurations)[:min_configurations]),
            "run_seconds": max([float(_measured(t).get("elapsed_seconds") or t.get("execution_seconds") or 0) for t in own] or [0]) or threshold}


def _affordable(workspace, campaign_id, state):
    """Whether the campaign's remaining compute covers the missing runs, each as long as the proposal's longest run so far."""
    limit = workspace.store.get(campaign_id, "campaign").get("compute_budget_seconds")
    if not limit:
        return True
    remaining = limit - workspace.resources.assessment(campaign_id)["allocated_seconds"]
    return state["missing_runs"] * state["run_seconds"] <= remaining


def requirement_id(hypothesis):
    return "tuning_requirement_" + hypothesis["id"]


def waived(workspace, hypothesis):
    """The researcher's active waiver of the proposal's tuning requirement, or None (decision 16)."""
    try:
        workspace.store.get(requirement_id(hypothesis), "validation_requirement")
    except KeyError:
        return None
    assessment = workspace.validations.assess(requirement_id(hypothesis))
    return next((row for row in reversed(assessment["waivers"]) if row["id"] in assessment["active_waiver_ids"]
                 and row.get("authority_kind") == "researcher"), None)


def require(workspace, hypothesis):
    """The proposal's tuning requirement, created once: what the researcher waives to accept a stop on fewer runs."""
    store, campaign_id = workspace.store, hypothesis["campaign_id"]
    try:
        return store.get(requirement_id(hypothesis), "validation_requirement")
    except KeyError:
        pass
    study_id = store.get(campaign_id, "campaign").get("active_study_id")
    if not study_id:
        raise ValueError("The campaign has no study yet; confirm its problem first")
    subject = {"id": "tuning_subject_" + hypothesis["id"], "campaign_id": campaign_id, "hypothesis_id": hypothesis["id"], "created_at": now()}
    try:
        subject = store.get(subject["id"], "assessment_subject")
    except KeyError:
        store.put_immutable("assessment_subject", subject, "assessment.subject")
    from optimization_framework.contracts.validation import ValidationRequirement
    return workspace.validations.require(ValidationRequirement(id=requirement_id(hypothesis), campaign_id=campaign_id, study_id=study_id,
        subject_id=subject["id"], subject_digest=workspace.validations.subject_digest(subject["id"]), kind=KIND, recipe_id=RECIPE,
        scope={"hypothesis_id": hypothesis["id"]},
        evidence_requirements=["The assessment minimums of the experiment rules (decision 14), or the researcher's waiver to stop on fewer runs"],
        authority="assessment_gate", created_at=now()))


def gate(workspace, hypothesis, outcome, actor):
    """None when the stop may go through; refused for an agent's performance stop on an inadequate assessment.
    Returns what the stop records about its assessment."""
    from .hypotheses import AGENT_ACTORS
    if outcome not in PERFORMANCE:
        return None
    state = adequacy(workspace, hypothesis)
    record = {key: state[key] for key in ("adequate", "configurations", "seeds_per_configuration", "stochastic", "words")}
    if state["adequate"]:
        return record
    waiver = waived(workspace, hypothesis)
    if waiver is not None:
        return {**record, "waiver_id": waiver["id"]}
    if actor not in AGENT_ACTORS:
        return record
    honest = "under_evaluated" if _affordable(workspace, hypothesis["campaign_id"], state) else "unaffordable_within_allocation"
    raise ValueError(f"A stop as {outcome} needs an adequate assessment first (decision 14): {'; '.join(state['missing'])}. "
                     f"Run the missing configurations or seeds, stop it as {honest}, or ask the researcher to waive the minimums "
                     f"with approval.request kind waiver, tuning_hypothesis_id {hypothesis['id']} and the runs as evidence_ids")
