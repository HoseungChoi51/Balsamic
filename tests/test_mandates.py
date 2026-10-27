"""A mandate records what one researcher request allows (roadmap R1): its classes of work, what it names, its envelope. Every
command operation has a class, the templates follow decision 10, and every compute consent reads as a Screen mandate."""
from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest

from optimization_framework.campaigns import mandates
from optimization_framework.contracts.commands import Command, Operation
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace

ROOT = {"thread_id": "thread_main", "message_id": "message_ask", "run_id": "run_asked"}


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Mandates", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign["id"], workspace.current_tasks(campaign["id"])[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def granted(workspace, campaign_id, template="run_campaign", root=None, worker_seconds=0.0):
    """A mandate the researcher granted, for this request, or with no root campaign-wide: the bus checks an agent's commands
    against its request's mandate (R3), and a test of another guard grants the work first."""
    from optimization_framework.storage.sqlite import identifier, now
    decision = workspace.store.put("decision", {"id": identifier("decision"), "campaign_id": campaign_id, "title": "Go ahead", "question": "Go ahead",
        "status": "resolved", "requested_by": "researcher", "audience": "researcher", "created_at": now()})
    return mandates.grant(workspace, campaign_id, template, root=root, granted_by=decision["id"], compute={"worker_seconds": worker_seconds})


def proposal(workspace, campaign_id, identity):
    workspace.store.put("hypothesis", {"id": identity, "campaign_id": campaign_id, "title": identity, "status": "proposed"})


def approve(workspace, campaign_id, identity, plan):
    send(workspace, campaign_id, identity, "approval.request", {"kind": "compute", "rationale": "Screen it", "meanwhile": "Read the results", **plan})
    decision = workspace.store.list("decision", campaign_id)[-1]
    send(workspace, campaign_id, identity + "_yes", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
         "expected_resolution_revision": 0}, actor="researcher")
    return decision, workspace.store.list("compute_consent", campaign_id)[-1]


