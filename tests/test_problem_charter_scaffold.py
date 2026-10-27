"""A standalone Python project generated from a charter revision (roadmap F1).

The generated project imports nothing from Balsamic, so it is written to a temporary directory and run there with this
environment's Python, as a researcher or a coding agent would run it.
"""
import ast
import json
import subprocess
import sys
import textwrap
import time

import pytest

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.problem_charter.scaffold import package_name, scaffold
from test_problem_charter import reactor

FILES = {"pyproject.toml", "charter.json", "README.md", "tests/test_problem.py", "tests/test_methods.py"}
MODULES = {"__init__", "data", "problem", "harness", "compare", "objective", "methods"}


def ovens(**changes):
    """Tray temperatures chosen from a list: a discrete, minimized problem with two instances and a checkable reference."""
    charter = {
        "title": "Oven tray temperatures",
        "summary": "Set each of {trays} trays to a listed temperature, as close to {target_c} as the heater allows.",
        "quantities": {
            "trays": {"description": "Trays in the oven", "kind": "integer", "value": 4, "units": "1"},
            "target_c": {"description": "Target temperature", "value": 180.0, "units": "C"},
            "heater_limit_c": {"description": "Sum of the settings the heater can hold", "value": 760.0, "units": "C"},
        },
        "variables": [{"name": "setting", "description": "Each tray's temperature", "representation": "discrete",
                       "shape": ["trays"], "values": [150.0, 175.0, 200.0], "units": "C", "layout": "tray by tray"}],
        "constraints": [{"id": "heater", "form": "linear", "statement": "The settings add up to at most {heater_limit_c}.",
                         "terms": [{"variable": "setting"}], "relation": "le", "bound": "heater_limit_c"}],
        "objective": {"name": "squared_gap", "direction": "minimize", "units": "C^2",
                      "definition": "The sum over trays of (setting - {target_c}) squared"},
        "evaluator": {"kind": "declared", "problem_id": "oven_trays", "configuration": {"target_c": "target_c"}},
        "instances": [{"name": "Four trays"},
                      {"name": "Six trays", "split": "selection", "values": {"trays": 6, "heater_limit_c": 1100.0}}],
        "references": [{"statement": "Every tray at 175 C misses by 100 C^2", "value": 100.0, "units": "C^2",
                        "holds_at": {"trays": 4, "setting": [175.0, 175.0, 175.0, 175.0]}},
                       {"statement": "The oven's manual reports a gap of 400", "value": 400.0, "units": "C^2"}],
    }
    charter.update(changes)
    return charter


OBJECTIVE = '''
from .problem import Problem


def objective(problem: Problem, candidate) -> float:
    return float(((problem.unpack(candidate)["setting"] - problem.values.target_c) ** 2).sum())
'''

METHODS = '''
import numpy as np

from .harness import deterministic
from .objective import objective

METHODS = {
    "random_search": {"name": "Random search", "description": "Valid settings drawn at random until the cap."},
    "all_middle": {"name": "All at 175", "description": "Every tray at 175 C, returned."},
    "all_cold": {"name": "All at 150", "description": "Every tray at 150 C."},
}


def random_search(problem, evaluate, rng):
    while True:
        candidate = problem.random_candidate(rng)
        if problem.is_valid(candidate):
            evaluate(candidate)


@deterministic
def all_middle(problem, evaluate, rng):
    candidate = np.full(problem.dimensions, 175.0)
    evaluate(candidate)
    return candidate


@deterministic
def all_cold(problem, evaluate, rng):
    evaluate(np.full(problem.dimensions, 150.0))


def spin(problem, evaluate, rng):
    """White-box: computes the objective itself, forever, after one evaluation."""
    candidate = np.full(problem.dimensions, 150.0)
    evaluate(candidate)
    while True:
        objective(problem, candidate)
'''

HARNESS_CHECKS = '''
import numpy as np
import pytest

from oven_trays.harness import InvalidCandidate, run
from oven_trays.methods import all_middle
from oven_trays.problem import PROBLEMS, problem


def test_a_run_needs_a_cap():
    with pytest.raises(ValueError, match="max_seconds, max_evaluations"):
        run(all_middle, problem(), seed=0)


def test_evaluate_refuses_what_the_charter_does_not_allow():
    def too_hot(problem, evaluate, rng):
        evaluate(np.full(problem.dimensions, 200.0))      # 800 C over a 760 C heater
    with pytest.raises(InvalidCandidate, match="heater"):
        run(too_hot, problem("Four trays"), seed=0, max_evaluations=3)
    with pytest.raises(InvalidCandidate, match="heater"):
        run(too_hot, problem("Six trays"), seed=0, max_evaluations=3)    # 1200 C over 1100 C


def test_instances_have_their_own_values():
    assert (PROBLEMS["Four trays"].dimensions, PROBLEMS["Six trays"].dimensions) == (4, 6)
    assert PROBLEMS["Six trays"].values["heater_limit_c"] == 1100.0 and PROBLEMS["Six trays"].split == "selection"
    assert PROBLEMS["Four trays"].unpack([150, 175, 200, 150])["setting"].shape == (4,)
'''


