"""Raw objectives at observed, fully attributed costs on compatible problems."""
from collections import defaultdict
import math
import statistics

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.evaluation import sizes


AXES = {"worker_seconds": "elapsed_seconds", "core_seconds": "elapsed_seconds", "evaluation_requests": "evaluations",
        "solver_executions": "solver_calls"}
# Time axes: a run with unknown worker cost has no cost on them.
TIME = {"worker_seconds", "core_seconds"}


def threads(trial):
    return trial.get("numerical_threads", 1) or 1


def default_axis(trials, tasks):
    """The compared problems' own axis (N11): the one their tasks declare; problems that declare different ones are
    compared on worker-seconds. Declaring none, time: on cores when a white-box run used several threads (decision 23)."""
    from optimization_framework.evaluation.access import REPORT_AXES, of_task
    declared = [of_task(tasks.get(trial.get("task_id")) or {}) for trial in trials]
    axes = {row["cost_axis"] for row in declared}
    if axes - {None}:
        return REPORT_AXES[axes.pop()] if len(axes) == 1 else "worker_seconds"
    threaded = any(row["access"] == "white_box" and threads(trial) > 1 for row, trial in zip(declared, trials))
    return "core_seconds" if threaded else "worker_seconds"


def method_identity(trial):
    procedure = trial.get("experiment_spec", {})
    parameters = procedure.get("parameters") or {key: trial.get(key, {}) for key in ("algorithm", "algorithm_config", "training")}
    training = {key: value for key, value in parameters.get("training", {}).items() if key != "seed"}
    identity = {"algorithm": trial["algorithm"], "parameters": parameters.get("algorithm_config", {}),
        "training": training if trial["algorithm"] == "dqn" else {}, "schedule": procedure.get("schedule", {"steps": trial["schedule_steps"]}),
        "implementation": trial.get("implementation_version_id") or trial.get("scientific_source_hash") or "unknown:" + trial["id"],
        "runtime": trial.get("implementation_runtime_digest") or trial.get("scientific_environment"),
        "initial_assets": procedure.get("initial_assets", trial.get("initial_assets", [])),
        "asset_digests": procedure.get("asset_digests", {})}
    return content_hash(identity), identity


def number(value):
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def observed_at(curve, budget, *, held=False):
    """The best objective a curve had reached at a cost; past its end only when held (a method that finished keeps its value)."""
    if not curve or budget < curve[0]["cost"] or (budget > curve[-1]["cost"] and not held):
        return None
    return next(point["objective"] for point in reversed(curve) if point["cost"] <= budget)


def thin(curve):
    """The same curve without the inside of each run of equal objectives.

    A best-so-far journal has one row per evaluation and changes at a few of them. Both ends
    of every run stay, so the curve reads and draws as before; a 60,000-evaluation experiment
    gives a few hundred points instead of 60,000.
    """
    last = len(curve) - 1
    return [point for index, point in enumerate(curve) if index in (0, last)
            or point["objective"] != curve[index - 1]["objective"] or point["objective"] != curve[index + 1]["objective"]]


def rank(summaries, objective):
    """Number method summaries by mean under the objective's direction: 1 is best, ties share a rank, no mean no rank."""
    ordered = sorted((s for s in summaries if s["mean"] is not None), key=lambda s: objective.utility(s["mean"]), reverse=True)
    for index, summary in enumerate(ordered):
        tied = index and summary["mean"] == ordered[index - 1]["mean"]
        summary["rank"] = ordered[index - 1]["rank"] if tied else index + 1
    for summary in summaries:
        summary.setdefault("rank", None)
    return summaries


def ladder_method(trial):
    """A method on a size ladder: its identity without its schedule, since the budget may grow with the size."""
    return content_hash({key: value for key, value in trial["method"].items() if key != "schedule"})


