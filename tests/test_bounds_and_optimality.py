"""Bounds and optimality (roadmap N13): a method's bound and proof of optimality are recorded as claims, checked by the
built-in ``enumerate`` or a charter reference result, and the comparison shows the gap and ranks methods by their cost to
a checked optimum.
"""
from itertools import permutations
from types import SimpleNamespace

import pytest

from optimization_benchmarks.problems import KnapsackProblem
from optimization_framework.analysis.general import report
from optimization_framework.analysis.optimality import charter_references, summarize
from optimization_framework.contracts.problems import CandidateSchema, ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput
from optimization_framework.execution.service import Workspace
from optimization_framework.execution.worker import read_journal, run
from optimization_framework.optimizers import conformance, registry
from optimization_framework.optimizers.finish import MethodFinished
from optimization_framework.optimizers.functions import FunctionMethod

from test_permutations import instance
from test_swap_search import OPTIMUM, tardiness


def observe(optimizer, proposal, value):
    optimizer.observe([SimpleNamespace(proposal_id=proposal.id, status="ok", candidate=proposal.candidate,
                                       objectives={"tardiness": value}, error=None)])


def drive(optimizer, objective):
    """Propose and observe until the method finishes; the evaluations it made."""
    evaluations = 0
    while True:
        try:
            proposal, = optimizer.propose()
        except MethodFinished:
            return evaluations
        evaluations += 1
        observe(optimizer, proposal, objective(proposal.candidate))


def test_enumerate_finds_the_eight_bake_optimum_and_proves_it():
    assert registry.capability_reason("enumerate", instance()) is None
    oracle = registry.create("enumerate", instance(), {}, 0, 10)
    assert drive(oracle, tardiness) == 40_320   # 8!: every order is one evaluation on an oracle problem
    assert oracle.inspect() == {"decisions": 40_320, "enumerated": 40_320, "candidates": 40_320, "bound": OPTIMUM, "proved_optimal": True}
    # On a white-box problem it enumerates through problem.objective and records only the optimum.
    white = registry.create("enumerate", instance(), {}, 0, 10)
    white.open_objective(tardiness)
    assert drive(white, tardiness) == 1
    assert white.inspect()["bound"] == OPTIMUM and white.inspect()["proved_optimal"] is True
    # A checkpoint taken part way continues the same order.
    part = registry.create("enumerate", instance(4), {}, 0, 10)
    seen = []
    for _ in range(10):
        proposal, = part.propose()
        seen.append(proposal.candidate)
        observe(part, proposal, 0.0)
    resumed = registry.create("enumerate", instance(4), {}, 0, 10)
    resumed.restore(part.checkpoint())
    rest = []
    while True:
        try:
            proposal, = resumed.propose()
        except MethodFinished:
            break
        rest.append(proposal.candidate)
        observe(resumed, proposal, 0.0)
    assert [tuple(order) for order in seen + rest] == list(permutations(range(4)))


def test_enumerate_refuses_more_candidates_than_its_cap_with_the_count():
    wide = ProblemInstance(**{**instance().model_dump(), "candidate_schema": CandidateSchema(representation="binary", dimensions=40)})
    with pytest.raises(ValueError, match="1,099,511,627,776 candidates, more than max_candidates \\(1,000,000\\)"):
        registry.validate_parameters("enumerate", wide, {})
    with pytest.raises(ValueError, match="1,099,511,627,776"):
        registry.create("enumerate", wide, {}, 0, 10)
    with pytest.raises(ValueError, match="40,320 candidates"):
        registry.validate_parameters("enumerate", instance(), {"max_candidates": 1000})
    continuous = ProblemInstance(**{**instance().model_dump(), "candidate_schema": CandidateSchema(representation="continuous", dimensions=2,
                                                                                                    bounds=[[0, 1], [0, 1]])})
    assert "requires binary or discrete or permutation" in registry.capability_reason("enumerate", continuous)


def test_enumerate_meets_the_optimizer_contract_and_a_bound_its_best_beats_fails_it(monkeypatch):
    result = conformance.check("enumerate", instance(3), steps=8)
    assert result["finished_at_step"] == {0: 6, 7: 6} and "bounds its own best does not beat" in result["checks"]
    from optimization_framework.optimizers.enumerate import Enumeration
    # A method claiming a bound worse than a value it has already seen breaks the contract.
    monkeypatch.setattr(Enumeration, "diagnostics", lambda self: {"decisions": self.index, "bound": 1.5, "proved_optimal": True})
    with pytest.raises(AssertionError, match="reports bound 1.5, which its own best .* beats"):
        conformance.check("enumerate", instance(3), steps=8)


