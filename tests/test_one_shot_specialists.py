"""The two review specialists that only read answer in one call too (roadmap T3).

Their input is a reviewer's (the proposal, the tasks, the installed methods, what the asker cited) plus the resources, with a
cited trial read as its status, result and metrics and no reviewer's verdict; their result is their role's schema, saved as
submit_output saves it. GRATING_ONE_SHOT_ROLES returns a role to its session; with "analyst" in it, one call with the two
roles' briefs and schemas merged answers for either name (the harness plan's D2)."""
import json

import pytest

from optimization_framework.agents import calls
from optimization_framework.agents.roles import ROLE_OUTPUT_SCHEMAS
from optimization_framework.contracts.base import content_hash
from test_one_shot_reviews import Harness as ReviewerHarness, dispatch, proposal, reviewed
from test_pi_agents import invoke, prepared   # noqa: F401  (the fixture)

MODES = {"failure_modes": [
    {"mechanism": "A binary mask", "why_it_could_fail": "The task is continuous", "falsifying_test": "Read the candidate schema",
     "cost": "none", "severity": "high"},
    {"mechanism": "An annealer", "why_it_could_fail": "It is not installed", "falsifying_test": "Compare with the methods",
     "cost": "none", "severity": "medium"}]}


class Harness(ReviewerHarness):
    """The agent service, also offering the fast tier's model the specialists run on."""
    def status(self):
        status = super().status()
        status["models"].append({**status["models"][0], "id": "gpt-6-sol", "name": "Sol"})
        return status


def trial(w, c, identity="trial_1"):
    task = w.current_tasks(c["id"])[0]
    return w.store.put("trial", {"id": identity, "campaign_id": c["id"], "task_id": task["id"], "status": "completed", "algorithm": "coordinate",
        "algorithm_config": {"step": 0.1}, "created_at": "2026-10-27T11:00:00+00:00",
        "result": {"status": "completed", "best_objective": 0.731, "evaluations": 64, "history": list(range(500)),
                   "metrics": {"best_objective": 0.731, "wall_seconds": 12.5}}})


def test_a_specialists_input_holds_what_its_brief_needs_and_no_review(prepared):
    w, c, lead, _ = prepared
    h = proposal(w, c, "h1")
    verdict = reviewed(w, h, "r1", "reject", ["Use an installed method"])
    other = reviewed(w, proposal(w, c, "h2"), "r2", "test")
    run = trial(w, c)
    delegated = invoke(prepared, "delegate", {"role": "methodology_specialist", "objective": "Which installed methods fit H1?", "request_key": "m",
                                              "hypothesis_id": "h1", "evidence_ids": [run["id"], verdict["id"], other["id"], "h2"]}, "m")
    agent = w.store.get(delegated["agent_id"], "agent_session")
    assert (agent["one_shot"], agent["hypothesis_id"], agent["output_schema"]) == (True, "h1", ROLE_OUTPUT_SCHEMAS["methodology_specialist"])
    content = calls.assemble(w, c["id"], "methodology_specialist", agent["objective"], agent["evidence_ids"], "h1")
    text = json.dumps(content)
    # The methods, the representation, the proposal and the cited evidence: what the brief judges from.
    assert content["methods"] and content["tasks"][0]["representation"] and content["proposal"]["algorithm"] == "quantum_annealer"
    assert "resources" in content
    evidence = {item["record_id"]: item for item in content["assignment"]["evidence"]}
    cited = evidence[run["id"]]["record"]
    assert (cited["status"], cited["result"]["best_objective"], cited["metrics"]) == ("completed", 0.731, {"best_objective": 0.731, "wall_seconds": 12.5})
    assert "history" not in cited["result"] and cited["algorithm_config"] == {"step": 0.1}
    # No reviewer's verdict: neither on this proposal nor on another; a cited proposal is read without its reviews.
    assert "SECRET" not in text and {verdict["id"], other["id"]} == {key for key, item in evidence.items() if "not_read" in item}
    assert evidence["h2"]["kind"] == "hypothesis" and "reviews" not in evidence["h2"]["record"]
    # The brief's result paragraph stays, its tool lines go, and the schema is the role's.
    system = calls.instructions("methodology_specialist")
    assert "A good result" in system and "you have no tools" in system and "campaign_inspect" not in system and "submit_output" not in system
    assert json.dumps(ROLE_OUTPUT_SCHEMAS["methodology_specialist"]) in system


