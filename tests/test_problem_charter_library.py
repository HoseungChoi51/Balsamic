"""The generated project as a Balsamic library (roadmap F3): its adapter is the problem the charter declares, its
functions are Balsamic methods, and the project still runs without Balsamic."""
import ast
import itertools
import subprocess
import sys
import textwrap
import tomllib

import pytest

from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.evaluation.registry import ProblemRegistry
from optimization_framework.execution.provenance import _imports
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.plugins import OptimizerPlugins
from optimization_framework.problem_charter.charter import compare_provided, findings, manifest, resolve
from optimization_framework.problem_charter.scaffold import scaffold
from test_problem_charter import reactor
from test_problem_charter_scaffold import METHODS, OBJECTIVE, ovens, pytest_in, write

NAMES = itertools.count()
LIBRARY_CODE = {"objective", "problem", "methods", "harness"}


def bakes(**changes):
    """The order of four bakes, to minimize total lateness: a permutation charter."""
    charter = {
        "title": "Baking order",
        "quantities": {"n_bakes": {"description": "Bakes", "kind": "integer", "value": 4, "units": "1"},
                       "minutes": {"description": "Each bake's duration", "kind": "data", "value": [30, 20, 50, 10]},
                       "due": {"description": "Each bake's due time", "kind": "data", "value": [40, 30, 110, 20]}},
        "variables": [{"name": "order", "description": "The order of the bakes", "representation": "permutation",
                       "shape": ["n_bakes"]}],
        "objective": {"name": "lateness", "direction": "minimize", "units": "min",
                      "definition": "The total lateness of the bakes, in minutes"},
        "evaluator": {"kind": "declared", "problem_id": "baking_order",
                      "configuration": {"minutes": "minutes", "due": "due"}},
        "instances": [{"name": "Four bakes"}],
    }
    charter.update(changes)
    return charter


BAKES_OBJECTIVE = '''
def objective(problem, candidate) -> float:
    clock, late = 0, 0
    for bake in problem.unpack(candidate)["order"].astype(int):
        clock += problem.values.minutes[bake]
        late += max(0, clock - problem.values.due[bake])
    return float(late)
'''

BAKES_METHODS = '''
from .harness import deterministic

METHODS = {"shuffle": {"name": "Shuffle", "description": "Random orders until the cap."},
           "earliest_due": {"name": "Earliest due date", "description": "Sorted by due time, evaluated once."}}


def shuffle(problem, evaluate, rng):
    while True:
        evaluate(problem.random_candidate(rng))


@deterministic
def earliest_due(problem, evaluate, rng):
    evaluate(sorted(range(problem.dimensions), key=lambda bake: problem.values.due[bake]))
    return "one order"
'''


def library(charter, tmp_path, monkeypatch, objective=OBJECTIVE, methods=METHODS):
    """A filled library on sys.path, as an install leaves it, under a package name of its own."""
    pkg = f"glued_{next(NAMES)}_{tmp_path.name.replace('-', '_').lower()}"
    files = scaffold(charter, 1, name=pkg, balsamic=True)
    files[f"{pkg}/objective.py"] = objective.encode()
    files[f"{pkg}/methods.py"] = methods.encode()
    root = write(files, tmp_path / "library")
    monkeypatch.syspath_prepend(str(root))
    return pkg, root


@pytest.fixture(autouse=True)
def forget_libraries():
    yield
    for name in [name for name in sys.modules if name.startswith("glued_")]:
        sys.modules.pop(name)


def entry_points(root):
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["entry-points"]


def declared(charter, inputs=None):
    return manifest(ProblemCharter.model_validate(charter), resolve(charter, inputs)["values"])


def test_balsamic_adds_the_adapter_both_entry_points_and_a_contract_test():
    plain, glued = scaffold(ovens(), 2), scaffold(ovens(), 2, balsamic=True)
    assert set(glued) - set(plain) == {"oven_trays/adapter.py", "tests/test_contract.py"}
    assert "entry-points" not in plain["pyproject.toml"].decode() and "\nCHARTER = " not in plain["oven_trays/data.py"].decode()
    project = tomllib.loads(glued["pyproject.toml"].decode())["project"]
    assert project["entry-points"] == {"optimization_framework.problems": {"oven_trays": "oven_trays.adapter:problem_adapter"},
                                       "optimization_framework.optimizers": {"oven_trays": "oven_trays.adapter:method_plugin"}}
    assert 'MODULE = "oven_trays.methods"' in glued["oven_trays/adapter.py"].decode()
    data = {}
    exec(compile(glued["oven_trays/data.py"].decode(), "data.py", "exec"), data)
    assert data["CHARTER"] == ProblemCharter.model_validate(ovens()).model_dump(mode="json")
    assert scaffold(ovens(), 2, balsamic=True) == glued


