"""Roadmap V5: each ledger row shows its gates, why a closed one refuses a transition and what opens it; the researcher
waives a gate in one step (decision 16)."""
import pytest

from balsamic.evolution import ledger
from optimization_framework.execution.service import Workspace

from test_assessment_gate import prepare, run, stop, stopped, trials
from test_promotion_fidelity import PART_F, campaign_of, order_check, promote, publish, strategy
from test_promotion_fidelity import run as command


def row_of(workspace, campaign_id, hypothesis_id):
    return next(row for row in ledger.rows(workspace, campaign_id)[0] if row["id"] == hypothesis_id)


def gate_of(row, name):
    return next((gate for gate in row["gates"] if gate["gate"] == name), None)


def waive(workspace, campaign, field, hypothesis_id, evidence, actor="researcher", identity="waive_gate"):
    return run(workspace, campaign, identity, "validation.waive", {field: hypothesis_id, "rationale": "the default is the paper's setting",
                                                                    "evidence_ids": evidence}, actor=actor)


def test_a_row_shows_the_closed_assessment_gate_and_the_researchers_waiver_opens_it(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    row = row_of(workspace, campaign["id"], target["id"])
    gate = gate_of(row, "assessment")
    assert gate["state"] == "closed" and gate["transition"] == "stop as inferior" and gate["words"] == "1 of 3 configurations, 1 seed each"
    assert "1 of 3 configurations; 1 of 2 seeds" in gate["why"] and gate["unlock"]["waive"] is True
    assert "5 runs" in gate["unlock"]["runs"] and gate["evidence_ids"] == runs
    # Only the researcher waives a gate; the agent asks (approval.request), and its stop as inferior stays refused.
    with pytest.raises(ValueError, match="Only the researcher waives a proposal's gate"):
        waive(workspace, campaign, "tuning_hypothesis_id", target["id"], runs, actor="manager", identity="agent_waive")
    with pytest.raises(ValueError, match="needs an adequate assessment first"):
        stop(workspace, campaign, target, "refused", "configuration_unpromising", runs)
    outcome = waive(workspace, campaign, "tuning_hypothesis_id", target["id"], runs)["outcome"]
    gate = gate_of(row_of(workspace, campaign["id"], target["id"]), "assessment")
    assert gate["state"] == "waived" and gate["waiver_id"] == outcome["waiver_id"] == workspace.store.list("waiver")[0]["id"]
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)
    assert stopped(workspace, target)["stop"]["assessment"]["waiver_id"] == outcome["waiver_id"]
    # A stopped proposal has no stop left to gate.
    assert gate_of(row_of(workspace, campaign["id"], target["id"]), "assessment") is None


def test_an_adequate_assessment_is_an_open_gate_and_needs_no_waiver(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 3, [0, 1])
    gate = gate_of(row_of(workspace, campaign["id"], target["id"]), "assessment")
    assert gate["state"] == "open" and "why" not in gate and gate["words"] == "3 of 3 configurations, 2 seeds each"
    with pytest.raises(ValueError, match="no waiver is needed"):
        waive(workspace, campaign, "tuning_hypothesis_id", target["id"], runs)
    # The bounded continuous problem declares no fidelity check: its gate is open.
    fidelity = gate_of(row_of(workspace, campaign["id"], target["id"]), "fidelity")
    assert fidelity["state"] == "open" and fidelity["words"] == "not required for this problem"


