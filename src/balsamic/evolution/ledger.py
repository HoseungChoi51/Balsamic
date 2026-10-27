"""The hypothesis ledger: one row per strategy, from the records that already exist. Cached by event cursor.

Stages: proposed → reviewed → screening (short runs) → extended (long runs or race rungs) → finalist → confirmed → stopped.
Stopped is a decision with a reason, never a failure. Unknown values stay None.
"Best" follows the objective's direction: the lowest score when minimizing.
"""
import math

from optimization_framework.campaigns.experiment_rules import check_trial_ids, classify, current as experiment_rules
from optimization_framework.campaigns.hypotheses import stop_of
from optimization_framework.campaigns.proposals import readiness
from optimization_framework.contracts.problems import Objective

RACE_ACTIVE = {"preflight", "running", "paused"}
CURVE_POINTS = 200
_cache = {}


def score_of(trial):
    result = trial.get("result") or {}
    progress = trial.get("progress") or {}
    for source, basis in ((result, "result"), (progress, "progress")):
        for key in ("best_objective", "best_efficiency", "best_score"):
            if isinstance(source.get(key), (int, float)):
                return float(source[key]), basis
    return None, None


def direction_of(trial, task=None):
    """The direction a run's objective is ranked in: its result's, else its problem's, else its task's.

    A record that says none predates objective definitions; those were all maximized (efficiency).
    """
    sources = [((trial.get(key) or {}).get("objective_definition") or {}) for key in ("result", "progress")]
    sources += [((problem or {}).get("primary_objective") or {}) for problem in (trial.get("problem"), (task or {}).get("problem"))]
    return next((source["direction"] for source in sources if source.get("direction") in {"minimize", "maximize"}), "maximize")


def best_of(entries):
    """The best of (score, direction, item) entries, and the direction they share.

    Entries that disagree on direction have no single best: (None, None), never a mixed comparison.
    """
    entries = [entry for entry in entries if entry[0] is not None and math.isfinite(entry[0])]
    directions = {direction for _, direction, _ in entries}
    if len(directions) != 1:
        return None, None
    objective = Objective(name="score", direction=directions.pop())
    best = None
    for entry in entries:
        if best is None or objective.better(entry[0], best[0]):
            best = entry
    return best, objective.direction


def curve(workspace, trial_id):
    try:
        rows = workspace.metrics(trial_id, fields=["evaluations", "best_objective", "best_efficiency", "elapsed_seconds", "step"])
    except (KeyError, OSError, ValueError):
        return []
    points = []
    for index, row in enumerate(rows):
        y = row.get("best_objective", row.get("best_efficiency"))
        if isinstance(y, (int, float)):
            points.append({"x": row.get("evaluations", row.get("step", index)), "y": y, "t": row.get("elapsed_seconds")})
    if len(points) > CURVE_POINTS:
        step = (len(points) - 1) / (CURVE_POINTS - 1)
        points = [points[round(i * step)] for i in range(CURVE_POINTS)]
    return points


def stage_of(hypothesis, trials, kinds, race, finalist, confirmation, review):
    if hypothesis.get("status") == "archived":
        return "stopped"
    if confirmation and confirmation.get("promising") is not None:
        return "confirmed"
    if hypothesis.get("status") == "finalist" or finalist:
        return "finalist"
    if race and race.get("highest_rung_seconds") and race["highest_rung_seconds"] >= 1800 or any(kinds.get(t["id"]) == "long" for t in trials):
        return "extended"
    if trials:
        return "screening"
    if review.get("verdict") or hypothesis.get("reviews"):
        return "reviewed"
    return "proposed"


