"""Outcome constraints (roadmap N10, M5 part 2).

A charter states a condition on what the evaluator measured (a floor on a second metric, a cap on a measured cost) as an
``outcome`` constraint: an expression over the objective and the metrics by name. The task's problem carries it, the
worker checks it on each observation, and an observation that breaks it is kept but marked infeasible: it never counts as
a run's best, and the comparison and the ledger rank feasible results only and count the others.
"""
from copy import deepcopy

import pytest

from optimization_framework.analysis.general import report
from optimization_framework.contracts.evaluators import EvaluatorManifest
from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.contracts.problems import CandidateSchema, Objective, OutcomeConstraint, ProblemInstance
from optimization_framework.contracts.requests import TaskInput, TrialInput
from optimization_framework.execution.worker import read_journal, run
from optimization_framework.optimizers.functions import FunctionMethod
from optimization_framework.problem_charter import charter as C

from balsamic.evolution.ledger import rows
from support import command

# The analytic quadratic reports one objective, ``value`` (minimized): its optimum, 0 at the centre, breaks a floor of 2.
FLOOR = {"name": "floor", "expression": "value >= least_value", "constants": {"least_value": 2.0}}
QUADRATIC = {"name": "Floored quadratic", "problem_id": "bounded_continuous", "configuration": {"dimensions": 2},
             "outcomes": [FLOOR]}


def cooler(**changes):
    """A cooler to be designed: minimise its thermal resistance, with the pressure drop it costs capped."""
    charter = {
        "title": "Plate cooler",
        "text": "The fan gives at most {max_pressure_drop} of pressure.",
        "quantities": {"max_pressure_drop": {"description": "Pressure the fan gives", "value": 40.0, "units": "Pa", "citation": 1},
                       "air_speed": {"description": "Air speed", "value": 2.0, "units": "m/s", "citation": 1}},
        "variables": [{"name": "fin_width_mm", "description": "Fin width", "representation": "continuous", "lower": 0.5,
                       "upper": 5.0, "units": "mm"}],
        "constraints": [{"id": "fan", "form": "outcome", "statement": "The pressure drop stays within {max_pressure_drop}.",
                         "test": "pressure_drop <= max_pressure_drop"}],
        "objective": {"name": "thermal_resistance", "direction": "minimize", "units": "K/W", "definition": "Base to air"},
        "metrics": [{"name": "pressure_drop", "units": "Pa", "direction": "minimize"}],
        "evaluator": {"kind": "declared", "problem_id": "plate_cooler", "configuration": {"air_speed": "air_speed"},
                      "notes": "Compute the resistance and the pressure drop."},
        "instances": [{"name": "Base", "split": "development"}],
        "citations": [{"id": 1, "source": "brief.md"}],
    }
    charter.update(changes)
    return charter


def blocking(rows):
    return {row["code"] for row in rows if row["severity"] == "blocking"}


def constraint(charter, **changes):
    charter = deepcopy(charter)
    charter["constraints"][0].update(changes)
    return charter


def execute(workspace, campaign_id, task, candidates, hypothesis_id=None, seed=0, algorithm="random"):
    """A run that evaluates the given designs in order, then finishes."""
    def method(problem, evaluate, rng):
        for candidate in candidates:
            evaluate(candidate)
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm=algorithm, max_steps=40,
                                              wall_seconds=30, seed=seed, hypothesis_id=hypothesis_id))
    result = run(workspace.job_dir(trial["id"]), optimizer=FunctionMethod(method, ProblemInstance(**trial["problem"]), {}, trial["seed"]))
    trial.update(result=result, progress=result, attempt=1, status="completed")
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return trial, result


