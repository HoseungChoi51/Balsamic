"""Thread records and reads.

Every campaign has a ``main`` thread, created with the campaign (or on first read of an older one). M0 reads the
conversation through it; M1 adds fork, park and merge on the same records, so the addresses and the after-cursor are
settled first. Messages carry ``thread_id``; messages written before threads existed belong to ``main``.
"""
from optimization_framework.agents.models import LEAD, PAGE_AGENTS
from optimization_framework.storage.sqlite import now

MAIN = "main"
MESSAGE_LIMIT = 200


def main_thread_id(campaign_id):
    return f"thread_{MAIN}_{campaign_id}"


def ensure_main(workspace, campaign_id):
    """The campaign's main thread record; written once."""
    identity = main_thread_id(campaign_id)
    try:
        return workspace.store.get(identity, "thread")
    except KeyError:
        campaign = workspace.store.get(campaign_id, "campaign")
        record = {"id": identity, "campaign_id": campaign_id, "name": MAIN, "title": campaign["name"], "parent_thread_id": None,
                  "fork_message_id": None, "fork_entry_id": None, "agent_leaf": None, "status": "active", "merged_into": None,
                  "pinned_ids": [], "excluded_ids": [], "anchors": [], "summary": None, "guidance_revision": 0,
                  "last_seen_message_id": None, "created_at": campaign.get("created_at") or now(), "updated_at": now()}
        with workspace.lock:
            return workspace.store.put("thread", record, "thread.created")


def thread_of(workspace, thread_id):
    record = workspace.store.get(thread_id, "thread")
    return record


def lead_agent(workspace, campaign_id):
    return next((agent for agent in workspace.store.list("agent_session", campaign_id) if agent["role"] == LEAD), None)


def conversation(workspace, campaign_id):
    """The researcher's conversation with the lead: its messages and the lab's own lines, never a page agent's desk."""
    page_agents = {agent["id"] for agent in workspace.store.list("agent_session", campaign_id) if agent["role"] in PAGE_AGENTS}
    rows = []
    for message in workspace.store.list("message", campaign_id):
        if message.get("desk") or message.get("agent_id") in page_agents or message.get("to_agent_id") in page_agents:
            continue
        rows.append(message)
    return rows


def event_cursor(workspace, campaign_id):
    with workspace.store.connection() as db:
        return db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE campaign_id=?", (campaign_id,)).fetchone()[0]


def thread_messages(workspace, thread):
    main = main_thread_id(thread["campaign_id"])
    return [message for message in conversation(workspace, thread["campaign_id"])
            if message.get("thread_id", main) == thread["id"]]


def threads(workspace, campaign_id):
    ensure_main(workspace, campaign_id)
    lead = lead_agent(workspace, campaign_id)
    config = workspace.pi.configuration(campaign_id) or {}
    active_run = next((run for run in workspace.store.list("agent_run", campaign_id)
                       if lead and run["agent_id"] == lead["id"] and run["status"] in {"queued", "submitted", "running"}), None)
    rows = []
    for thread in workspace.store.list("thread", campaign_id):
        messages = thread_messages(workspace, thread)
        last = messages[-1] if messages else None
        rows.append({**thread, "message_count": len(messages), "last_message_id": last["id"] if last else None,
                     "last_activity_at": last.get("created_at") if last else thread.get("created_at"),
                     "busy": bool(active_run and (active_run.get("origin") or {}).get("thread_id", main_thread_id(campaign_id)) == thread["id"]),
                     "queued": 0})
    return {"threads": rows, "lead": {"id": lead["id"], "status": lead["status"]} if lead else None,
            "request_open": bool(config.get("request_open")),
            "active_run": {"id": active_run["id"], "thread_id": (active_run.get("origin") or {}).get("thread_id", main_thread_id(campaign_id))} if active_run else None}


def messages(workspace, thread_id, *, limit=MESSAGE_LIMIT, before=None):
    thread = thread_of(workspace, thread_id)
    rows = thread_messages(workspace, thread)
    if before:
        index = next((i for i, row in enumerate(rows) if row["id"] == before), len(rows))
        rows = rows[:index]
    questions = [q for q in workspace.store.list("agent_question", thread["campaign_id"]) if q["status"] == "pending"]
    return {"thread_id": thread_id, "campaign_id": thread["campaign_id"], "messages": rows[-limit:], "truncated": len(rows) > limit,
            "inherited": [], "parent_path": [], "fork_message_id": thread.get("fork_message_id"), "questions": questions}


def register(workspace):
    """Thread commands come with M1; M0 only makes sure a campaign has its main thread when one is created."""
    original = workspace.create_campaign

    def create_campaign(values, *args, **kwargs):
        campaign = original(values, *args, **kwargs)
        ensure_main(workspace, campaign["id"])
        return campaign
    workspace.create_campaign = create_campaign
