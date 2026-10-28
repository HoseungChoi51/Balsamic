import itertools
import json
from pathlib import Path
import importlib
import numpy as np
import pytest
from single_oven_total_tardiness import subset_dp, due_date_insertion, swap_search, recalculate
from single_oven_total_tardiness.common import inputs
from single_oven_total_tardiness.due_date_insertion import construct
from single_oven_total_tardiness._swap_core import SwapSearch, moves, apply


def oracle(p, d, order):
    t = total = 0
    for j in order:
        t += p[j]
        total += max(0, t-d[j])
    return total


@pytest.mark.parametrize('n', range(7))
@pytest.mark.parametrize('seed', [0, 3, 11])
def test_dp_oracle(n, seed):
    rng = np.random.default_rng(seed)
    p = rng.integers(0, 5, n).tolist()
    d = rng.integers(-2, 12, n).tolist()
    orders = list(itertools.permutations(range(n)))
    expected = min(orders, key=lambda o: (oracle(p, d, o), tuple(reversed(o))))
    result = subset_dp(p, d)
    assert result.order == expected
    assert result.total_tardiness == oracle(p, d, expected)
    assert sorted(result.order) == list(range(n))


def test_dp_last_ties():
    assert subset_dp([1, 1, 1], [100]*3).order == (2, 1, 0)
    assert subset_dp([0]*3, [-1]*3).order == (2, 1, 0)


@pytest.mark.parametrize('solve', [subset_dp, due_date_insertion, swap_search])
def test_objective_edges_and_no_mutation(solve):
    p, d = [0, 2, 3], [-1, 10, 1]
    before = (p[:], d[:])
    result = solve(p, d)
    assert (p, d) == before
    assert result.total_tardiness == oracle(p, d, result.order)
    assert solve([], []).total_tardiness == 0
    assert solve([0], [-2]).wait == (2,)
    assert solve([2], [9]).wait == (0,)


def test_hand_objective_elapsed():
    r = recalculate([0, 2, 3], [-1, 10, 1], [0, 1, 2])
    assert r.completion == (0, 2, 5)
    assert r.wait == (1, 0, 4) and r.total_tardiness == 5
    assert recalculate([3], [2], [0]).total_tardiness == 1


@pytest.mark.parametrize('p,d', [([1], []), ([-1], [0]), ([float('nan')], [1]), ([1], [float('inf')]), ([float('inf')], [0])])
@pytest.mark.parametrize('solve', [subset_dp, due_date_insertion, swap_search])
def test_invalid_inputs(p, d, solve):
    with pytest.raises(ValueError):
        solve(p, d)


@pytest.mark.parametrize('order', [[0, 0], [0], [-1, 1], [0, 2], [0.0, 1], [False, 1]])
def test_invalid_permutations(order):
    with pytest.raises(ValueError):
        recalculate([1, 2], [3, 4], order)


def test_limits_and_overflow():
    # Cap test changes the constant so no fixture exceeds six jobs.
    module = importlib.import_module('single_oven_total_tardiness.subset_dp')
    old = module.MAX_JOBS
    try:
        module.MAX_JOBS = 2
        with pytest.raises(ValueError): module.solve([1]*3, [1]*3)
    finally:
        module.MAX_JOBS = old
    for solve in (subset_dp, due_date_insertion, swap_search):
        with pytest.raises(OverflowError): solve([1e308]*2, [-1e308]*2)


@pytest.mark.parametrize('p,d', [([4, 1, 1, 2], [3, 3, 3, -1]), ([0, 0, 0], [10]*3), ([3, 2, 4], [0, 2, 5])])
def test_insertion_each_position_whole_objective(p, d):
    previous = ()
    steps = list(construct(p, d))
    assert [j for j, _, _ in steps] == sorted(range(len(p)), key=lambda j: (d[j], p[j], j))
    for j, pos, order in steps:
        trials = [previous[:k]+(j,)+previous[k:] for k in range(len(previous)+1)]
        expected = min(range(len(trials)), key=lambda k: oracle(p, d, trials[k]))
        assert pos == expected and order == trials[expected]
        assert tuple(x for x in order if x != j) == previous
        previous = order
    assert due_date_insertion(p, d).order == previous


