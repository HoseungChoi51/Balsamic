"""Problem-owned candidates (roadmap N12): a ``structured`` representation whose form and rules the problem's library owns.

The fixture is parallel-machine scheduling: four jobs on two identical machines, a candidate is an order of jobs per
machine. No flat vector says that, so the charter declares one ``structured`` variable; the generated library's
``structure.py`` canonicalizes a schedule (the machines are identical, so their lists are sorted) and says which rules it
breaks (a job dropped or run twice). The core stores and hashes the canonical value and checks nothing else.
"""
import itertools
import sys

import pytest

from optimization_framework.contracts.problems import CandidateSchema, Structure, register_structure, structure_rules
from optimization_framework.evaluation.registry import ProblemRegistry
from optimization_framework.execution.worker import ExperimentWorker, read_journal
from optimization_framework.optimizers import conformance, registry
from optimization_framework.optimizers.functions import FunctionMethod
from optimization_framework.optimizers.plugins import OptimizerPlugins
from optimization_framework.problem_charter import charter as C
from optimization_framework.problem_charter.scaffold import scaffold
from optimization_framework.storage.artifacts import atomic_json
from test_problem_charter_library import declared, entry_points
from test_problem_charter_scaffold import pytest_in, write

NAMES = itertools.count()
REFUSAL = "the problem's library owns this representation; use a library method"


def machines(**changes):
    """Four jobs on two identical machines, to minimize the makespan; a schedule is an order of jobs per machine."""
    charter = {
        "title": "Parallel machines",
        "quantities": {"durations": {"description": "Each job's duration, in minutes", "kind": "data", "value": [3, 5, 2, 4]},
                       "n_machines": {"description": "Identical machines", "kind": "integer", "value": 2, "units": "1"},
                       "horizon": {"description": "The shift's length", "value": 9.0, "units": "min"}},
        "variables": [{"name": "schedule", "description": "Which machine runs each job, and in what order",
                       "representation": "structured", "meaning": "The jobs each machine runs, in the order it runs them",
                       "layout": "A list with one list per machine; each holds job indices 0 to 3, every job exactly once",
                       "fields": ["loads"]}],
        "constraints": [{"id": "every_job_once", "form": "evaluator", "statement": "Every job runs exactly once."},
                        {"id": "shift", "form": "design", "statement": "Every machine finishes within {horizon}.",
                         "test": "max(loads) <= horizon"}],
        "objective": {"name": "makespan", "direction": "minimize", "units": "min", "definition": "When the last machine finishes"},
        "evaluator": {"kind": "declared", "problem_id": "parallel_machines",
                      "configuration": {"durations": "durations", "n_machines": "n_machines"}},
        "instances": [{"name": "Four jobs"}],
    }
    charter.update(changes)
    return charter


STRUCTURE = '''
from .problem import Problem

EXAMPLES = {"Four jobs": [[1, 2], [0, 3]]}


def canonicalize(problem: Problem, candidate):
    if not isinstance(candidate, list) or not all(isinstance(machine, list) for machine in candidate):
        raise ValueError("a schedule is a list of job lists")
    return sorted([int(job) for job in machine] for machine in candidate)   # identical machines: their order does not matter


def is_valid(problem: Problem, candidate) -> list[str]:
    jobs = len(problem.values.durations)
    out = []
    if len(candidate) != problem.values.n_machines:
        out.append(f"{len(candidate)} machines, not {problem.values.n_machines}")
    run = sorted(job for machine in candidate for job in machine)
    if run != list(range(jobs)):
        out.append(f"the jobs run are {run}, not each of 0 to {jobs - 1} once")
    return out


def describe(problem: Problem, candidate) -> str:
    return " | ".join(" ".join(map(str, machine)) for machine in candidate)


def random_candidate(problem: Problem, rng):
    schedule = [[] for _ in range(problem.values.n_machines)]
    for job in rng.permutation(len(problem.values.durations)):
        schedule[int(rng.integers(problem.values.n_machines))].append(int(job))
    return schedule


def fields(problem: Problem, candidate) -> dict:
    return {"loads": [float(sum(problem.values.durations[job] for job in machine)) for machine in candidate]}
'''

OBJECTIVE = '''
def objective(problem, candidate) -> float:
    return float(max(sum(problem.values.durations[job] for job in machine) for machine in candidate))
'''

METHODS = '''
from .harness import deterministic

METHODS = {"longest_first": {"name": "Longest job first", "description": "Each job, longest first, to the least loaded machine.",
                             "constraints": True},
           "shuffle": {"name": "Random schedules", "description": "Valid random schedules until the cap.", "constraints": True}}


@deterministic
def longest_first(problem, evaluate, rng):
    durations = problem.values.durations
    schedule = [[] for _ in range(problem.values.n_machines)]
    for job in sorted(range(len(durations)), key=lambda job: -durations[job]):
        min(schedule, key=lambda machine: sum(durations[j] for j in machine)).append(job)
    evaluate(schedule)
    return "one schedule"


def shuffle(problem, evaluate, rng):
    while True:
        candidate = problem.random_candidate(rng)
        loads = [sum(problem.values.durations[job] for job in machine) for machine in candidate]
        if problem.is_valid(candidate) and max(loads) <= problem.values.horizon:   # the framework checks the shift
            evaluate(candidate)
'''