def rows(workspace, campaign_id, *, with_curves=False):
    """Ledger rows; recomputed only when the campaign has new events."""
    with workspace.store.connection() as db:
        cursor = db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE campaign_id=?", (campaign_id,)).fetchone()[0]
    key = (id(workspace.store), campaign_id, with_curves)   # one cache per open store: the same campaign id in another workspace is another campaign
    cached = _cache.get(key)
    if cached and cached[0] == cursor:
        return cached[1], cursor
    store = workspace.store
    hypotheses = store.list("hypothesis", campaign_id)
    trials = store.list("trial", campaign_id)
    tasks = {task["id"]: task for task in store.list("task", campaign_id)}
    aliases = {row["record_id"]: row["label"] for row in store.list("agent_alias", campaign_id)}
    rules = experiment_rules(store, campaign_id)
    kinds = classify(trials, rules.get("short_run_seconds") or rules.get("long_run_threshold_seconds") or 600, check_trial_ids(store, campaign_id)) if trials else {}
    races = [race for race in store.list("adaptive_race", campaign_id)]
    race_views = {}
    for race in races:
        try:
            race_views[race["id"]] = workspace.racing.view(race["id"])
        except (KeyError, ValueError):
            continue
    finalists = {trial_id for selection in store.list("finalist_selection", campaign_id) for trial_id in selection.get("trial_ids", [])}
    protocols = store.list("confirmation_protocol", campaign_id)
    commands = {row["id"]: row for row in store.list("work_command", campaign_id)}
    created_by = {}
    for row in commands.values():
        if row["request"]["operation"] == "hypothesis.create":
            created_by[(row.get("outcome") or {}).get("hypothesis_id")] = row.get("origin") or {}
    out = []
    for hypothesis in hypotheses:
        own = [t for t in trials if t.get("hypothesis_id") == hypothesis["id"]]
        own_ids = {t["id"] for t in own}
        scored = []
        for trial in own:
            score, how = score_of(trial)
            scored.append((score, direction_of(trial, tasks.get(trial.get("task_id"))), (trial, how)))
        chosen, direction = best_of(scored)
        best, (best_trial, basis) = (chosen[0], chosen[2]) if chosen else (None, (None, None))
        race = None
        for view in race_views.values():
            for configuration in view["configurations"]:
                protocol_configuration = next((c for c in workspace.racing._protocol(store.get(view["id"], "adaptive_race"))["configurations"] if c["id"] == configuration["id"]), {})
                if protocol_configuration.get("hypothesis_id") == hypothesis["id"] or own_ids & set(configuration.get("trial_ids", [])):
                    latest = next((d for d in reversed(view["decisions"]) if configuration["id"] in d.get("configuration_ids", [])), None)
                    race = {"race_id": view["id"], "configuration_id": configuration["id"], "status": configuration["status"], "race_status": view["status"],
                            "highest_rung_seconds": configuration.get("rung_seconds"), "mean_score": configuration.get("mean_score"), "seeds": configuration.get("seeds"),
                            "latest_decision": {"action": latest.get("action"), "rationale": latest.get("rationale"), "at": latest.get("created_at")} if latest else None}
        finalist = bool(own_ids & finalists)
        confirmation = None
        for protocol in protocols:
            cells = protocol.get("cells") or []
            if any(cell.get("trial_id") in own_ids or cell.get("hypothesis_id") == hypothesis["id"] for cell in cells) or protocol.get("hypothesis_id") == hypothesis["id"]:
                try:
                    assessment = workspace.confirmations.assess(protocol["id"])
                except (KeyError, ValueError):
                    assessment = {}
                confirmation = {"protocol_id": protocol["id"], "status": assessment.get("status", protocol.get("status")), "promising": assessment.get("promising"),
                                "seeds_won": assessment.get("seeds_won")}
        reviews = hypothesis.get("reviews") or []
        verdicts = [r.get("verdict") for r in reviews if r.get("verdict")]
        review = {"verdict": verdicts[-1] if verdicts else None, "count": len(reviews), "readiness": readiness(store, hypothesis)}
        origin = created_by.get(hypothesis["id"], {})
        row = {"id": hypothesis["id"], "label": aliases.get(hypothesis["id"]), "title": hypothesis["title"], "short_title": hypothesis.get("short_title"), "status": hypothesis.get("status", "proposed"),
               "origin": hypothesis.get("origin"), "actor": origin.get("actor"), "autonomous": origin.get("actor") == "autopilot", "round": hypothesis.get("round"),
               "parent_links": hypothesis.get("parent_links") or [{"id": p, "kind": "revision"} for p in hypothesis.get("parent_ids") or []],
               "family": hypothesis.get("family"), "algorithm": hypothesis.get("algorithm"), "worker_seconds": sum(float(t.get("execution_seconds") or 0) for t in own),
               "allotted_seconds": sum(float(t.get("wall_seconds") or 0) for t in own),
               "evaluations": sum(int(((t.get("result") or t.get("progress") or {}).get("evaluations") or 0)) for t in own) or None,
               "best": {"score": best, "basis": "measured" if best is not None else None, "source": basis, "trial_id": best_trial["id"] if best_trial else None, "interval": None,
                        "direction": direction},
               "highest_rung_seconds": (race or {}).get("highest_rung_seconds") or (max((t.get("wall_seconds") or 0) for t in own) if own else None),
               "race": race, "review": review, "implementation_readiness": workspace.implementations.readiness(hypothesis),
               "trial_ids": [t["id"] for t in own], "live_trials": sum(1 for t in own if t.get("status") in {"queued", "running", "pausing", "stopping"}),
               "finalist": finalist or hypothesis.get("status") == "finalist", "confirmation": confirmation,
               "stop_reason": hypothesis.get("stop_reason"), "stopped_at": hypothesis.get("stopped_at"), "stop": stop_of(hypothesis),
               "created_at": hypothesis.get("created_at")}
        row["stage"] = stage_of(hypothesis, own, kinds, race, finalist, confirmation, review)
        if with_curves and best_trial:
            row["curve"] = curve(workspace, best_trial["id"])
        out.append(row)
    _cache[key] = (cursor, out)
    if len(_cache) > 32:
        _cache.pop(next(iter(_cache)))
    return out, cursor
