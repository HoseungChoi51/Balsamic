"""V3: a score becomes a finalist or a library entry only once the problem's fidelity check passed on it, or the researcher waived it."""
import math

import pytest

from dqn_meent.problem_2d import Meent2DProblem, ORDER_CONVERGENCE_RECIPE
from optimization_framework.campaigns import promotion
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.contracts.validation import ValidationRequirement, ValidationResult
from optimization_framework.evaluation.recipes import compile_recipe
from optimization_framework.execution.service import Workspace
from optimization_framework.storage.sqlite import now

CONFIGURATION = {"wavelength_nm": 1050, "target_angle_deg": 75, "period_x_nm": 1050 / math.sin(math.radians(75)),
    "period_y_nm": 525, "thickness_nm": 325, "grid_x": 4, "grid_y": 2, "incident_n": 1.45, "exit_n": 1.0,
    "incident_angle_deg": 0, "target_order_x": 1, "target_order_y": 0, "silicon_index_source": "Fixture",
    "silicon_n_1050": 3.567390909090909, "reference_meent_version": "0.9.5"}
DESIGN = [0, 1, 0, 1, 1, 0, 1, 0]
# Readiness Part F: a design found at RCWA orders (10, 5) scored 93.75% there and 67.56% at (26, 22).
PART_F = {(10, 5): 0.9375, (26, 22): 0.6756}
LADDER = [{"rcwa_order_x": 10, "rcwa_order_y": 5}, {"rcwa_order_x": 26, "rcwa_order_y": 22}]


def run(workspace, campaign_id, operation, payload, *, actor="researcher", identity=None):
    campaign = workspace.store.get(campaign_id, "campaign")
    command = Command(id=identity or f"{operation.replace('.', '_')}_{actor}_{len(workspace.store.list('work_command'))}",
        campaign_id=campaign_id, operation=operation, expected_revision=campaign["version"], payload=payload,
        expected_guidance_revision=workspace.memory.state(campaign_id)["guidance_revision"],
        expected_authority_hash=workspace.commands.authority_hash(campaign))
    return workspace.commands.execute(command, actor=actor)["outcome"]


def campaign_of(workspace, problem_id="meent_2d_dual_polarization_deflector"):
    task = (TaskInput(name="2D deflector", problem_id=problem_id, configuration=CONFIGURATION, fidelity=LADDER[0])
            if problem_id.startswith("meent") else TaskInput(name="Trap", problem_id=problem_id, fidelity={"resolution": "coarse"})
            if problem_id == "fidelity_trap" else TaskInput(name="Quadratic", problem_id=problem_id))
    return workspace.create_campaign(CampaignInput(name="Promotion", autonomy="delegated", compute_budget_seconds=10000, validation_reserve_seconds=0, tasks=[task]))


def strategy(workspace, campaign, *, score, title="Level-set search"):
    """A researcher's proposal with one finished run whose best design scored `score` at the searched orders."""
    hypothesis = run(workspace, campaign["id"], "hypothesis.create", {"title": title, "mechanism": "m", "rationale": "r", "algorithm": "random"})["hypothesis"]
    task = workspace.current_tasks(campaign["id"])[0]
    trial = {"id": "trial_" + hypothesis["id"], "campaign_id": campaign["id"], "task_id": task["id"], "study_id": campaign["active_study_id"],
             "hypothesis_id": hypothesis["id"], "algorithm": "random", "status": "completed", "seed": 0, "max_steps": 10, "wall_seconds": 60,
             "execution_seconds": 50, "control_revision": 0, "created_at": now(), "problem": task["problem"],
             "result": {"best_objective": score, "best_candidate": DESIGN if task["problem"]["definition_id"].startswith("meent") else None,
                        "evaluations": 10, "scientific_complete": True}}
    workspace.store.put("trial", trial, "trial.evidence_cataloged")
    return hypothesis, trial


