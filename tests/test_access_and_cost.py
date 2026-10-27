"""Access and cost per problem (roadmap N11, decisions 22 and 23).

A problem is white_box unless it declares oracle: a method may then compute the objective itself as often as it likes,
and is judged by its time. An oracle problem's objective is reached only through ``evaluate``. A run on several threads
is compared with single-thread runs on core-seconds and kept apart on worker-seconds. Records made before this part
keep their digests and read as oracle, the rule they were built under.
"""
import json
import time

import pytest

from optimization_framework.analysis.general import report
from optimization_framework.contracts.evaluators import EvaluatorManifest
from optimization_framework.contracts.experiments import ExperimentSpec
from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.evaluation.access import declared, of_task
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import read_journal, run
from optimization_framework.optimizers.functions import FunctionMethod
from optimization_framework.problem_charter import charter as C

from test_problem_charter import reactor


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Access", compute_budget_seconds=400, validation_reserve_seconds=0,
        tasks=[TaskInput(name="White box", problem_id="bounded_continuous", configuration={"dimensions": 2}),
               TaskInput(name="Oracle", problem_id="bounded_continuous", configuration={"dimensions": 3}, access="oracle")]))
    white, oracle = sorted(workspace.current_tasks(campaign["id"]), key=lambda task: task["name"] != "White box")
    return workspace, campaign["id"], white, oracle


def execute(workspace, campaign_id, task, fn, *, threads=1, seed=0):
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm="random", max_steps=50,
                                              wall_seconds=30, seed=seed, numerical_threads=threads))
    method = FunctionMethod(fn, ProblemInstance(**trial["problem"]), {}, trial["seed"])
    result = run(workspace.job_dir(trial["id"]), optimizer=method)
    trial.update(result=result, progress=result, attempt=1, status="completed")
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return trial, result, method


def test_a_problem_is_white_box_unless_it_or_its_pack_declares_oracle():
    assert declared("bounded_continuous") == {"access": "white_box", "cost_axis": None}
    # MEENT's pack keeps it an oracle problem on worker-seconds: its RCWA solver is the expensive evaluator.
    for problem_id in ("meent_grating", "meent_2d_dual_polarization_deflector"):
        assert declared(problem_id) == {"access": "oracle", "cost_axis": "worker_seconds"}
    task = TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})
    assert (task.access, task.cost_axis) == ("white_box", None)
    chosen = TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2}, access="oracle",
                       cost_axis="evaluations")
    assert (chosen.access, chosen.cost_axis) == ("oracle", "evaluations")


def test_a_white_box_method_computes_the_objective_freely_and_is_judged_by_its_time(lab):
    workspace, campaign_id, white, _ = lab
    spent = {}

    def exhaustive(problem, evaluate, rng):
        """Computes the objective 10,000 times itself, then records only its best."""
        started = time.monotonic()
        best = min(([float(x), float(y)] for x, y in rng.uniform(-1, 1, size=(10_000, 2))), key=problem.objective)
        spent["seconds"] = time.monotonic() - started
        evaluate(best)

    trial, result, method = execute(workspace, campaign_id, white, exhaustive)
    assert trial["access"] == "white_box" and trial["experiment_spec"]["schedule"]["access"] == "white_box"
    assert result["status"] == "completed" and result["reason"] == "method_finished"
    # One observation: what the method computed itself is not recorded.
    observations = read_journal(workspace.job_dir(trial["id"]) / "observations.jsonl")
    assert result["evaluations"] == 1 and len(observations) == 1
    assert result["best_objective"] == observations[0]["objectives"]["value"]
    # The cost row charges the method's own compute: its 10,000 objective calls are in the run's time.
    costs = read_journal(workspace.job_dir(trial["id"]) / "costs.jsonl")
    assert costs[0]["quantities"]["worker_seconds"] >= spent["seconds"] > 0
    assert costs[0]["quantities"]["core_seconds"] == costs[0]["quantities"]["worker_seconds"]
    comparison = report(workspace, campaign_id)
    assert comparison["cost_axis"] == "worker_seconds"
    run_row = next(row for group in comparison["groups"] for row in group["trials"] if row["id"] == trial["id"])
    assert run_row["curve"][-1]["cost"] >= spent["seconds"]


def test_on_an_oracle_problem_the_objective_is_not_in_problem(lab):
    workspace, campaign_id, _, oracle = lab
    seen = {}

    def look(problem, evaluate, rng):
        seen["objective"] = hasattr(problem, "objective")
        evaluate([0.0, 0.0, 0.0])

    trial, result, _ = execute(workspace, campaign_id, oracle, look)
    assert result["reason"] == "method_finished" and seen == {"objective": False}
    assert "access" not in trial and "access" not in trial["experiment_spec"]["schedule"]


