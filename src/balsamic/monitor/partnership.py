"""Partnership metrics: for each researcher request, how much the researcher had to do, how long it took, what it cost and how
good the result was by then (roadmap J3). The same four numbers are recorded by hand for the researcher working alone
(docs/evals/partnership.md), so the two can be compared.

A request is a lead turn a researcher message started (decision 7: not an autopilot turn, not a notice). Its work is every turn
that continues it (the lead's notice turns, whose root names it, and the turns of the agents assigned for it) and every command
those turns sent. It closes at the lead's report: the first of its lead turns that ended with yield_work(complete).

Unknown is None, never zero: a turn that never reported has no report time, a call the price catalogue could not price has no cost.
"""
import json
from datetime import datetime, timedelta, timezone

from optimization_framework.agents.models import LEAD
from optimization_framework.execution.resources import spent

from balsamic.evolution.ledger import best_of, direction_of, score_of

TERMINAL = ("completed", "failed", "stopped", "interrupted")
_AFTER = timedelta(seconds=1)   # an unfinished run sorts after any end
DECISIONS = {"decision.resolve", "issue.resolve"}
BASIS = {
    "researcher": "commands the researcher sent from the request's message to the lead's report (or until now): messages, "
                  "decisions resolved and other commands. Requests open at the same time each count the actions in their window.",
    "time": "from the researcher's message to the lead's report (yield_work complete) and to the first comparison report its work made",
    "worker_seconds": "measured worker time of the runs the request's commands started, including a race's runs",
    "model_usd": "list price of the model calls of the request's turns, by the harness's price catalogue; charged_usd is what was "
                 "billed through an API key",
    "best": "the best objective of any run in the campaign that finished by the report (or by now), in the objective's direction",
}


def _clock(at):
    if not isinstance(at, str) or not at:
        return None
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _seconds(start, end):
    return round((end - start).total_seconds(), 3) if start and end else None


def _finished(store, campaign_id, runs):
    """When each agent turn ended: its own finished_at, else (turns from before that field) its first terminal update's event."""
    found = {run["id"]: _clock(run.get("finished_at")) for run in runs}
    missing = [identity for identity, at in found.items() if at is None]
    if missing:
        with store.connection() as db:
            rows = db.execute("SELECT json_extract(data, '$.record_id'), MIN(created_at) FROM events WHERE campaign_id=? "
                              "AND kind='agent.run_updated' AND json_extract(data, '$.status') IN (?,?,?,?) "
                              "GROUP BY json_extract(data, '$.record_id')", (campaign_id, *TERMINAL)).fetchall()
        for identity, at in rows:
            if identity in found and found[identity] is None:
                found[identity] = _clock(at)
    return found


def _root_of(workspace, run, agent):
    """The run id of the request a turn works on (as compute_consent.request_root tells it), or None."""
    root = workspace.pi.request_root(run) if agent.get("role") == LEAD else agent.get("assignment_origin")
    return (root or {}).get("run_id")


def _usage(store, campaign_id):
    with store.connection() as db:
        return [dict(zip(("agent_id", "occurred_at", "cost_usd", "charged_usd"), row)) for row in db.execute(
            "SELECT agent_id, occurred_at, cost_usd, charged_usd FROM llm_usage WHERE campaign_id=?", (campaign_id,)).fetchall()]


def _calls_by_run(store, campaign_id, runs, finished):
    """Each model call, given to the turn its agent was in when it was made: an agent's turns run one after another, so a call
    belongs to the earliest turn queued before it that had not yet ended."""
    by_agent = {}
    for run in sorted(runs, key=lambda run: run.get("created_at") or ""):
        by_agent.setdefault(run["agent_id"], []).append(run)
    calls = {}
    for call in _usage(store, campaign_id):
        at = _clock(call["occurred_at"])
        for run in by_agent.get(call["agent_id"], []):
            end = finished.get(run["id"])
            if at is not None and (_clock(run.get("created_at")) or at) <= at and (end is None or at <= end):
                calls.setdefault(run["id"], []).append(call)
                break
    return calls


def _launched(command):
    outcome = command.get("outcome") if isinstance(command.get("outcome"), dict) else {}
    trials = [value for value in [outcome.get("trial_id"), *(outcome.get("trial_ids") or [])] if isinstance(value, str)]
    races = [outcome["race_id"]] if isinstance(outcome.get("race_id"), str) else []
    for item in outcome.get("items") or []:   # intervention.batch: each item's own outcome
        if isinstance(item, dict):
            more, raced = _launched(item)
            trials, races = trials + more, races + raced
    return trials, races


