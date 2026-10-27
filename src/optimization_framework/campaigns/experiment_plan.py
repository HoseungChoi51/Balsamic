"""What an experiment plan costs and records, computed from the campaign's records, never written by an agent.

For each planned run: the design it searches, the speed and the disk use per output file measured on the nearest earlier
run of the same problem (same method and device first), the evaluations its wall time allows, and what ends it. A go-ahead
request for experiments carries its runs (approval.request kind compute, runs), and a draft is one run; the researcher reads
the plan before anything starts. What was not measured is said, never guessed.
"""
import os

JOURNALS = {"observations.jsonl": "every evaluated design with its scores", "requests.jsonl": "every proposed design",
            "metrics.jsonl": "progress after each evaluation", "costs.jsonl": "the cost of each evaluation"}
MIN_EVALUATIONS = 20              # a shorter earlier run measures too little to scale from
GOOD_EVALUATIONS = 200            # one this long is preferred
LARGE_RUN_BYTES = 2 * 1024 ** 3   # a run writing more than this is called out


def _evaluations(trial):
    return int(((trial.get("result") or {}).get("evaluations")) or ((trial.get("progress") or {}).get("evaluations")) or 0)


def _elapsed(trial):
    return float(((trial.get("result") or {}).get("elapsed_seconds")) or ((trial.get("progress") or {}).get("elapsed_seconds")) or 0)


def _method(trial):
    return trial.get("implementation_version_id") or trial.get("algorithm") or ""


def _size(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def reference(workspace, campaign_id, task_id, method, device):
    """The earlier run measurements come from: same problem, then the same method, the same device and a run long enough
    (GOOD_EVALUATIONS), latest first."""
    runs = [trial for trial in workspace.store.list_trial_rows(campaign_id) if trial.get("task_id") == task_id
            and _evaluations(trial) >= MIN_EVALUATIONS and _elapsed(trial) > 0]
    if not runs:
        return None
    return max(runs, key=lambda trial: (_method(trial) == method, trial.get("device") == device, _evaluations(trial) >= GOOD_EVALUATIONS,
                                        trial.get("created_at") or ""))


def measure(workspace, trial):
    """Seconds and bytes per evaluation of an earlier run, and the bytes it wrote besides its journals (frozen code,
    checkpoints, outputs), which do not grow with evaluations."""
    directory = workspace.job_dir(trial["id"])
    evaluations = _evaluations(trial)
    journals = {name: os.path.getsize(directory / name) for name in JOURNALS if (directory / name).exists()}
    return {"trial_id": trial["id"], "method": _method(trial), "device": trial.get("device"), "evaluations": evaluations,
            "seconds_per_evaluation": _elapsed(trial) / evaluations,
            "bytes_per_evaluation": {name: size / evaluations for name, size in journals.items()},
            "other_bytes": max(0, _size(directory) - sum(journals.values()))}


def _design(task):
    schema = (task.get("problem") or {}).get("candidate_schema") or {}
    dimensions, kind = schema.get("dimensions"), schema.get("representation") or schema.get("kind")
    return f"{dimensions:,} {kind} values" if isinstance(dimensions, int) and kind else None


def plan(workspace, campaign_id, runs):
    """The plan of these runs (each a dict: task_id, hypothesis_id or algorithm, seeds, wall_seconds, max_evaluations, device)."""
    store = workspace.store
    rows, warnings = [], []
    aliases = {row["record_id"]: row["label"] for row in store.list("agent_alias", campaign_id)}
    for run in runs:
        task = store.get(run["task_id"], "task")
        if task["campaign_id"] != campaign_id:
            raise ValueError("A planned run names a task of another campaign")
        hypothesis = store.get(run["hypothesis_id"], "hypothesis") if run.get("hypothesis_id") else None
        method = run.get("algorithm") or (hypothesis or {}).get("implementation_version_id") or (hypothesis or {}).get("algorithm") or ""
        label = " · ".join(part for part in (aliases.get((hypothesis or {}).get("id")), (hypothesis or {}).get("short_title"), method) if part) or "run"
        seeds = list(run.get("seeds") or [0])
        earlier = reference(workspace, campaign_id, task["id"], method, run.get("device"))
        measured = measure(workspace, earlier) if earlier else None
        cap, wall = run.get("max_evaluations"), float(run["wall_seconds"])
        by_wall = int(wall / measured["seconds_per_evaluation"]) if measured else None
        expected = min(value for value in (cap, by_wall) if value is not None) if (cap or by_wall) else None
        ends_by = "unknown" if by_wall is None and cap is None else "the evaluation cap" if by_wall is None or (cap is not None and cap < by_wall) else "its wall time"
        outputs, disk = [], None
        if measured and expected:
            outputs = [{"file": name, "what": JOURNALS[name], "bytes": round(per * expected)} for name, per in measured["bytes_per_evaluation"].items()]
            disk = sum(row["bytes"] for row in outputs) + measured["other_bytes"]
        row = {"label": label, "hypothesis_id": (hypothesis or {}).get("id"), "method": method, "task_id": task["id"], "task": task.get("name"),
               "design": _design(task), "seeds": seeds, "device": run.get("device"), "wall_seconds": wall, "max_evaluations": cap,
               "speed": {"seconds_per_evaluation": measured["seconds_per_evaluation"] if measured else None,
                         "basis": (f"measured on {measured['trial_id']} ({measured['evaluations']:,} evaluations, {measured['method'] or 'its method'}"
                                   f"{', ' + measured['device'] if measured['device'] else ''})") if measured else "not measured: no earlier run of this problem"},
               "evaluations": {"expected": expected, "ends_by": ends_by},
               "outputs": outputs, "other_bytes": measured["other_bytes"] if measured else None, "disk_bytes": disk}
        if measured and measured["method"] != method:
            row["speed"]["basis"] += "; another method, so speed and sizes are indicative"
        if not measured:
            warnings.append(f"{label}: speed and disk use are not measured on this problem, so how many evaluations the run makes and "
                            "what it writes are unknown. A short run or a runtime profile measures them.")
        elif ends_by == "the evaluation cap" and by_wall:
            warnings.append(f"{label}: the cap of {cap:,} evaluations ends each run after about "
                            f"{cap * measured['seconds_per_evaluation'] / 60:.0f} of its {wall / 60:.0f} minutes.")
        if disk and disk > LARGE_RUN_BYTES:
            warnings.append(f"{label}: each run writes about {disk / 1024 ** 3:.1f} GB ({len(seeds)} run{'s' if len(seeds) > 1 else ''}: "
                            f"{disk * len(seeds) / 1024 ** 3:.1f} GB).")
        rows.append(row)
    known = [row["disk_bytes"] * len(row["seeds"]) for row in rows if row["disk_bytes"] is not None]
    return {"runs": rows, "warnings": warnings,
            "totals": {"runs": sum(len(row["seeds"]) for row in rows), "worker_seconds": sum(row["wall_seconds"] * len(row["seeds"]) for row in rows),
                       "disk_bytes": sum(known) if len(known) == len(rows) else None, "max_workers": getattr(workspace, "max_workers", None)}}


def draft_plan(workspace, draft):
    """A draft is one run: its plan."""
    procedure = draft["procedure"]
    return plan(workspace, draft["campaign_id"], [{"task_id": procedure["task_id"], "hypothesis_id": procedure.get("hypothesis_id"),
        "algorithm": procedure.get("implementation_version_id") or procedure.get("algorithm") or None, "seeds": [procedure.get("seed", 0)],
        "wall_seconds": procedure.get("wall_seconds", 60), "max_evaluations": procedure.get("max_steps"), "device": procedure.get("device")}])