def test_insertion_delays_and_ties():
    assert list(construct([2, 3], [0, 2])) == [(0, 0, (0,)), (1, 1, (0, 1))]
    assert due_date_insertion([0, 0, 0], [5]*3).order == (2, 1, 0)


def test_moves_and_copy():
    assert moves(3) == [('swap', 0, 1), ('swap', 0, 2), ('swap', 1, 2), ('insert', 0, 2), ('insert', 2, 0)]
    order = [0, 1, 2]
    assert apply(order, ('insert', 0, 2)) == [1, 2, 0]
    assert order == [0, 1, 2]


@pytest.mark.parametrize('seed', [0, 7, 19])
def test_random_initialization_shuffled_pop_strict_acceptance(seed):
    s = SwapSearch(3, seed)
    rng = np.random.default_rng(seed)
    initial = rng.permutation(3).tolist()
    assert s.current is None and s.ask().tolist() == initial
    s.tell(initial, -10)
    remaining = rng.permutation(len(moves(3))).tolist()
    assert s.remaining == remaining and s.restarts_after == len(moves(3))
    candidate = s.ask().tolist()
    assert candidate == apply(initial, moves(3)[remaining.pop()])
    s.tell(candidate, -10)  # tie rejected
    assert s.current == initial and s.stagnation == 1
    candidate = s.ask().tolist()
    assert candidate == apply(initial, moves(3)[remaining.pop()])
    s.tell(candidate, -9)  # first strict improvement, immediately accepted
    assert s.current == candidate and s.stagnation == 0
    assert s.remaining == rng.permutation(len(moves(3))).tolist()
    assert s.count == 3


@pytest.mark.parametrize('trigger', ['exhaustion', 'threshold'])
def test_restart_retains_global_best(trigger):
    s = SwapSearch(3, 4)
    first = s.ask().tolist(); s.tell(first, -1)
    if trigger == 'exhaustion':
        for _ in range(len(s.moves)):
            c = s.ask(); s.tell(c, -2)
        assert not s.remaining
        s.stagnation = 0  # isolate exhausted-neighborhood trigger
    else:
        s.stagnation = s.restarts_after  # isolate threshold with moves remaining
        assert s.remaining
    c = s.ask().tolist()
    assert s.pending_restart and s.restarts == 1
    s.tell(c, -100)
    assert s.current == c and s.current_score == -100
    assert s.best == first and s.best_score == -1 and s.stagnation == 0


@pytest.mark.parametrize('seed', [1, 6, 23])
def test_source_parity_replay_json_restart(seed):
    from optimization_framework.optimizers.swap_search import SwapSearch as Source
    a, b = SwapSearch(3, seed), Source(3, seed)
    for step in range(15):
        ca, cb = a.ask().tolist(), b.ask().tolist()
        assert ca == cb
        # outstanding proposal, including near and during restarts
        state = json.loads(json.dumps(a.state_dict()))
        restored = SwapSearch(3, 999); restored.load_state_dict(state)
        utility = -float(step+1)
        for obj in (a, b, restored): obj.tell(ca, utility)
        assert a.state_dict() == b.state_dict() == restored.state_dict()
    assert a.restarts >= 2


def test_nonfinite_rejected_and_small_search():
    for n in (0, 1):
        s = SwapSearch(n, 0)
        assert s.restarts_after == 1
        c = s.ask()
        for score in (float('inf'), float('nan')):
            with pytest.raises(FloatingPointError): s.tell(c, score)
        assert s.count == 0
        s.tell(c, 0); s.ask()
        assert s.restarts == 1
    with pytest.raises(ValueError): swap_search([1], [0], evaluations=0)


def test_vendored_source_identical():
    root = Path(__file__).resolve().parents[3]
    assert (root/'src/optimization_framework/optimizers/swap_search.py').read_bytes() == (Path(__file__).resolve().parents[1]/'single_oven_total_tardiness/_swap_core.py').read_bytes()