def write(files: dict, root):
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def pytest_in(root, *args):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *args],
                          cwd=root, capture_output=True, text=True, timeout=300)


def test_a_continuous_charter_gives_the_project_its_data_and_two_files_to_fill():
    files = scaffold(reactor(), 3, charter_id="problem_charter_reactor")
    pkg = "flow_reactor_yield"
    assert set(files) == FILES | {f"{pkg}/{module}.py" for module in MODULES}
    text = {path: content.decode() for path, content in files.items()}
    assert 'name = "flow-reactor-yield"' in text["pyproject.toml"] and 'version = "0.1.0"' in text["pyproject.toml"]
    assert 'dependencies = ["numpy"]' in text["pyproject.toml"] and 'test = ["pytest"]' in text["pyproject.toml"]
    stored = json.loads(text["charter.json"])
    charter = ProblemCharter.model_validate(reactor()).model_dump(mode="json")
    assert stored == {"charter_id": "problem_charter_reactor", "revision": 3, "content_hash": content_hash(charter), "charter": charter}
    data = {}
    exec(compile(text[f"{pkg}/data.py"], "data.py", "exec"), data)
    assert data["OBJECTIVE"] == {"name": "isolated_yield", "direction": "maximize", "units": "fraction"}
    assert data["DETERMINISTIC"] is False and data["REPRESENTATION"] == "continuous"
    base = data["INSTANCES"]["Base conditions"]
    assert base["values"]["residence_time_s"] == 300.0            # derived quantities are resolved
    assert base["candidate"]["dimensions"] == 3
    assert (base["candidate"]["variables"][0]["lower"], base["candidate"]["variables"][0]["upper"]) == (0.0, 1.0)
    assert [c["id"] for c in base["candidate"]["constraints"]] == ["loading_budget"]
    objective = text[f"{pkg}/objective.py"]
    assert "raise NotImplementedError" in objective and "Isolated yield, mean of 3 repeats" in objective
    assert "Run below 150 C." in objective and "Run the reaction and measure yield by HPLC." in objective
    assert "METHODS = {}" in text[f"{pkg}/methods.py"]
    assert "reactor_volume_ml: float | None" in text[f"{pkg}/problem.py"] and "repeats: int | None" in text[f"{pkg}/problem.py"]
    assert f"python -m {pkg}.compare" in text["README.md"] and "Maximize the yield of a flow reaction at 5 bar." in text["README.md"]


def test_a_discrete_charter_resolves_each_instance_and_keeps_its_references():
    files = scaffold(ovens(), 2)
    pkg = "oven_trays"
    assert set(files) == FILES | {f"{pkg}/{module}.py" for module in MODULES}
    data = {}
    exec(compile(files[f"{pkg}/data.py"].decode(), "data.py", "exec"), data)
    four, six = data["INSTANCES"]["Four trays"], data["INSTANCES"]["Six trays"]
    assert (four["candidate"]["dimensions"], six["candidate"]["dimensions"]) == (4, 6)
    assert four["candidate"]["variables"][0]["values"] == [150.0, 175.0, 200.0]
    assert (four["candidate"]["constraints"][0]["bound"], six["candidate"]["constraints"][0]["bound"]) == (760.0, 1100.0)
    assert six["candidate"]["constraints"][0]["statement"] == "The settings add up to at most 1100 C."
    assert six["split"] == "selection" and data["CHARTER_ID"] is None and data["REVISION"] == 2
    assert [r["value"] for r in data["REFERENCES"]] == [100.0, 400.0]


def test_the_same_revision_always_gives_the_same_bytes():
    assert scaffold(ovens(), 2) == scaffold(ovens(), 2)
    assert scaffold(reactor(), 3, charter_id="c") == scaffold(ProblemCharter.model_validate(reactor()), 3, charter_id="c")
    later = scaffold(ovens(), 3)
    assert later["oven_trays/problem.py"] == scaffold(ovens(), 2)["oven_trays/problem.py"]
    assert later["charter.json"] != scaffold(ovens(), 2)["charter.json"]