def test_the_adapter_imports_balsamic_only_inside_its_functions():
    tree = ast.parse(scaffold(ovens(), 1, balsamic=True)["oven_trays/adapter.py"].decode())
    top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert [(node.module, node.level) for node in top] == [("__future__", 0), (None, 1)]   # from . import data
    # A frozen capture follows the imports inside the functions, so a run's digest covers the objective and the problem.
    imported = _imports("oven_trays.adapter", "oven_trays/adapter.py", ast.unparse(tree))
    assert {"oven_trays.objective", "oven_trays.problem", "oven_trays.data"} <= imported


def test_an_installed_evaluator_gives_only_the_methods_and_a_charter_without_one_is_refused():
    charter = ovens(evaluator={"kind": "installed", "problem_id": "bounded_continuous", "configuration": {}})
    project = tomllib.loads(scaffold(charter, 1, name="oven_trays", balsamic=True)["pyproject.toml"].decode())["project"]
    assert project["entry-points"] == {"optimization_framework.optimizers": {"oven_trays": "oven_trays.adapter:method_plugin"}}
    with pytest.raises(ValueError, match="names no evaluator"):
        scaffold(ovens(evaluator=None), 1, balsamic=True)
    assert "oven_tray_temperatures/data.py" in scaffold(ovens(evaluator=None), 1)


def test_the_library_is_the_declared_problem_and_its_functions_pass_conformance(tmp_path, monkeypatch):
    pkg, root = library(ovens(), tmp_path, monkeypatch)
    entries = entry_points(root)
    registry = ProblemRegistry.from_entries(entries["optimization_framework.problems"])
    adapter = registry.get("oven_trays")
    want = declared(ovens())
    instance = registry.resolve("oven_trays", want.configuration, want.fidelity)
    # Describing and resolving read only the data: none of the library's own code ran (INV-F3-1).
    assert not {f"{pkg}.{module}" for module in LIBRARY_CODE} & set(sys.modules)
    assert compare_provided(want, instance) == []
    definition = adapter.describe()
    assert (definition.id, definition.version) == ("oven_trays", want.version)
    assert instance.candidate_schema.dimensions == 4 and instance.definition_version == want.version
    assert ProblemRegistry().extended(adapter).get("oven_trays") is adapter

    plugins = OptimizerPlugins(entries["optimization_framework.optimizers"])
    listed = {method["id"]: method for method in plugins.methods()}
    assert set(listed) == {"random_search", "all_middle", "all_cold"} and listed["all_cold"]["representations"] == ["discrete"]
    assert f"{pkg}.methods" not in sys.modules
    plugin = plugins.get("random_search")[0]
    for method in listed:
        conformance.check_function(plugin, method, instance, registry=registry)
    # The method is given the library's own Problem, and the evaluator computes the library's objective.
    assert plugin.problem(instance) is sys.modules[f"{pkg}.problem"].PROBLEMS["Four trays"]
    evaluation = registry.evaluator(instance).evaluate([175.0, 175.0, 175.0, 175.0])
    assert evaluation.objectives == {"squared_gap": 100.0} and evaluation.constraints == {"heater": True}
    with pytest.raises(ValueError, match="heater"):
        registry.evaluator(instance).evaluate([200.0, 200.0, 200.0, 200.0])


def test_a_configuration_that_is_no_instance_gets_a_problem_of_its_own(tmp_path, monkeypatch):
    pkg, _ = library(ovens(), tmp_path, monkeypatch)
    adapter = sys.modules.get(f"{pkg}.adapter") or __import__(f"{pkg}.adapter", fromlist=["x"])
    problem = adapter.problem_adapter()
    instance = problem.resolve({"target_c": 170.0})
    own = problem.problem(instance)
    assert (own.instance, own.values.target_c, own.dimensions) == ("configuration", 170.0, 4)
    assert problem.evaluator(instance).evaluate([175.0] * 4).objectives == {"squared_gap": 100.0}
    with pytest.raises(ValueError, match="no field trays"):
        problem.resolve({"trays": 6})