def test_a_claim_of_optimality_is_checked_claimed_or_contradicted():
    objective = {"name": "tardiness", "direction": "minimize"}
    run = lambda trial_id, algorithm, best, proved=False, bound=None: {"trial_id": trial_id, "algorithm": algorithm, "hypothesis_id": None,
        "best": best, "bound": best if proved and bound is None else bound, "proved_optimal": proved, "method_finished": proved}
    # A method that proves a value enumeration beats is not shown as proved: its claim is contradicted.
    summary = summarize([run("t_enum", "enumerate", 290.0, True), run("t_wrong", "dp", 305.0, True), run("t_swap", "swap_search", 305.0)], objective)
    claims = {claim["trial_id"]: claim for claim in summary["claims"]}
    assert claims["t_wrong"]["status"] == "contradicted" and claims["t_wrong"]["contradicted_by"] == "t_enum"
    assert claims["t_enum"] == {**claims["t_enum"], "status": "checked", "checked_by": "enumerate"}
    assert summary["optimum"] == {"value": 290.0, "status": "checked", "claimed_by": ["enumerate"], "checked_by": "enumerate"}
    # With nothing to check it, a proof is shown as claimed by its method, and the bound sets the gap.
    alone = summarize([run("t_bb", "branch_and_bound", 300.0, bound=280.0), run("t_swap", "swap_search", 305.0)], objective)
    assert alone["optimum"] is None and alone["best_bound"] == 280.0 and alone["bound_algorithm"] == "branch_and_bound"
    assert alone["gap"] == pytest.approx(20.0) and alone["relative_gap"] == pytest.approx(20 / 280)
    claimed = summarize([run("t_dp", "dp", 290.0, True)], objective)
    assert claimed["optimum"]["status"] == "claimed" and claimed["optimum"]["claimed_by"] == ["dp"] and claimed["gap"] == 0
    # A reference result of the charter with the same value checks it.
    assert summarize([run("t_dp", "dp", 290.0, True)], objective, [290.0])["optimum"]["checked_by"] == "reference"
    # A bound some run beats is false, and is not the best bound.
    assert summarize([run("t_bad", "lp", 300.0, bound=295.0), run("t_swap", "swap_search", 290.0)], objective)["best_bound"] is None


# The comparison, on a knapsack small enough to enumerate (2¹² subsets).
ITEMS, CAPACITY = 12, 60


def knapsack_optimum():
    resolved = KnapsackProblem().resolve({"items": ITEMS, "capacity": CAPACITY})
    weights, values = resolved.configuration["weights"], resolved.configuration["values"]
    best = [0] * (CAPACITY + 1)
    for weight, value in zip(weights, values):
        for room in range(CAPACITY, weight - 1, -1):
            best[room] = max(best[room], best[room - weight] + value)
    return best[CAPACITY], weights, values


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Exact", compute_budget_seconds=400, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Small knapsack", problem_id="knapsack_dp", configuration={"items": ITEMS, "capacity": CAPACITY})]))
    return workspace, campaign["id"], workspace.current_tasks(campaign["id"])[0]


def execute(workspace, campaign_id, task, *, algorithm="random", fn=None, seed=0, max_steps=50):
    trial = workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=task["id"], algorithm=algorithm, max_steps=max_steps,
                                              wall_seconds=60, seed=seed))
    method = FunctionMethod(fn, ProblemInstance(**trial["problem"]), {}, trial["seed"]) if fn else None
    result = run(workspace.job_dir(trial["id"]), **({"optimizer": method} if method else {}))
    trial.update(result=result, progress=result, attempt=1, status="completed")
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return trial, result