def size_ladders(groups):
    """How methods scale with instance size (N14), from the observed runs only.

    Groups that differ only in their instance and share a size name form a ladder. A method that finished on its own at
    some size is one that finishes (an exact method): at a size it finished when every run of it there did. A method
    that never did is anytime: it finished when its runs reached their budget, uncensored. At each size the leader is
    the method whose mean at the group's matched cost is better (a method with no value there does not lead; groups at
    the same size that disagree name no leader). A crossover is a size whose leader differs from the last one before it.
    """
    ladders = defaultdict(list)
    for group in groups:
        if group.get("size") is not None:
            condition = {key: value for key, value in group["condition"].items() if key != "evaluation_identity"}
            ladders[content_hash([condition, group["size"]["name"]])].append(group)
    out = []
    for members in ladders.values():
        values = sorted({group["size"]["value"] for group in members})
        if len(values) < 2:
            continue
        objective = ProblemInstance(**members[0]["problem"]).primary_objective
        methods = {}   # ladder method -> {size: [runs]}
        names = {}
        for group in members:
            for trial in group["trials"]:
                key = ladder_method(trial)
                names.setdefault(key, trial["algorithm"])
                methods.setdefault(key, defaultdict(list))[group["size"]["value"]].append(trial)
        finishing = {key for key, by_size in methods.items() if any(t["method_finished"] for runs in by_size.values() for t in runs)}

        def finished(key, value):
            runs = methods[key].get(value) or []
            return bool(runs) and all(t["method_finished"] if key in finishing else t["scientific_complete"] for t in runs)

        means = {}   # (ladder method, group id) -> mean at the group's matched cost
        for group in members:
            ids = {trial["method_id"]: ladder_method(trial) for trial in group["trials"]}
            for summary in group.get("method_summaries", []):
                means[(ids[summary["method_id"]], group["id"])] = summary["mean"]

        def leader(a, b, value):
            leaders = set()
            for group in (group for group in members if group["size"]["value"] == value):
                left, right = means.get((a, group["id"])), means.get((b, group["id"]))
                if left is None and right is None or left is not None and right is not None and left == right:
                    leaders.add(None)
                elif right is None or left is not None and objective.better(left, right):
                    leaders.add(a)
                else:
                    leaders.add(b)
            return leaders.pop() if len(leaders) == 1 else None

        rows = [{"method": key, "algorithm": names[key], "kind": "finishes" if key in finishing else "anytime",
                 "sizes": [{"size": value, "runs": len(methods[key].get(value) or []), "finished": finished(key, value)}
                           for value in values if methods[key].get(value)],
                 "largest_finished_size": max((value for value in values if finished(key, value)), default=None)}
                for key in methods]
        largest = {row["method"]: row["largest_finished_size"] for row in rows}
        pairs = []
        keys = sorted(methods, key=lambda key: (names[key], key))
        for index, a in enumerate(keys):
            for b in keys[index + 1:]:
                shared = [value for value in values if methods[a].get(value) and methods[b].get(value)]
                if len(shared) < 2:
                    continue
                leaders = [{"size": value, "leader": leader(a, b, value)} for value in shared]
                crossovers, last = [], None
                for row in leaders:
                    if row["leader"] is None:
                        continue
                    if last is not None and row["leader"] != last:
                        crossovers.append({"size": row["size"], "from": last, "to": row["leader"]})
                    last = row["leader"]
                pairs.append({"methods": [a, b], "algorithms": [names[a], names[b]], "leaders": leaders,
                              "largest_finished_size": {a: largest[a], b: largest[b]},
                              "crossover": crossovers[0] if crossovers else None, "crossovers": crossovers})
        out.append({"size": members[0]["size"]["name"], "sizes": values, "direction": objective.direction,
                    "group_ids": [group["id"] for group in sorted(members, key=lambda group: group["size"]["value"])],
                    "methods": rows, "pairs": pairs})
    return out


