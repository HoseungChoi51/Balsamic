"""Bounds and optimality (N13): what a method claims of its own result, and whether anything checks the claim.

A method may report ``bound`` (a value no feasible candidate can beat, in the objective's direction) and
``proved_optimal`` in ``inspect()``; the worker copies the latest to a run's progress as ``best_bound`` and
``proved_optimal``. A bound is a claim. A claim of optimality is **checked** when the built-in ``enumerate`` finished on
the same task with the same optimum (an ``enumerate`` run that finished is its own check: it saw every candidate), or
when a reference result of the charter gives the same value. It is **contradicted** when any run's best beats it, and
otherwise it is **claimed**, by the method that made it. Only a checked optimum ranks methods by the cost of reaching it.
"""
import math

from optimization_framework.contracts.problems import Objective

CHECKING_METHOD = "enumerate"


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def same(left, right):
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def beats(objective, value, bound):
    """Whether ``value`` is strictly better than ``bound`` under the objective, beyond rounding."""
    return not same(value, bound) and objective.better(value, bound)


def claim_of(diagnostics):
    """The ``bound`` and ``proved_optimal`` an inspection reports, as a progress record keeps them; {} when it reports none."""
    if not isinstance(diagnostics, dict):
        return {}
    bound, proved = number(diagnostics.get("bound")), diagnostics.get("proved_optimal") is True
    return {**({"best_bound": bound} if bound is not None else {}), **({"proved_optimal": True} if proved else {})}


def run_of(trial):
    """What the optimality summary needs of one run, from its result or its progress."""
    latest = trial.get("result") or trial.get("progress") or {}
    best = number(latest.get("best_objective"))
    proved = latest.get("proved_optimal") is True and best is not None
    bound = number(latest.get("best_bound"))
    if proved and bound is None:
        bound = best   # a proof of optimality bounds the problem at the value it proved
    return {"trial_id": trial["id"], "algorithm": trial.get("algorithm"), "hypothesis_id": trial.get("hypothesis_id"),
            "best": best, "bound": bound, "proved_optimal": proved, "method_finished": latest.get("method_finished") is True}


def summarize(runs, objective, references=()):
    """Per task: the best value, the tightest bound no run beats, the gap between them, and each claim of optimality.

    ``runs`` are ``run_of`` rows; ``references`` the values the charter's reference results give for this task.
    """
    if isinstance(objective, dict):
        objective = Objective(**objective)
    found = [run for run in runs if run["best"] is not None]
    best_run = None
    for run in found:
        if best_run is None or objective.better(run["best"], best_run["best"]):
            best_run = run
    best = best_run["best"] if best_run else None
    enumerated = [run["best"] for run in found if run["algorithm"] == CHECKING_METHOD and run["proved_optimal"] and run["method_finished"]]
    claims = []
    for run in found:
        if not run["proved_optimal"]:
            continue
        value = run["best"]
        if beats(objective, best, value):
            status, checked_by = "contradicted", None
        elif run["algorithm"] == CHECKING_METHOD and run["method_finished"]:
            status, checked_by = "checked", "enumerate"
        elif any(same(value, other) for other in enumerated):
            status, checked_by = "checked", "enumerate"
        elif any(same(value, reference) for reference in references):
            status, checked_by = "checked", "reference"
        else:
            status, checked_by = "claimed", None
        claims.append({"trial_id": run["trial_id"], "algorithm": run["algorithm"], "hypothesis_id": run["hypothesis_id"], "value": value,
                       "status": status, **({"checked_by": checked_by} if checked_by else {}),
                       **({"contradicted_by": best_run["trial_id"]} if status == "contradicted" else {})})
    # The tightest bound that nothing found beats: the largest lower bound when minimizing, the smallest upper bound when maximizing.
    bounds = [run for run in found if run["bound"] is not None and not beats(objective, best, run["bound"])]
    bound_run = None
    for run in bounds:
        if bound_run is None or objective.better(bound_run["bound"], run["bound"]):
            bound_run = run
    bound = bound_run["bound"] if bound_run else None
    gap = None if bound is None or best is None else max(0., objective.utility(bound) - objective.utility(best))
    checked = next((claim for claim in claims if claim["status"] == "checked"), None)
    standing = next((claim for claim in claims if claim["status"] == "claimed"), None)
    optimum = None
    if checked or standing:
        claim = checked or standing
        optimum = {"value": claim["value"], "status": claim["status"],
                   "claimed_by": sorted({c["algorithm"] for c in claims if c["status"] in {"checked", "claimed"} and same(c["value"], claim["value"])}),
                   **({"checked_by": claim["checked_by"]} if checked else {})}
    return {"direction": objective.direction, "best_value": best, "best_trial_id": best_run["trial_id"] if best_run else None,
            "best_bound": bound, "bound_trial_id": bound_run["trial_id"] if bound_run else None,
            "bound_algorithm": bound_run["algorithm"] if bound_run else None, "gap": gap,
            "relative_gap": None if gap is None or not bound else gap / abs(bound),
            "optimum": optimum, "claims": claims}


def charter_references(workspace, campaign_id, tasks):
    """{task_id: [values]}: the reference results of the campaign's confirmed charter that hold at each task's instance."""
    from optimization_framework.problem_charter import charter as mechanics
    out = {}
    for record in workspace.store.list("problem_charter"):
        if campaign_id not in record.get("campaign_ids", []) or not record.get("confirmed_revision"):
            continue
        document = record["charter"] if record.get("revision") == record["confirmed_revision"] else \
            workspace.store.get(f"{record['id']}_r{record['confirmed_revision']}", "problem_charter_revision")["charter"]
        try:
            charter = mechanics.parse(document)
        except ValueError:
            continue
        if not any(number(reference.value) is not None for reference in charter.references):
            continue
        instances = {instance.name: instance for instance in charter.instances}
        for task in tasks.values() if isinstance(tasks, dict) else tasks:
            instance = instances.get(task.get("name"))
            if instance is None:
                continue
            values = mechanics.resolve(charter, instance.values)["values"] if instance.values else mechanics.resolve(charter)["values"]
            out.setdefault(task["id"], []).extend(float(reference.value) for reference in charter.references
                                                  if number(reference.value) is not None and mechanics.applies(reference, values))
    return out


def by_task(workspace, campaign_id):
    """The optimality summary of every task of a campaign that has runs, in task order."""
    tasks = {task["id"]: task for task in workspace.store.list("task", campaign_id)}
    runs = {}
    for trial in workspace.store.list("trial", campaign_id):
        if trial.get("task_id") in tasks and not trial.get("recipe") and trial.get("problem"):
            runs.setdefault(trial["task_id"], []).append(run_of(trial))
    references = charter_references(workspace, campaign_id, tasks) if runs else {}
    out = []
    for task_id, task in tasks.items():
        if task_id not in runs:
            continue
        objective = (task.get("problem") or {}).get("primary_objective")
        if not objective:
            continue
        out.append({"task_id": task_id, "task_name": task.get("name"), **summarize(runs[task_id], objective, references.get(task_id, ()))})
    return out
