"""The lead's turn as AG-UI events: text and reasoning as they arrive, each tool call as a step, the message list.

Pure functions over what the controller already records and what the harness reports live. Nothing here starts work.
"""


def agent_state(workspace, campaign_id, agent_id, thread_id):
    agent = workspace.store.get(agent_id, "agent_session")
    if agent["campaign_id"] != campaign_id:
        raise KeyError(agent_id)
    config = workspace.pi.configuration(campaign_id) or {}
    disposition = agent.get("disposition") or {}
    return {"threadId": thread_id, "agentId": agent_id, "role": agent["role"], "status": agent["status"], "requestOpen": bool(config.get("request_open")),
            "disposition": disposition.get("disposition"), "summary": disposition.get("summary"),
            "questions": sum(1 for question in workspace.store.list("agent_question", campaign_id)
                             if question["status"] == "pending" and question.get("agent_id") in {agent_id, None})}


def live_entry(workspace, campaign_id, agent_id):
    try:
        for row in workspace.pi.live(campaign_id)["agents"]:
            if row["agent_id"] == agent_id and row.get("run_id"):
                return row
    except (ValueError, KeyError, OSError):
        return None
    return None


def delta(previous, current):
    """JSON Patch replace operations for changed top-level fields."""
    return [{"op": "replace", "path": "/" + key, "value": value} for key, value in current.items() if previous.get(key) != value]


def stream_events(previous, state, entry, messages):
    """AG-UI events that take a listener from the previous observation to this one. Returns the next observation too."""
    events = []
    thread_id = state["threadId"]
    run = entry["run_id"] if entry else None
    old_run = previous.get("run")
    if run != old_run:
        if old_run:
            if previous.get("text"):
                events.append({"type": "TEXT_MESSAGE_END", "messageId": f"live_{old_run}"})
            for step in previous.get("steps", []):
                if not step["done"]:
                    events.append({"type": "TOOL_CALL_END", "toolCallId": step["id"]})
            failed = state["status"] == "failed"
            events.append({"type": "RUN_ERROR", "threadId": thread_id, "runId": old_run, "message": state.get("summary") or "The agent's turn failed; its work is saved."}
                          if failed else {"type": "RUN_FINISHED", "threadId": thread_id, "runId": old_run})
        if run:
            events.append({"type": "RUN_STARTED", "threadId": thread_id, "runId": run})
        previous = {"run": run, "text": "", "thinking": "", "steps": []}
    if entry and run:
        text, thinking = entry.get("text") or "", entry.get("thinking") or ""
        if text != previous["text"]:
            if not previous["text"]:
                events.append({"type": "TEXT_MESSAGE_START", "messageId": f"live_{run}", "role": "assistant"})
            tail = text[len(previous["text"]):] if text.startswith(previous["text"]) else text
            events.append({"type": "TEXT_MESSAGE_CONTENT", "messageId": f"live_{run}", "delta": tail})
        if thinking != previous["thinking"] and thinking:
            tail = thinking[len(previous["thinking"]):] if thinking.startswith(previous["thinking"]) else thinking
            events.append({"type": "THINKING_TEXT_MESSAGE_CONTENT", "delta": tail})
        steps = [{"id": f"{run}:{index}", "label": step["label"], "done": step["done"], "failed": step["failed"], "link": step.get("link")}
                 for index, step in enumerate(entry.get("steps", []))]
        known = {step["id"]: step for step in previous["steps"]}
        for step in steps:
            if step["id"] not in known:
                events.append({"type": "TOOL_CALL_START", "toolCallId": step["id"], "toolCallName": step["label"], "parentMessageId": f"live_{run}"})
            if step["done"] and not known.get(step["id"], {}).get("done"):
                events.append({"type": "TOOL_CALL_END", "toolCallId": step["id"], **({"failed": True} if step["failed"] else {}),
                               **({"link": step["link"]} if step.get("link") else {})})
        previous = {"run": run, "text": text, "thinking": thinking, "steps": steps}
    if messages != previous.get("messages"):
        events.append({"type": "MESSAGES_SNAPSHOT", "threadId": thread_id, "messages": messages})
    previous = {**previous, "messages": messages}
    state_before = previous.get("state")
    if state_before is None:
        events.append({"type": "STATE_SNAPSHOT", "snapshot": state})
    elif state != state_before:
        events.append({"type": "STATE_DELTA", "delta": delta(state_before, state)})
    previous = {**previous, "state": state}
    return events, previous
