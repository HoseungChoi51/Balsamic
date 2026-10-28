"""Roadmap V2: a proposal is stopped as inferior only after an adequate assessment (decision 14), or the researcher's waiver."""
import textwrap

import pytest

from optimization_framework.campaigns.assessment import adequacy, evaluator_stochastic
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.registry import BUILTINS, stochastic
from optimization_framework.storage.sqlite import now

from test_function_plugins import library, plugins_of   # noqa: F401  (the fixture)
from test_mandates import granted


def prepare(path, algorithm="coordinate"):
    workspace = Workspace(path)
    campaign = workspace.create_campaign(CampaignInput(name="Assessment", autonomy="delegated", compute_budget_seconds=100000,
        validation_reserve_seconds=0, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    granted(workspace, campaign["id"])   # a stop is decide work under the mandate guard (R3)
    target = run(workspace, campaign, "create", "hypothesis.create",
                 {"title": "Annealing", "mechanism": "m", "rationale": "r", "algorithm": algorithm}, actor="researcher")
    return workspace, campaign, target["outcome"]["hypothesis"]


def run(workspace, campaign, identity, operation, payload, actor="manager"):
    current = workspace.store.get(campaign["id"], "campaign")
    command = Command(id=identity, campaign_id=campaign["id"], expected_revision=current["version"], operation=operation, payload=payload)
    if actor != "researcher":
        command = command.model_copy(update={"expected_guidance_revision": workspace.memory.state(campaign["id"])["guidance_revision"],
                                             "expected_authority_hash": workspace.commands.authority_hash(current)})
    return workspace.commands.execute(command, actor=actor)


def trials(workspace, campaign, target, configurations, seeds, *, algorithm="coordinate", elapsed=900.0, complete=True, prefix="t"):
    """Runs of the proposal: one per configuration and seed, each at the horizon unless told otherwise."""
    task = workspace.store.list("task", campaign["id"])[0]
    made = []
    for c in range(configurations):
        for seed in seeds:
            identity = f"trial_{prefix}{c}_{seed}"
            workspace.store.put("trial", {"id": identity, "campaign_id": campaign["id"], "task_id": task["id"], "hypothesis_id": target["id"],
                "status": "completed", "algorithm": algorithm, "algorithm_config": {"radius": 0.1 * (c + 1)}, "seed": seed, "split": "development",
                "created_at": now(), "result": {"scientific_complete": complete, "best_objective": 0.5, "elapsed_seconds": elapsed, "evaluations": 40}})
            made.append(identity)
    return made


def stop(workspace, campaign, target, identity, outcome, evidence, actor="manager"):
    revision = workspace.store.get(target["id"], "hypothesis").get("status_revision", 0)
    return run(workspace, campaign, identity, "hypothesis.status", {"hypothesis_id": target["id"], "status": "archived",
        "expected_status_revision": revision, "outcome": outcome, "evidence_ids": evidence, "stop_reason": "worse than the others"}, actor=actor)


def stopped(workspace, target):
    return workspace.store.get(target["id"], "hypothesis")


def test_one_default_configuration_is_not_enough_to_stop_as_unpromising(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    with pytest.raises(ValueError, match=r"needs an adequate assessment first .*1 of 3 configurations; 1 of 2 seeds.*stop it as under_evaluated"):
        stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)
    with pytest.raises(ValueError, match="1 of 3 configurations"):
        stop(workspace, campaign, target, "deprioritized", "adequately_assessed_deprioritized", runs, actor="autopilot")
    assert stopped(workspace, target)["status"] == "proposed"
    stop(workspace, campaign, target, "honest", "under_evaluated", runs)
    assert stopped(workspace, target)["stop"]["outcome"] == "under_evaluated" and "assessment" not in stopped(workspace, target)["stop"]


def test_three_configurations_with_two_seeds_each_past_the_horizon_are_enough(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 3, [0, 1])
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs[:2])
    assessment = stopped(workspace, target)["stop"]["assessment"]
    assert assessment == {"adequate": True, "configurations": 3, "seeds_per_configuration": 2, "stochastic": True,
                          "words": "3 of 3 configurations, 2 seeds each"}


def test_a_deterministic_method_needs_one_run_per_configuration_and_a_stochastic_one_two_seeds(tmp_path):
    workspace, campaign, target = prepare(tmp_path / "a", algorithm="replay")
    runs = trials(workspace, campaign, target, 3, [0], algorithm="replay")
    assert not stochastic("replay") and adequacy(workspace, target)["words"] == "3 of 3 configurations, deterministic"
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)
    assert stopped(workspace, target)["stop"]["assessment"]["adequate"] is True

    workspace, campaign, target = prepare(tmp_path / "b")
    runs = trials(workspace, campaign, target, 3, [0])
    with pytest.raises(ValueError, match="1 of 2 seeds") as refused:
        stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)
    assert "configurations" not in str(refused.value).split("first (decision 14): ")[1].split(".")[0]


