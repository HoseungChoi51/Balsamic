"""Tests accumulate and kept methods reproduce their recorded runs (roadmap L4, decision 25). Validation outside the box runs
every earlier version's tests the new version does not hold unchanged, and replays the first evaluations of the recorded runs of
each kept method and problem: a method fed the recorded results must propose the recorded candidates, a problem must evaluate
them to the recorded results. The sandbox is real here; the recorded run is made in this process from the same library."""
import importlib
import json
import shutil
import sys

import pytest

from optimization_framework.agents import library_repository as repositories, library_validation as validation
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace

from optimization_framework.agents.library_install import kept_text

from test_development_generated_library import delivered   # noqa: F401  (the fixture)
from test_library_keep import Versioned
from test_library_validation import files
from test_problem_charter_scaffold import METHODS, OBJECTIVE

pytestmark = pytest.mark.skipif(not shutil.which("bwrap"), reason="validation outside the box needs bubblewrap")

PREFIX = "libraries/oven_trays/"
# random_search draws one number more before its first candidate: the same name, another behaviour.
DRIFTED = METHODS.replace("    while True:\n        candidate = problem.random_candidate(rng)",
                          "    rng.random()\n    while True:\n        candidate = problem.random_candidate(rng)")
# The objective counts one more: the same problem id, another scoring function.
RESCORED = OBJECTIVE.replace(".sum())", ".sum()) + 1.0")
# An earlier version's test of all_middle, which the new version dropped from its own tests.
EARLIER = '''
import numpy as np
import pytest

from oven_trays.harness import methods, run
from oven_trays.problem import problem


@pytest.mark.parametrize("name", ["all_middle"])
def test_all_middle_sets_every_tray_to_175(name):
    result = run(methods()[name], problem(), seed=0, max_evaluations=5)
    assert (np.asarray(result.best) == 175.0).all()
'''


@pytest.fixture
def recorded(tmp_path):
    """A run of random_search on the ovens, seed 3, recorded as the worker records it: its instance and first 6 observations."""
    root = tmp_path / "recorded"
    for path, content in files().items():
        (root / path[len(PREFIX):]).parent.mkdir(parents=True, exist_ok=True)
        (root / path[len(PREFIX):]).write_bytes(content)
    sys.path.insert(0, str(root))
    try:
        adapter = importlib.import_module("oven_trays.adapter")
        registry = problems.extended(adapter.problem_adapter())
        instance = registry.resolve("oven_trays", {}, None)
        evaluator, method = registry.evaluator(instance), adapter.method_plugin().create("random_search", instance, {}, 3)
        observations = []
        from optimization_framework.contracts.problems import Observation
        for index in range(6):
            proposal = method.propose(1)[0]
            candidate = instance.candidate_schema.canonicalize(proposal.candidate)
            objectives = evaluator.evaluate(candidate).objectives
            observations.append({"candidate": candidate, "status": "ok", "objectives": objectives, "constraints": {}})
            method.observe([Observation(id=f"o{index}", experiment_id="trial_r", attempt_id="a", request_id=f"r{index}", proposal_id=proposal.id,
                                        candidate=candidate, status="ok", objectives=objectives, fidelity=instance.fidelity,
                                        evaluator_identity=instance.evaluation_identity)])
        method.close()
    finally:
        sys.path.remove(str(root))
        for name in [name for name in sys.modules if name == "oven_trays" or name.startswith("oven_trays.")]:
            del sys.modules[name]
    problem = json.loads(instance.model_dump_json())
    common = {"trial_id": "trial_r", "campaign_id": "campaign_a", "problem": problem, "parameters": {}, "seed": 3, "schedule_steps": 0,
              "observations": json.loads(json.dumps(observations))}
    return [{"kind": "method", "id": "random_search", **common}, {"kind": "problem", "id": "oven_trays", **common}]


def test_an_unchanged_method_and_problem_reproduce_their_recorded_run(recorded):
    result = validation.run(files(), "oven_trays", replays=recorded)
    assert [(row["kind"], row["outcome"], row["at"]) for row in result["replays"]] == [("method", "reproduced", 6), ("problem", "reproduced", 6)]
    judged = validation.verdict(result, {})
    assert judged["refused_methods"] == [] and judged["library_failures"] == []
    assert validation.reproduced(result) == {"methods": ["random_search"], "problems": ["oven_trays"], "runs": 1}


def test_a_kept_method_whose_proposals_changed_is_refused_naming_the_run_and_the_evaluation(recorded):
    result = validation.run(files(DRIFTED), "oven_trays", replays=recorded)
    [refused] = validation.verdict(result, {})["refused_methods"]
    assert refused["method_id"] == "random_search"
    assert refused["failing"] == ["does not reproduce run trial_r at evaluation 1: it proposed another candidate than the recorded run"]


def test_a_kept_problem_whose_objective_changed_refuses_the_library(recorded):
    result = validation.run(files(**{"oven_trays/objective.py": RESCORED}), "oven_trays", replays=recorded[1:])
    failures = validation.verdict(result, {})["library_failures"]
    assert any(failure.startswith("problem oven_trays does not reproduce run trial_r at evaluation 1: squared_gap is ") for failure in failures), failures