def files_for(charter, pkg):
    files = scaffold(charter, 1, name=pkg, balsamic=True)
    files[f"{pkg}/structure.py"] = STRUCTURE.encode()
    files[f"{pkg}/objective.py"] = OBJECTIVE.encode()
    files[f"{pkg}/methods.py"] = METHODS.encode()
    return files


@pytest.fixture
def library(tmp_path, monkeypatch):
    """The scheduling library on sys.path, as an install leaves it, with its registries."""
    pkg = f"machines_{next(NAMES)}_{tmp_path.name.replace('-', '_').lower()}"
    root = write(files_for(machines(), pkg), tmp_path / "library")
    monkeypatch.syspath_prepend(str(root))
    entries = entry_points(root)
    problems = ProblemRegistry.from_entries(entries["optimization_framework.problems"])
    want = declared(machines())
    yield pkg, problems, OptimizerPlugins(entries["optimization_framework.optimizers"]), problems.resolve(want.id, want.configuration)
    for name in [name for name in sys.modules if name.startswith("machines_")]:
        sys.modules.pop(name)


def blocking(rows):
    return {row["code"] for row in rows if row["severity"] == "blocking"}


def test_a_schedule_canonicalizes_and_one_that_drops_a_job_is_refused(library):
    pkg, problems, plugins, instance = library
    schema = instance.candidate_schema
    assert schema.representation == "structured" and schema.structure.owner == "parallel_machines"
    problems.evaluator(instance)   # the library's code is loaded where it evaluates, and its rules with it
    assert schema.canonicalize([[0, 3], [2, 1]]) == schema.canonicalize([[2, 1], [0, 3]]) == [[0, 3], [2, 1]]
    assert schema.canonicalize(((0.0, 3), [2, 1])) == [[0, 3], [2, 1]]                 # tuples and floats read as the library reads them
    with pytest.raises(ValueError, match="breaks the problem's rules: the jobs run are \\[0, 1, 3\\]"):
        schema.canonicalize([[0, 3], [1]])                                               # job 2 dropped
    with pytest.raises(ValueError, match="3 machines, not 2"):
        schema.canonicalize([[0], [1, 2], [3]])
    with pytest.raises(ValueError, match="violates constraints: shift"):
        schema.canonicalize([[0, 1, 2], [3]])                                            # 10 minutes on the first machine
    with pytest.raises(ValueError, match="JSON value"):
        schema.canonicalize([[float("nan")]])
    assert schema.describe([[0, 3], [1, 2]]) == "0 3 | 1 2"
    assert schema.broken([[0, 3], [1]]) and schema.feasible([[1, 2], [0, 3]])
    evaluation = problems.evaluator(instance).evaluate([[1, 2], [3, 0]])
    assert evaluation.objectives == {"makespan": 7.0}


def test_a_function_method_runs_to_completion_on_a_structured_problem(library, tmp_path):
    pkg, problems, plugins, instance = library
    for method in ("longest_first", "shuffle"):
        report = conformance.check_function(plugins.get(method)[0], method, instance, registry=problems)
        assert report["ended"] == ({"0": "returned", "7": "returned"} if method == "longest_first" else {"0": "cap", "7": "cap"})
    # The worker runs it to its end and records the canonical schedule.
    atomic_json(tmp_path / "run" / "spec.json", {
        "id": "experiment_structured", "campaign_id": "campaign_test", "study_id": "study_test", "seed": 0,
        "algorithm": "longest_first", "algorithm_config": {}, "problem": instance.model_dump(mode="json"), "max_steps": 10,
        "wall_seconds": 60, "schedule_steps": 10, "recovery": {"every_observations": 5, "every_seconds": 30}})
    plugin = plugins.get("longest_first")[0]
    method = plugin.create("longest_first", instance, {}, 0)
    try:
        result = ExperimentWorker(tmp_path / "run", evaluator=problems.evaluator(instance), optimizer=method).run()
    finally:
        method.close()   # a worker process ends with its method; this one is the test's
    assert result["status"] == "completed" and result["evaluations"] == 1, result
    assert result["best_candidate"] == [[1, 2], [3, 0]] and result["best_objective"] == 7.0     # 5 + 2 and 4 + 3 minutes
    assert [row["candidate"] for row in read_journal(tmp_path / "run" / "observations.jsonl")] == [[[1, 2], [3, 0]]]


def test_a_method_without_the_library_gets_its_rules_on_the_descriptor(library):
    pkg, problems, plugins, instance = library
    problems.evaluator(instance)
    seen = []

    def method(problem, evaluate, rng):
        seen.append((problem.is_valid([[0, 1], [2, 3]]), problem.is_valid([[0, 1], [2]]), problem.violations([[0, 1], [2]]),
                     problem.canonicalize([[3, 2], [1, 0]])))
        return "looked"

    runner = FunctionMethod(method, instance, {}, 0)
    with pytest.raises(Exception):
        runner.propose()
    runner.close()
    (whole, dropped, why, canonical), = seen
    assert whole and not dropped and "the jobs run are [0, 1, 2]" in why[0] and canonical == [[1, 0], [3, 2]]