def test_a_stochastic_evaluator_needs_the_seeds_again(tmp_path):
    workspace, campaign, target = prepare(tmp_path, algorithm="replay")
    trials(workspace, campaign, target, 3, [0], algorithm="replay")
    task = workspace.store.list("task", campaign["id"])[0]
    assert evaluator_stochastic(workspace, task) is False   # bounded_continuous declares nothing: deterministic
    noisy = {**task, "evaluator_manifest": {**(task.get("evaluator_manifest") or {}), "deterministic": False}}
    state = adequacy(workspace, target, tasks={task["id"]: noisy})
    assert state["stochastic"] and not state["adequate"] and state["missing"] == ["1 of 2 seeds"]


def test_runs_short_of_the_horizon_do_not_count(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    trials(workspace, campaign, target, 3, [0, 1], elapsed=30, complete=False)
    state = adequacy(workspace, target)
    assert not state["adequate"] and state["configurations"] == 0 and state["short_runs"] == 6
    assert state["missing"][-1].startswith("6 runs short of the horizon")
    # A completed run counts whatever its length; the researcher's evaluation horizon then applies on top.
    trials(workspace, campaign, target, 3, [0, 1], elapsed=30, complete=True, prefix="done")
    assert adequacy(workspace, target)["adequate"]
    run(workspace, campaign, "horizon", "experiments.rules", {"assessment": {"min_evaluations": 100}, "expected_revision": 0,
        "rationale": "a run is informative after 100 evaluations"}, actor="researcher")
    assert adequacy(workspace, target)["configurations"] == 0


def test_only_the_researcher_changes_the_minimums(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0, 1])
    with pytest.raises(ValueError, match="Only the researcher changes the assessment minimums"):
        run(workspace, campaign, "lower", "experiments.rules", {"assessment": {"min_configurations": 1}, "expected_revision": 0, "rationale": "faster"})
    run(workspace, campaign, "lower", "experiments.rules", {"assessment": {"min_configurations": 1}, "expected_revision": 0,
        "rationale": "one configuration is the method's only sensible setting"}, actor="researcher")
    stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)
    assert stopped(workspace, target)["stop"]["assessment"]["words"] == "1 of 1 configurations, 2 seeds each"


def test_the_researchers_waiver_lets_the_stop_through_and_an_agents_waiver_is_refused(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    with pytest.raises(ValueError, match="names the measurements it rests on"):
        run(workspace, campaign, "ask_bare", "approval.request", {"kind": "waiver", "tuning_hypothesis_id": target["id"], "rationale": "r"})
    run(workspace, campaign, "ask", "approval.request", {"kind": "waiver", "tuning_hypothesis_id": target["id"], "evidence_ids": runs,
        "rationale": "The default configuration is the only one the paper reports"})
    decision = workspace.store.list("decision", campaign["id"])[-1]
    assert decision["title"] == "Let Annealing be stopped as inferior on fewer runs?" and "1 of 3 configurations" in decision["proposal"]
    requirement = workspace.store.get("tuning_requirement_" + target["id"], "validation_requirement")
    assert requirement["kind"] == "tuning" and requirement["scope"] == {"hypothesis_id": target["id"]}
    # The agent cannot waive it itself (decision 16), and the stop is still refused.
    with pytest.raises(ValueError, match="Only the researcher waives the assessment minimums"):
        run(workspace, campaign, "self_waive", "validation.waive", {"requirement_id": requirement["id"], "rationale": "r", "evidence_ids": runs})
    with pytest.raises(ValueError, match="1 of 3 configurations"):
        stop(workspace, campaign, target, "early", "configuration_unpromising", runs)
    run(workspace, campaign, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "the paper's setting",
        "expected_resolution_revision": 0}, actor="researcher")
    [waiver] = workspace.store.list("waiver", campaign["id"])
    assert waiver["authority_kind"] == "researcher" and waiver["requirement_id"] == requirement["id"]
    stop(workspace, campaign, target, "waived", "configuration_unpromising", runs)
    assessment = stopped(workspace, target)["stop"]["assessment"]
    assert assessment["adequate"] is False and assessment["waiver_id"] == waiver["id"]


def test_the_researchers_own_stop_is_not_gated_and_records_the_assessment(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0])
    stop(workspace, campaign, target, "mine", "configuration_unpromising", runs, actor="researcher")
    assert stopped(workspace, target)["stop"]["assessment"]["words"] == "1 of 3 configurations, 1 seed each"


def test_a_stop_that_the_budget_cannot_complete_names_unaffordable(tmp_path):
    workspace, campaign, target = prepare(tmp_path)
    runs = trials(workspace, campaign, target, 1, [0], elapsed=60000)
    with pytest.raises(ValueError, match="stop it as unaffordable_within_allocation"):
        stop(workspace, campaign, target, "unpromising", "configuration_unpromising", runs)