def order_check(workspace, trial, scores):
    """The order-convergence recipe on the run's best design, measured as `scores` at the ladder's orders (both polarizations equal)."""
    problem = ProblemInstance(**trial["problem"])
    recipe = compile_recipe(problem, ORDER_CONVERGENCE_RECIPE, {"fidelities": LADDER}, [DESIGN])
    observations = []
    for index, case in enumerate(recipe["cases"]):
        instance = ProblemInstance(**case["problem"])
        value = scores[(instance.fidelity["rcwa_order_x"], instance.fidelity["rcwa_order_y"])]
        observations.append({"id": f"observation_{index}", "proposal_id": f"case_{index}", "status": "ok", "candidate": case["candidate"],
            "fidelity": instance.fidelity, "evaluator_identity": instance.evaluation_identity,
            "objectives": {"mean_plus1_transmission": value, "te_plus1_transmission": value, "tm_plus1_transmission": value},
            "metadata": {"meent": {"energy_totals": [1.0, 1.0]}}})
    summary = Meent2DProblem().summarize_recipe(recipe, observations)
    store = workspace.store
    subject = store.put("asset", {"id": "snapshot_" + content_hash([trial["id"], sorted(scores.items())])[:12], "campaign_id": trial["campaign_id"], "kind": "solution",
                                  "payload": {"candidate": DESIGN}})
    scope = {"parameters": recipe["parameters"], "rule": recipe["validation_rule"], "parent_trial_id": trial["id"], "subject_index": 0,
             "recipe_cases_hash": content_hash(recipe["cases"]), "recipe": recipe}
    requirement = workspace.validations.require(ValidationRequirement(id="requirement_" + subject["id"], campaign_id=trial["campaign_id"],
        study_id=trial["study_id"], subject_id=subject["id"], subject_digest=workspace.validations.subject_digest(subject["id"]),
        kind="solution_fidelity", recipe_id=ORDER_CONVERGENCE_RECIPE, scope=scope, authority="researcher", created_at=now()))
    finding = summary["subjects"][0]
    result = workspace.validations.record_result(ValidationResult(id="validation_" + subject["id"], campaign_id=trial["campaign_id"],
        requirement_id=requirement["id"], subject_digest=requirement["subject_digest"], recipe_id=ORDER_CONVERGENCE_RECIPE,
        verdict=finding["verdict"], evidence_ids=[trial["id"]], measurements=finding, rationale=finding["rationale"],
        producer="trusted_service", authority="experiment_service", created_at=now()))
    return requirement, result, finding


def promote(workspace, campaign, hypothesis, actor):
    current = workspace.store.get(hypothesis["id"], "hypothesis")
    return run(workspace, campaign["id"], "hypothesis.status",
               {"hypothesis_id": hypothesis["id"], "status": "finalist", "expected_status_revision": current.get("status_revision", 0)}, actor=actor)["hypothesis"]


def publish(workspace, campaign, hypothesis):
    from balsamic.library.service import PublishInput, publish
    return publish(workspace, campaign["id"], PublishInput(hypothesis_id=hypothesis["id"]), command_id="publish_" + hypothesis["id"], actor="researcher")


def test_the_2d_problem_declares_its_order_check_and_part_f_fails_it(tmp_path):
    definition = Meent2DProblem().describe()
    assert [check.model_dump(exclude={"schema_version"}) for check in definition.promotion_validation] == [
        {"recipe_id": ORDER_CONVERGENCE_RECIPE, "parameters": {"absolute_tolerance": .005}}]
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    _, trial = strategy(workspace, campaign, score=PART_F[(10, 5)])
    _, _, finding = order_check(workspace, trial, PART_F)
    assert finding["verdict"] == "failed" and finding["last_two_absolute_differences"]["mean_plus1_transmission"] == pytest.approx(0.2619)


