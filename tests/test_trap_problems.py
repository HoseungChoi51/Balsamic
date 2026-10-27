"""The lead evals' trap problems (roadmap J1): a cheap fidelity with a spurious peak, and a knapsack only an exact method solves."""
import pytest

from optimization_benchmarks.problems import SPURIOUS, HILL, KnapsackProblem, FidelityTrapProblem, knapsack_items
from optimization_framework.contracts.requests import CampaignInput, RecipeInput, TaskInput, TrialInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import run

# The seeded default instance's optimum, from the dynamic program below; filling by the best value-to-weight ratio reaches 1630.
KNAPSACK_OPTIMUM = 1632


def dynamic_program(weights, values, capacity):
    best = [0] * (capacity + 1)
    for weight, value in zip(weights, values):
        for room in range(capacity, weight - 1, -1):
            best[room] = max(best[room], best[room - weight] + value)
    return best[capacity]


def greedy_by_ratio(weights, values, capacity):
    chosen, room = [0] * len(weights), capacity
    for index in sorted(range(len(weights)), key=lambda i: -values[i] / weights[i]):
        if weights[index] <= room:
            chosen[index], room = 1, room - weights[index]
    return chosen


def test_the_trap_problems_are_installed():
    assert {"fidelity_trap", "knapsack_dp"} <= set(problems.ids())
    assert problems.get("fidelity_trap").describe().validation_recipes == ["fidelity_comparison:v1"]


def test_the_knapsack_optimum_is_the_dynamic_programs_and_the_greedy_ratio_rule_misses_it():
    instance = KnapsackProblem().resolve({})
    config = instance.configuration
    assert (config["items"], config["capacity"], len(config["weights"])) == (200, 1000, 200)
    assert all(isinstance(weight, int) for weight in config["weights"])
    assert (config["weights"], config["values"]) == knapsack_items(200, 0)
    assert dynamic_program(config["weights"], config["values"], config["capacity"]) == KNAPSACK_OPTIMUM
    greedy = greedy_by_ratio(config["weights"], config["values"], config["capacity"])
    evaluator = KnapsackProblem().evaluator(instance)
    assert evaluator.evaluate(greedy).objectives["value"] == 1630 < KNAPSACK_OPTIMUM
    with pytest.raises(ValueError, match="capacity"):
        evaluator.evaluate([1] * 200)
    assert instance.primary_objective.direction == "maximize" and instance.candidate_schema.representation == "binary"


def test_the_spurious_peak_exists_at_coarse_and_not_at_fine():
    trap = FidelityTrapProblem()
    coarse, fine = (trap.evaluator(trap.resolve({}, {"resolution": name})) for name in ("coarse", "fine"))
    assert trap.resolve({}).fidelity == {"resolution": "coarse"}
    value = lambda evaluator, x: evaluator.evaluate(list(x)).objectives["value"]
    assert value(coarse, SPURIOUS) > .85 and value(fine, SPURIOUS) < .05
    assert value(coarse, HILL) == pytest.approx(value(fine, HILL)) == pytest.approx(.6)
    assert value(coarse, SPURIOUS) > value(coarse, HILL)
    with pytest.raises(ValueError, match="resolution"):
        trap.resolve({}, {"resolution": "medium"})


def finish(workspace, identity):
    trial = workspace.store.get(identity, "trial")
    result = run(workspace.job_dir(identity))
    assert result["scientific_complete"], result
    trial.update(status=result["status"], result=result, progress=result, attempt=1)
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return workspace.store.get(identity, "trial")


def test_the_generic_fidelity_comparison_fails_for_the_peak_and_passes_for_the_true_optimum(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Trap", compute_budget_seconds=100, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Trap", problem_id="fidelity_trap", fidelity={"resolution": "coarse"})]))
    task = workspace.current_tasks(campaign["id"])[0]
    source = finish(workspace, workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm="replay",
        algorithm_config={"candidates": [list(SPURIOUS), list(HILL)]}, max_steps=2, wall_seconds=10))["id"])
    assert source["result"]["best_objective"] > .85
    check = finish(workspace, workspace.run_recipe(source["id"], RecipeInput(recipe_id="fidelity_comparison:v1", subject_limit=2, wall_seconds=10))["id"])
    summary = check["result"]["recipe_result"]
    assert summary["kind"] == "solution_fidelity" and summary["complete"]
    verdicts = {tuple(subject["candidate"]): subject["verdict"] for subject in summary["subjects"]}
    assert verdicts == {tuple(SPURIOUS): "failed", tuple(HILL): "passed"}