def requests(workspace, campaign_id, *, clock=None):
    """One row per researcher request, oldest first."""
    from optimization_framework.campaigns.compute_consent import request_root
    store = workspace.store
    clock = clock or datetime.now(timezone.utc)
    agents = {agent["id"]: agent for agent in store.list("agent_session", campaign_id)}
    runs = [run for run in store.list("agent_run", campaign_id) if run.get("agent_id") in agents]
    finished = _finished(store, campaign_id, runs)
    asked = [run for run in runs if agents[run["agent_id"]].get("role") == LEAD and not run.get("autopilot")
             and not (run.get("origin") or {}).get("root") and (run.get("origin") or {}).get("actor") == "researcher"
             and (run.get("origin") or {}).get("message_id")]
    turns = {}
    for run in runs:
        root = _root_of(workspace, run, agents[run["agent_id"]])
        if root:
            turns.setdefault(root, []).append(run)
    calls = _calls_by_run(store, campaign_id, runs, finished)
    commands = store.list("work_command", campaign_id)
    by_root = {}
    for command in commands:
        if command.get("actor") != "researcher" and (command.get("origin") or {}).get("run_id"):
            root = (request_root(workspace, command["origin"]) or {}).get("run_id")
            if root:
                by_root.setdefault(root, []).append(command)
    researcher = [(command, _clock(command.get("created_at"))) for command in commands if command.get("actor") == "researcher"
                  and not command["id"].startswith("decision_action_")]   # a decision's own effect is not another action
    trials = {trial["id"]: trial for trial in store.list("trial", campaign_id)}
    tasks = {task["id"]: task for task in store.list("task", campaign_id)}
    messages = {message["id"]: message for message in store.list("message", campaign_id) if message.get("origin") == "researcher"}
    rows = []
    for run in sorted(asked, key=lambda run: run.get("created_at") or ""):
        origin = run["origin"]
        start = _clock((messages.get(origin["message_id"]) or {}).get("created_at")) or _clock(run.get("created_at"))
        own = turns.get(run["id"], [run])
        reports = [finished[turn["id"]] for turn in own if agents[turn["agent_id"]].get("role") == LEAD and turn.get("status") == "completed"
                   and (turn.get("disposition") or {}).get("disposition") == "complete" and finished.get(turn["id"])]
        reported = min(reports) if reports else None
        end = reported or clock
        counts = {"messages": 0, "decisions": 0, "commands": 0}
        for command, at in researcher:
            if at is not None and start is not None and start <= at <= end:
                operation = (command.get("request") or {}).get("operation")
                counts["messages" if operation == "agent.message" else "decisions" if operation in DECISIONS else "commands"] += 1
        sent = by_root.get(run["id"], [])
        ranked = [_clock(command.get("created_at")) for command in sent if (command.get("request") or {}).get("operation") == "comparison.report"]
        ranked = min((at for at in ranked if at), default=None)
        launched, races = set(), set()
        for command in sent:
            more, raced = _launched(command)
            launched.update(more)
            races.update(raced)
        launched.update(identity for identity, trial in trials.items() if trial.get("race_id") in races)
        mine = [trials[identity] for identity in launched if identity in trials]
        used = [call for turn in own for call in calls.get(turn["id"], [])]
        priced = [call["cost_usd"] for call in used if call["cost_usd"] is not None]
        done = [trial for trial in trials.values() if (_clock(trial.get("finished_at")) or end + _AFTER) <= end]
        best, direction = best_of([(score_of(trial)[0], direction_of(trial, tasks.get(trial.get("task_id"))), trial) for trial in done])
        rows.append({
            "run_id": run["id"], "thread_id": origin.get("thread_id"), "message_id": origin["message_id"],
            "text": " ".join(str(run.get("input") or "").split())[:160],
            "asked_at": start.isoformat() if start else None, "closed": reported is not None,
            "reported_at": reported.isoformat() if reported else None,
            "researcher_actions": {**counts, "total": sum(counts.values())},
            "seconds_to_report": _seconds(start, reported), "seconds_to_first_ranked": _seconds(start, ranked),
            "runs": len(mine), "worker_seconds": round(sum(float(spent(trial) or 0) for trial in mine), 3),
            "model_calls": len(used), "model_usd": round(sum(priced), 6) if priced or not used else None,
            "model_charged_usd": round(sum(float(call["charged_usd"] or 0) for call in used), 6),
            "best": {"value": best[0], "direction": direction, "trial_id": best[2]["id"]} if best else None,
        })
    return rows


def view(workspace, campaign_id, *, clock=None):
    return {"campaign_id": campaign_id, "requests": requests(workspace, campaign_id, clock=clock), "basis": BASIS}
