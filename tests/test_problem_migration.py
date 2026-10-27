"""No MEENT paths in execution (roadmap N7): old records get their problem once, from their problem's pack; nothing falls
back to a default problem, and trials of the old execution contract are read-only history."""
import pytest

from optimization_benchmarks.problems import ContinuousProblem
from optimization_framework.contracts.packs import ProblemPack
from optimization_framework.contracts.commands import TrialContinueInput
from optimization_framework.contracts.requests import CampaignInput, ControlInput, RecipeInput, TaskInput, ValidationInput
from optimization_framework.evaluation.registry import ProblemRegistry, problems
from optimization_framework.execution import problem_migration
from optimization_framework.execution.problem_migration import migrate
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.source import runtime_identity
from optimization_framework.implementations.models import ImplementationSpec

PHYSICS = {"n_cells": 4}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    lab = Workspace(tmp_path / "workspace")
    yield lab
    lab.close()


def old_records(workspace):
    """A campaign with records written before problems were declared: a grating task and trial that store only their
    physics, a trial that stores nothing but its task, and a task and trial no installed problem recognises."""
    campaign = workspace.create_campaign(CampaignInput(name="History", compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    base = {"campaign_id": campaign["id"], "split": "train", "archived": True}
    trial = {"campaign_id": campaign["id"], "status": "completed", "algorithm": "random", "seed": 0, "attempt": 1,
             "max_steps": 10, "wall_seconds": 10, "control_revision": 0, "progress": {"checkpoint_available": True}}
    workspace.store.put("task", {**base, "id": "task_grating", "name": "Grating", "physics": PHYSICS})
    workspace.store.put("trial", {**trial, "id": "trial_grating", "task_id": "task_grating", "physics": PHYSICS})
    workspace.store.put("trial", {**trial, "id": "trial_of_task", "task_id": "task_grating", "problem": None})
    workspace.store.put("task", {**base, "id": "task_unknown", "name": "Unknown", "physics": {"wavelength": 900}})
    workspace.store.put("trial", {**trial, "id": "trial_unknown", "task_id": "task_unknown", "physics": {"wavelength": 900},
                                  "progress": {"best_design": [1, 0, 1, 0]}})
    return campaign


def test_the_migration_resolves_old_tasks_and_trials_through_the_pack_and_is_idempotent(workspace):
    old_records(workspace)
    result = migrate(workspace.store)
    assert result == {"tasks": ["task_grating"], "trials": ["trial_grating", "trial_of_task"],
                      "unresolved": ["task_unknown", "trial_unknown"]}
    expected = problems.resolve("meent_grating", PHYSICS).model_dump(mode="json")
    for kind, record_id in (("task", "task_grating"), ("trial", "trial_grating"), ("trial", "trial_of_task")):
        assert workspace.store.get(record_id, kind)["problem"] == expected
    assert workspace.store.get("task_unknown", "task").get("problem") is None
    assert any(event["kind"] == "problem.migration_unresolved" and event["data"]["record_ids"] == ["task_unknown", "trial_unknown"]
               for event in workspace.store.events())
    before = {kind: workspace.store.list(kind) for kind in ("task", "trial")}
    assert migrate(workspace.store) == {"tasks": [], "trials": [], "unresolved": ["task_unknown", "trial_unknown"]}
    assert {kind: workspace.store.list(kind) for kind in ("task", "trial")} == before


def test_the_workspace_migrates_at_start_and_the_command_reports_on_a_copy(workspace, tmp_path, capsys):
    old_records(workspace)
    directory = workspace.directory
    workspace.close()
    reopened = Workspace(directory)
    try:
        assert reopened.store.get("trial_grating", "trial")["problem"]["definition_id"] == "meent_grating"
    finally:
        reopened.close()
    assert problem_migration.main([str(directory)]) == 1   # the unknown records stay unresolved
    assert '"unresolved": [\n    "task_unknown",\n    "trial_unknown"\n  ]' in capsys.readouterr().out
    assert problem_migration.main([str(tmp_path / "absent")]) == 2


def test_a_record_with_no_problem_after_the_migration_is_refused_naming_it(workspace):
    campaign = old_records(workspace)
    migrate(workspace.store)
    with pytest.raises(ValueError, match="experiment trial_unknown records no problem"):
        workspace.validate_trial("trial_unknown", ValidationInput(orders=[5, 9], max_designs=1))
    with pytest.raises(ValueError, match="experiment trial_unknown records no problem"):
        workspace.run_recipe("trial_unknown", RecipeInput(recipe_id="fourier_convergence:v1"))
    with pytest.raises(ValueError, match="task task_unknown records no problem"):
        workspace.runtime.subject(workspace.store.get("task_unknown", "task"))
    assert campaign["id"]


def test_an_old_contract_trial_is_read_only_history(workspace):
    old_records(workspace)
    migrate(workspace.store)
    message = "Experiment trial_grating ran under the old execution contract.*read-only history"
    with pytest.raises(ValueError, match=message + ".*resumed or extended"):
        workspace.control("trial_grating", ControlInput(action="resume"))
    with pytest.raises(ValueError, match=message + ".*extended"):
        workspace.control("trial_grating", ControlInput(action="extend", max_steps=20))
    with pytest.raises(ValueError, match=message + ".*continued"):
        workspace.continue_trial(TrialContinueInput(trial_id="trial_grating", wall_seconds=10))
    with pytest.raises(ValueError, match=message):
        workspace._start_trial(workspace.store.get("trial_grating", "trial"))
    trial = workspace.store.get("trial_grating", "trial")   # reading it works
    assert trial["status"] == "completed" and trial["attempt"] == 1
    assert workspace.trial_archive(trial) == []


def test_the_runtime_identity_takes_meent_from_its_pack_once():
    identity = runtime_identity()
    assert set(identity) >= {"python", "numpy", "scipy", "torch", "meent"}
    assert problems.pack("meent_grating").legacy == {"problem": "dqn_meent.pack.legacy:problem",
                                                     "runtime": "dqn_meent.pack.legacy:runtime"}
    assert len(problems.legacy("runtime")) == 1   # one pack serves both MEENT problems


def test_a_problem_without_a_legacy_hook_adds_nothing(tmp_path, monkeypatch):
    root = tmp_path / "site" / "legacy_fixture"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "hooks.py").write_text("def runtime():\n    return {'solver': '1.0'}\n")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))

    class Packed(ContinuousProblem):
        def describe(self):
            return super().describe().model_copy(update={"id": "packed"})

        def pack(self):
            return ProblemPack(package="legacy_fixture", problem_ids=["packed"], legacy={"runtime": "legacy_fixture.hooks:runtime"})

    registry = ProblemRegistry()
    for adapter in (Packed(), ContinuousProblem()):
        registry.register(adapter.describe().id, lambda adapter=adapter: lambda: adapter)
    assert [hook() for hook in registry.legacy("runtime")] == [{"solver": "1.0"}]
    assert registry.legacy("problem") == []


def test_an_implementation_spec_names_its_problem():
    values = {"name": "Search", "mechanism": "Random search", "acceptance_criteria": ["Proposes valid candidates"]}
    with pytest.raises(ValueError, match="problem_id"):
        ImplementationSpec.model_validate(values)
    assert ImplementationSpec.model_validate({**values, "problem_id": "bounded_continuous"}).problem_id == "bounded_continuous"
    from optimization_framework.implementations.bridge import ImplementationBridge
    with pytest.raises(ValueError, match="version_old names no problem"):
        ImplementationBridge.compatible({"id": "version_old", "spec": {"capabilities": []}}, None, {})
