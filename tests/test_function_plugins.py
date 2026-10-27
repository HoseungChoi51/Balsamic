"""A library of plain functions as plug-in methods: listed from its source without importing it, created in the worker,
checked by ``conformance.check_function`` on the problem's own evaluator, and run with a fixed hash seed."""
import os
import subprocess
import sys
import textwrap

import pytest

from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution import service
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import run
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.functions import FunctionPlugin, listed_methods
from optimization_framework.optimizers.plugins import OptimizerPlugins
from optimization_framework.optimizers.registry import create, methods


PLUGIN = '''
from optimization_framework.optimizers.functions import FunctionPlugin


class Plugin(FunctionPlugin):
    MODULE = "{package}.methods"
    REPRESENTATIONS = ["continuous"]
'''

METHODS = '''
import time

METHODS = {
    "three_draws": {"name": "Three draws", "description": "Three seeded draws, then returns.", "hypothesis_id": "hypothesis_1"},
    "walk": {"name": "Seeded walk", "description": "A seeded random walk until the cap.",
             "parameters": {"step": 0.1}, "parameter_properties": {"step": {"type": "number", "exclusiveMinimum": 0}}},
    "clocked": {"name": "Clocked", "description": "Reads the clock, so the same seed proposes other candidates."},
    "outside": {"name": "Outside", "description": "Proposes a candidate outside the bounds."},
}


def three_draws(problem, evaluate, rng):
    bounds = problem["candidate_schema"]["bounds"]
    for _ in range(3):
        evaluate([float(rng.uniform(low, high)) for low, high in bounds])
    return "three draws done"


def walk(problem, evaluate, rng):
    point = [0.0 for _ in problem["candidate_schema"]["bounds"]]
    best = evaluate(point)
    while True:
        trial = [min(1.0, max(-1.0, value + float(rng.normal(0, 0.1)))) for value in point]
        score = evaluate(trial)
        if score < best:
            point, best = trial, score


def clocked(problem, evaluate, rng):
    while True:
        evaluate([(time.perf_counter_ns() % 1000) / 1000, 0.0])


def outside(problem, evaluate, rng):
    evaluate([99.0, 0.0])
'''


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A function library on sys.path, as an install leaves it; a fresh package name per test, so nothing is cached."""
    package = "fnlib_" + os.path.basename(tmp_path).replace("-", "_").lower()
    root = tmp_path / "site" / package
    root.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "plugin.py").write_text(textwrap.dedent(PLUGIN).format(package=package))
    (root / "methods.py").write_text(textwrap.dedent(METHODS))
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    yield package, root
    for name in [name for name in sys.modules if name.startswith(package)]:
        sys.modules.pop(name)


def plugins_of(package):
    return OptimizerPlugins({"functions": f"{package}.plugin:Plugin"})


def instance():
    return ProblemInstance(**problems.resolve("bounded_continuous", {"dimensions": 2}).model_dump())


def test_listing_a_function_plugin_does_not_import_its_methods(library):
    package, _ = library
    listed = {method["id"]: method for method in methods(plugins_of(package))}
    assert f"{package}.methods" not in sys.modules
    assert {"three_draws", "walk", "clocked", "outside"} <= set(listed)
    assert listed["three_draws"]["representations"] == ["continuous"] and listed["three_draws"]["hypothesis_id"] == "hypothesis_1"
    assert listed["walk"]["parameters"] == {"step": 0.1}
    assert listed["walk"]["parameter_schema"]["properties"] == {"step": {"type": "number", "exclusiveMinimum": 0}}


def test_a_methods_module_that_cannot_import_on_the_server_is_still_listed(library):
    package, root = library
    (root / "methods.py").write_text("import a_package_only_the_worker_has\n\nMETHODS = {'idea': {'name': 'Idea', 'description': 'An idea.'}}\n")
    assert [method["id"] for method in plugins_of(package).methods()] == ["idea"]
    assert f"{package}.methods" not in sys.modules


@pytest.mark.parametrize("source, message", [
    ("METHODS = dict(idea={'name': 'Idea', 'description': 'An idea.'})\n", "must be a literal"),
    ("NOTHING = {}\n", "must assign METHODS once"),
    ("METHODS = {'idea': {'name': 'Idea'}}\n", "needs a name and a description"),
    ("METHODS = {'not-a-name': {'name': 'Idea', 'description': 'An idea.'}}\n", "public function"),
])
def test_a_methods_module_that_cannot_be_listed_fails_loudly(library, source, message):
    package, root = library
    (root / "methods.py").write_text(source)
    with pytest.raises(ValueError, match=message):
        listed_methods(f"{package}.methods")
    assert f"{package}.methods" not in sys.modules


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path / "lab")
    campaign = workspace.create_campaign(CampaignInput(name="Functions", compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})]))
    return workspace, campaign["id"], workspace.current_tasks(campaign["id"])[0]


def test_create_runs_the_function_in_the_worker(library, lab):
    package, _ = library
    workspace, campaign_id, task = lab
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm="random",
                                              max_steps=20, wall_seconds=20, seed=0))
    problem = ProblemInstance(**trial["problem"])
    method = create("three_draws", problem, {}, trial["seed"], 20, optimizer_plugins=plugins_of(package))
    assert f"{package}.methods" in sys.modules
    result = run(workspace.job_dir(trial["id"]), optimizer=method)
    assert result["status"] == "completed" and result["reason"] == "method_finished"
    assert result["evaluations"] == 3 and result["finish_reason"] == "three draws done"
    walk = create("walk", problem, {"step": 0.2}, 0, 20, optimizer_plugins=plugins_of(package))
    try:
        assert walk.parameters == {"step": 0.2}
    finally:
        walk.close()


def test_a_listed_id_without_its_function_is_refused_on_create(library):
    package, root = library
    (root / "methods.py").write_text("METHODS = {'missing': {'name': 'Missing', 'description': 'Not defined.'}}\n")
    with pytest.raises(ValueError, match="defines no function missing"):
        plugins_of(package).get("missing")[0].create("missing", instance(), {}, 0)


def plugin(package):
    return plugins_of(package).get("walk")[0]


def test_check_function_passes_for_a_seeded_method(library):
    package, _ = library
    one_shot = conformance.check_function(plugin(package), "three_draws", instance())
    assert one_shot["ended"] == {"0": "returned", "7": "returned"}
    endless = conformance.check_function(plugin(package), "walk", instance(), max_evaluations=12)
    assert endless["ended"] == {"0": "cap", "7": "cap"}
    assert endless["checks"] == ["valid candidates", "seeded replay", "checkpoint continuation", "clean end"]


def test_check_function_uses_the_problems_own_evaluator(library):
    package, _ = library
    seen = []

    class Recording:
        def evaluator(self, instance):
            inner = problems.evaluator(instance)

            class Evaluator:
                def evaluate(self, candidate):
                    seen.append(candidate)
                    return inner.evaluate(candidate)
            return Evaluator()

    conformance.check_function(plugin(package), "three_draws", instance(), seeds=(0,), registry=Recording())
    assert len(seen) == 3   # each distinct candidate once; the replays reuse its score


def test_check_function_fails_a_method_that_is_not_deterministic_for_its_seed(library):
    package, _ = library
    with pytest.raises(AssertionError, match="the same seed proposed a different candidate"):
        conformance.check_function(plugin(package), "clocked", instance(), max_evaluations=10)


def test_check_function_fails_a_method_that_proposes_an_invalid_candidate(library):
    package, _ = library
    with pytest.raises(AssertionError, match="an invalid candidate"):
        conformance.check_function(plugin(package), "outside", instance())


def test_a_worker_started_by_the_service_has_a_fixed_hash_seed(lab, monkeypatch):
    workspace, campaign_id, task = lab
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm="random",
                                              max_steps=2, wall_seconds=20, seed=0))
    launched, real = [], subprocess.Popen

    def spy(*args, **kwargs):
        launched.append(kwargs.get("env"))
        return real(*args, **kwargs)

    monkeypatch.setattr(service.subprocess, "Popen", spy)
    workspace._start_trial(workspace.store.get(trial["id"], "trial"))
    process = workspace.processes[trial["id"]]
    assert process.wait(timeout=30) == 0, (workspace.job_dir(trial["id"]) / "worker.log").read_text()
    assert launched and launched[-1]["PYTHONHASHSEED"] == "0"



def test_a_frozen_capture_pins_the_methods_module_it_never_imports(library, tmp_path, monkeypatch):
    from optimization_framework.execution import provenance, source
    from optimization_framework.optimizers import plugins
    package, root = library
    monkeypatch.setattr(plugins, "installed", plugins_of(package))
    monkeypatch.setattr(source, "package_names", lambda: ["optimization_framework", package])
    first = provenance.capture(tmp_path / "first", problem_ids=["bounded_continuous"])
    assert f"{package}/methods.py" in first["scientific_files"] and f"{package}.methods" not in sys.modules
    (root / "methods.py").write_text(textwrap.dedent(METHODS).replace("range(3)", "range(4)"))
    second = provenance.capture(tmp_path / "second", problem_ids=["bounded_continuous"])
    assert second["scientific_digest"] != first["scientific_digest"]
