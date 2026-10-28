"""Validation outside the box (roadmap H6): before a delivered library's install counts, the host runs on the exact commit's
files, in a sandbox with no network, the library's own tests, each method's conformance and the protected acceptance tests the
box never saw. A method that fails there is not installed, not bound and does not run, and the coder is told what failed in a
result file; protected tests come back by name and outcome only. The sandbox is real here; uv is faked as in the install tests."""
import json
import shutil

import pytest

from optimization_framework.agents import library_validation as validation
from optimization_framework.agents.library_install import Installer
from optimization_framework.problem_charter.scaffold import scaffold
from test_development_generated_library import LIBRARY, delivered  # noqa: F401  (the fixture)
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens

pytestmark = pytest.mark.skipif(not shutil.which("bwrap"), reason="validation outside the box needs bubblewrap")

# all_cold sets every tray to 160 C, which is not a listed temperature: an invalid candidate at its first evaluation.
BROKEN = METHODS.replace("evaluate(np.full(problem.dimensions, 150.0))\n\n\ndef spin", "evaluate(np.full(problem.dimensions, 160.0))\n\n\ndef spin")
REPORTED = {"methods": [{"method_id": method, "conformance": "passed"} for method in ("random_search", "all_middle", "all_cold")]}
SECRET = "words of the protected test that the coding agent never reads"
# A protected acceptance test, as the ticket (H4) will keep one: no method leaves every tray cold. all_cold does.
PROTECTED = f'''
import numpy as np
import pytest

from oven_trays.harness import methods, run
from oven_trays.problem import problem


@pytest.mark.parametrize("name", sorted(methods()))
def test_no_method_leaves_every_tray_cold(name):
    result = run(methods()[name], problem(), seed=0, max_evaluations=20)
    assert not (np.asarray(result.best) == 150.0).all(), "{SECRET}"
'''


def files(methods=METHODS, **changes):
    """libraries/oven_trays/ as a commit holds it: the ovens' generated library with its objective and methods filled."""
    generated = scaffold(ovens(), 1, charter_id="problem_charter_ovens", balsamic=True)
    generated.update({"oven_trays/objective.py": OBJECTIVE.encode(), "oven_trays/methods.py": methods.encode()})
    generated.update({path: text.encode() for path, text in changes.items()})
    return {f"{LIBRARY}/{path}": content for path, content in generated.items()}


def test_a_library_that_passes_everything_passes_on_the_host_with_each_methods_conformance():
    result = validation.run(files(), "oven_trays")
    assert result["tests"]["failed"] == 0 and result["tests"]["passed"] >= 10, result["tests"]
    assert {row["method_id"]: (row["conformance"], row["check"], row["problem_id"]) for row in result["methods"]} == {
        method: ("passed", "check_function", "oven_trays") for method in ("random_search", "all_middle", "all_cold")}
    assert result["protected"] is None and result["seconds"] > 0
    judged = validation.verdict(result, REPORTED)
    assert judged["refused_methods"] == [] and judged["library_failures"] == []


def test_a_method_reported_passing_that_fails_conformance_on_the_host_is_refused_with_what_failed():
    # The coder emptied the library's own tests: only the host's conformance catches the method.
    result = validation.run(files(BROKEN, **{"tests/test_methods.py": "", "tests/test_contract.py": ""}), "oven_trays")
    assert result["tests"]["failed"] == 0
    judged = validation.verdict(result, REPORTED)
    [refused] = judged["refused_methods"]
    assert (refused["method_id"], refused["reported"]) == ("all_cold", "passed") and judged["library_failures"] == []
    assert refused["failing"] == ["conformance (check_function on oven_trays): seed 0, evaluation 1: an invalid candidate "
                                  "(Candidate contains a value outside the declared discrete domain)"]
    # With its tests, they fail too, each named on the method it tests.
    [refused] = validation.verdict(validation.run(files(BROKEN), "oven_trays"), REPORTED)["refused_methods"]
    assert {"tests/test_methods.py::test_a_method_evaluates_valid_candidates[all_cold]",
            "tests/test_contract.py::test_each_method_meets_the_contract[all_cold]"} <= set(refused["failing"])


def test_the_sandbox_has_no_network_and_none_of_the_hosts_files():
    probe = '''
import os, socket
from pathlib import Path


def test_no_network():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
    except OSError:
        return
    raise AssertionError("the sandbox reached the network")


def test_none_of_the_hosts_files():
    assert not Path("/root").exists() and not Path("/etc/passwd").exists() and not Path("/home/user/Balsamic/workspace").exists()
    assert not os.access("/library", os.W_OK)
'''
    result = validation.run(files(**{"tests/test_walls.py": probe}), "oven_trays")
    outcomes = {row["test"]: row["outcome"] for row in result["tests"]["results"]}
    assert outcomes["tests/test_walls.py::test_no_network"] == "passed"
    assert outcomes["tests/test_walls.py::test_none_of_the_hosts_files"] == "passed", result["tests"]