def test_a_field_on_a_derived_quantity_must_agree_with_the_charter(tmp_path, monkeypatch):
    objective = "def objective(problem, candidate):\n    return float(sum(candidate))\n"
    methods = 'METHODS = {"one": {"name": "One", "description": "One candidate."}}\n\n\n' \
              "def one(problem, evaluate, rng):\n    evaluate([0.5, 0.5, 0.5])\n"
    pkg, _ = library(reactor(), tmp_path, monkeypatch, objective=objective, methods=methods)
    problem = __import__(f"{pkg}.adapter", fromlist=["x"]).problem_adapter()
    want = declared(reactor())
    assert compare_provided(want, problem.resolve(want.configuration, want.fidelity)) == []   # metrics, fidelity included
    with pytest.raises(ValueError, match="residence_time_s = 99.0, but the charter computes residence_time_s = 300.0"):
        problem.resolve({**want.configuration, "residence_time_s": 99.0})


def test_a_charter_installed_from_the_library_has_no_mismatch(tmp_path, monkeypatch):
    pkg, root = library(ovens(), tmp_path, monkeypatch)
    registry = ProblemRegistry.from_entries(entry_points(root)["optimization_framework.problems"])
    rows = {row["code"]: row for row in findings(ovens(), registry)}
    assert "evaluator.provided" in rows and "evaluator.provided_mismatch" not in rows


def test_edited_data_is_refused(tmp_path, monkeypatch):
    pkg, root = library(ovens(), tmp_path, monkeypatch)
    data = root / pkg / "data.py"
    data.write_text(data.read_text().replace("'value': 760.0", "'value': 900.0"))
    with pytest.raises(ValueError, match="no longer holds the charter revision"):
        __import__(f"{pkg}.adapter", fromlist=["x"]).problem_adapter()


def test_a_permutation_charter_is_generated_and_its_library_passes_conformance(tmp_path, monkeypatch):
    pkg, root = library(bakes(), tmp_path, monkeypatch, objective=BAKES_OBJECTIVE, methods=BAKES_METHODS)
    want = declared(bakes())
    entries = entry_points(root)
    registry = ProblemRegistry.from_entries(entries["optimization_framework.problems"])
    instance = registry.resolve("baking_order", want.configuration)
    assert instance.candidate_schema.representation == "permutation" and compare_provided(want, instance) == []
    plugins = OptimizerPlugins(entries["optimization_framework.optimizers"])
    for method in ("shuffle", "earliest_due"):
        conformance.check_function(plugins.get(method)[0], method, instance, registry=registry)
    # Sorted by due time: 3, 1, 0, 2 finish at 10, 30, 60, 110; only bake 0 is late, by 20 minutes.
    assert registry.evaluator(instance).evaluate([3, 1, 0, 2]).objectives == {"lateness": 20.0}


def test_the_generated_projects_pass_their_own_tests_with_balsamic(tmp_path, monkeypatch):
    for charter, objective, methods, folder in ((ovens(), OBJECTIVE, METHODS, "ovens"),
                                                (bakes(), BAKES_OBJECTIVE, BAKES_METHODS, "bakes")):
        files = scaffold(charter, 1, balsamic=True)
        pkg = next(path.split("/")[0] for path in files if path.endswith("/adapter.py"))
        files[f"{pkg}/objective.py"], files[f"{pkg}/methods.py"] = objective.encode(), methods.encode()
        result = pytest_in(write(files, tmp_path / folder), "-vv", "-rs")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_contract.py::test_the_library_is_the_problem_the_charter_declares PASSED" in result.stdout
        contract = [line for line in result.stdout.splitlines() if line.startswith("tests/test_contract.py::")]
        assert len(contract) >= 4 and all(line.split()[1] == "PASSED" for line in contract), contract


WITHOUT_BALSAMIC = """
import sys
sys.modules["optimization_framework"] = None   # as if Balsamic were not installed
import {pkg}, {pkg}.adapter
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "-p", "no:randomly", "-rs"]))
"""


def test_the_library_runs_without_balsamic(tmp_path):
    files = scaffold(ovens(), 1, balsamic=True)
    files["oven_trays/objective.py"], files["oven_trays/methods.py"] = OBJECTIVE.encode(), METHODS.encode()
    root = write(files, tmp_path)
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(WITHOUT_BALSAMIC.format(pkg="oven_trays"))],
                            cwd=root, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "19 passed, 2 skipped" in result.stdout and "could not import 'optimization_framework'" in result.stdout


def test_methods_must_be_listed_as_balsamic_lists_them(tmp_path):
    files = scaffold(ovens(), 1, balsamic=True)
    files["oven_trays/objective.py"] = OBJECTIVE.encode()
    files["oven_trays/methods.py"] = b"def idea(problem, evaluate, rng):\n    pass\n\n\nMETHODS = {'idea': idea}\n"
    result = pytest_in(write(files, tmp_path), "tests/test_methods.py")
    assert "METHODS['idea'] must be a dict with a name and a description" in result.stdout