def test_the_comparison_shows_the_gap_and_ranks_methods_that_reached_a_checked_optimum_by_their_cost(lab):
    workspace, campaign_id, task = lab
    optimum, weights, values = knapsack_optimum()

    def greedy(problem, evaluate, rng):
        """By value-to-weight ratio, then claims (wrongly, if it falls short) that this is optimal."""
        chosen, room = [0] * ITEMS, CAPACITY
        for item in sorted(range(ITEMS), key=lambda i: -values[i] / weights[i]):
            if weights[item] <= room:
                chosen[item], room = 1, room - weights[item]
        value = evaluate(chosen)
        return {"reason": "greedy fill", "bound": value, "proved_optimal": True}

    def dynamic_program(problem, evaluate, rng):
        best = [(0, ())] * (CAPACITY + 1)
        for item, (weight, value) in enumerate(zip(weights, values)):
            for room in range(CAPACITY, weight - 1, -1):
                if best[room - weight][0] + value > best[room][0]:
                    best[room] = (best[room - weight][0] + value, best[room - weight][1] + (item,))
        evaluate([int(item in best[CAPACITY][1]) for item in range(ITEMS)])
        return {"reason": "dynamic program over the capacity", "bound": float(best[CAPACITY][0]), "proved_optimal": True}

    enumerated, ended = execute(workspace, campaign_id, task, algorithm="enumerate")
    # White box (the default): enumerate computes every subset through the objective and records one evaluation.
    assert ended["reason"] == "method_finished" and ended["evaluations"] == 1
    assert (ended["best_objective"], ended["best_bound"], ended["proved_optimal"]) == (optimum, optimum, True)
    assert ended["final_inspection"]["candidates"] == 2 ** ITEMS
    # A function method runs in place of the trial's named built-in; distinct step budgets keep the methods apart in the report.
    dp, dp_ended = execute(workspace, campaign_id, task, fn=dynamic_program, max_steps=51)
    assert (dp_ended["best_bound"], dp_ended["proved_optimal"]) == (optimum, True)
    greedy_trial, greedy_ended = execute(workspace, campaign_id, task, fn=greedy, max_steps=52)
    assert greedy_ended["best_objective"] < optimum and greedy_ended["proved_optimal"] is True
    execute(workspace, campaign_id, task, algorithm="random", max_steps=5)

    comparison = report(workspace, campaign_id)
    group, = comparison["groups"]
    optimality = group["optimality"]
    assert optimality["best_value"] == optimum and optimality["best_bound"] == optimum and optimality["gap"] == 0
    assert optimality["optimum"] == {"value": optimum, "status": "checked", "claimed_by": ["enumerate", "random"], "checked_by": "enumerate"}
    claims = {claim["trial_id"]: claim["status"] for claim in optimality["claims"]}
    assert claims == {enumerated["id"]: "checked", dp["id"]: "checked", greedy_trial["id"]: "contradicted"}
    # The methods that reached the checked optimum rank first, by their cost to it; the others after, by their value.
    method_of = {row["id"]: row["method_id"] for row in group["trials"]}
    summaries = {summary["method_id"]: summary for summary in group["method_summaries"]}
    exact = sorted((summaries[method_of[enumerated["id"]]], summaries[method_of[dp["id"]]]), key=lambda summary: summary["cost_to_optimum"])
    assert [summary["rank"] for summary in exact] == [1, 2] and all(summary["optimum_reached"] == 1 for summary in exact)
    wrong = summaries[method_of[greedy_trial["id"]]]
    assert wrong["cost_to_optimum"] is None and wrong["optimum_reached"] == 0 and wrong["rank"] not in (1, 2)
    rows = {row["id"]: row for row in group["trials"]}
    assert rows[greedy_trial["id"]]["proved_optimal"] is True and rows[greedy_trial["id"]]["optimum_reached_at"] is None
    assert len(read_journal(workspace.job_dir(enumerated["id"]) / "observations.jsonl")) == 1


def test_a_charter_reference_result_checks_a_claim(lab, monkeypatch):
    workspace, campaign_id, task = lab
    workspace.store.put("problem_charter", {"id": "problem_charter_ref", "campaign_ids": [campaign_id], "revision": 1, "confirmed_revision": 1,
        "charter": {"title": "Small knapsack", "instances": [{"name": "Small knapsack", "values": {}}],
                    "references": [{"statement": "The optimum is 290", "value": 290}, {"statement": "Another size", "value": 1, "holds_at": {"items": 99}}]}})
    monkeypatch.setattr("optimization_framework.problem_charter.charter.resolve", lambda charter, values=None: {"values": {"items": 12}, "errors": []})
    assert charter_references(workspace, campaign_id, [task]) == {task["id"]: [290.0]}
