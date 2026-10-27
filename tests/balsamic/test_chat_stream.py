"""The lead's turn as AG-UI events: a pure fold over the harness's live view and the saved messages."""
from balsamic.threads.stream import stream_events


def types(events):
    return [event["type"] for event in events]


def test_a_turn_streams_text_steps_and_its_end():
    state = {"threadId": "thread_main_demo", "agentId": "lead_demo", "status": "running", "requestOpen": True}
    messages = [{"id": "message_1", "content": "hi"}]
    events, previous = stream_events({}, state, {"run_id": "pi_run_1", "text": "Look", "thinking": "", "steps": []}, messages)
    assert types(events) == ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "MESSAGES_SNAPSHOT", "STATE_SNAPSHOT"]
    assert events[2]["delta"] == "Look" and events[1]["messageId"] == "live_pi_run_1"
    entry = {"run_id": "pi_run_1", "text": "Looking now", "thinking": "hmm", "steps": [{"label": "Reading the campaign's state", "done": False, "failed": False, "link": None}]}
    events, previous = stream_events(previous, state, entry, messages)
    assert types(events) == ["TEXT_MESSAGE_CONTENT", "THINKING_TEXT_MESSAGE_CONTENT", "TOOL_CALL_START"]
    assert events[0]["delta"] == "ing now" and events[2] == {"type": "TOOL_CALL_START", "toolCallId": "pi_run_1:0", "toolCallName": "Reading the campaign's state", "parentMessageId": "live_pi_run_1"}
    entry["steps"][0].update(done=True, link="#experiments/trial_1")
    events, previous = stream_events(previous, state, entry, messages)
    assert events == [{"type": "TOOL_CALL_END", "toolCallId": "pi_run_1:0", "link": "#experiments/trial_1"}]
    done = {**state, "status": "waiting", "requestOpen": False}
    events, previous = stream_events(previous, done, None, messages + [{"id": "message_2", "content": "Looking now"}])
    assert types(events) == ["TEXT_MESSAGE_END", "RUN_FINISHED", "MESSAGES_SNAPSHOT", "STATE_DELTA"]
    assert {op["path"] for op in events[-1]["delta"]} == {"/status", "/requestOpen"}
    events, _ = stream_events(previous, done, None, messages + [{"id": "message_2", "content": "Looking now"}])
    assert events == []


def test_a_failed_turn_ends_with_an_error_and_open_steps_are_closed():
    state = {"threadId": "t", "agentId": "a", "status": "running"}
    _, previous = stream_events({}, state, {"run_id": "r1", "text": "", "thinking": "", "steps": [{"label": "Starting an experiment", "done": False, "failed": False}]}, [])
    events, _ = stream_events(previous, {**state, "status": "failed", "summary": "Provider refused"}, None, [])
    assert types(events) == ["TOOL_CALL_END", "RUN_ERROR", "STATE_DELTA"]
    assert events[1]["message"] == "Provider refused" and events[1]["runId"] == "r1"
    # The turn's own error comes first: a model the harness cannot reach says so, not only that the turn failed (issue #70).
    error = "Model unavailable: centinels/gpt-6.1-sol. The dev profile defines centinels from CENTINELS_BASE_URL, which is not set"
    events, _ = stream_events(previous, {**state, "status": "failed", "summary": "Provider refused", "error": error}, None, [])
    assert events[1]["message"] == error


def test_the_state_of_a_failed_agent_carries_its_turns_error(workspace, campaign):
    from balsamic.threads.stream import agent_state
    workspace.store.put("agent_session", {"id": "agent_lead_failed", "campaign_id": campaign["id"], "role": "lead", "status": "failed",
                                          "activity": "Model unavailable: centinels/gpt-6.1-sol"})
    assert agent_state(workspace, campaign["id"], "agent_lead_failed", "thread_main_demo")["error"] == "Model unavailable: centinels/gpt-6.1-sol"
    workspace.store.put("agent_session", {"id": "agent_lead_failed", "campaign_id": campaign["id"], "role": "lead", "status": "waiting",
                                          "activity": "Reading the campaign"})
    assert agent_state(workspace, campaign["id"], "agent_lead_failed", "thread_main_demo")["error"] is None
