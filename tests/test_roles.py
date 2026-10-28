"""Specialist roles (harness plan, Phase 7): a brief, a tool scope and an output schema each, from agents/roles; a contract of
their own instead of the shared instructions; a result submitted before the assignment is complete."""
import jsonschema
import pytest

from optimization_framework.agents import tools as tools_module
from optimization_framework.agents.discussions import view
from optimization_framework.agents.models import DISCUSSION_ROLES, NOTICE
from optimization_framework.agents.roles import BRIEF_WORDS, ROLE_BRIEFS, ROLE_OUTPUT_SCHEMAS, SPECIALIST_CONTRACT
from optimization_framework.agents.tools import INSTRUCTIONS, PiTools

from test_pi_agents import invoke, prepared   # noqa: F401  (the fixture)

FAILURE = {"failure_modes": [{"mechanism": "Hill climbing on 32,768 binary cells", "why_it_could_fail": "The lane is not installed",
                              "falsifying_test": "Check campaign_inspect.methods", "cost": "none", "severity": "high"}]}


def specialist(prepared, role="skeptical_domain_analyst", key="look"):
    w = prepared[0]
    child = invoke(prepared, "delegate", {"role": role, "objective": "Find how H1 could fail.", "request_key": key}, "delegate_" + key)
    w.store.put("agent_run", {**w.store.get(child["run_id"], "agent_run"), "status": "submitted"})
    return w.store.get(child["agent_id"], "agent_session"), w.store.get(child["run_id"], "agent_run")


def test_every_discussion_role_has_a_brief_and_a_valid_schema():
    assert set(ROLE_BRIEFS) == set(DISCUSSION_ROLES)
    for role, brief in ROLE_BRIEFS.items():
        assert brief["description"] and brief["tools"] and "yield_work" in brief["tools"] and len(brief["brief"].split()) <= BRIEF_WORDS, role
        if role == "proposal_reviewer":
            assert role not in ROLE_OUTPUT_SCHEMAS and "proposal_review" in brief["tools"]   # its proposal_review is its structured output
        else:
            jsonschema.Draft202012Validator.check_schema(ROLE_OUTPUT_SCHEMAS[role])
            assert "submit_output" in brief["tools"]
    assert len(SPECIALIST_CONTRACT.split()) <= 300


def test_a_specialist_is_told_its_contract_and_brief_and_given_its_tools_and_schema(prepared):
    w = prepared[0]
    agent, run = specialist(prepared)
    assert agent["output_schema"] == ROLE_OUTPUT_SCHEMAS["skeptical_domain_analyst"]
    manifest = PiTools(w.pi).manifest(agent["id"], run["id"])
    assert manifest["instructions"].startswith(SPECIALIST_CONTRACT) and INSTRUCTIONS.splitlines()[0] not in manifest["instructions"]
    assert ROLE_BRIEFS["skeptical_domain_analyst"]["brief"] in manifest["instructions"] and "submit_output using this JSON schema" in manifest["instructions"]
    names = {tool["name"] for tool in manifest["tools"]}
    assert names <= set(ROLE_BRIEFS["skeptical_domain_analyst"]["tools"]) | {"procedure_read"} and {"submit_output", "yield_work", "evidence_read"} <= names
    assert not {"source_search", "analysis_run", "workspace_write", "campaign_command"} & names
    w.store.put("hypothesis", {"id": "h1", "candidate_id": "H1", "campaign_id": prepared[1]["id"], "title": "H1", "mechanism": "Coordinate search."})
    reviewer, review_run = specialist(prepared, "proposal_reviewer", "review")
    reviewer_tools = {tool["name"] for tool in PiTools(w.pi).manifest(reviewer["id"], review_run["id"])["tools"]}
    assert "proposal_review" in reviewer_tools and "submit_output" not in reviewer_tools and reviewer["output_schema"] is None


def test_a_result_is_validated_and_submitted_before_the_assignment_is_complete(prepared):
    w = prepared[0]
    agent, run = specialist(prepared)
    call = lambda name, args, key: PiTools(w.pi).call(agent["id"], run["id"], key, name, args)
    refused = call("yield_work", {"disposition": "complete", "summary": "Done"}, "early")
    assert "submit_output first" in refused["error"]
    invalid = call("submit_output", {"result": {"failure_modes": [{"mechanism": "x", "severity": "fatal"}]}}, "invalid")
    assert invalid["executed"] is False and w.store.get(agent["id"], "agent_session")["output"] is None
    assert call("submit_output", {"result": FAILURE}, "valid") == {"saved": True}
    assert w.store.get(run["id"], "agent_run")["output"] == FAILURE
    assert call("yield_work", {"disposition": "complete", "summary": "One failure mode of high severity"}, "done")["saved"] is True


def test_a_specialist_past_its_tool_calls_may_only_record_its_result_and_end(prepared, monkeypatch):
    w = prepared[0]
    monkeypatch.setattr(tools_module, "SPECIALIST_TOOL_CALLS", 2)
    agent, run = specialist(prepared)
    call = lambda name, args, key: PiTools(w.pi).call(agent["id"], run["id"], key, name, args)
    call("campaign_inspect", {}, "one"); call("evidence_search", {"query": "H1"}, "two")
    assert "tool calls are spent" in call("evidence_search", {"query": "more"}, "three")["error"]
    assert call("submit_output", {"result": FAILURE}, "submit") == {"saved": True}
    assert call("yield_work", {"disposition": "complete", "summary": "Done"}, "end")["saved"] is True


def test_the_discussion_shows_results_and_the_asking_agent_is_told_where_to_read_them(prepared):
    w, c, lead, _ = prepared
    agent, run = specialist(prepared)
    PiTools(w.pi).call(agent["id"], run["id"], "submit", "submit_output", {"result": FAILURE})
    PiTools(w.pi).call(agent["id"], run["id"], "end", "yield_work", {"disposition": "complete", "summary": "One failure mode"})
    w.pi._receive(agent["id"], {"runs": {run["id"]: {"status": "completed", "result": {"text": "One failure mode."}}}, "events": [], "cursor": 0})
    notice = next(r for r in w.store.list("agent_run") if r["id"].startswith("pi_child_result_"))
    assert notice["input"].startswith(NOTICE) and "pointer /output" in notice["input"]
    person = view(w, c["id"])["rounds"][0]["assistants"][0]
    assert person["role"] == "skeptical_domain_analyst" and person["output"] == FAILURE and person["output_schema"] is True


def test_a_specialist_saved_before_roles_had_schemas_still_works(prepared):
    w, c, lead, _ = prepared
    old = w.pi.create_agent(c["id"], "results_analyst", "Summarise the runs.", "agent_saved_long_ago", parent_id=lead["id"])
    assert old["output_schema"] is None
    run = w.pi.enqueue(old, "assignment_agent_saved_long_ago", "Summarise the runs.")
    w.store.put("agent_run", {**run, "status": "submitted"})
    tools = PiTools(w.pi)
    manifest = tools.manifest(old["id"], run["id"])
    assert manifest["instructions"].startswith(SPECIALIST_CONTRACT) and "submit_output" not in {tool["name"] for tool in manifest["tools"]}
    assert tools.call(old["id"], run["id"], "end", "yield_work", {"disposition": "complete", "summary": "Two runs"})["saved"] is True