def test_the_verdict_names_each_methods_tests_and_leaves_the_rest_to_the_library():
    result = {"methods": [{"method_id": "all", "conformance": "passed", "check": "check_function", "problem_id": "p"},
                          {"method_id": "all_cold", "conformance": "passed", "check": "check_function", "problem_id": "p"}],
              "tests": {"results": [{"test": "tests/test_methods.py::test_valid[all_cold]", "outcome": "failed", "detail": "x"},
                                    {"test": "tests/test_methods.py::test_cap[all-7]", "outcome": "failed", "detail": "x"},
                                    {"test": "tests/test_problem.py::test_reference", "outcome": "failed", "detail": "x"},
                                    {"test": "tests/test_methods.py::test_valid[all]", "outcome": "passed"}]},
              "protected": {"passed": 0, "failed": 1, "skipped": 0,
                            "results": [{"test": "test_hidden.py::test_secret[all_cold]", "outcome": "failed", "detail": SECRET}]}}
    judged = validation.verdict(result, {"methods": [{"method_id": "all", "conformance": "passed"}]})
    assert [(row["method_id"], row["reported"], row["failing"]) for row in judged["refused_methods"]] == [
        ("all", "passed", ["tests/test_methods.py::test_cap[all-7]"]),
        ("all_cold", "not_reported", ["tests/test_methods.py::test_valid[all_cold]", "test_hidden.py::test_secret[all_cold]"])]
    assert judged["library_failures"] == ["tests/test_problem.py::test_reference"]
    shown = validation.public(result)
    assert SECRET not in json.dumps(shown)
    assert shown["protected"]["results"] == [{"test": "test_hidden.py::test_secret[all_cold]", "outcome": "failed"}]


# Through the install ------------------------------------------------------------------------------------------------------
def real(installer, workspace, record):
    """The fixture's installer (a fake uv, the lab's plug-ins faked), validating with the real sandbox; the workspace's record
    as create() writes it, so the coder can be messaged."""
    workspace.store.put("development_workspace", {**workspace.store.get(record["id"], "development_workspace"), "guidance_revision": 0})
    return Installer(installer.workspace, installer.development, installer.root, runner=installer.runner, uv="uv",
                     plugins=installer.plugins, problems=installer.problems, providers=installer.providers)


def told(workspace, cid):
    return [row for row in workspace.store.list("development_command", cid) if row["request_key"].startswith("host-validation-")]


def test_a_library_that_passes_everything_installs_as_before(delivered):  # noqa: F811
    workspace, cid, record, installer, deliver, root = delivered
    submission = deliver({})
    install = real(installer, workspace, record).request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "installed" and install["refused_methods"] == [] and (root / LIBRARY / "pyproject.toml").exists()
    host = install["host_validation"]
    assert host["tests"]["failed"] == 0 and {row["method_id"]: (row["reported"], row["host"]) for row in host["methods"]} == {
        method: ("passed", "passed") for method in ("random_search", "all_middle", "all_cold")}
    assert told(workspace, cid) == [] and not (installer.development.driver.root(record) / "incoming/results").exists()