def test_names_and_charters_it_cannot_generate():
    assert package_name(ProblemCharter.model_validate(ovens()), "My Oven 2!") == "my_oven_2"
    assert package_name(ProblemCharter.model_validate(ovens(evaluator=None))) == "oven_tray_temperatures"
    assert set(scaffold(ovens(), 1, name="kiln")) >= {"kiln/data.py", "kiln/methods.py"}
    with pytest.raises(ValueError, match="no objective"):
        scaffold(ovens(objective=None), 1)
    with pytest.raises(ValueError, match="no decision variables"):
        scaffold(ovens(variables=[], constraints=[]), 1)
    with pytest.raises(ValueError, match="Six trays.*trays"):
        scaffold(ovens(instances=[{"name": "Six trays", "values": {"trays": 0}}]), 1)


def test_no_generated_file_imports_balsamic():
    for files in (scaffold(reactor(), 1), scaffold(ovens(), 1)):
        for path, content in files.items():
            if not path.endswith(".py"):
                continue
            imported = set()
            for node in ast.walk(ast.parse(content.decode(), path)):
                if isinstance(node, ast.Import):
                    imported |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    imported.add(node.module.split(".")[0])
            assert not imported & {"optimization_framework", "balsamic", "dqn_meent"}, path


def test_the_unfilled_project_fails_only_on_the_objective(tmp_path):
    result = pytest_in(write(scaffold(ovens(), 1), tmp_path))
    assert "NotImplementedError: Write the objective in objective.py: squared_gap" in result.stdout
    assert result.returncode == 1 and " passed" in result.stdout, result.stdout


def test_the_project_filled_in_passes_its_own_tests(tmp_path):
    files = scaffold(ovens(), 1)
    files["oven_trays/objective.py"] = OBJECTIVE.encode()
    files["oven_trays/methods.py"] = METHODS.encode()
    files["tests/test_harness_checks.py"] = HARNESS_CHECKS.encode()
    root = write(files, tmp_path)
    result = pytest_in(root, "-vv", "-rs")
    assert result.returncode == 0, result.stdout + result.stderr
    # The reference with a candidate is checked; the one without is skipped, naming its number.
    assert "test_reference_results[reference_1] PASSED" in result.stdout
    assert "The charter's reference 400.0 C^2 (The oven's manual reports a gap of 400) names no candidate" in result.stdout


def test_compare_ranks_by_the_direction_and_stops_a_method_on_its_seconds(tmp_path):
    files = scaffold(ovens(), 1)
    files["oven_trays/objective.py"] = OBJECTIVE.encode()
    files["oven_trays/methods.py"] = (METHODS + 'METHODS["spin"] = {"name": "Spin", "description": "Computes the objective forever."}\n').encode()
    root = write(files, tmp_path)
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "oven_trays.compare", "--seconds", "0.5", "--method", "all_cold",
                             "--method", "spin", "--method", "all_middle", "--instance", "Four trays"],
                            cwd=root, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 30
    lines = result.stdout.splitlines()
    assert lines[0] == "Four trays (development): minimize squared_gap (C^2)"
    runs = [line.split() for line in lines[2:]]
    assert [row[1] for row in runs][0] == "all_middle" and runs[0][:4] == ["1", "all_middle", "—", "100"]
    assert {row[1]: row[-1] for row in runs} == {"all_middle": "finished", "all_cold": "finished", "spin": "seconds"}
    # Deterministic methods run once whatever --seeds says; spin runs once per seed (2 by default).
    assert [row[1] for row in runs].count("spin") == 2 and len(runs) == 4


def test_compare_runs_each_stochastic_method_once_per_seed_and_maximizes_when_asked(tmp_path):
    files = scaffold(ovens(objective={"name": "squared_gap", "direction": "maximize", "units": "C^2",
                                      "definition": "The same sum, maximized"}), 1)
    files["oven_trays/objective.py"] = OBJECTIVE.encode()
    files["oven_trays/methods.py"] = METHODS.encode()
    root = write(files, tmp_path)
    script = textwrap.dedent("""
        from oven_trays.compare import compare, ranked
        from oven_trays.problem import problem
        rows = compare(None, [problem()], seeds=3, evaluations=20)
        print([(row["method"], row["seed"]) for row in rows])
        print([row["method"] for row in ranked(rows, problem())][-1])
    """)
    result = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    pairs, last = result.stdout.splitlines()
    assert pairs == str([("random_search", 0), ("random_search", 1), ("random_search", 2), ("all_middle", 0), ("all_cold", 0)])
    assert last == "all_middle"                             # the smallest gap is the worst when maximizing
