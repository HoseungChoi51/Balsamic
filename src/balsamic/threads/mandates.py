"""The mandate shown above a thread's chat (roadmap R7): the one the thread's current request works under, and the others still in
force that were granted for earlier requests in the thread, each of which the researcher can close (mandate.close)."""
from optimization_framework.campaigns import mandates

from .service import thread_messages, thread_of


def current_root(workspace, thread):
    """The request the thread's latest researcher message opened, as the lead's request_root() (or a page agent's desk_root) gives
    it; for an agents' conversation, the request it serves. None before the researcher has written in the thread."""
    if thread.get("kind") == "agents" and thread.get("root_run_id"):
        try:
            return workspace.pi.request_root(workspace.store.get(thread["root_run_id"], "agent_run"))
        except KeyError:
            return None
    asked = [message for message in thread_messages(workspace, thread)
             if message.get("role") == "user" and message.get("origin") == "researcher" and message["id"].startswith("message_")]
    if not asked or not asked[-1].get("thread_id"):
        return None
    last = asked[-1]
    return {"thread_id": last["thread_id"], "message_id": last["id"], "run_id": "pi_run_" + last["id"].removeprefix("message_")}


def thread_view(workspace, thread_id):
    thread = thread_of(workspace, thread_id)
    campaign_id = thread["campaign_id"]
    root = current_root(workspace, thread)
    found = mandates.mandates(workspace, campaign_id)
    current = mandates.governing(workspace, campaign_id, root, found)
    others = [mandate for mandate in reversed(found) if mandate.root is not None and mandate.root.thread_id == thread_id
              and mandate.status in {"active", "exhausted"} and (current is None or mandate.id != current.id)]
    return {"thread_id": thread_id, "campaign_id": campaign_id, "request": root,
            "current": mandates.view(workspace, current) if current is not None else None,
            "others": [mandates.view(workspace, mandate) for mandate in others],
            "default_template": mandates.default_template(workspace.store.get(campaign_id, "campaign"))}
