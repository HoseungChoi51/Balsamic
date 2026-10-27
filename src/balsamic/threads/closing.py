"""When an agents' side conversation closes. It is the record of the work on one researcher request, not a discussion of its own,
so it is open while that work goes on and closes when it has ended: no turn of the lead's on the request (the request's own turn
and the notice turns that continue it) and no turn of an agent working for it is queued or running, no question of theirs waits
for the researcher, and nothing was said in it for QUIET_SECONDS. Closing keeps the messages and writes an activity card; the
conversation opens again when work on its request resumes. Branches the researcher forked are the researcher's to park.
Checked on the manager tick.
"""
from datetime import datetime, timezone

from optimization_framework.agents.models import LEAD
from optimization_framework.storage.sqlite import now

QUIET_SECONDS = 300
CHECK_SECONDS = 30
ACTIVE_TURNS = {"queued", "submitted", "running"}
_checked = {}


def _age(at, clock):
    return (clock - datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds() if at else float("inf")


def working(workspace, campaign_id):
    """The requests (the run ids of the lead turns that started them) whose work is in progress or waits for the researcher."""
    store = workspace.store
    agents = {agent["id"]: agent for agent in store.list("agent_session", campaign_id)}
    roots = set()
    for run in store.list("agent_run", campaign_id):
        if run["status"] in ACTIVE_TURNS:
            agent = agents.get(run["agent_id"]) or {}
            root = workspace.pi.request_root(run) if agent.get("role") == LEAD else agent.get("assignment_origin")
            roots.add((root or {}).get("run_id"))
    for question in store.list("agent_question", campaign_id):
        if question["status"] == "pending":
            roots.add(((agents.get(question.get("agent_id")) or {}).get("assignment_origin") or {}).get("run_id"))
    return roots - {None}


def check(workspace, campaign_id, clock=None):
    """Close the side conversations whose work has ended and reopen those whose work resumed; returns what changed."""
    from balsamic.threads.service import write_summary
    clock = clock or datetime.now(timezone.utc)
    sides = [thread for thread in workspace.store.list("thread", campaign_id) if thread.get("kind") == "agents" and thread["status"] in {"active", "closed"}]
    if not sides:
        return {"closed": [], "reopened": []}
    roots = working(workspace, campaign_id)
    last = {}
    for message in workspace.store.list("message", campaign_id):
        if message.get("thread_id") and message.get("origin") != "lab_event":
            last[message["thread_id"]] = max(last.get(message["thread_id"], ""), message.get("created_at") or "")
    closed, reopened = [], []
    for thread in sides:
        live = thread.get("root_run_id") in roots
        if thread["status"] == "active" and not live and _age(last.get(thread["id"]) or thread.get("created_at"), clock) >= QUIET_SECONDS:
            with workspace.lock:
                thread = workspace.store.get(thread["id"], "thread")
                thread.update(status="closed", closed_at=now(), updated_at=now())
                workspace.store.put("thread", thread, "thread.closed")
            write_summary(workspace, thread["id"], reason="closed", model=False)
            closed.append(thread["id"])
        elif thread["status"] == "closed" and live:
            reopen(workspace, thread["id"])
            reopened.append(thread["id"])
    return {"closed": closed, "reopened": reopened}


def reopen(workspace, thread_id):
    with workspace.lock:
        thread = workspace.store.get(thread_id, "thread")
        if thread["status"] != "closed":
            return thread
        thread.update(status="active", closed_at=None, updated_at=now())
        if thread.get("summary"):
            thread["summary"] = {**thread["summary"], "stale": True}
        return workspace.store.put("thread", thread, "thread.reopened")


def tick(workspace):
    clock = datetime.now(timezone.utc)
    if clock.timestamp() - _checked.get(id(workspace), 0) < CHECK_SECONDS:
        return
    _checked[id(workspace)] = clock.timestamp()
    for campaign in workspace.store.list("campaign"):
        if campaign.get("archived") or campaign.get("status") in {"archived", "removed"}:
            continue
        try:
            check(workspace, campaign["id"], clock)
        except (KeyError, ValueError):
            continue


def register(workspace):
    previous = workspace.on_manager_tick

    def on_tick():
        if previous:
            previous()
        tick(workspace)
    workspace.on_manager_tick = on_tick
