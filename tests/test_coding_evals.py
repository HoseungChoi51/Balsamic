"""The coding-eval runner (roadmap J4): the source a workspace clones holds no trace of the method, the delivered library is
checked outside the box, and a run goes through the normal path (the implementation lead opens the workspace under the
researcher's go-ahead) with a workspace that submits a prepared library. No model, no Docker; the real run is
scripts/run_coding_evals.py without --fake."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]
LIBRARY = REPO / "libraries" / "grating-mask-search"


def runner():
    spec = importlib.util.spec_from_file_location("run_coding_evals", REPO / "scripts" / "run_coding_evals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def methods(plugin_text):
    tree = ast.parse(plugin_text)
    listed = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "cyclic_geometric_vnd"
                  or isinstance(k, ast.Constant) and k.value == "elite_spread_relinking" for k in n.keys))
    imported = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 1)
    return [k.value for k in listed.keys], [a.name for a in imported.names]


def test_each_method_of_the_library_is_a_scenario_whose_withheld_files_exist():
    evals = runner()
    scenarios = evals.load_scenarios(REPO / "evals" / "coding" / "scenarios")
    assert {s["method_id"] for s in scenarios} == {"cyclic_geometric_vnd", "conditional_mirror_search", "elite_spread_relinking"}
    for scenario in scenarios:
        assert all((REPO / path).is_file() for path in scenario["withhold"])
        assert any(path.endswith(f"{scenario['method_id']}.py") and "/src/" in path for path in scenario["withhold"])
        assert scenario["proposal"]["mechanism"] and "{hypothesis_id}" in scenario["say"] and "{method_id}" in scenario["say"]
    assert [s["id"] for s in evals.load_scenarios(REPO / "evals" / "coding" / "scenarios", "C2")] == ["C2-conditional-mirror-search"]


@pytest.mark.parametrize("method", ["cyclic_geometric_vnd", "conditional_mirror_search", "elite_spread_relinking"])
def test_the_plugin_loses_one_method_and_keeps_the_others(method):
    original = (LIBRARY / "src" / "grating_mask_search" / "plugin.py").read_text()
    listed, imported = methods(runner().drop_method(original, method))
    others = sorted({"cyclic_geometric_vnd", "conditional_mirror_search", "elite_spread_relinking"} - {method})
    assert sorted(listed) == others and sorted(imported) == others
    with pytest.raises(ValueError):
        runner().drop_method(original, "not_a_method")


def test_the_workspace_source_has_no_trace_of_the_method_and_the_original_fails_the_checks(tmp_path):
    evals = runner()
    scenario = evals.load_scenarios(REPO / "evals" / "coding" / "scenarios", "C1")[0]
    source = evals.build_source(REPO, scenario, tmp_path / "source")
    log = subprocess.run(["git", "-C", str(source), "log", "--oneline"], capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(log) == 1   # no history to recover the method from
    for path in scenario["withhold"]:
        assert not (source / path).exists()
    found = subprocess.run(["git", "-C", str(source), "grep", "-l", "cyclic_geometric_vnd", "--", "libraries/grating-mask-search/src",
                            "libraries/grating-mask-search/tests"], capture_output=True, text=True).stdout.split()
    assert found == ["libraries/grating-mask-search/tests/test_contract.py"]   # the contract test is the scenario's input
    # The library as the workspace receives it, delivered unchanged: the method is missing, so it fails outside the box.
    package = {"files": [{"path": str(p.relative_to(source)), "content": p.read_text()}
                         for p in (source / scenario["library"]).rglob("*") if p.is_file()]}
    delivery = evals.check_delivery({"package": package, "manifest": {"dependencies": {}}}, scenario, tmp_path / "delivered")
    assert delivery["library"] == "libraries/grating-mask-search" and delivery["contract"]["names_method"]
    assert not delivery["passed"] and not delivery["conformance"]["passed"] and delivery["contract"]["failed"] >= 1


def test_a_delivered_library_is_checked_by_its_contract_test_and_conformance(tmp_path):
    evals = runner()
    scenario = evals.load_scenarios(REPO / "evals" / "coding" / "scenarios", "C3")[0]
    files = [p for p in LIBRARY.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    package = {"files": [{"path": str(p.relative_to(REPO)), "content": p.read_text()} for p in files]}
    delivery = evals.check_delivery({"package": package, "manifest": {"dependencies": {}}}, scenario, tmp_path / "whole")
    assert delivery["passed"] and delivery["contract"]["passed"] == 3 and delivery["tests"]["failed"] == 0
    assert "seeded replay" in delivery["conformance"]["checks"]
    # A contract test that leaves the method out does not count, whatever it passes.
    narrowed = [{**item, "content": item["content"].replace('"elite_spread_relinking"', '"cyclic_geometric_vnd"')}
                if item["path"].endswith("tests/test_contract.py") else item for item in package["files"]]
    delivery = evals.check_delivery({"package": {"files": narrowed}, "manifest": {}}, scenario, tmp_path / "narrowed")
    assert delivery["conformance"]["passed"] and not delivery["contract"]["names_method"] and not delivery["passed"]
    with pytest.raises(ValueError, match="leaves the repository"):
        evals.write_delivery({"files": [{"path": "../escape.py", "content": ""}]}, tmp_path / "escape")


def test_a_fake_run_opens_the_workspace_through_the_implementation_lead_and_records_a_baseline(tmp_path):
    evals = runner()
    baseline = tmp_path / "baseline.json"
    mode = os.environ.get("GRATING_DEVELOPMENT_HARNESS_MODE")
    assert evals.main(["--fake", "--scenarios", "C1", "--timeout", "120", "--out", str(tmp_path / "out"), "--record-baseline", str(baseline),
                       "--harness-mode", "headless"]) == 0
    [row] = json.loads((tmp_path / "out" / "results.json").read_text())["scenarios"]
    assert row["status"] == "pass" and row["error"] is None
    metrics = row["metrics"]
    assert metrics["harness"] == {"name": "pi", "mode": "headless"}   # the workspace ran Pi headless (H2), as asked
    assert metrics["researcher_approvals"] == 1 and metrics["submissions"] == 1 and metrics["cost_usd"] == 0
    assert 0 <= metrics["seconds_to_workspace"] <= metrics["seconds_to_submission"]
    assert metrics["lead_turns"] >= 2 and metrics["notices_from_workspace"] >= 1
    assert metrics["ticket"] == {"acceptance_tests": 1, "protected_tests": 0}   # the ticket route (H4): the request's contract test
    assert row["delivery"]["conformance"]["passed"] and row["delivery"]["contract"]["ok"]
    assert (tmp_path / "out" / "delivered" / "C1-cyclic-geometric-vnd" / "libraries" / "grating-mask-search" / "pyproject.toml").exists()
    assert "| C1-cyclic-geometric-vnd | pass |" in (tmp_path / "out" / "summary.md").read_text()
    recorded = json.loads(baseline.read_text())
    assert recorded["mode"] == "fake" and recorded["scenarios"]["C1-cyclic-geometric-vnd"]["conformance"] is True
    assert recorded["harness_mode"] == "headless" and os.environ.get("GRATING_DEVELOPMENT_HARNESS_MODE") == mode   # the lab's setting restored
    regressed = {**recorded, "scenarios": {"C1-cyclic-geometric-vnd": {**recorded["scenarios"]["C1-cyclic-geometric-vnd"], "passed": True}}}
    failing = {"mode": "real", "commit": "abc", "started_at": "now", "seconds": 1, "model": None,
               "scenarios": [{**row, "passed": False, "status": "fail", "delivery": None}]}
    assert "**regressed**" in evals.summary_markdown(failing, regressed)


def test_a_workspace_clones_the_source_it_is_given(tmp_path):
    from optimization_framework.agents.development_runtime import ROOT, DockerWorkspace
    assert DockerWorkspace(tmp_path).source == ROOT
    assert DockerWorkspace(tmp_path, source=tmp_path / "source").source == tmp_path / "source"