def test_a_proposal_never_run_cannot_be_waived_through(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    assert gate_of(row_of(workspace, campaign["id"], target["id"]), "assessment")["unlock"]["waive"] is False
    workspace = Workspace(tmp_path / "2d")
    campaign = campaign_of(workspace)
    hypothesis = command(workspace, campaign["id"], "hypothesis.create", {"title": "Unrun", "mechanism": "m", "rationale": "r", "algorithm": "random"})["hypothesis"]
    gate = gate_of(row_of(workspace, campaign["id"], hypothesis["id"]), "fidelity")
    assert gate["state"] == "closed" and "no measured run" in gate["why"] and gate["unlock"] == {"runs": "Run it first.", "check": None, "waive": False}
    with pytest.raises(ValueError, match="run it first"):
        command(workspace, campaign["id"], "validation.waive", {"fidelity_hypothesis_id": hypothesis["id"], "rationale": "r", "evidence_ids": [hypothesis["id"]]})


def test_a_failed_fidelity_check_shows_why_and_the_researchers_waiver_unlocks_finalist_and_library(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    hypothesis, trial = strategy(workspace, campaign, score=PART_F[(10, 5)])
    requirement, result, _ = order_check(workspace, trial, PART_F)
    row = row_of(workspace, campaign["id"], hypothesis["id"])
    assert row["fidelity"]["state"] == "failed" and row["fidelity"]["words"] == "failed: meent_2d_order_convergence:v1"
    gate = gate_of(row, "fidelity")
    assert gate["state"] == "closed" and gate["transition"] == "finalist and library" and gate["words"] == "failed"
    assert "does not hold at higher fidelity" in gate["why"]
    assert gate["unlock"] == {"runs": None, "check": None, "waive": True} and gate["evidence_ids"] == [trial["id"], result["id"]]
    with pytest.raises(ValueError, match="does not hold at higher fidelity"):
        promote(workspace, campaign, hypothesis, "manager")
    with pytest.raises(ValueError, match="Only the researcher waives a proposal's gate"):
        command(workspace, campaign["id"], "validation.waive", {"fidelity_hypothesis_id": hypothesis["id"], "rationale": "r", "evidence_ids": [trial["id"]]}, actor="manager")
    outcome = command(workspace, campaign["id"], "validation.waive", {"fidelity_hypothesis_id": hypothesis["id"], "rationale": "the paper's orders",
                                                                     "evidence_ids": [trial["id"]]})
    assert outcome["requirement_ids"] == [requirement["id"]]
    gate = gate_of(row_of(workspace, campaign["id"], hypothesis["id"]), "fidelity")
    assert gate["state"] == "waived" and outcome["waiver_id"] in gate["evidence_ids"]
    assert promote(workspace, campaign, hypothesis, "manager")["promotion"]["state"] == "waived"
    assert publish(workspace, campaign, hypothesis)["entry"]["evidence"]["fidelity"]["state"] == "waived"


def test_an_unchecked_score_names_the_check_to_run_and_the_waiver_creates_its_requirement(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    hypothesis, trial = strategy(workspace, campaign, score=0.9)
    gate = gate_of(row_of(workspace, campaign["id"], hypothesis["id"]), "fidelity")
    assert gate["state"] == "closed" and "has not been checked" in gate["why"]
    assert gate["unlock"]["check"] == {"trial_id": trial["id"], "recipe_id": "meent_2d_order_convergence:v1", "parameters": {"absolute_tolerance": .005}}
    # The waiver creates the requirement on the best run's best design, as validation.require would, then waives it.
    made = []

    def require_only(trial_id, request, *, authority, require_only):
        assert (trial_id, request.recipe_id, request.parameters, authority, require_only) == (
            trial["id"], "meent_2d_order_convergence:v1", {"absolute_tolerance": .005}, "researcher", True)
        made.append(order_check(workspace, trial, {(10, 5): 0.9, (26, 22): 0.9})[0]["id"])
        return {"requirement_ids": made}
    monkeypatch.setattr(workspace, "run_recipe", require_only)
    outcome = command(workspace, campaign["id"], "validation.waive", {"fidelity_hypothesis_id": hypothesis["id"], "rationale": "r", "evidence_ids": [trial["id"]]})
    assert outcome["requirement_ids"] == made and workspace.store.get(outcome["waiver_id"], "waiver")["requirement_id"] == made[0]


def test_a_waiver_names_exactly_one_subject(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    with pytest.raises(ValueError, match="exactly one of requirement_id, tuning_hypothesis_id or fidelity_hypothesis_id"):
        run(workspace, campaign, "both", "validation.waive", {"tuning_hypothesis_id": target["id"], "fidelity_hypothesis_id": target["id"],
                                                             "rationale": "r", "evidence_ids": runs}, actor="researcher")