def test_every_operation_the_bus_lists_has_a_mandate_class(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    workspace = create_app(tmp_path / "workspace", start_workers=False).state.workspace
    listed = set(workspace.commands.describe())
    assert listed - set(mandates.CLASSES) == set(), "give each new operation a class in campaigns/mandates.py CLASSES"
    assert set(get_args(Operation)) - set(mandates.CLASSES) == set() and set(mandates.CLASSES) <= set(get_args(Operation))
    assert set(mandates.CLASSES.values()) == set(mandates.ALL_CLASSES)
    assert mandates.classes_of("intervention.batch", {"items": [{"operation": "hypothesis.status"}, {"operation": "hypothesis.create"}]}) == {"decide", "propose"}


def test_the_templates_follow_decision_10():
    classes = {name: set(template["classes"]) for name, template in mandates.TEMPLATES.items()}
    assert classes["answer"] == {"answer", "ask"}
    assert classes["explore"] == classes["answer"] | {"propose", "review", "run", "validate", "record"}
    assert classes["screen"] == classes["explore"] | {"implement", "decide"}
    assert classes["run_campaign"] == set(mandates.ALL_CLASSES)
    assert [name for name, template in mandates.TEMPLATES.items() if template["go_ahead"]] == ["screen", "run_campaign"]


def test_a_consent_recorded_before_mandates_reads_as_a_screen_mandate_with_its_plan_seconds_and_workspaces(lab):
    workspace, cid, task = lab
    # A consent recorded before B2, with none of the fields it added, and one recorded after it for H1 in a request.
    workspace.store.put("compute_consent", {"id": "compute_consent_old", "campaign_id": cid, "decision_id": "decision_old", "plan": "Old plan",
        "worker_seconds": 1200, "wall_seconds": 600, "coding_workspaces": 1, "used_seconds": 300.0, "used_workspaces": 0,
        "granted_at": "2026-10-20T00:00:00+00:00", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    proposal(workspace, cid, "H1")
    run = {"task_id": task["id"], "hypothesis_id": "H1", "seeds": [0, 1], "wall_seconds": 600}
    decision, consent = approve(workspace, cid, "screen_h1", {"plan": "Build and screen H1", "wall_seconds": 600, "worker_seconds": 2400,
                                                              "coding_workspaces": 1, "runs": [run]})
    before = {row["id"]: dict(row) for row in workspace.store.list("compute_consent", cid)}
    old, new = mandates.mandates(workspace, cid)
    assert (old.id, old.template, old.plan, old.root, old.hypothesis_ids, old.granted_by, old.consent_id) == \
        ("compute_consent_old", "screen", "Old plan", None, [], "decision_old", "compute_consent_old")
    assert (old.compute.worker_seconds, old.compute.coding_workspaces, old.used.worker_seconds, old.status) == (1200, 1, 300, "active")
    assert set(old.classes) == set(mandates.TEMPLATES["screen"]["classes"]) and old.model_usd is None and old.deadline_at is None
    assert (new.plan, new.hypothesis_ids, new.granted_by, new.compute.worker_seconds, new.compute.coding_workspaces) == \
        ("Build and screen H1", ["H1"], decision["id"], 2400, 1)
    assert [(item.task_id, item.hypothesis_id, item.seeds) for item in new.runs] == [(task["id"], "H1", [0, 1])]
    # A view, never a rewrite: the consents are as they were, and no mandate was recorded.
    assert {row["id"]: row for row in workspace.store.list("compute_consent", cid)} == before and workspace.store.list("mandate", cid) == []
    # An old consent covers the campaign, so it is a standing mandate for every request.
    assert mandates.active(workspace, cid, ROOT).id == consent["id"]
    workspace.store.put("compute_consent", {**before["compute_consent_old"], "expires_at": "2026-10-21T00:00:00+00:00"})
    assert mandates.mandates(workspace, cid)[0].status == "expired"


def test_explore_envelope_follows_the_campaigns_thresholds(lab):
    workspace, cid, _ = lab
    explore = mandates.grant(workspace, cid, "explore", root=ROOT)
    assert (explore.compute.worker_seconds, explore.compute.coding_workspaces, explore.granted_by, explore.status) == (300.0, 0, "automatic", "active")
    send(workspace, cid, "tighten", "campaign.update", {"compute_gate_seconds": 120, "rationale": "An expensive problem"}, actor="researcher")
    [explore] = mandates.mandates(workspace, cid)
    assert explore.compute.worker_seconds == 120.0
    mandates.charge(workspace, explore.id, 90)
    assert mandates.active(workspace, cid, ROOT).used.worker_seconds == 90
    mandates.charge(workspace, explore.id, 30)
    assert mandates.mandates(workspace, cid)[0].status == "exhausted" and mandates.active(workspace, cid, ROOT) is None
    answer = mandates.grant(workspace, cid, "answer", root=ROOT)
    assert answer.compute.worker_seconds == 0 and answer.status == "active"


def test_a_mandate_serves_only_its_own_request_unless_it_is_standing(lab):
    workspace, cid, _ = lab
    mine = mandates.grant(workspace, cid, "explore", root=ROOT)
    assert mandates.active(workspace, cid, ROOT).id == mine.id
    assert mandates.active(workspace, cid, {**ROOT, "message_id": "message_other", "run_id": "run_other"}) is None
    # A notice turn continuing the request has the same root, whatever its own run.
    assert mandates.active(workspace, cid, {**ROOT, "run_id": "run_notice"}).id == mine.id
    standing = mandates.grant(workspace, cid, "answer")
    assert mandates.active(workspace, cid, {"thread_id": "thread_side", "message_id": "message_side"}).id == standing.id


def test_screen_and_run_the_campaign_need_the_researchers_go_ahead_and_charge_their_consent(lab):
    workspace, cid, task = lab
    proposal(workspace, cid, "H1")
    with pytest.raises(ValueError, match="the researcher's go-ahead"):
        mandates.grant(workspace, cid, "screen", root=ROOT, compute={"worker_seconds": 600})
    with pytest.raises(ValueError, match="sets its own compute envelope"):
        mandates.grant(workspace, cid, "explore", compute={"worker_seconds": 6000})
    with pytest.raises(ValueError, match="not a hypothesis of this campaign"):
        mandates.grant(workspace, cid, "explore", hypothesis_ids=["H9"])
    decision, consent = approve(workspace, cid, "screen_h1", {"plan": "Screen H1", "wall_seconds": 600, "worker_seconds": 1200, "hypothesis_ids": ["H1"]})
    screen = mandates.grant(workspace, cid, "screen", root=ROOT, granted_by=decision["id"], consent_id=consent["id"], model_usd=2.0,
                            deadline_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                            stop_when={"text": "Both seeds of H1 finished", "machine": "all_runs_terminal"})
    assert (screen.plan, screen.hypothesis_ids, screen.compute.worker_seconds) == ("Screen H1", ["H1"], 1200)
    assert [mandate.id for mandate in mandates.mandates(workspace, cid)] == [screen.id]   # the consent is its compute part, not a second mandate
    receipt = send(workspace, cid, "seed_0", "trial.create", {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 590, "hypothesis_id": "H1"})
    trial_id = receipt["outcome"]["trial_id"]
    screen = mandates.charge(workspace, screen.id, model_usd=0.5)
    assert (screen.used.worker_seconds, screen.used.model_usd) == (590, 0.5)   # the bus charged the consent; the model spend is the mandate's
    assert workspace.store.get(consent["id"], "compute_consent")["launched"] == [trial_id]
    assert not mandates.stop_reached(workspace, screen)
    workspace.store.put("trial", {**workspace.store.get(trial_id, "trial"), "status": "completed"})
    assert mandates.stop_reached(workspace, screen)
    assert mandates.charge(workspace, screen.id, model_usd=1.5).status == "exhausted"   # the model envelope is spent
    workspace.store.put("compute_consent", {**workspace.store.get(consent["id"], "compute_consent"), "id": "compute_consent_alone"})
    with pytest.raises(ValueError, match="no model-spend envelope"):   # a consent no mandate names has none
        mandates.charge(workspace, "compute_consent_alone", model_usd=1)


def test_a_mandate_past_its_deadline_is_expired(lab):
    workspace, cid, _ = lab
    decision = {"id": "decision_run", "campaign_id": cid, "status": "resolved"}
    workspace.store.put("decision", decision)
    autopilot = mandates.grant(workspace, cid, "run_campaign", granted_by="decision_run", compute={"worker_seconds": 36000},
                               deadline_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    assert autopilot.root is None and autopilot.status == "expired" and set(autopilot.classes) == set(mandates.ALL_CLASSES)
    mandates.charge(workspace, autopilot.id, 60, coding=1, subjects=["development_one"], trial_ids=["trial_one"])
    [row] = workspace.store.list("mandate", cid)
    assert row["used"]["worker_seconds"] == 60 and row["opened"] == ["development_one"] and row["launched"] == ["trial_one"]
    assert mandates.mandates(workspace, cid)[0].workspace_ids == ["development_one"]
