"""What the lead sees in a thread, by layer: the project (the manifest's problem block), the branch (Pi's own context from
the leaf), and the live records the thread pinned or excluded. Sizes are measured where the harness answers, estimated
and labelled otherwise."""
import json

from balsamic.threads.service import lead_agent, thread_messages, thread_of


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


def _title(record):
    return record.get("title") or record.get("name") or record.get("question") or record.get("id")


def context_view(workspace, thread_id):
    thread = thread_of(workspace, thread_id)
    campaign = workspace.store.get(thread["campaign_id"], "campaign")
    tasks = workspace.store.list("task", campaign["id"])
    charters = workspace.store.list("charter", campaign["id"])
    project_items = [{"id": campaign["id"], "kind": "campaign", "title": campaign["name"], "bytes": _bytes({k: campaign.get(k) for k in ("objective", "name", "autonomy")})}]
    project_items += [{"id": task["id"], "kind": "task", "title": task["name"], "bytes": _bytes(task.get("problem"))} for task in tasks if not task.get("archived")]
    if charters:
        project_items.append({"id": charters[-1]["id"], "kind": "charter", "title": "charter v" + str(charters[-1].get("version")), "bytes": _bytes(charters[-1])})
    guidance = workspace.memory.state(campaign["id"])
    project_items.append({"id": guidance["id"], "kind": "guidance", "title": "researcher guidance", "bytes": len(guidance["guidance"].encode())})
    messages = thread_messages(workspace, thread)
    branch = {"entries_since_fork": len(messages), "summary_entries": 0, "bytes": sum(_bytes(m.get("content")) for m in messages), "leaf_entry_id": thread.get("agent_leaf"),
              "measured": False, "basis": "estimated from the thread's saved messages"}
    lead = lead_agent(workspace, campaign["id"])
    if lead and thread.get("agent_leaf"):
        try:
            measured = workspace.pi.client.context(lead["id"], leaf=thread["agent_leaf"])
        except (ValueError, OSError):
            measured = None
        if measured:
            branch = {"entries_since_fork": measured.get("entries"), "summary_entries": measured.get("summaries"), "compactions": measured.get("compactions"),
                      "bytes": measured.get("bytes"), "leaf_entry_id": measured.get("leaf_id"), "measured": True, "basis": "the harness's context from this leaf"}
    live = []
    for record_id in [*(thread.get("pinned_ids") or []), *(thread.get("excluded_ids") or [])]:
        try:
            entry = workspace.store.get_entry(record_id)
        except KeyError:
            live.append({"id": record_id, "kind": None, "title": record_id, "status": "missing", "revision": None})
            continue
        data = entry["data"]
        live.append({"id": record_id, "kind": entry["kind"], "title": _title(data), "status": data.get("status"), "revision": data.get("revision") or data.get("version"),
                     "excluded": record_id in (thread.get("excluded_ids") or [])})
    return {"thread_id": thread_id, "layers": {"project": {"items": project_items, "bytes": sum(item["bytes"] for item in project_items)},
                                               "branch": branch, "live": {"items": live}},
            "pinned_ids": thread.get("pinned_ids") or [], "excluded_ids": thread.get("excluded_ids") or [],
            "lab_events_since_last_turn": sum(1 for m in messages if m.get("origin") == "lab_event" and m["created_at"] > (next((x["created_at"] for x in reversed(messages) if x.get("role") == "assistant" and x.get("origin") != "lab_event"), "")))}
