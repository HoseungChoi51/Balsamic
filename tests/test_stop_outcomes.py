"""Roadmap V1: a stop is a typed outcome resting on evidence, so an under-tuned method and a bad mechanism read differently."""
import pytest
from pydantic import ValidationError

from optimization_framework.campaigns.hypotheses import stop_of
from optimization_framework.contracts.commands import Command, HypothesisStatusInput, STOP_OUTCOMES
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace
from optimization_framework.storage.sqlite import now


def prepare(path):
    workspace = Workspace(path)
    campaign = workspace.create_campaign(CampaignInput(name="Stops", autonomy="delegated", compute_budget_seconds=100,
        validation_reserve_seconds=0, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    target = workspace.commands.execute(Command(id="create", campaign_id=campaign["id"], expected_revision=campaign["version"],
        operation="hypothesis.create", payload={"title": "Annealing", "mechanism": "m", "rationale": "r", "algorithm": "coordinate"}))
    return workspace, campaign, target["outcome"]["hypothesis"]


def trial(workspace, campaign, identity, **fields):
    workspace.store.put("trial", {"id": identity, "campaign_id": campaign["id"], "status": "completed", "created_at": now(), **fields})
    return identity


def stop(workspace, campaign, target, identity, actor="manager", **payload):
    current = workspace.store.get(campaign["id"], "campaign")
    command = Command(id=identity, campaign_id=campaign["id"], expected_revision=current["version"], operation="hypothesis.status",
        payload={"hypothesis_id": target["id"], "status": "archived", "expected_status_revision": 0, **payload})
    if actor != "researcher":
        command = command.model_copy(update={"expected_guidance_revision": workspace.memory.state(campaign["id"])["guidance_revision"],
                                             "expected_authority_hash": workspace.commands.authority_hash(current)})
    return workspace.commands.execute(command, actor=actor)


def test_the_six_outcomes_of_decision_13():
    assert set(STOP_OUTCOMES) == {"implementation_invalid", "assumptions_incompatible", "configuration_unpromising", "under_evaluated",
                                  "unaffordable_within_allocation", "adequately_assessed_deprioritized"}
    with pytest.raises(ValidationError):
        HypothesisStatusInput(hypothesis_id="h", status="archived", expected_status_revision=0, outcome="dominated")
    with pytest.raises(ValidationError, match="archived only"):
        HypothesisStatusInput(hypothesis_id="h", status="investigating", expected_status_revision=0, outcome="under_evaluated")


@pytest.mark.parametrize("actor", ["manager", "autopilot"])
def test_an_agent_stop_without_an_outcome_or_evidence_is_refused_with_the_text(tmp_path, actor):
    workspace, campaign, target = prepare(tmp_path)
    evidence = trial(workspace, campaign, "trial_seen", split="development")
    with pytest.raises(ValueError, match="needs a stop outcome and at least one evidence id"):
        stop(workspace, campaign, target, "no_outcome", actor=actor, stop_reason="dominated", evidence_ids=[evidence])
    with pytest.raises(ValueError, match="needs a stop outcome and at least one evidence id"):
        stop(workspace, campaign, target, "no_evidence", actor=actor, outcome="configuration_unpromising")
    assert workspace.store.get(target["id"], "hypothesis")["status"] == "proposed"
    rejected = {row["command_id"]: row["reason"] for row in workspace.store.list("command_rejection", campaign["id"])}
    assert "stop outcome" in rejected["no_outcome"] and "stop outcome" in rejected["no_evidence"]


def test_an_agent_stop_citing_an_invisible_record_is_refused(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    seen = trial(workspace, campaign, "trial_seen", split="development")
    locked = trial(workspace, campaign, "trial_locked", split="development", locked=True)
    other = workspace.create_campaign(CampaignInput(name="Other", tasks=[TaskInput(name="Other", problem_id="bounded_continuous")]))
    elsewhere = trial(workspace, other, "trial_elsewhere", split="development")
    for identity, cited in (("locked", locked), ("elsewhere", elsewhere), ("missing", "trial_never_was")):
        with pytest.raises(ValueError, match=f"not a visible record of this campaign: {cited}"):
            stop(workspace, campaign, target, identity, outcome="under_evaluated", evidence_ids=[seen, cited])
    assert workspace.store.get(target["id"], "hypothesis")["status"] == "proposed"


def test_an_agent_stop_with_its_outcome_and_evidence_is_recorded(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    evidence = trial(workspace, campaign, "trial_seen", split="development")
    review = workspace.commands.execute(Command(id="review", campaign_id=campaign["id"], expected_revision=campaign["version"],
        operation="hypothesis.review", payload={"hypothesis_id": target["id"], "text": "one default configuration only"}))
    review_id = review["outcome"]["hypothesis"]["reviews"][0]["id"]
    stop(workspace, campaign, target, "stop", actor="autopilot", outcome="under_evaluated", evidence_ids=[evidence, review_id, evidence],
         stop_reason="only the default configuration ran")
    stopped = workspace.store.get(target["id"], "hypothesis")
    assert stopped["status"] == "archived" and stopped["stop_reason"] == "only the default configuration ran"
    assert stopped["stop"] == {"outcome": "under_evaluated", "evidence_ids": [evidence, review_id], "reason": "only the default configuration ran",
                               "by": "autopilot", "at": stopped["stopped_at"]}
    assert stop_of(stopped)["label"] == "stopped: under-evaluated"


def test_the_researchers_stop_without_an_outcome_records_researcher_decision(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    stop(workspace, campaign, target, "stop", actor="researcher", stop_reason="not worth the time")
    stopped = workspace.store.get(target["id"], "hypothesis")
    assert stopped["stop"]["outcome"] == "researcher_decision" and stopped["stop"]["by"] == "researcher" and stopped["stop"]["evidence_ids"] == []
    assert stop_of(stopped)["label"] == "stopped: researcher's decision"
    # Taken up again, the stop is gone with its reason.
    workspace.commands.execute(Command(id="revive", campaign_id=campaign["id"], expected_revision=campaign["version"], operation="hypothesis.status",
        payload={"hypothesis_id": target["id"], "status": "investigating", "expected_status_revision": 1}))
    revived = workspace.store.get(target["id"], "hypothesis")
    assert "stop" not in revived and "stop_reason" not in revived and stop_of(revived) is None


def test_the_researcher_may_give_an_outcome_but_not_cite_an_invisible_record(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    with pytest.raises(ValueError, match="not a visible record"):
        stop(workspace, campaign, target, "hidden", actor="researcher", outcome="implementation_invalid", evidence_ids=["trial_never_was"])
    stop(workspace, campaign, target, "stop", actor="researcher", outcome="implementation_invalid")
    assert stop_of(workspace.store.get(target["id"], "hypothesis"))["label"] == "stopped: implementation invalid"


def test_a_record_stopped_before_typed_outcomes_reads_as_unspecified(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    old = {**workspace.store.get(target["id"], "hypothesis"), "status": "archived", "stop_reason": "dominated", "stopped_at": "2026-10-20T00:00:00Z"}
    workspace.store.put("hypothesis", old, "hypothesis.status")
    assert stop_of(old) == {"outcome": "unspecified", "evidence_ids": [], "reason": "dominated", "by": None, "at": "2026-10-20T00:00:00Z",
                            "words": "no outcome recorded", "label": "stopped: no outcome recorded"}
    from balsamic.evolution.ledger import rows
    row = next(row for row in rows(workspace, campaign["id"])[0] if row["id"] == target["id"])
    assert row["stage"] == "stopped" and row["stop"]["outcome"] == "unspecified" and row["stop_reason"] == "dominated"
