"""Decisions 2 and 7: a proposal the lead records answering the researcher's message, or one a compute plan the researcher
approved names, runs without a concept review; one an agent made up on its own still waits for an independent review."""
import pytest

from optimization_framework.campaigns.proposals import hypothesis_revision, readiness
from optimization_framework.contracts.commands import Command, CommandOrigin
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Asked", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    cid = campaign["id"]
    workspace.store.put("agent_session", {"id": "agent_lead", "campaign_id": cid, "role": "lead"})
    workspace.store.put("agent_session", {"id": "agent_helper", "campaign_id": cid, "role": "analyst",
                                          "assignment_origin": {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_asked"}})
    turns = {
        "run_asked": {"thread_id": "thread_main", "message_id": "message_ask", "actor": "researcher"},
        "run_autopilot": {"thread_id": "thread_main", "message_id": "message_round", "actor": "autopilot"},
        "run_notice_of_asked": {"thread_id": "thread_main", "actor": "lab", "root": {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_asked"}},
        "run_notice_of_autopilot": {"thread_id": "thread_main", "actor": "lab",
                                    "root": {"thread_id": "thread_main", "message_id": "message_round", "run_id": "run_autopilot"}},
        "run_notice_alone": None,
    }
    for identity, origin in turns.items():
        workspace.store.put("agent_run", {"id": identity, "campaign_id": cid, "agent_id": "agent_lead", "status": "running", "origin": origin,
                                          "autopilot": identity == "run_autopilot"})
    workspace.store.put("agent_run", {"id": "run_helper", "campaign_id": cid, "agent_id": "agent_helper", "status": "running", "origin": {}})
    return workspace, campaign, workspace.current_tasks(cid)[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager", origin=None):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, origin=origin, **pins), actor=actor)


def from_turn(run_id, agent_id="agent_lead"):
    return CommandOrigin(thread_id="thread_main", actor="lead" if agent_id == "agent_lead" else "page_agent", agent_id=agent_id, run_id=run_id)


def create(workspace, campaign_id, identity, run_id, agent_id="agent_lead"):
    send(workspace, campaign_id, identity, "hypothesis.create", {"title": identity, "mechanism": "A coordinate search", "rationale": "r",
         "algorithm": "coordinate"}, origin=from_turn(run_id, agent_id) if run_id else None)
    return workspace.store.get("hypothesis_" + identity, "hypothesis")


def trial(task, hypothesis_id, seconds=30):
    return {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": seconds, "hypothesis_id": hypothesis_id}


def objection(workspace, hypothesis):
    workspace.store.put("agent_artifact", {"id": "review_of_" + hypothesis["id"], "campaign_id": hypothesis["campaign_id"], "agent_id": "agent_reviewer",
        "kind": "proposal_review", "created_at": "2026-10-27T10:00:00+00:00",
        "content": {"hypothesis_id": hypothesis["id"], "hypothesis_hash": hypothesis_revision(hypothesis), "verdict": "reject"}})


def test_a_proposal_the_lead_records_answering_the_researcher_runs_with_no_review(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    for identity, run_id in (("asked", "run_asked"), ("asked_later", "run_notice_of_asked")):
        hypothesis = create(workspace, cid, identity, run_id)
        assert hypothesis["requires_concept_review"] is True
        assert hypothesis["requested_by"] == {"thread_id": "thread_main", "message_id": "message_ask"}
        state = readiness(workspace.store, hypothesis)
        assert state["eligible"] and state["state"] == "not_required" and state["reason"] == "Asked for by the researcher."
        send(workspace, cid, "launch_" + identity, "trial.create", trial(task, hypothesis["id"]))
    # A reviewer's objection is shown as advice; it does not stop the run.
    objection(workspace, hypothesis)
    state = readiness(workspace.store, hypothesis)
    assert state["eligible"] and state["advisory"] == ["review_of_" + hypothesis["id"]] == state["review_ids"]
    send(workspace, cid, "run_after_objection", "trial.create", trial(task, hypothesis["id"]))


def test_a_proposal_from_autopilot_or_a_notice_without_a_researchers_request_still_waits_for_review(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    cases = (("autopilot", "run_autopilot", "agent_lead"), ("autopilot_notice", "run_notice_of_autopilot", "agent_lead"),
             ("lone_notice", "run_notice_alone", "agent_lead"), ("helper", "run_helper", "agent_helper"), ("no_turn", None, "agent_lead"))
    for identity, run_id, agent_id in cases:
        hypothesis = create(workspace, cid, identity, run_id, agent_id)
        assert "requested_by" not in hypothesis, identity
        assert readiness(workspace.store, hypothesis)["state"] == "pending"
        with pytest.raises(ValueError, match="independent conceptual review is required"):
            send(workspace, cid, "launch_" + identity, "trial.create", trial(task, hypothesis["id"]))


def test_a_proposal_named_in_an_approved_plan_runs_and_an_objection_is_advisory(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    named, other = create(workspace, cid, "named", "run_autopilot"), create(workspace, cid, "other", "run_autopilot")
    objection(workspace, named)
    send(workspace, cid, "plan", "approval.request", {"kind": "compute", "rationale": "Screen it", "meanwhile": "Read the charter",
         "plan": "Screen the named proposal", "wall_seconds": 600, "worker_seconds": 600, "hypothesis_ids": [named["id"]]})
    assert not readiness(workspace.store, workspace.store.get(named["id"], "hypothesis"))["eligible"]   # asked, not yet approved
    send(workspace, cid, "approve_plan", "decision.resolve", {"decision_id": "approval_plan", "choice": "0", "comment": "",
         "expected_resolution_revision": 0}, actor="researcher")
    consent_id = workspace.store.get("approval_plan", "decision")["outcome"]["consent_id"]
    named = workspace.store.get(named["id"], "hypothesis")
    assert named["approved_by"] == {"decision_id": "approval_plan", "consent_id": consent_id}
    state = readiness(workspace.store, named)
    assert state["eligible"] and state["reason"] == "In a plan the researcher approved." and state["advisory"] == ["review_of_" + named["id"]]
    send(workspace, cid, "run_named", "trial.create", trial(task, named["id"], seconds=590))
    # The plan approved only what it named.
    assert "approved_by" not in workspace.store.get(other["id"], "hypothesis")
    with pytest.raises(ValueError, match="independent conceptual review is required"):
        send(workspace, cid, "run_other", "trial.create", trial(task, other["id"]))