def test_the_ledger_row_carries_the_assessment(tmp_path):
    from balsamic.evolution.ledger import rows
    workspace, campaign, target = prepare(tmp_path)
    trials(workspace, campaign, target, 2, [0, 1])
    row = next(row for row in rows(workspace, campaign["id"])[0] if row["id"] == target["id"])
    assert row["assessment"]["words"] == "2 of 3 configurations, 2 seeds each" and row["assessment"]["missing"] == ["2 of 3 configurations"]


def proposals(method, instance, seed, parameters=None, steps=6):
    from optimization_framework.optimizers.registry import create
    optimizer, out = create(method, instance, parameters or {}, seed, steps + 2), []
    try:
        for step in range(steps):
            proposal, candidate = conformance._next(optimizer, instance)
            conformance._observe(optimizer, instance, proposal, candidate, step)
            out.append(candidate)
    finally:
        optimizer.close()
    return out


def test_bundled_methods_declare_whether_they_draw_from_the_seed():
    declared = {method["id"]: method["stochastic"] for method in BUILTINS}
    assert {name for name, value in declared.items() if not value} == {"replay", "evaluate_asset"}
    assert stochastic("a_method_nobody_installed") is True
    instance = ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())
    # The declarations hold: replay proposes the same for seeds 0 and 7; random and coordinate do not.
    listed = {"candidates": [[0.1 * k, -0.1 * k] for k in range(6)]}
    assert proposals("replay", instance, 0, listed) == proposals("replay", instance, 7, listed)
    for method in ("random", "coordinate"):
        assert proposals(method, instance, 0) != proposals(method, instance, 7)


DECLARED = '''
from .harness import deterministic

METHODS = {
    "sweep": {"name": "Sweep", "description": "A fixed grid, whatever the seed."},
    "liar": {"name": "Liar", "description": "Says it ignores the seed, but draws from it.", "stochastic": False},
}


@deterministic
def sweep(problem, evaluate, rng):
    for x in (-0.5, 0.0, 0.5):
        evaluate([x, x])


def liar(problem, evaluate, rng):
    for _ in range(3):
        evaluate([float(rng.uniform(-1, 1)), 0.0])
'''


def test_a_library_declares_deterministic_and_conformance_confirms_it(library):
    package, root = library
    (root / "harness.py").write_text("def deterministic(method):\n    method.deterministic = True\n    return method\n")
    (root / "methods.py").write_text(textwrap.dedent(DECLARED))
    plugins = plugins_of(package)
    listed = {method["id"]: method for method in plugins.methods()}
    assert listed["sweep"]["stochastic"] is False and listed["liar"]["stochastic"] is False
    assert not stochastic("sweep", plugins)
    instance = ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())
    plugin = plugins.get("sweep")[0]
    assert "declared deterministic" in conformance.check_function(plugin, "sweep", instance)["checks"]
    with pytest.raises(AssertionError, match="declared deterministic .* seeds 0 and 7 gave different proposals at step 1"):
        conformance.check_function(plugin, "liar", instance)


class SeedPlugin:
    """Two ask/tell methods declared deterministic: one ignores its seed, the other passes it on to coordinate search."""

    def methods(self):
        return [{"id": name, "name": name, "description": name, "representations": ["continuous"], "constraints": True, "parameters": {},
                 "parameter_properties": {}, "stochastic": False} for name in ("fixed_start", "seeded_start")]

    def unavailable_reason(self):
        return None

    def validate(self, name, instance, parameters):
        return None

    def create(self, name, instance, parameters, seed):
        return Walk(0 if name == "fixed_start" else seed)


class Walk:
    """A seeded walk in two dimensions, its checkpoint the step it is at."""

    def __init__(self, seed):
        self.seed, self.step = seed, 0

    def propose(self, max_candidates=1):
        import random
        from optimization_framework.contracts.problems import Proposal
        rng = random.Random(self.seed * 1000 + self.step)
        self.step += 1
        return [Proposal(id=f"p{self.step}", candidate=[rng.uniform(-1, 1), rng.uniform(-1, 1)])]

    def observe(self, observations):
        return None

    def checkpoint(self):
        return {"step": self.step}

    def restore(self, state):
        self.step = state["step"]

    def inspect(self):
        return {"step": self.step}

    def close(self):
        return None


def test_conformance_refuses_an_ask_tell_method_falsely_declared_deterministic():
    from optimization_framework.optimizers.plugins import OptimizerPlugins
    registry = OptimizerPlugins({"seeds": "test_assessment_gate:SeedPlugin"})
    instance = ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())
    assert not stochastic("fixed_start", registry)
    assert "declared deterministic" in conformance.check("fixed_start", instance, optimizer_plugins=registry)["checks"]
    with pytest.raises(AssertionError, match="declared deterministic .* seeds 0 and 7 gave different proposals"):
        conformance.check("seeded_start", instance, optimizer_plugins=registry)