def test_a_method_that_fails_on_the_host_is_not_installed_bound_or_run_and_the_coder_is_told_once(delivered):  # noqa: F811
    from optimization_framework.contracts.base import content_hash
    from optimization_framework.contracts.requests import TrialInput
    from optimization_framework.implementations.builtin import bind
    workspace, cid, record, installer, deliver, root = delivered
    validation.protect(workspace.store, record, "test_heater.py", PROTECTED)
    submission = deliver({"oven_trays/methods.py": BROKEN})
    validating = real(installer, workspace, record)
    install = validating.request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "installed"
    [refused] = install["refused_methods"]
    assert (refused["method_id"], refused["reported"]) == ("all_cold", "passed")
    assert refused["failing"][0].startswith("conformance (check_function on oven_trays): seed 0, evaluation 1: an invalid candidate")
    assert "test_heater.py::test_no_method_leaves_every_tray_cold[all_cold]" in refused["failing"]
    assert "all_cold" not in install["methods_added"] + install["missing_methods"]
    # The protected test ran outside the box: its outcomes are on the install by name, never its source or its failure text.
    protected = install["host_validation"]["protected"]
    assert {row["test"]: row["outcome"] for row in protected["results"]} == {
        f"test_heater.py::test_no_method_leaves_every_tray_cold[{method}]": "failed" if method == "all_cold" else "passed"
        for method in ("all_cold", "all_middle", "random_search")}
    assert SECRET not in json.dumps(install)
    # The coder gets one result file and one message naming what failed; nothing of the protected test is in the box.
    box = installer.development.driver.root(record)
    [result] = (box / "incoming/results").glob("host-validation-*.json")
    shown = json.loads(result.read_text())
    assert (shown["commit"], shown["refused_methods"]) == (submission["commit"], install["refused_methods"])
    for path in box.rglob("*"):
        assert not path.is_file() or (SECRET.encode() not in path.read_bytes() and b"def test_no_method_leaves" not in path.read_bytes())
    [message] = told(workspace, cid)
    assert message["actor"] == "system" and "Methods not installed: all_cold (reported passed" in message["message"]
    assert f"The results are in /bridge/in/results/{result.name}." in message["message"]   # where the box mounts incoming/
    validating.request(cid, record["id"], submission["id"], request_key="one", background=False)   # replayed: told once
    assert len(told(workspace, cid)) == 1
    # The method is not installed: binding it or starting a run of it is refused with what failed.
    assert validation.refused_reason(workspace.store, "all_cold").startswith("all_cold failed validation outside the box (conformance")
    assert validation.refused_reason(workspace.store, "all_middle") is None
    [task] = workspace.current_tasks(cid)
    with pytest.raises(ValueError, match="all_cold failed validation outside the box"):
        workspace.create_trial(TrialInput(campaign_id=cid, task_id=task["id"], algorithm="all_cold", max_steps=5, wall_seconds=30))
    workspace.store.put("hypothesis", {"id": "hypothesis_cold", "campaign_id": cid, "title": "Cold", "status": "proposed",
                                       "algorithm": "custom", "algorithm_config": {}})
    with pytest.raises(ValueError, match="all_cold failed validation outside the box"):
        bind(workspace, cid, {"hypothesis_id": "hypothesis_cold", "task_id": task["id"], "algorithm": "all_cold", "parameters": {},
                              "expected_algorithm": "custom", "expected_configuration_hash": content_hash({}), "reason": "Try it"}, "bind_cold")


def test_a_library_failing_in_a_test_no_method_owns_is_not_installed_at_all(delivered):  # noqa: F811
    workspace, cid, record, installer, deliver, root = delivered
    submission = deliver({"tests/test_extra.py": "def test_the_library_imports():\n    import oven_trays.missing\n"})
    install = real(installer, workspace, record).request(cid, record["id"], submission["id"], request_key="one", background=False)
    assert install["status"] == "failed" and "tests no method owns: tests/test_extra.py::test_the_library_imports" in install["error"]
    assert not (root / LIBRARY).exists() and install["methods_added"] == []
    [result] = (installer.development.driver.root(record) / "incoming/results").glob("host-validation-*.json")
    assert json.loads(result.read_text())["status"] == "failed" and len(told(workspace, cid)) == 1


def test_validation_is_charged_to_the_go_ahead_the_workspace_opened_under(delivered):  # noqa: F811
    from optimization_framework.campaigns import compute_consent
    workspace, cid, record, installer, deliver, root = delivered
    consent = compute_consent.grant(workspace, {"id": "decision_go", "campaign_id": cid}, {"plan": "Build the ovens' methods",
        "wall_seconds": 3600, "worker_seconds": 600, "coding_workspaces": 1})
    workspace.store.put("development_workspace", {**workspace.store.get(record["id"], "development_workspace"),
                                                  "consent": {"id": consent["id"], "decision_id": "decision_go", "plan": consent["plan"]}})
    submission = deliver({})
    install = real(installer, workspace, record).request(cid, record["id"], submission["id"], request_key="one", background=False)
    used = workspace.store.get(consent["id"], "compute_consent")["used_seconds"]
    assert install["status"] == "installed" and 0 < used == pytest.approx(install["host_validation"]["seconds"])


def test_an_interpreter_reached_through_a_linked_directory_starts_in_the_sandbox(tmp_path, monkeypatch):
    """uv's python lives in cpython-3.13-... -> cpython-3.13.13-...: binding the one file at the link's path left Python
    without its standard library ("No module named 'encodings'"), so the link itself is recreated."""
    real = tmp_path / "cpython-3.13.13" / "bin"
    real.mkdir(parents=True)
    (real / "python3.13").write_text("")
    link = tmp_path / "cpython-3.13"
    link.symlink_to("cpython-3.13.13")
    monkeypatch.setattr(validation, "links", lambda executable=None: [str(link / "bin" / "python3.13")])
    monkeypatch.setattr(validation, "roots", lambda: [])
    args = validation.command(tmp_path, tmp_path, tmp_path, {})
    assert args[args.index("--symlink") + 1:args.index("--symlink") + 3] == ["cpython-3.13.13", str(link)]
    assert str(real.parent) in args and str(link / "bin" / "python3.13") not in args
