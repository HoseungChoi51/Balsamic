"""Stalls: work that stopped without anyone saying so, surfaced inside Balsamic instead of watched from outside it.

Two signals, checked on the manager tick and shown in the Monitor's attention list (the top bar's pill):
- An open request with nothing in progress: the researcher's request is open, nothing waits for the researcher, and no agent
  turn, run, implementation job or coding agent is queued or working. After IDLE_SECONDS the lead gets one notice; if nothing
  starts within ESCALATE_SECONDS more, the researcher gets an inbox issue.
- A long wait: an agent turn with no reply or step for WAIT_SECONDS, typically a slow or stuck model call. The researcher gets
  an inbox issue naming the role, model and turn.
Each issue clears itself once the work moves again; autopilot paces its own rounds and is left to them.
"""
from datetime import datetime, timezone

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

IDLE_SECONDS = 300
ESCALATE_SECONDS = 600
WAIT_SECONDS = 1200
CHECK_SECONDS = 30
ACTIVE_TURNS = {"queued", "submitted", "running"}
LIVE_RUNS = {"queued", "running", "pausing", "stopping"}
CODING = {"queued", "starting", "running", "resuming"}
NOTICE_PREFIX = "pi_stall_"
_checked = {}


def _age(at, clock=None):
    """Seconds since an ISO timestamp, or None without one."""
    if not at:
        return None
    return ((clock or datetime.now(timezone.utc)) - datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds()


def in_progress(workspace, campaign_id):
    """What moves the campaign's work along right now, by kind; all empty when nothing does."""
    from optimization_framework.implementations.bridge import SETTLED
    store = workspace.store
    return {"turns": [run["id"] for run in store.list("agent_run", campaign_id) if run["status"] in ACTIVE_TURNS],
            "runs": [trial["id"] for trial in store.list_trials_in_status(LIVE_RUNS, campaign_id)],
            "implementations": [grant["id"] for grant in store.list("implementation_grant", campaign_id)
                                if grant["status"] not in SETTLED | {"blocked", "needs_reconciliation"}],
            "coding": [record["id"] for record in store.list("development_workspace", campaign_id) if record["status"] in CODING]}


def idle_request(workspace, campaign_id):
    """{since, seconds, notice_running} while the researcher's request is open and nothing is in progress or waiting for
    them, else None. The lead's turn on this module's own notice is not progress: notice_running says it is under way."""
    store, pi = workspace.store, workspace.pi
    if not pi.owns(campaign_id):
        return None
    config = pi.configuration(campaign_id)
    campaign = store.get(campaign_id, "campaign")
    if (config.get("status") != "running" or not config.get("request_open") or not (config.get("provider") or {}).get("configured")
            or (campaign.get("autopilot") or {}).get("enabled")):
        return None
    if any(row.get("status") in {"pending", "executing"} for row in store.list("decision", campaign_id)) or any(
            row.get("status") == "pending" for row in store.list("agent_question", campaign_id)):
        return None
    progress = in_progress(workspace, campaign_id)
    notices = [turn for turn in progress["turns"] if turn.startswith(NOTICE_PREFIX)]
    if len(notices) < len(progress["turns"]) or any(progress[kind] for kind in ("runs", "implementations", "coding")):
        return None
    watch = _watch(store, campaign_id)
    since = watch.get("idle_since") or now()
    return {"since": since, "seconds": _age(since) or 0.0, "notice_running": bool(notices)}


def long_waits(workspace, campaign_id):
    """Agent turns with no reply or step for WAIT_SECONDS: [{run_id, agent_id, role, model, seconds}]."""
    store, waits = workspace.store, []
    for run in store.list("agent_run", campaign_id):
        if run["status"] not in {"submitted", "running"} or not run.get("dispatched_at"):
            continue
        try:
            agent = store.get(run["agent_id"], "agent_session")
        except KeyError:
            continue
        # Since its latest sign of life: the dispatch, or its agent's last event if that came later.
        seconds = min(_age(at) for at in (run["dispatched_at"], agent.get("last_activity_at")) if at)
        if seconds >= WAIT_SECONDS:
            waits.append({"run_id": run["id"], "agent_id": agent["id"], "role": agent["role"], "seconds": seconds,
                          "model": f"{agent.get('provider')}/{agent.get('model')}" + (f" at {agent['reasoning_effort']} effort" if agent.get("reasoning_effort") else "")})
    return waits


def attention(workspace, campaign_id):
    """The Monitor's attention entries for these signals, computed from the current state."""
    entries = []
    idle = idle_request(workspace, campaign_id)
    if idle and not idle["notice_running"] and idle["seconds"] >= IDLE_SECONDS:
        entries.append(("agents", f"Your request is open but nothing has been in progress for {int(idle['seconds'] // 60)} min"))
    for wait in long_waits(workspace, campaign_id):
        entries.append(("agents", f"The {wait['role'].replace('_', ' ')} has waited {int(wait['seconds'] // 60)} min on {wait['model']}"))
    return entries


def _watch(store, campaign_id):
    try:
        return store.get("stall_watch_" + campaign_id, "stall_watch")
    except KeyError:
        return {"id": "stall_watch_" + campaign_id, "campaign_id": campaign_id, "idle_since": None, "notified_at": None,
                "issue_id": None, "wait_issues": {}}


def _clear(workspace, issue_id, basis):
    """Mark a stall issue resolved once the work moved again; the researcher's guidance is not touched."""
    try:
        issue = workspace.store.get(issue_id, "manager_issue")
    except KeyError:
        return
    if issue["status"] == "pending":
        issue.update(status="resolved", resolution_basis=basis, resolved_at=now(), revision=issue.get("revision", 1) + 1)
        workspace.store.put("manager_issue", issue, "manager.issue_resolved")


def check(workspace, campaign_id):
    """Advance both signals for one campaign: notify the lead, raise or clear the researcher's issues."""
    store = workspace.store
    watch = _watch(store, campaign_id)
    before = dict(watch)
    idle = idle_request(workspace, campaign_id)
    if idle is None:
        if watch.get("issue_id"):
            _clear(workspace, watch["issue_id"], "Work is in progress again, or the request is no longer open.")
        watch.update(idle_since=None, notified_at=None, issue_id=None)
    elif not idle["notice_running"]:
        watch["idle_since"] = idle["since"]
        if idle["seconds"] >= IDLE_SECONDS and not watch.get("notified_at"):
            from optimization_framework.agents.models import NOTICE
            lead = store.get(workspace.pi.configuration(campaign_id)["lead_id"], "agent_session")
            workspace.pi.enqueue(lead, NOTICE_PREFIX + content_hash([campaign_id, idle["since"]])[:24], NOTICE +
                f"The researcher's request is still open, but nothing has been in progress for {int(idle['seconds'] // 60)} minutes: "
                "no agent is working and no run, implementation job or coding agent is active or queued. Read campaign_inspect and "
                "continue the request. If it is done, say so and end with yield_work(complete); if it needs the researcher, ask them.")
            watch["notified_at"] = now()
        elif watch.get("notified_at") and not watch.get("issue_id") and (_age(watch["notified_at"]) or 0) >= ESCALATE_SECONDS:
            issue = workspace.memory.issue(campaign_id, "request_stalled",
                "Your request is still open, but nothing has been in progress since "
                f"{watch['idle_since'][11:16]} UTC, and a notice to the lead did not get it moving. Tell the lead how to go on, "
                "or tell it the request is done.", affected="stall_" + watch["idle_since"], options=["Discuss with the lead", "Defer"])
            watch["issue_id"] = issue["id"]
    waits = {wait["run_id"]: wait for wait in long_waits(workspace, campaign_id)}
    raised = dict(watch.get("wait_issues") or {})
    for run_id, issue_id in list(raised.items()):
        if run_id not in waits:
            _clear(workspace, issue_id, "The agent's turn moved on or ended.")
            raised.pop(run_id)
    for run_id, wait in waits.items():
        if run_id not in raised:
            issue = workspace.memory.issue(campaign_id, "agent_long_wait",
                f"The {wait['role'].replace('_', ' ')} ({wait['agent_id']}) has had no reply or step for more than "
                f"{WAIT_SECONDS // 60} minutes in turn {run_id}, on {wait['model']}. It may be stuck on a slow model call. You can stop "
                "the agent on the Agents page, or move its role to another model on the Models page.",
                affected=run_id, options=["Discuss with the lead", "Defer"])
            raised[run_id] = issue["id"]
    watch["wait_issues"] = raised
    if watch != before:
        store.put("stall_watch", watch)


def tick(workspace):
    clock = datetime.now(timezone.utc).timestamp()
    if clock - _checked.get(id(workspace), 0) < CHECK_SECONDS:
        return
    _checked[id(workspace)] = clock
    for campaign in workspace.store.list("campaign"):
        if campaign.get("archived") or campaign.get("status") in {"archived", "removed"}:
            continue
        try:
            check(workspace, campaign["id"])
        except (KeyError, ValueError):
            continue


def register(workspace):
    previous = workspace.on_manager_tick

    def on_tick():
        if previous:
            previous()
        tick(workspace)
    workspace.on_manager_tick = on_tick