def test_built_in_methods_are_refused_with_the_reason(library):
    pkg, problems, plugins, instance = library
    for method in ("random", "enumerate", "replay", "hillclimb", "coordinate"):
        assert registry.capability_reason(method, instance) == REFUSAL
    assert registry.capability_reason("shuffle", instance, plugins) is None
    with pytest.raises(ValueError, match="use a library method"):
        registry.create("random", instance, {}, 0, 10)


def test_a_structured_charter_compiles_and_its_digest_covers_meaning_and_layout():
    rows = C.findings(machines())
    assert not blocking(rows), [row for row in rows if row["severity"] == "blocking"]
    manifest = declared(machines())
    structure = manifest.candidate_schema.structure
    assert (structure.meaning, structure.fields, structure.context) == (
        "The jobs each machine runs, in the order it runs them", ["loads"], {"durations": [3, 5, 2, 4], "n_machines": 2})
    assert [(d.name, d.expression, d.constants) for d in manifest.candidate_schema.design] == [("shift", "max(loads) <= horizon", {"horizon": 9.0})]
    variable = machines()["variables"][0]
    for part in ("meaning", "layout"):
        changed = declared(machines(variables=[{**variable, part: variable[part] + " (changed)"}]))
        assert changed.version != manifest.version
    assert C.compare_provided(manifest, manifest.resolve("v1")) == []
    other = manifest.resolve("v1").candidate_schema.model_dump()
    other["structure"]["layout"] = "One list of jobs per machine"
    rows = C.compare_provided(manifest, manifest.resolve("v1").model_copy(update={"candidate_schema": CandidateSchema(**other)}))
    assert [row["what"] for row in rows] == ["structure layout"]
    # The setup compiles: a declared problem with a structured candidate is a campaign task like any other.
    assert C.compile_setups(machines())[0]["evaluator_manifest"]["candidate_schema"]["representation"] == "structured"


def test_findings_keep_a_structured_variable_alone_and_described():
    variable = machines()["variables"][0]
    other = {"name": "speed", "description": "Machine speed", "representation": "continuous", "lower": 1, "upper": 2}
    assert "variable.structured" in blocking(C.findings(machines(variables=[variable, other])))
    assert "variable.structured" in blocking(C.findings(machines(variables=[{**variable, "layout": ""}])))
    assert "variable.structured" in blocking(C.findings(machines(variables=[{**variable, "shape": [4]}])))
    linear = machines(constraints=[{"id": "cap", "form": "linear", "statement": "A cap.", "terms": [{"variable": "schedule"}],
                                    "relation": "le", "bound": 4}])
    assert "constraint.structured" in blocking(C.findings(linear))
    unknown = machines(constraints=[{"id": "shift", "form": "design", "statement": "A rule.", "test": "max(idle) <= horizon"}])
    row, = [row for row in C.findings(unknown) if row["key"] == "constraint.design_name:shift"]
    assert "fields of the structured candidate" in row["message"]
    whole = machines(constraints=[{"id": "shift", "form": "design", "statement": "A rule.", "test": "len(schedule) == 2"}])
    assert "constraint.design_name" in blocking(C.findings(whole))


def test_the_schema_checks_its_structure_and_says_where_the_rules_live():
    with pytest.raises(ValueError, match="names the structure"):
        CandidateSchema(representation="structured", dimensions=1)
    with pytest.raises(ValueError, match="takes no bounds"):
        CandidateSchema(representation="structured", dimensions=2, structure=Structure(owner="nowhere_here", meaning="m", layout="l"))
    schema = CandidateSchema(representation="structured", dimensions=1, structure=Structure(owner="nowhere_here", meaning="m", layout="l"))
    with pytest.raises(ValueError, match="rules for them are not loaded here"):
        schema.canonicalize([1])
    with pytest.raises(ValueError, match="need canonicalize"):
        register_structure("nowhere_here", object())

    class Rules:
        def canonicalize(self, candidate, context):
            return sorted(candidate)

        def is_valid(self, candidate, context):
            return [] if len(candidate) == 2 else ["two items"]

    register_structure("nowhere_here", Rules())
    assert structure_rules("nowhere_here") and schema.canonicalize([3, 1]) == [1, 3] and not schema.feasible([1])
    assert schema.model_dump()["structure"] == {"owner": "nowhere_here", "meaning": "m", "layout": "l"}


def test_the_generated_project_passes_its_own_tests(tmp_path):
    files = files_for(machines(), "machines_project")
    assert b"raise NotImplementedError" in scaffold(machines(), 1)["parallel_machines/structure.py"]
    result = pytest_in(write(files, tmp_path / "project"), "-vv", "-rs")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_a_valid_example_passes_the_structure[Four jobs] PASSED" in result.stdout
    assert "test_contract.py::test_each_method_meets_the_contract[longest_first] PASSED" in result.stdout