def test_an_agent_cannot_promote_a_2d_score_that_failed_or_was_not_checked_and_can_once_it_passed(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    unchecked, unchecked_trial = strategy(workspace, campaign, score=0.9, title="Unchecked")
    with pytest.raises(ValueError, match="has not been checked") as refused:
        promote(workspace, campaign, unchecked, "manager")
    assert "validation.run" in str(refused.value) and unchecked_trial["id"] in str(refused.value) and "approval.request kind waiver" in str(refused.value)
    assert promotion.fidelity_state(workspace, unchecked)["state"] == "not_checked"

    failed, trial = strategy(workspace, campaign, score=PART_F[(10, 5)], title="Part F")
    order_check(workspace, trial, PART_F)
    with pytest.raises(ValueError, match="does not hold at higher fidelity"):
        promote(workspace, campaign, failed, "manager")
    assert workspace.store.get(failed["id"], "hypothesis").get("status") != "finalist"
    workspace.store.put("hypothesis", {**workspace.store.get(failed["id"], "hypothesis"), "status": "finalist"})   # the researcher's earlier choice
    with pytest.raises(ValueError, match="fidelity check, or your waiver"):
        publish(workspace, campaign, failed)
    assert workspace.store.list("library_entry") == []

    held, trial = strategy(workspace, campaign, score=0.9, title="Holds")
    _, result, _ = order_check(workspace, trial, {(10, 5): 0.9, (26, 22): 0.898})
    promoted = promote(workspace, campaign, held, "manager")
    assert promoted["status"] == "finalist" and promoted["promotion"]["state"] == "passed" and promoted["promotion"]["warning"] is None
    entry = publish(workspace, campaign, held)["entry"]
    assert entry["evidence"]["fidelity"]["state"] == "passed" and entry["evidence"]["fidelity"]["checks"][0]["validation_result_id"] == result["id"]


def test_only_the_researchers_waiver_opens_the_gate(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    hypothesis, trial = strategy(workspace, campaign, score=PART_F[(10, 5)])
    requirement, _, _ = order_check(workspace, trial, PART_F)
    waiver = {"requirement_id": requirement["id"], "rationale": "The (10, 5) score is what the paper reports", "evidence_ids": [trial["id"]]}
    with pytest.raises(ValueError, match="Only the researcher waives"):
        run(workspace, campaign["id"], "validation.waive", waiver, actor="manager")
    assert workspace.store.list("waiver") == []
    run(workspace, campaign["id"], "validation.waive", waiver)
    state = promotion.fidelity_state(workspace, hypothesis)
    assert state["state"] == "waived" and state["checks"][0]["waiver_id"] == workspace.store.list("waiver")[0]["id"]
    assert promote(workspace, campaign, hypothesis, "manager")["promotion"]["state"] == "waived"
    assert publish(workspace, campaign, hypothesis)["entry"]["evidence"]["fidelity"]["state"] == "waived"


def test_the_researchers_own_finalist_passes_with_a_recorded_warning(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace)
    hypothesis, trial = strategy(workspace, campaign, score=0.9)
    promoted = promote(workspace, campaign, hypothesis, "researcher")
    assert promoted["status"] == "finalist" and promoted["promotion"]["state"] == "not_checked" and promoted["promotion"]["by"] == "researcher"
    assert "fidelity check not checked" in promoted["promotion"]["warning"]
    created = run(workspace, campaign["id"], "hypothesis.create", {"title": "Straight to finalist", "mechanism": "m", "rationale": "r",
                                                                   "algorithm": "random", "status": "finalist"})["hypothesis"]
    assert created["status"] == "finalist" and created["promotion"]["state"] == "not_checked" and created["promotion"]["warning"]
    with pytest.raises(ValueError, match="has no measured run"):
        run(workspace, campaign["id"], "hypothesis.create", {"title": "Agent finalist", "mechanism": "m", "rationale": "r",
                                                             "algorithm": "random", "status": "finalist"}, actor="manager")


def test_a_bounded_continuous_strategy_is_not_gated(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace, "bounded_continuous")
    hypothesis, _ = strategy(workspace, campaign, score=0.5)
    assert promotion.fidelity_state(workspace, hypothesis)["state"] == "not_required"
    promoted = promote(workspace, campaign, hypothesis, "manager")
    assert promoted["status"] == "finalist" and promoted["promotion"]["state"] == "not_required"
    assert publish(workspace, campaign, hypothesis)["entry"]["evidence"]["fidelity"]["state"] == "not_required"


def test_the_best_score_follows_the_objectives_direction(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace, "bounded_continuous")
    hypothesis, first = strategy(workspace, campaign, score=0.5)
    direction = first["problem"]["primary_objective"]["direction"]
    second = {**first, "id": first["id"] + "_b", "seed": 1, "result": {**first["result"], "best_objective": 0.2}}
    workspace.store.put("trial", second, "trial.evidence_cataloged")
    best = promotion.best_trial(workspace.store, hypothesis)
    assert best["id"] == (second["id"] if direction == "minimize" else first["id"])


def test_a_shortlist_records_each_runs_fidelity_and_warns_the_researcher(tmp_path, monkeypatch):
    from test_framework_finalists import prepare, select
    from optimization_framework.analysis.finalists import set_selection
    from optimization_framework.contracts.commands import FinalistSetInput
    workspace, campaign, trials = prepare(tmp_path)
    selection = workspace.store.get(select(workspace, campaign, [trials[0]["id"]])["outcome"]["finalist_selection_id"], "finalist_selection")
    assert selection["fidelity"][trials[0]["id"]]["state"] == "not_required" and selection["fidelity"][trials[0]["id"]]["warning"] is None
    # A problem that declares a check the run never had: the researcher's shortlist passes with the warning recorded; an agent's would not.
    monkeypatch.setattr(promotion, "declared", lambda *args, **kwargs: [{"recipe_id": "fidelity_comparison:v1", "parameters": {}}])
    selection = workspace.store.get(select(workspace, campaign, [trials[1]["id"]], command_id="choose_again")["outcome"]["finalist_selection_id"], "finalist_selection")
    assert selection["fidelity"][trials[1]["id"]]["state"] == "not_checked" and "fidelity_comparison:v1 has not been checked" in selection["fidelity"][trials[1]["id"]]["warning"]
    with pytest.raises(ValueError, match="A finalist needs the problem's fidelity check"):
        set_selection(workspace, campaign["id"], FinalistSetInput(study_id=campaign["active_study_id"], trial_ids=[trials[2]["id"]]),
                      command_id="agent_choice", actor="manager")


def test_the_lead_eval_fidelity_trap_is_gated_at_the_fine_resolution(tmp_path):
    """S13's problem: its coarse peak cannot become an agent's finalist before the comparison with the fine resolution."""
    workspace = Workspace(tmp_path)
    campaign = campaign_of(workspace, "fidelity_trap")
    hypothesis, trial = strategy(workspace, campaign, score=0.9)
    assert promotion.declared(workspace, campaign["id"], trial) == [
        {"recipe_id": "fidelity_comparison:v1", "parameters": {"fidelities": [{"resolution": "coarse"}, {"resolution": "fine"}]}}]
    with pytest.raises(ValueError, match="fidelity_comparison:v1 has not been checked"):
        promote(workspace, campaign, hypothesis, "manager")
