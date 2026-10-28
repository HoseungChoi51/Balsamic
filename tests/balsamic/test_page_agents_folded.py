"""Roadmap T4: a campaign's page_agents switch. Under lead, the lead does the moderator's and the operator's work itself and answers
the researcher on their pages; under standing (the default) they keep their sessions and the routing is as before."""
import json

import pytest

from support import command, finish_run, state_of, submitted, tool_call


@pytest.fixture
def folded(client, workspace, campaign, monkeypatch):
    """The team started with page_agents lead; turns are driven by hand (finish_run)."""
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    command(client, "agent.activate", campaign["id"], {"page_agents": "lead"}, campaign["version"])
    return workspace.store.get(workspace.pi.configuration(campaign["id"])["lead_id"], "agent_session")


def version(workspace, campaign):
    return workspace.store.get(campaign["id"], "campaign")["version"]


def manifest(workspace, agent, run):
    from optimization_framework.agents.tools import PiTools
    found = PiTools(workspace.pi).manifest(agent["id"], run["id"])
    return found["instructions"], {tool["name"]: tool for tool in found["tools"]}


def operations(tools):
    return set(tools["campaign_command"]["input_schema"]["properties"]["operation"]["enum"])


def lead_turn(client, workspace, campaign, text, **extra):
    receipt = command(client, "agent.message", campaign["id"], {"message": text, **extra}, version(workspace, campaign))
    return submitted(workspace, "pi_run_" + receipt["id"])


def test_under_lead_the_lead_has_the_folded_pages_operations_tools_and_procedures(client, workspace, campaign, folded):
    from optimization_framework.agents.tools import LEAD_PAGE_WORK, ROLE_OPERATIONS
    assert workspace.pi.configuration(campaign["id"])["page_agents"] == "lead"
    run = lead_turn(client, workspace, campaign, "Wait for my next message.")
    instructions, tools = manifest(workspace, folded, run)
    # The moderator's and the operator's commands are the lead's; the implementation lead's stay refused.
    assert ROLE_OPERATIONS["discussion_moderator"] | ROLE_OPERATIONS["experiment_operator"] <= operations(tools)
    assert not {op for op, owner in LEAD_PAGE_WORK.items() if owner == "implementation_lead"} & operations(tools)
    assert operations(tools) == set(tools["command_schema"]["input_schema"]["properties"]["operation"]["enum"])
    assert {"config_suggest", "review_synthesis", "experiment_progress", "delegate"} <= set(tools)
    assert tools["page_agent_message"]["input_schema"]["properties"]["page_agent"]["enum"] == ["implementation_lead", "resource_planner"]
    # Their page instructions are procedures the lead reads when needed, named in its catalog.
    assert "procedure review-rounds" in instructions and "procedure running-experiments" in instructions
    assert "- review-rounds:" in instructions and "- running-experiments:" in instructions
    assert "Three agents are in charge of a page" not in instructions
    body = tool_call(workspace, folded, run, "procedure_read", {"name": "running-experiments"}, call_id="read")
    assert "experiment_progress" in body["text"] and "trial.hide" in body["text"]
    assert "reviewer's own word" in tool_call(workspace, folded, run, "procedure_read", {"name": "review-rounds"}, call_id="read2")["text"]
    # A run is the lead's to start; a build still goes to the implementation lead.
    refused = tool_call(workspace, folded, run, "campaign_command", {"operation": "trial.create", "payload": {}, "request_key": "t"}, call_id="trial")
    assert "experiment operator" not in str(refused.get("error"))
    refused = tool_call(workspace, folded, run, "campaign_command", {"operation": "implementation.commission", "payload": {}, "request_key": "i"}, call_id="impl")
    assert refused["executed"] is False and "implementation lead" in refused["error"]
    asked = tool_call(workspace, folded, run, "page_agent_message", {"page_agent": "experiment_operator", "message": "Run two."}, call_id="ask")
    assert asked["executed"] is False and not [a for a in workspace.store.list("agent_session", campaign["id"]) if a["role"] == "experiment_operator"]
    inspected = tool_call(workspace, folded, run, "campaign_inspect", {}, call_id="inspect")
    assert {(p["role"], p.get("answered_by")) for p in inspected["page_agents"]} == {("discussion_moderator", "lead"), ("experiment_operator", "lead")}
    # The operator's state (the experiment rules) is in the lead's state block.
    assert "The campaign's experiment rules" in state_of(workspace, folded)


def test_under_standing_the_lead_and_the_procedures_are_as_before(client, workspace, campaign, team):
    assert workspace.pi.configuration(campaign["id"])["page_agents"] == "standing"
    run = lead_turn(client, workspace, campaign, "Wait for my next message.")
    instructions, tools = manifest(workspace, team, run)
    assert "Three agents are in charge of a page" in instructions and "review-rounds" not in instructions
    assert not {"config_suggest", "review_synthesis"} & set(tools) and "trial.create" not in operations(tools)
    refused = tool_call(workspace, team, run, "procedure_read", {"name": "review-rounds"}, call_id="read")
    assert refused["executed"] is False
    assert "The campaign's experiment rules" not in state_of(workspace, team)


@pytest.fixture
def team(client, workspace, campaign, monkeypatch):
    from support import activate_team
    monkeypatch.delenv("GRATING_PAGE_AGENTS", raising=False)
    return activate_team(client, workspace, campaign, monkeypatch)


