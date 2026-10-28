"""Size ladders (roadmap N14): instance size is an axis of the comparison.

Exact methods win on small instances and run out of budget on large ones, and where that happens is often the finding. A
charter instance may name its size; the comparison then reports, per pair of methods, the largest size each finished at
and the size where one overtakes the other, from the observed runs only. "Extend" on a method that finished on its own
proposes the next size, not more budget. A problem with no ladder compares per task, as before.
"""
import pytest

from optimization_framework.analysis.general import report
from optimization_framework.contracts.packs import PackRacing
from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.contracts.problem_imports import ProblemSetup
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import TaskInput, TrialInput
from optimization_framework.evaluation import sizes
from optimization_framework.execution.worker import run
from optimization_framework.optimizers.functions import FunctionMethod
from optimization_framework.problem_charter import charter as C

from balsamic.evolution.ledger import rows
from support import command

DIMENSIONS = (2, 3, 4)


def sized(dimensions):
    return {"name": f"{dimensions} dimensions", "problem_id": "bounded_continuous", "configuration": {"dimensions": dimensions},
            "size": {"name": "dimensions", "value": dimensions}}


@pytest.fixture
def ladder(client, workspace):
    receipt = command(client, "campaign.create", "ladder", {"name": "Ladder", "objective": "Where does the exact method stop?",
        "tasks": [sized(d) for d in DIMENSIONS], "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)
    campaign = receipt["outcome"]["campaign"]
    tasks = {task["size"]["value"]: task for task in workspace.current_tasks(campaign["id"])}
    made = {}
    for title, family in (("Exact", "exact"), ("Heuristic", "local_search")):
        made[title] = command(client, "hypothesis.create", campaign["id"], {"title": title, "mechanism": "m", "rationale": "r",
            "family": family, "algorithm": "random"}, workspace.store.get(campaign["id"], "campaign")["version"])["outcome"]["hypothesis"]["id"]
    return campaign["id"], tasks, made


def exact(problem, evaluate, rng):
    """Proves the optimum (the centre) at once on up to three dimensions; on more it never finishes within its budget."""
    if problem["candidate_schema"]["dimensions"] <= 3:
        evaluate([0.0] * problem["candidate_schema"]["dimensions"])
        return
    while True:
        evaluate([float(x) for x in rng.uniform(-5, 5, size=problem["candidate_schema"]["dimensions"])])


def heuristic(problem, evaluate, rng):
    """Samples near the centre until its budget ends: close to the optimum at every size, never on it."""
    while True:
        evaluate([float(x) for x in 0.05 + rng.normal(0, 0.05, size=problem["candidate_schema"]["dimensions"])])


def execute(workspace, campaign_id, task, fn, algorithm, hypothesis_id, seed=0):
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm=algorithm, max_steps=40,
                                              wall_seconds=30, seed=seed, hypothesis_id=hypothesis_id))
    result = run(workspace.job_dir(trial["id"]), optimizer=FunctionMethod(fn, ProblemInstance(**trial["problem"]), {}, trial["seed"]))
    trial.update(result=result, progress=result, attempt=1, status="completed")
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return trial, result


def test_the_comparison_names_the_crossover_and_the_exact_methods_largest_finished_size(workspace, ladder):
    campaign_id, tasks, made = ladder
    ended = {}
    for size, task in tasks.items():
        ended["exact", size] = execute(workspace, campaign_id, task, exact, "random", made["Exact"])[1]
        ended["heuristic", size] = execute(workspace, campaign_id, task, heuristic, "coordinate", made["Heuristic"])[1]
    assert [ended["exact", size]["method_finished"] for size in DIMENSIONS] == [True, True, False]
    assert not any(ended["heuristic", size]["method_finished"] for size in DIMENSIONS)
    comparison = report(workspace, campaign_id)
    assert len(comparison["groups"]) == 3 and {group["size"]["value"] for group in comparison["groups"]} == {2.0, 3.0, 4.0}
    [found] = comparison["size_ladders"]
    assert found["size"] == "dimensions" and found["sizes"] == [2.0, 3.0, 4.0] and found["direction"] == "minimize"
    methods = {row["algorithm"]: row for row in found["methods"]}
    assert methods["random"]["kind"] == "finishes" and methods["random"]["largest_finished_size"] == 3.0
    assert [row["finished"] for row in methods["random"]["sizes"]] == [True, True, False]
    # The heuristic never finishes on its own: it finished wherever its runs reached their budget.
    assert methods["coordinate"]["kind"] == "anytime" and methods["coordinate"]["largest_finished_size"] == 4.0
    [pair] = found["pairs"]
    leader = dict(zip(pair["algorithms"], pair["methods"]))
    assert [row["leader"] for row in pair["leaders"]] == [leader["random"], leader["random"], leader["coordinate"]]
    assert pair["crossover"] == {"size": 4.0, "from": leader["random"], "to": leader["coordinate"]}
    assert pair["largest_finished_size"] == {leader["random"]: 3.0, leader["coordinate"]: 4.0}