def test_a_specialists_result_is_saved_as_submit_output_saves_it_and_the_asker_is_told(prepared):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    w.pi.client = harness = Harness(reply=MODES)
    delegated = invoke(prepared, "delegate", {"role": "skeptical_domain_analyst", "objective": "How could H1 fail?", "request_key": "s"}, "s")
    agent = w.store.get(delegated["agent_id"], "agent_session")
    assert agent["hypothesis_id"] == "h1"   # named by its candidate id in the objective
    dispatch(w, c)
    [body] = harness.calls
    assert body["label"] == "skeptical_domain_analyst"
    run = w.store.get(delegated["run_id"], "agent_run")
    assert run["status"] == "completed" and run["output"] == MODES and run["result"]["text"] == "2 failure modes, 1 of high severity."
    assert w.store.get(delegated["agent_id"], "agent_session")["output"] == MODES
    call = w.store.get("agent_call_" + run["id"], "agent_call")
    assert call["status"] == "completed" and call["input"] == json.loads(body["prompt"]) and call["output"] == MODES
    # The asker is told, and pointed at the structured result, as for a session's submit_output.
    notice = w.store.get("pi_child_result_" + content_hash(run["id"])[:28], "agent_run")
    assert notice["agent_id"] == lead["id"] and "pointer /output" in notice["input"]
    refused = invoke(prepared, "agent_message", {"agent_id": delegated["agent_id"], "message": "And the seeds?"}, "follow")
    assert "answers once" in refused["error"]
    # No proposal is needed: a specialist asked about the campaign at large is given none.
    general = invoke(prepared, "delegate", {"role": "methodology_specialist", "objective": "Which methods fit this campaign?", "request_key": "g"}, "g")
    agent = w.store.get(general["agent_id"], "agent_session")
    assert agent["one_shot"] and "hypothesis_id" not in agent
    assert calls.assemble(w, c["id"], "methodology_specialist", agent["objective"], [], None)["proposal"] is None


def test_a_result_outside_the_schema_is_saved_as_nothing(prepared):
    w, c, lead, _ = prepared
    w.pi.client = harness = Harness(reply={"failure_modes": [{"mechanism": "x", "severity": "fatal"}]})
    delegated = invoke(prepared, "delegate", {"role": "skeptical_domain_analyst", "objective": "How could this fail?", "request_key": "s"}, "s")
    dispatch(w, c)
    run = w.store.get(delegated["run_id"], "agent_run")
    assert len(harness.calls) == 1 and run["status"] == "failed" and "invalid structured result" in run["error"]
    assert w.store.get(delegated["agent_id"], "agent_session").get("output") is None and run.get("output") is None
    assert w.store.get("agent_call_" + run["id"], "agent_call")["status"] == "failed"


def test_the_switch_returns_a_role_to_its_session(prepared, monkeypatch):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    monkeypatch.setenv("GRATING_ONE_SHOT_ROLES", "proposal_reviewer")
    session = invoke(prepared, "delegate", {"role": "methodology_specialist", "objective": "Which methods fit H1?", "request_key": "a"}, "a")
    agent = w.store.get(session["agent_id"], "agent_session")
    assert not agent.get("one_shot") and agent["output_schema"] == ROLE_OUTPUT_SCHEMAS["methodology_specialist"]
    monkeypatch.setenv("GRATING_ONE_SHOT_ROLES", "")
    reviewer = invoke(prepared, "delegate", {"role": "proposal_reviewer", "objective": "Review the proposals.", "request_key": "b"}, "b")
    assert not w.store.get(reviewer["agent_id"], "agent_session").get("one_shot")   # a session reviewer is not told one proposal
    monkeypatch.setenv("GRATING_ONE_SHOT_ROLES", "proposal_reviewer,results_analyst")
    with pytest.raises(ValueError, match="results_analyst"):
        calls.answers_as("methodology_specialist")
    monkeypatch.delenv("GRATING_ONE_SHOT_ROLES")
    assert {role: calls.answers_as(role) for role in ("proposal_reviewer", "methodology_specialist", "skeptical_domain_analyst", "literature_specialist")} == {
        "proposal_reviewer": "proposal_reviewer", "methodology_specialist": "methodology_specialist",
        "skeptical_domain_analyst": "skeptical_domain_analyst", "literature_specialist": None}


def test_one_analyst_answers_for_both_specialists_when_the_switch_names_it(prepared, monkeypatch):
    w, c, lead, _ = prepared
    proposal(w, c, "h1")
    monkeypatch.setenv("GRATING_ONE_SHOT_ROLES", "proposal_reviewer,analyst")
    w.pi.client = harness = Harness(reply=MODES)
    delegated = invoke(prepared, "delegate", {"role": "skeptical_domain_analyst", "objective": "How could H1 fail?", "request_key": "s"}, "s")
    agent = w.store.get(delegated["agent_id"], "agent_session")
    # The old name stays the session's role (an alias); the brief and the schema are the merged analyst's.
    assert (agent["role"], agent["answers_as"], agent["output_schema"]) == ("skeptical_domain_analyst", "analyst", calls.analyst_schema())
    assert set(agent["output_schema"]["properties"]) == {"fits", "failure_modes"}
    dispatch(w, c)
    [body] = harness.calls
    assert "As the methodology specialist" in body["system"] and "As the skeptical domain analyst" in body["system"]
    run = w.store.get(delegated["run_id"], "agent_run")
    assert run["status"] == "completed" and run["output"] == MODES   # one part is a valid answer
    assert w.store.get("agent_call_" + run["id"], "agent_call")["answers_as"] == "analyst"