def test_an_earlier_versions_test_of_a_kept_method_refuses_it_and_one_of_a_removed_method_does_not_count():
    broken = METHODS.replace("np.full(problem.dimensions, 175.0)", "np.full(problem.dimensions, 150.0)")
    result = validation.run(files(broken), "oven_trays", earlier={"0.1.0/tests/test_earlier.py": EARLIER.encode()})
    assert result["earlier"]["failed"] == 1
    [refused] = validation.verdict(result, {})["refused_methods"]
    assert refused["method_id"] == "all_middle"
    assert refused["failing"][-1] == "tests/test_earlier.py::test_all_middle_sets_every_tray_to_175[all_middle] (an earlier version's test)".replace(
        "tests/", "0.1.0/tests/")
    # A failed earlier test naming a method the version removed does not count; one naming nothing is the library's.
    synthetic = {"methods": [], "earlier": {"results": [{"test": "0.1.0/tests/test_x.py::test_old", "outcome": "failed", "detail": "KeyError: 'bakery_old'"},
                                                        {"test": "0.1.0/tests/test_x.py::test_other", "outcome": "failed", "detail": "AssertionError"}]}}
    assert validation.verdict(synthetic, {}, removed={"bakery_old"})["library_failures"] == [
        "0.1.0/tests/test_x.py::test_other (an earlier version's test)"]


def test_the_host_gathers_earlier_tests_and_recorded_runs(tmp_path, recorded):
    workspace = Workspace(tmp_path / "workspace")
    current = files(**{"tests/test_problem.py": "# rewritten\n"})
    store, made = repositories.commit(workspace.directory, "oven_trays", files(), "oven-trays 0.1.0")
    repositories.record(workspace.store, "oven_trays", "oven-trays", "0.1.0", repositories.publish(store, made, "0.1.0"), source={},
                        methods=["random_search"], problems=["oven_trays"])
    earlier = validation.earlier_tests(workspace.store, workspace.directory, "oven_trays", current)
    # The test file the new version rewrote, with the helpers of its tests/ beside it; unchanged test files are not run twice.
    assert "0.1.0/tests/test_problem.py" in earlier and "0.1.0/tests/test_methods.py" not in earlier
    assert all(not path.split("/")[-1].startswith("test_") or path == "0.1.0/tests/test_problem.py" for path in earlier)

    campaign = workspace.create_campaign(CampaignInput(name="Ovens", compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    item = recorded[0]
    workspace.store.put("trial", {"id": "trial_r", "campaign_id": campaign["id"], "algorithm": "random_search", "seed": 3,
                                  "problem": item["problem"], "algorithm_config": {}, "schedule_steps": 0})
    journal = workspace.job_dir("trial_r") / "observations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("".join(json.dumps(row) + "\n" for row in [*item["observations"], {"status": "uncertain", "candidate": []}]))
    runs = validation.recorded_runs(workspace, {"random_search", "never_ran"}, {"oven_trays"}, evaluations=4)
    assert [(row["kind"], row["id"], row["trial_id"], len(row["observations"])) for row in runs] == [
        ("method", "random_search", "trial_r", 4), ("problem", "oven_trays", "trial_r", 4)]


def test_an_install_whose_kept_method_does_not_reproduce_a_run_another_campaign_made_is_refused(delivered, recorded):  # noqa: F811
    workspace, cid, record, installer, deliver, root = delivered
    # oven-trays 0.1.0 is installed, and random_search ran in a campaign: its recorded run.
    (root / "libraries/oven_trays").mkdir(parents=True)
    for path, content in files().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
    item = recorded[0]
    workspace.store.put("trial", {"id": "trial_r", "campaign_id": cid, "algorithm": "random_search", "seed": 3, "problem": item["problem"],
                                  "algorithm_config": {}, "schedule_steps": 0, "status": "completed"})
    journal = workspace.job_dir("trial_r") / "observations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("".join(json.dumps(row) + "\n" for row in item["observations"]))
    class Ovens(Versioned):
        def origin(self, method_id):
            return None if method_id == "random" else {"distribution": "oven-trays"}
    installer.plugins = Ovens(["random_search", "all_middle", "all_cold"], ["random_search", "all_middle", "all_cold"])
    installer.validator = validation.run
    submission = deliver({"oven_trays/methods.py": DRIFTED, "pyproject.toml": (root / "libraries/oven_trays/pyproject.toml").read_text()
                          .replace('version = "0.1.0"', 'version = "0.2.0"')})
    install = installer.request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "failed" and "method random_search fails validation outside the box, and Ovens uses it" in install["error"]
    [refused] = install["refused_methods"]
    assert refused["failing"] == ["does not reproduce run trial_r at evaluation 1: it proposed another candidate than the recorded run"]
    # The same version with random_search unchanged installs, and says its kept methods reproduce the recorded run.
    submission = deliver({"oven_trays/methods.py": METHODS}, number=2)
    install = installer.request(cid, record["id"], submission["id"], request_key="two", background=False)
    assert install["status"] == "installed", install.get("error")
    assert install["host_validation"]["reproduced"] == {"methods": ["random_search"], "problems": [], "runs": 1}
    assert kept_text(install) == "Of the version it replaced, it keeps 3 methods (1 reproduces 1 recorded run)"


def test_protected_tests_of_earlier_workspaces_on_the_library_stay_with_it(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    store = workspace.store
    for wid, name in (("development_workspace_aaaaaaaa", "oven_trays"), ("development_workspace_bbbbbbbb", "oven_trays"),
                      ("development_workspace_cccccccc", "bakery")):
        store.put("development_workspace", {"id": wid, "campaign_id": "campaign_a", "library": {"name": name}})
    records = {row["id"]: row for row in store.list("development_workspace")}
    validation.protect(store, records["development_workspace_aaaaaaaa"], "test_hot.py", "def test_hot():\n    pass\n")
    validation.protect(store, records["development_workspace_cccccccc"], "test_other.py", "def test_other():\n    pass\n")
    # The second workspace on oven_trays carries the first one's protected test; another library's stays with it.
    assert validation.earlier_protected(store, records["development_workspace_bbbbbbbb"], "oven_trays") == {
        "test_aaaaaaaa_hot.py": "def test_hot():\n    pass\n"}
    assert validation.earlier_protected(store, records["development_workspace_aaaaaaaa"], "oven_trays") == {}