def test_a_researchers_message_on_experiments_reaches_the_lead_which_answers_on_the_page(client, workspace, campaign, folded):
    receipt = command(client, "agent.message", campaign["id"], {"message": "How are the runs going?", "page_agent": "experiment_operator"},
                      version(workspace, campaign))
    run = workspace.store.get("pi_run_" + receipt["id"], "agent_run")
    assert run["agent_id"] == folded["id"] and run["origin"]["thread_id"] == "desk_experiment_operator"
    assert workspace.pi.configuration(campaign["id"])["request_open"]
    assert not [a for a in workspace.store.list("agent_session", campaign["id"]) if a["role"] == "experiment_operator"]
    finish_run(workspace, run["id"], "No runs yet. See [Experiments](#experiments).", disposition="complete")
    desk = client.get(f"/api/v1/campaigns/{campaign['id']}/desks/experiment_operator").json()
    assert desk["answered_by"] == "lead" and desk["agent"]["role"] == "lead" and desk["page"] == "#experiments"
    assert [(m["role"], m["content"]) for m in desk["messages"]] == [("user", "How are the runs going?"),
                                                                    ("assistant", "No runs yet. See [Experiments](#experiments).")]
    # The exchange stays on the page, not in the chat.
    chat = client.get(f"/api/v1/threads/thread_main_{campaign['id']}/messages").json()["messages"]
    assert not [m for m in chat if m.get("desk") or "runs going" in m["content"]]
    # The other pages keep their agents.
    planner = command(client, "agent.message", campaign["id"], {"message": "Plan.", "page_agent": "resource_planner"}, version(workspace, campaign))
    assert workspace.store.get(workspace.store.get("pi_run_" + planner["id"], "agent_run")["agent_id"], "agent_session")["role"] == "resource_planner"
    assert client.get(f"/api/v1/campaigns/{campaign['id']}/desks/resource_planner").json()["answered_by"] == "resource_planner"


def test_under_lead_the_lead_records_the_synthesis_of_a_round_it_ran(client, workspace, campaign, folded):
    workspace.store.put("hypothesis", {"id": "h1", "candidate_id": "H1", "campaign_id": campaign["id"], "title": "H1", "mechanism": "Coordinate search.",
                                       "requires_concept_review": True, "created_at": "2026-10-27T10:00:00+00:00"})
    run = lead_turn(client, workspace, campaign, "Have H1 reviewed.", page_agent="discussion_moderator")
    asked = tool_call(workspace, folded, run, "delegate", {"role": "proposal_reviewer", "objective": "Review H1.", "request_key": "h1", "hypothesis_id": "h1"},
                      call_id="review")
    reviewer = workspace.store.get(asked["agent_id"], "agent_session")
    reviewer.update(status="completed"); workspace.store.put("agent_session", reviewer)
    for row in workspace.store.list("agent_run", campaign["id"]):
        if row["agent_id"] == reviewer["id"]:
            workspace.store.put("agent_run", {**row, "status": "completed"})
    held = tool_call(workspace, folded, run, "yield_work", {"disposition": "complete", "summary": "Reviewed"}, call_id="early")
    assert "review_synthesis" in held["error"]


def test_the_switch_changes_only_in_the_dev_profile_and_with_no_request_open(client, workspace, campaign, team, tmp_path, monkeypatch):
    configure = lambda mode, expect=200: command(client, "agent.configure", campaign["id"], {"page_agents": mode}, version(workspace, campaign), expect=expect)
    refused = configure("lead", expect=None)
    assert "dev profile" in json.dumps(refused)
    profile = tmp_path / "profile"; profile.mkdir()
    (profile / "settings.json").write_text(json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.5"}))
    monkeypatch.setenv("GRATING_PI_PROFILE", str(profile))
    run = lead_turn(client, workspace, campaign, "Wait.")
    assert "request is open" in json.dumps(configure("lead", expect=None))
    finish_run(workspace, run["id"], "Waiting.", disposition="complete")
    workspace.pi._request(campaign["id"], False)
    configure("lead")
    assert workspace.pi.folded(campaign["id"]) == {"discussion_moderator", "experiment_operator"}
    configure("standing")
    assert workspace.pi.folded(campaign["id"]) == frozenset()
    assert "Change page_agents on its own" in json.dumps(command(client, "agent.configure", campaign["id"],
        {"page_agents": "lead", "follow_tier": True}, version(workspace, campaign), expect=None))


def test_the_default_comes_from_the_environment_and_an_unknown_value_is_refused(monkeypatch):
    from optimization_framework.agents.models import folded, page_agents_mode
    monkeypatch.delenv("GRATING_PAGE_AGENTS", raising=False)
    assert page_agents_mode() == "standing" and page_agents_mode("lead") == "lead"
    monkeypatch.setenv("GRATING_PAGE_AGENTS", "lead")
    assert page_agents_mode() == "lead"
    monkeypatch.setenv("GRATING_PAGE_AGENTS", "everyone")
    with pytest.raises(ValueError, match="standing or lead"):
        page_agents_mode()
    assert folded({}) == frozenset() and folded({"page_agents": "lead"}) == {"discussion_moderator", "experiment_operator"}