def test_a_two_thread_run_is_compared_with_one_thread_on_core_seconds_and_kept_apart_on_worker_seconds(lab):
    workspace, campaign_id, white, _ = lab

    def few(problem, evaluate, rng):
        for _ in range(3):
            evaluate([float(x) for x in rng.uniform(-1, 1, size=2)])

    single, _, _ = execute(workspace, campaign_id, white, few, threads=1, seed=0)
    double, ended, _ = execute(workspace, campaign_id, white, few, threads=2, seed=1)
    costs = read_journal(workspace.job_dir(double["id"]) / "costs.jsonl")
    assert all(row["quantities"]["core_seconds"] == 2 * row["quantities"]["worker_seconds"] for row in costs)
    on_cores = report(workspace, campaign_id, trial_ids=[single["id"], double["id"]])
    assert on_cores["cost_axis"] == "core_seconds"   # unset axis, white box, several threads: decision 23
    assert [len(group["trials"]) for group in on_cores["groups"]] == [2]
    assert "worker_threads" not in on_cores["groups"][0]["condition"]
    rows = {row["id"]: row for row in on_cores["groups"][0]["trials"]}
    assert rows[double["id"]]["curve"][-1]["cost"] == pytest.approx(2 * ended["elapsed_seconds"])
    on_time = report(workspace, campaign_id, cost_axis="worker_seconds", trial_ids=[single["id"], double["id"]])
    assert sorted((group["condition"].get("worker_threads", 1), len(group["trials"])) for group in on_time["groups"]) == [(1, 1), (2, 1)]


def test_records_made_before_this_part_keep_their_digests_and_read_as_oracle(lab):
    workspace, campaign_id, white, _ = lab
    # A manifest dumped before N11 has no access: the same bytes, the same version, an oracle problem.
    manifest = C.manifest(ProblemCharter.model_validate(reactor()), C.resolve(reactor())["values"])
    old = {key: value for key, value in manifest.model_dump(mode="json").items() if key not in {"access", "cost_axis"}}
    parsed = EvaluatorManifest.model_validate(old)
    assert parsed.model_dump(mode="json") == old and parsed.access is None and parsed.effective_access == "oracle"
    assert parsed.describe("v1").access == "oracle"
    assert TaskInput(name="Old", problem_id=parsed.id, configuration=parsed.configuration, fidelity=parsed.fidelity,
                     evaluator_manifest=parsed).access == "oracle"
    # Definitions, bindings and setups that declare nothing dump as before.
    assert "access" not in problems.get("bounded_continuous").describe().model_dump(mode="json")
    binding = ProblemCharter.model_validate(reactor()).evaluator
    assert "access" not in binding.model_dump(mode="json") and "cost_axis" not in binding.model_dump(mode="json")
    setup = ProblemSetup(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})
    assert "access" not in setup.model_dump(mode="json")
    # A task stored before N11 has neither field: it is an oracle task, and its runs freeze as they always did.
    legacy = {key: value for key, value in white.items() if key not in {"access", "cost_axis"}}
    workspace.store.put("task", legacy)
    assert of_task(legacy) == {"access": "oracle", "cost_axis": None}
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=white["id"], algorithm="random", max_steps=4, wall_seconds=20))
    assert "access" not in trial and "access" not in trial["experiment_spec"]["schedule"]
    frozen = ExperimentSpec.model_validate(trial["experiment_spec"])
    assert frozen.digest() == trial["experiment_spec_hash"]
    result = run(workspace.job_dir(trial["id"]))
    assert result["status"] == "completed" and result["evaluations"] == 4


def test_a_campaign_update_with_the_same_tasks_keeps_a_task_made_before_this_part(lab):
    workspace, campaign_id, white, oracle = lab
    for task in (white, oracle):
        workspace.store.put("task", {key: value for key, value in task.items() if key not in {"access", "cost_axis"}})
    from optimization_framework.contracts.requests import CampaignUpdate
    same = [TaskInput(id=task["id"], name=task["name"], problem_id=task["problem_id"], configuration=task["configuration"])
            for task in (white, oracle)]
    workspace.update_campaign(campaign_id, CampaignUpdate(tasks=same))
    assert {task["id"] for task in workspace.current_tasks(campaign_id)} == {white["id"], oracle["id"]}


def test_a_charter_sets_the_access_and_the_axis_and_its_view_names_both():
    charter = reactor()
    view = C.describe(charter)
    assert view["access"]["access"] == "white_box" and view["access"]["cost_axis"] is None
    setup = ProblemSetup.model_validate(C.compile_setups(charter)[0])
    assert setup.evaluator_manifest.access == "white_box" and setup.task_input().access == "white_box"
    charter = C.apply_changes(charter, [{"op": "set", "path": "evaluator.access", "value": "oracle"},
                                        {"op": "set", "path": "evaluator.cost_axis", "value": "evaluations"}])
    setup = ProblemSetup.model_validate(C.compile_setups(charter)[0])
    assert (setup.evaluator_manifest.access, setup.evaluator_manifest.cost_axis) == ("oracle", "evaluations")
    task = setup.task_input()
    assert (task.access, task.cost_axis) == ("oracle", "evaluations")
    assert C.describe(charter)["access"]["charter"] == {"access": "oracle", "cost_axis": "evaluations"}
    with pytest.raises(ValueError):
        C.apply_changes(charter, [{"op": "set", "path": "evaluator.access", "value": "glass_box"}])


def test_an_installed_problems_charter_shows_its_own_declaration_until_the_charter_sets_one():
    example = next(e for e in problems.examples() if e["instances"][0].get("problem_id", "").startswith("meent"))
    charter = example.get("charter") or C.from_setups(example["name"], example["instances"])
    assert C.describe(charter)["access"] == {"access": "oracle", "cost_axis": "worker_seconds",
        "problem": {"access": "oracle", "cost_axis": "worker_seconds"}, "charter": {"access": None, "cost_axis": None}}
    json.dumps(C.describe(charter)["access"])
