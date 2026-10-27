"""Helpers shared by the service-layer tests: a command through the bus, a problem instance."""
import uuid


QUADRATIC = {"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}


def command(client, operation, campaign_id, payload, expected_revision, *, expect=200, **extra):
    body = {"id": "ui_" + uuid.uuid4().hex, "campaign_id": campaign_id, "operation": operation, "expected_revision": expected_revision, "payload": payload, **extra}
    response = client.post("/api/v1/commands", json=body)
    if expect is not None:
        assert response.status_code == expect, response.text
    return response.json()




def activate_team(client, workspace, campaign, monkeypatch):
    """Start the lead agent without a harness: the locked provider names a model; turns are driven by hand (finish_run)."""
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    command(client, "agent.activate", campaign["id"], {}, campaign["version"])
    config = workspace.pi.configuration(campaign["id"])
    return workspace.store.get(config["lead_id"], "agent_session")


def submitted(workspace, run_id):
    run = workspace.store.get(run_id, "agent_run")
    run["status"] = "submitted"
    workspace.store.put("agent_run", run)
    return run


def finish_run(workspace, run_id, text, *, entry_ids=None, status="completed", disposition=None):
    """What the harness reports when a turn ends: the controller turns it into the reply message and moves the thread's leaf."""
    run = workspace.store.get(run_id, "agent_run")
    if run["status"] == "queued":
        submitted(workspace, run_id)
    if disposition:
        run = workspace.store.get(run_id, "agent_run")
        run["disposition"] = {"disposition": disposition, "report": text}
        workspace.store.put("agent_run", run)
    agent = workspace.store.get(run["agent_id"], "agent_session")
    workspace.pi._receive(agent["id"], {"events": [], "cursor": agent.get("event_cursor", 0), "session_id": "session_1",
                                        "runs": {run_id: {"status": status, "result": {"text": text, **({"entry_ids": entry_ids} if entry_ids else {})}}}})
    return workspace.store.get(run_id, "agent_run")


def lead_run_for(workspace, command_id):
    return workspace.store.get("pi_run_" + command_id, "agent_run")


def state_of(workspace, agent, run=None):
    """The state block the agent's next turn would begin with (agents/turn_state.py), read without a run of its own."""
    from optimization_framework.agents.tools import PiTools
    from optimization_framework.agents.turn_state import build
    return build(PiTools(workspace.pi), agent, run or {"id": "probe", "input": "", "origin": None})["text"]


def tool_call(workspace, agent, run, name, args, call_id="call"):
    from optimization_framework.agents.tools import PiTools
    return PiTools(workspace.pi).call(agent["id"], run["id"], call_id, name, args)
