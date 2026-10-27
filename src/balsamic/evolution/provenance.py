"""Where a record came from: the command, the run, the turn, the thread, the model; a strategy's parents; an asset's producers."""
from optimization_framework.agents.pages import command_pages


def _entry(store, identity):
    try:
        return store.get_entry(identity)
    except KeyError:
        return None


def _hop(kind, record, via, page=None):
    return {"hop": kind, "record": {"id": record.get("id"), "kind": kind, "title": record.get("title") or record.get("name") or record.get("content", "")[:80] or record.get("id"),
                                    "created_at": record.get("created_at"), "content_hash": record.get("content_hash"), "status": record.get("status")}, "via": via, "page": page}


def trail(workspace, record_id, *, limit=12):
    store = workspace.store
    entry = _entry(store, record_id)
    if entry is None:
        raise KeyError(record_id)
    pages = command_pages()
    hops = [_hop(entry["kind"], entry["data"], "the record")]
    data, kind = entry["data"], entry["kind"]
    # The command that created it: the receipt whose outcome names it.
    campaign_id = data.get("campaign_id")
    commands = store.list("work_command", campaign_id) if campaign_id else []
    command = next((c for c in reversed(commands) if record_id in {str(v) for v in (c.get("outcome") or {}).values() if isinstance(v, str)}
                    or (c.get("outcome") or {}).get("hypothesis_id") == record_id or (c.get("outcome") or {}).get("trial_id") == record_id), None)
    if command is None and kind == "work_command":
        command = data
    if command:
        operation = command["request"]["operation"]
        hops.append(_hop("work_command", {**command, "title": operation}, f"{command.get('actor')} ran {operation}", pages.get(operation)))
        origin = command.get("origin") or {}
        run = _entry(store, origin.get("run_id")) if origin.get("run_id") else None
        if run:
            hops.append(_hop("agent_run", {**run["data"], "title": (run["data"].get("input") or "")[:80]}, f"a turn of {origin.get('agent_id')}"))
            agent = _entry(store, run["data"].get("agent_id"))
            if agent:
                hops.append(_hop("agent_session", {**agent["data"], "title": f"{agent['data'].get('role')} on {agent['data'].get('model')}"}, "the agent and its model", "#monitor/agents"))
        message = _entry(store, origin.get("message_id")) if origin.get("message_id") else None
        if message:
            hops.append(_hop("message", {**message["data"], "title": (message["data"].get("content") or "")[:80]}, "the message that asked", "#branches"))
        thread = _entry(store, origin.get("thread_id")) if origin.get("thread_id") else None
        if thread:
            hops.append(_hop("thread", thread["data"], "the conversation thread", "#branches"))
    if kind == "hypothesis":
        for link in data.get("parent_links") or [{"id": p, "kind": "revision"} for p in data.get("parent_ids") or []]:
            parent = _entry(store, link["id"])
            if parent:
                hops.append(_hop(parent["kind"], parent["data"], f"parent ({link.get('kind')})", f"#hypotheses/{link['id']}"))
    if kind == "trial" and data.get("hypothesis_id"):
        parent = _entry(store, data["hypothesis_id"])
        if parent:
            hops.append(_hop("hypothesis", parent["data"], "the strategy it tests", f"#hypotheses/{data['hypothesis_id']}"))
    if kind == "asset":
        for key in ("producer_id", *(data.get("dependency_ids") or [])):
            producer = _entry(store, data.get(key) if key == "producer_id" else key)
            if producer:
                hops.append(_hop(producer["kind"], producer["data"], "produced by" if key == "producer_id" else "depends on"))
    return {"record_id": record_id, "trail": hops[:limit]}