def test_extend_on_a_finished_deterministic_run_proposes_the_next_size(client, workspace, ladder):
    campaign_id, tasks, made = ladder
    execute(workspace, campaign_id, tasks[2], exact, "random", made["Exact"])
    execute(workspace, campaign_id, tasks[2], heuristic, "coordinate", made["Heuristic"])
    ledger = {row["id"]: row for row in rows(workspace, campaign_id)[0]}
    proposal = ledger[made["Exact"]]["next_size"]
    assert proposal == {"task_id": tasks[3]["id"], "task_name": "3 dimensions", "name": "dimensions", "value": 3.0, "after": 2.0}
    assert ledger[made["Heuristic"]]["next_size"] is None, "a method that runs to its budget is extended with more budget"
    # The page sends the proposal's task: a new run there, not a continuation of the finished one.
    outcome = command(client, "intervention.batch", campaign_id, {"items": [{"operation": "hypothesis.allocate", "payload": {
        "hypothesis_id": made["Exact"], "worker_seconds": 30, "rationale": "the next size", "task_id": proposal["task_id"]}}],
        "rationale": "the next size"}, workspace.store.get(campaign_id, "campaign")["version"])["outcome"]
    created = workspace.store.get(outcome["items"][0]["outcome"]["trial_id"], "trial")
    assert outcome["items"][0]["outcome"]["how"] == "trial.create" and created["task_id"] == tasks[3]["id"]
    # Once it finished on the next size too, the proposal moves on; past the largest there is none.
    execute(workspace, campaign_id, tasks[3], exact, "random", made["Exact"], seed=1)
    assert rows(workspace, campaign_id)[0][0]["next_size"]["value"] == 4.0
    refused = command(client, "hypothesis.allocate", campaign_id, {"hypothesis_id": made["Exact"], "worker_seconds": 30,
        "rationale": "elsewhere", "task_id": "task_unknown"}, workspace.store.get(campaign_id, "campaign")["version"], expect=None)
    assert "Not a current development or selection task" in str(refused)


def test_a_problem_with_no_ladder_compares_per_task_as_before(client, workspace, campaign):
    task = workspace.current_tasks(campaign["id"])[0]
    assert "size" not in workspace.store.get(task["id"], "task") and sizes.of_task(task) is None
    hypothesis = command(client, "hypothesis.create", campaign["id"], {"title": "Exact", "mechanism": "m", "rationale": "r", "algorithm": "random"},
                         workspace.store.get(campaign["id"], "campaign")["version"])["outcome"]["hypothesis"]["id"]
    execute(workspace, campaign["id"], task, exact, "random", hypothesis)
    execute(workspace, campaign["id"], task, heuristic, "coordinate", hypothesis, seed=1)
    comparison = report(workspace, campaign["id"])
    assert "size_ladders" not in comparison and all("size" not in group for group in comparison["groups"])
    assert [len(group["method_summaries"]) for group in comparison["groups"]] == [2]
    assert rows(workspace, campaign["id"])[0][0]["next_size"] is None


def test_records_without_a_size_keep_their_bytes():
    setup = ProblemSetup(name="Continuous", problem_id="bounded_continuous", configuration={"dimensions": 2})
    assert "size" not in setup.model_dump(mode="json")
    assert "size" not in TaskInput(name="Continuous", problem_id="bounded_continuous").model_dump(mode="json")
    from test_problem_charter import reactor
    assert "size" not in ProblemCharter.model_validate(reactor()).instances[0].model_dump(mode="json")


def test_a_charter_names_its_instances_size_and_the_tasks_carry_it():
    from test_problem_charter import reactor
    quantities = {**reactor()["quantities"], "batches": {"description": "Batches per day", "kind": "integer", "value": 4,
                                                        "units": "1", "citation": 1}}
    instances = [{"name": f"{n} batches", "values": {"batches": n}, "size": "batches"} for n in (4, 8)]
    charter = reactor(quantities=quantities, instances=instances)
    assert not {row["code"] for row in C.findings(charter)} & {"instance.size_mixed", "instance.size_unknown"}
    setups = [ProblemSetup.model_validate(setup) for setup in C.compile_setups(charter)]
    assert [setup.size.model_dump() for setup in setups] == [{"name": "batches", "value": 4.0}, {"name": "batches", "value": 8.0}]
    assert setups[1].task_input().size.value == 8.0
    mixed = reactor(quantities=quantities, instances=[instances[0], {"name": "Other", "values": {"batches": 8}}])
    assert "instance.size_mixed" in {row["code"] for row in C.findings(mixed)}
    text = reactor(quantities=quantities, instances=[{**row, "size": "temperature_c"} for row in instances])
    assert "instance.size_unknown" not in {row["code"] for row in C.findings(text)}
    unknown = reactor(quantities=quantities, instances=[{**row, "size": "missing"} for row in instances])
    assert "instance.size_unknown" in {row["code"] for row in C.findings(unknown)}


def test_a_pack_may_declare_a_size_ladder_beside_its_fidelity_ladder():
    racing = PackRacing(sizes=[{"jobs": 8}, {"jobs": 12}, {"jobs": 20}])
    assert racing.size_key() == "jobs" and racing.applies_to({"anything": 1})
    for bad in ([{"jobs": 8}, {"machines": 12}], [{"jobs": 12}, {"jobs": 8}], [{"jobs": 8, "machines": 2}]):
        with pytest.raises(ValueError, match="size ladder"):
            PackRacing(sizes=bad)