def rank_by_optimum(summaries, objective):
    """With a checked optimum (N13): the methods whose every run reached it first, by their mean cost to reach it, then
    the others by mean as ``rank`` numbers them. Ties share a rank."""
    reached = sorted((s for s in summaries if s.get("cost_to_optimum") is not None), key=lambda s: s["cost_to_optimum"])
    for index, summary in enumerate(reached):
        tied = index and summary["cost_to_optimum"] == reached[index - 1]["cost_to_optimum"]
        summary["rank"] = reached[index - 1]["rank"] if tied else index + 1
    rest = rank([dict(s, rank=None) for s in summaries if s.get("cost_to_optimum") is None], objective)
    for summary, ranked in zip((s for s in summaries if s.get("cost_to_optimum") is None), rest):
        summary["rank"] = None if ranked["rank"] is None else ranked["rank"] + len(reached)
    return summaries


def report(workspace, campaign_id, *, study_id=None, cost_axis=None, cost_view="full_attributed_cost", trial_ids=None, withheld=frozenset()):
    """Compare a study's experiments, or only those named in trial_ids, at the costs they were observed.

    A run that was continued (trial.continue) is one run: its last experiment stands for it, with the
    earlier ones' curves in front and their costs added. Methods are compared at the largest cost every
    compared run reached, so a comparison of long runs names them: one short run in the same study
    would otherwise set that cost. A run whose method finished on its own does not set that cost: it holds
    its final value after its last point (held_after_finish), unless every compared run finished.
    Each group names its objective's direction, and each method summary its rank by mean under it.
    Only feasible results count (N10): a run's best is its best observation that meets the problem's outcome constraints,
    and each run, method summary and group counts the infeasible observations it left out.
    Each group also has its ``optimality`` (N13): the best value, the tightest bound no run beats, the gap, and each run's
    claim of optimality as checked, claimed or contradicted. With a checked optimum the methods that reached it rank
    first, by their mean cost to reach it (``cost_to_optimum``).
    withheld: a locked confirmation's trials, left out (and only counted) when an agent asks; naming one is refused.
    """
    if cost_view not in {"full_attributed_cost", "actual_expenditure"}:
        raise ValueError("Choose full_attributed_cost or actual_expenditure")
    campaign = workspace.store.get(campaign_id, "campaign")
    study_id = study_id or campaign.get("active_study_id")
    study = workspace.store.get(study_id, "study") if study_id else None
    if study and study["campaign_id"] != campaign_id:
        raise ValueError("Study belongs to another campaign")
    chosen_axis = cost_axis or (study or {}).get("comparison", {}).get("cost_axis")
    # worker-seconds is what every study has said by default; the problem's own axis replaces it (N11).
    chosen_axis = None if chosen_axis in {"worker_seconds", "full_worker_seconds"} and not cost_axis else chosen_axis
    chosen_axis = "worker_seconds" if chosen_axis == "full_worker_seconds" else chosen_axis
    if chosen_axis is not None and chosen_axis not in AXES:
        raise ValueError("Comparison supports worker_seconds, core_seconds, evaluation_requests, or solver_executions")
    # Capture output asset references together with their ledger: a trial cannot
    # advance to an asset newer than this report's cost snapshot. Release the
    # database before reading metrics or calculating any projection.
    with workspace.store.connection() as db:
        if not db.in_transaction:
            db.execute("BEGIN")
        trials = workspace.store.list("trial", campaign_id)
        tasks = {item["id"]: item for item in workspace.store.list("task", campaign_id)}
        hypotheses = {item["id"]: item for item in workspace.store.list("hypothesis", campaign_id)}
        amendments = {item["experiment_id"] for item in workspace.store.list("budget_amendment", campaign_id)}
        # Runtime-profile probes and equivalence replays measure the evaluator; they are no method's result.
        measurements = {identity for profile in workspace.store.list("runtime_profile", campaign_id)
                        for level in profile.get("levels", []) for identity in level.get("trial_ids", [])}
        measurements.update(item["replay_trial_id"] for item in workspace.store.list("evaluator_equivalence", campaign_id) if item.get("replay_trial_id"))
        costs = workspace.assets.cost_view()
    by_id = {trial["id"]: trial for trial in trials}
    chosen = None if trial_ids is None else set(trial_ids)
    if chosen is not None and chosen - set(by_id):
        raise ValueError("Not experiments of this campaign: " + ", ".join(sorted(chosen - set(by_id))))
    if chosen is not None and chosen & withheld:
        raise ValueError("A confirmation's runs are withheld until the confirmation is released; leave them out of trial_ids")
    groups = {}
    excluded = []
    compared = []
    for trial in trials:
        if chosen is not None and trial["id"] not in chosen:
            continue
        if trial["id"] in withheld:
            continue
        if study_id and trial.get("study_id") != study_id:
            if chosen is not None:
                excluded.append({"trial_id": trial["id"], "reason": "The experiment belongs to another study"})
            continue
        if trial["id"] in measurements:
            excluded.append({"trial_id": trial["id"], "reason": "A measurement of the evaluator (runtime profile or equivalence replay), not an optimization experiment"})
            continue
        if trial.get("recipe") or trial.get("algorithm") == "validate" or trial.get("diagnostic_grant_id"):
            excluded.append({"trial_id": trial["id"], "reason": "Scientific diagnostics are separate evidence"})
            continue
        if not trial.get("problem"):
            excluded.append({"trial_id": trial["id"], "reason": "Historical experiment needs an explicit problem mapping"})
            continue
        compared.append(trial)
    cost_axis = chosen_axis or default_axis(compared, tasks)
    # Upstream work (implementation, evaluator development) runs on one core: on core_seconds it counts its worker-seconds.
    upstream_axis = "worker_seconds" if cost_axis == "core_seconds" else cost_axis
    continued = {trial["continues"]["trial_id"]: trial["id"] for trial in compared if trial.get("continues")}
    for trial in compared:
        if trial["id"] in continued:
            excluded.append({"trial_id": trial["id"], "reason": f"Continued by {continued[trial['id']]}; reported as the beginning of that run"})
            continue
        chain = [trial]
        while (previous := (chain[0].get("continues") or {}).get("trial_id")) in by_id and by_id[previous] not in chain:
            chain.insert(0, by_id[previous])
        root = chain[0]
        problem = ProblemInstance(**trial["problem"])
        condition = {"study_id": trial.get("study_id"), "evaluation_identity": problem.evaluation_identity,
            "primary_objective": problem.primary_objective.model_dump(mode="json"),
            "confirmation_protocol_id": trial.get("confirmation_protocol_id")}
        if problem.outcomes:
            # Runs held to other conditions on their outcome count other results as their best (N10).
            condition["outcomes"] = [constraint.model_dump(mode="json") for constraint in problem.outcomes]
        if cost_axis in TIME and trial.get("device"):
            # A worker-second on the GPU buys other evaluations than one on CPU: on time, each device is its own comparison.
            condition["device"] = trial["device"]
        if cost_axis == "worker_seconds" and threads(trial) != 1:
            # A worker-second on several threads buys more than one on a single thread; core-seconds puts them together.
            condition["worker_threads"] = threads(trial)
        group_id = content_hash(condition)
        size = sizes.of_task(tasks.get(trial.get("task_id")))
        group = groups.setdefault(group_id, {"id": group_id, "condition": condition, "problem": problem.model_dump(mode="json"),
                                             **({"size": size} if size else {}), "trials": []})
        latest = trial.get("result") or trial.get("progress") or {}
        # The run's method is the one it began as: a later part differs only in the source it was carried on under.
        identity, definition = method_identity(root)
        upstream = costs.attributed_costs(root.get("initial_assets", []) + root.get("contribution_asset_ids", root.get("implementation_cost_asset_ids", [])) + root.get("operational_cost_asset_ids", []), axes=[upstream_axis])
        if root["algorithm"] == "package" and not root.get("implementation_cost_asset_ids"):
            upstream["quantities"][upstream_axis].update(total=None, unknown_provenance=1)
            upstream["reason"] = "Implementation development cost has not been declared"
        upstream_cost = upstream["quantities"][upstream_axis]["total"]
        points = {}
        unknown = False
        before = 0.   # what the earlier experiments of the run spent on this axis; None once one of them is unknown
        for member in chain:
            last = member.get("result") or member.get("progress") or {}
            rows = [*workspace.metrics(member["id"], fields=("best_objective", "elapsed_seconds", "evaluations", "solver_calls",
                "unknown_worker_cost", "unknown_solver_cost")), last]
            for row in rows:
                objective = number(row.get("best_objective"))
                direct = number(row.get(AXES[cost_axis]))
                if cost_axis == "core_seconds" and direct is not None:
                    direct *= threads(member)
                if cost_axis == "solver_executions" and row.get("unknown_solver_cost"):
                    direct = None
                if cost_axis in TIME and row.get("unknown_worker_cost"):
                    direct = None
                if objective is None:
                    continue
                direct = None if direct is None or before is None else direct + before
                cost = direct if cost_view == "actual_expenditure" else None if direct is None or upstream_cost is None else direct + upstream_cost
                if cost is None:
                    unknown = True
                    continue
                previous = points.get(cost)
                if previous is None or problem.primary_objective.better(objective, previous["objective"]):
                    points[cost] = {"cost": cost, "objective": objective, "direct_cost": direct,
                                    "upstream_cost": upstream_cost if cost_view == "full_attributed_cost" else 0.}
            if member is not trial:
                spent = number(last.get(AXES[cost_axis]))
                if cost_axis == "core_seconds" and spent is not None:
                    spent *= threads(member)
                if (cost_axis == "solver_executions" and last.get("unknown_solver_cost")) or (cost_axis in TIME and last.get("unknown_worker_cost")):
                    spent = None
                before = None if before is None or spent is None else before + spent
        assets = trial.get("latest_output_asset_ids", [])
        full = costs.attributed_costs(assets, axes=[cost_axis]) if assets else None
        # A measured final asset cost includes final checkpoint/export overhead.
        # No curve extrapolation is made: only its actually observed endpoint is added. On core-seconds the asset's cost
        # mixes the run's cores with upstream single-core work, so its endpoint is not added.
        final_cost = full["quantities"][cost_axis]["total"] if full and cost_view == "full_attributed_cost" and cost_axis != "core_seconds" else None
        if final_cost is not None and len(chain) > 1:
            final_cost = None if before is None else final_cost + before
        best = number(latest.get("best_objective"))
        if final_cost is not None and best is not None:
            points[final_cost] = {"cost": final_cost, "objective": best, "upstream_cost": upstream_cost,
                                  "direct_cost": None if upstream_cost is None else max(0., final_cost - upstream_cost)}
        scientific_complete = bool(latest.get("scientific_complete"))
        method_finished = bool(latest.get("method_finished"))
        from .finalists import prototype_details
        details = prototype_details(trial, study, tasks.get(trial.get("task_id")), hypotheses.get(trial.get("hypothesis_id")))
        group["trials"].append({"id": trial["id"], "task_id": trial.get("task_id"), "seed": trial["seed"], "method_id": identity, "method": definition,
            **details,
            **({"chain_trial_ids": [member["id"] for member in chain]} if len(chain) > 1 else {}),
            "algorithm": trial["algorithm"], "status": trial["status"], "best_objective": best,
            # Its best is its best feasible result; these were measured but broke a constraint on the outcome (N10).
            "infeasible_observations": sum(int((member.get("result") or member.get("progress") or {}).get("infeasible_observations") or 0)
                                           for member in chain),
            "scientific_complete": scientific_complete, "process_exit": latest.get("process_exit"),
            "allocation_stop": latest.get("allocation_stop"), "censored": not scientific_complete,
            "method_finished": method_finished, "held_after_finish": method_finished,
            "best_bound": number(latest.get("best_bound")), "proved_optimal": latest.get("proved_optimal") is True,
            "adaptive_extension": any(member["id"] in amendments for member in chain),
            "unknown_cost": unknown or upstream_cost is None, "upstream": upstream, "full_cost": full,
            "curve": thin([points[key] for key in sorted(points)])})
    from .optimality import charter_references, same, summarize
    proved = any(trial["proved_optimal"] for group in groups.values() for trial in group["trials"])
    references = charter_references(workspace, campaign_id, tasks) if proved else {}
    for group in groups.values():
        usable = [trial for trial in group["trials"] if trial["curve"]]
        # A finished method has no more points to give; the runs still going set the matched cost.
        open_ended = [trial for trial in usable if not trial["method_finished"]] or usable
        horizon = min((trial["curve"][-1]["cost"] for trial in open_ended), default=None)
        start = max((trial["curve"][0]["cost"] for trial in usable), default=None)
        if horizon is not None and start > horizon:
            horizon = None
        methods = defaultdict(list)
        for trial in group["trials"]:
            value = observed_at(trial["curve"], horizon, held=trial["method_finished"]) if horizon is not None else None
            methods[trial["method_id"]].append((trial, value))
        summaries = []
        for method_id, rows in methods.items():
            values = [value for _, value in rows if value is not None]
            seeds = [trial["seed"] for trial, value in rows if value is not None]
            summaries.append({"method_id": method_id, "algorithm": rows[0][0]["algorithm"], "trial_count": len(rows),
                "observed_count": len(values), "mean": statistics.mean(values) if values else None,
                "infeasible_observations": sum(trial["infeasible_observations"] for trial, _ in rows),
                "median": statistics.median(values) if values else None, "matched_cost": horizon,
                "independent_seed_ids": len(set(seeds)) == len(seeds), "uncertainty": "Not estimated by this descriptive report"})
        objective = ProblemInstance(**group["problem"]).primary_objective
        group["direction"] = objective.direction
        runs = [{"trial_id": trial["id"], "algorithm": trial["algorithm"], "hypothesis_id": trial.get("hypothesis_id"),
                 "best": trial["best_objective"], "proved_optimal": trial["proved_optimal"] and trial["best_objective"] is not None,
                 "bound": trial["best_bound"] if trial["best_bound"] is not None or not trial["proved_optimal"] else trial["best_objective"],
                 "method_finished": trial["method_finished"]} for trial in group["trials"]]
        group["optimality"] = summarize(runs, objective, [value for task_id in {trial["task_id"] for trial in group["trials"]}
                                                          for value in references.get(task_id, ())])
        optimum = group["optimality"]["optimum"]
        if optimum and optimum["status"] == "checked":
            for trial in group["trials"]:
                trial["optimum_reached_at"] = next((point["cost"] for point in trial["curve"] if same(point["objective"], optimum["value"])
                                                    or objective.better(point["objective"], optimum["value"])), None)
            for summary in summaries:
                reach = [trial["optimum_reached_at"] for trial, _ in methods[summary["method_id"]]]
                summary["optimum_reached"] = sum(cost is not None for cost in reach)
                summary["cost_to_optimum"] = statistics.mean(reach) if reach and None not in reach else None
            rank_by_optimum(summaries, objective)
        else:
            rank(summaries, objective)
        group["method_summaries"] = summaries
        group["common_observed_cost"] = horizon
        group["infeasible_observations"] = sum(trial["infeasible_observations"] for trial in group["trials"])
    ladders = size_ladders(list(groups.values()))
    return {"schema_version": 1, "campaign_id": campaign_id, "study_id": study_id, "cost_view": cost_view,
            "cost_axis": cost_axis, "groups": list(groups.values()), "excluded": excluded,
            **({"size_ladders": ladders} if ladders else {}),
            **({"withheld_runs": sum(trial["id"] in withheld for trial in trials if not study_id or trial.get("study_id") == study_id)} if withheld else {}),
            "actual_campaign_costs": costs.actual_costs(campaign_id,
                axes=("worker_seconds", "core_seconds", "evaluation_requests", "solver_executions", "implementation_seconds", "model_seconds", "model_calls", "model_input_tokens", "model_output_tokens", "api_usd")),
            "interpretation": "Raw objectives on compatible instances and fidelities at observed costs; no extrapolation or cross-problem ranking."
                + (" On worker-seconds, runs on the GPU and on CPU are compared separately (condition.device); compare on evaluation_requests "
                   "to put them together." if len({group["condition"].get("device") for group in groups.values()} - {None}) > 1 else ""),
            "claim_level": "descriptive", "confirmation_protocol": (study or {}).get("confirmation") or None}