@pytest.fixture
def floored(client, workspace):
    receipt = command(client, "campaign.create", "floored", {"name": "Floored", "objective": "Least value above the floor",
        "tasks": [QUADRATIC], "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)
    campaign = receipt["outcome"]["campaign"]
    return campaign["id"], workspace.current_tasks(campaign["id"])[0]


def test_a_charter_outcome_constraint_reaches_the_declared_problem_with_its_thresholds():
    assert not blocking(C.findings(cooler()))
    setup = ProblemSetup(**C.compile_setups(cooler())[0])
    assert [(c.name, c.expression, c.constants) for c in setup.evaluator_manifest.outcomes] == [
        ("fan", "pressure_drop <= max_pressure_drop", {"max_pressure_drop": 40.0})]
    instance = setup.evaluator_manifest.resolve("v1", setup.configuration, setup.fidelity)
    assert instance.outcome_failures({"thermal_resistance": 1.0, "pressure_drop": 30.0}) == []
    assert instance.outcome_failures({"thermal_resistance": 1.0, "pressure_drop": 50.0}) == ["fan"]
    assert instance.outcome_failures({"thermal_resistance": 1.0}) == ["fan (the evaluator did not report pressure_drop)"]
    # Another instance carries its own threshold.
    strict = cooler(instances=[{"name": "Weak fan", "values": {"max_pressure_drop": 20.0}}])
    weak = ProblemSetup(**C.compile_setups(strict)[0]).evaluator_manifest
    assert weak.outcomes[0].constants == {"max_pressure_drop": 20.0}


def test_the_findings_check_what_an_outcome_constraint_reads():
    assert "constraint.outcome_name" in blocking(C.findings(constraint(cooler(), test="noise_level <= max_pressure_drop")))
    assert "constraint.outcome_name" in blocking(C.findings(constraint(cooler(), test="air_speed <= max_pressure_drop")))
    assert "constraint.test" in blocking(C.findings(constraint(cooler(), test="pressure_drop + max_pressure_drop")))
    with pytest.raises(ValueError, match="outcome constraint needs an expression"):
        C.parse(constraint(cooler(), test=None))


def test_a_manifest_refuses_an_outcome_constraint_on_an_unreported_metric():
    schema = CandidateSchema(representation="continuous", dimensions=1, bounds=[(0, 1)])
    base = dict(id="cooler", name="Cooler", candidate_schema=schema, primary_objective=Objective(name="r", direction="minimize"))
    with pytest.raises(ValueError, match="not objectives or metrics"):
        EvaluatorManifest(**base, outcomes=[OutcomeConstraint(name="fan", expression="pressure_drop <= 40")])
    manifest = EvaluatorManifest(**base, extra_metrics=[Objective(name="pressure_drop", direction="minimize")],
                                 outcomes=[OutcomeConstraint(name="fan", expression="pressure_drop <= 40")])
    assert manifest.resolve("v1").outcomes == manifest.outcomes


def test_an_installed_problem_carries_the_charters_outcome_constraints_to_its_tasks():
    charter = C.from_setups("Quadratic", [{"name": "Base", "problem_id": "bounded_continuous", "configuration": {"dimensions": 2}}])
    charter["quantities"]["least_value"] = {"description": "Smallest acceptable value", "kind": "number", "role": "input",
                                            "value": 2.0, "units": "", "origin": "source"}
    charter["constraints"] = [{"id": "floor", "form": "outcome", "statement": "At least the floor", "test": "value >= least_value"}]
    assert not blocking(C.findings(charter))
    task = ProblemSetup(**C.compile_setups(charter)[0]).task_input()
    assert [c.model_dump() for c in task.problem.outcomes] == [FLOOR]
    charter["constraints"][0]["test"] = "value + 0 * gradient_norm >= least_value"
    charter["metrics"] = [{"name": "gradient_norm", "units": "1"}]
    assert "constraint.outcome_unreported" in blocking(C.findings(charter))


def test_records_without_outcome_constraints_keep_their_bytes():
    task = TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={"dimensions": 2})
    assert "outcomes" not in task.model_dump(mode="json") and "outcomes" not in task.problem.model_dump(mode="json")
    floored = TaskInput(**{key: value for key, value in QUADRATIC.items()})
    assert floored.problem.outcomes[0].name == "floor"
    assert floored.problem.evaluation_identity == task.problem.evaluation_identity, "the evaluation itself is the same"
    assert TaskInput(**floored.model_dump(mode="json")).problem == floored.problem


def test_a_run_whose_best_raw_score_violates_an_outcome_constraint_reports_the_best_feasible_one(workspace, floored):
    campaign_id, task = floored
    trial, result = execute(workspace, campaign_id, task, [[0.0, 0.0], [2.0, 2.0], [1.0, 1.0], [0.5, 0.5]])
    assert result["best_objective"] == 2.0 and result["best_candidate"] == [1.0, 1.0]
    assert result["infeasible_observations"] == 2 and result["confirmed_observations"] == 4
    assert all(entry["objective"] >= 2.0 for entry in result["archive"])
    journal = read_journal(workspace.job_dir(trial["id"]) / "observations.jsonl")
    assert [row["constraints"] for row in journal] == [{"floor": False}, {"floor": True}, {"floor": True}, {"floor": False}]
    assert journal[0]["objectives"] == {"value": 0.0} and journal[0]["metadata"]["infeasible"] == ["floor"]
    # A run that never met the floor has no best.
    _, none = execute(workspace, campaign_id, task, [[0.0, 0.0]], seed=1)
    assert none["best_objective"] is None and none["infeasible_observations"] == 1


def test_the_comparison_and_the_ledger_rank_feasible_results_and_count_the_infeasible_ones(client, workspace, floored):
    campaign_id, task = floored
    version = lambda: workspace.store.get(campaign_id, "campaign")["version"]
    made = {title: command(client, "hypothesis.create", campaign_id, {"title": title, "mechanism": "m", "rationale": "r",
                "algorithm": "random"}, version())["outcome"]["hypothesis"]["id"] for title in ("Raw", "Careful")}
    # Raw reaches the lowest value, 0, which breaks the floor; Careful stays above it.
    execute(workspace, campaign_id, task, [[3.0, 3.0], [0.0, 0.0], [0.1, 0.1]], made["Raw"])
    execute(workspace, campaign_id, task, [[1.5, 1.5], [1.0, 1.0], [1.2, 1.2]], made["Careful"], seed=1, algorithm="coordinate")
    group = report(workspace, campaign_id, cost_axis="evaluation_requests")["groups"][0]
    assert group["condition"]["outcomes"] == [FLOOR]
    assert group["infeasible_observations"] == 2
    summaries = {s["algorithm"]: s for s in group["method_summaries"]}
    assert summaries["coordinate"]["rank"] == 1 and summaries["coordinate"]["mean"] == 2.0
    assert summaries["coordinate"]["infeasible_observations"] == 0
    assert summaries["random"]["rank"] == 2 and summaries["random"]["mean"] == 18.0
    assert summaries["random"]["infeasible_observations"] == 2
    ledger = {row["id"]: row for row in rows(workspace, campaign_id)[0]}
    assert ledger[made["Raw"]]["best"]["score"] == 18.0 and ledger[made["Raw"]]["infeasible_observations"] == 2
    assert ledger[made["Careful"]]["best"]["score"] == 2.0 and ledger[made["Careful"]]["infeasible_observations"] == 0
