"""Built-in methods for orders (roadmap C2): swap search, and replay and reference evaluation of permutation candidates."""
from itertools import permutations
from types import SimpleNamespace

import pytest

from optimization_framework.optimizers import conformance, registry
from optimization_framework.optimizers.swap_search import SwapSearch, apply, moves

from test_permutations import instance

# Eight bakes: (minutes in the oven, minutes until due). Total tardiness has many local optima under single swaps.
BAKES = [(14, 20), (9, 25), (21, 40), (6, 18), (17, 70), (11, 45), (25, 95), (8, 60)]


def tardiness(order):
    clock = total = 0
    for item in order:
        clock += BAKES[item][0]
        total += max(0, clock - BAKES[item][1])
    return total


OPTIMUM = min(tardiness(order) for order in permutations(range(len(BAKES))))


def observe(optimizer, proposal, value):
    optimizer.observe([SimpleNamespace(proposal_id=proposal.id, status="ok", candidate=proposal.candidate,
                                       objectives={"tardiness": value}, error=None)])


def search(seed, budget, parameters=None):
    """Run swap search on the eight bakes; return the evaluation at which it first reached the optimum (or None) and the orders."""
    optimizer = registry.create("swap_search", instance(), parameters or {}, seed, budget)
    seen, reached = [], None
    for step in range(budget):
        proposal, = optimizer.propose()
        seen.append(proposal.candidate)
        value = tardiness(proposal.candidate)
        observe(optimizer, proposal, value)
        if value == OPTIMUM and reached is None:
            reached = step + 1
    return reached, seen, optimizer


def test_the_neighbourhood_has_every_swap_and_every_non_adjacent_insertion_once():
    found = {tuple(apply(range(8), move)) for move in moves(8)}
    assert len(moves(8)) == 28 + 42 == len(found) and tuple(range(8)) not in found
    assert apply([0, 1, 2, 3], ("insert", 0, 2)) == [1, 2, 0, 3] and apply([0, 1, 2, 3], ("swap", 0, 3)) == [3, 1, 2, 0]


def test_swap_search_reaches_the_enumerated_optimum_of_eight_bakes():
    assert registry.capability_reason("swap_search", instance()) is None
    for seed in range(4):   # 40,320 orders; each seed reaches the optimum within 300 evaluations (51, 55, 144, 124)
        reached, seen, _ = search(seed, 300)
        assert reached is not None, f"seed {seed}: best {min(map(tardiness, seen))}, optimum {OPTIMUM}"
    reached, seen, optimizer = search(0, 300)
    assert all(sorted(order) == list(range(8)) for order in seen)
    assert optimizer.optimizer.best_score == -OPTIMUM   # the adapter maximizes the utility; tardiness is minimized
    assert search(0, 300)[1] == seen   # the same seed gives the same search


def test_swap_search_restarts_after_a_plateau_and_only_takes_orders():
    _, _, patient = search(3, 300)
    _, _, restless = search(3, 300, {"restarts_after": 5})
    assert restless.inspect()["restarts"] > patient.inspect()["restarts"] >= 1
    for bad in (0, -1, 2.5):
        with pytest.raises(ValueError):
            registry.validate_parameters("swap_search", instance(), {"restarts_after": bad})
    with pytest.raises(ValueError, match="Unsupported optimizer parameters"):
        registry.validate_parameters("swap_search", instance(), {"initial_design": list(range(8))})
    binary = instance().model_copy(update={"candidate_schema": instance().candidate_schema.model_copy(update={"representation": "binary"})})
    assert "requires permutation" in registry.capability_reason("swap_search", binary)
    with pytest.raises(ValueError):
        SwapSearch(8, 0, {"restarts_after": True})


def test_swap_search_meets_the_optimizer_contract():
    result = conformance.check("swap_search", instance(), steps=12)
    assert result["method"] == "swap_search" and "finished_at_step" not in result


def test_a_checkpoint_mid_search_continues_the_same_search():
    _, seen, _ = search(5, 120)
    optimizer = registry.create("swap_search", instance(), {}, 5, 120)
    for _ in range(60):
        proposal, = optimizer.propose()
        observe(optimizer, proposal, tardiness(proposal.candidate))
    state = optimizer.checkpoint()
    restored = registry.create("swap_search", instance(), {}, 5, 120)
    restored.restore(state)
    for step in range(60, 120):
        proposal, = restored.propose()
        assert proposal.candidate == seen[step]
        observe(restored, proposal, tardiness(proposal.candidate))
    broken = dict(state, state={**state["state"], "current": [0] * 8})
    with pytest.raises(ValueError, match="not an order"):
        registry.create("swap_search", instance(), {}, 5, 120).restore(broken)


def test_replay_evaluates_each_listed_order_and_refuses_a_non_order():
    orders = [[0, 1, 2, 3, 4, 5, 6, 7], [3, 0, 1, 5, 2, 7, 4, 6], [7, 6, 5, 4, 3, 2, 1, 0]]
    assert registry.capability_reason("replay", instance()) is None
    optimizer = registry.create("replay", instance(), {"candidates": orders}, 0, 3)
    for order in orders:
        proposal, = optimizer.propose()
        assert proposal.candidate == order
        observe(optimizer, proposal, tardiness(proposal.candidate))
    assert optimizer.inspect() == {"replayed_evaluations": 3}
    with pytest.raises(ValueError):
        registry.create("replay", instance(), {"candidates": [[0, 0, 1, 2, 3, 4, 5, 6]]}, 0, 1)


def test_a_reference_order_is_evaluated_once():
    asset = {"kind": "solution", "payload": {"candidate": [3, 0, 1, 5, 2, 7, 4, 6]}}
    assert registry.capability_reason("evaluate_asset", instance()) is None
    registry.bind_inputs("evaluate_asset", instance(), {}, [asset])
    optimizer = registry.create("evaluate_asset", instance(), {}, 0, 1, assets=[asset])
    proposal, = optimizer.propose()
    assert proposal.candidate == [3, 0, 1, 5, 2, 7, 4, 6]
    with pytest.raises(ValueError):
        registry.bind_inputs("evaluate_asset", instance(), {}, [{"kind": "solution", "payload": {"candidate": [0, 1, 2]}}])
