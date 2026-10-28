"""Independent arithmetic and exhaustive-oracle correctness tests, not benchmarks."""
from dataclasses import replace
from itertools import permutations

import numpy as np
import pytest

from single_oven_total_tardiness.methods import solve
from single_oven_total_tardiness.objective import objective, schedule
from single_oven_total_tardiness.problem import problem


def synthetic(p, d, origin=360):
    from single_oven_total_tardiness.objective import ORDER_KEYS
    base = problem()
    updates = {'n_orders': len(p), 'order_names': list(base.values.order_names[:len(p)]),
               'start_minutes': origin}
    for key, duration, due in zip(ORDER_KEYS, p, d):
        updates['p_' + key], updates['d_' + key] = duration, due
    return replace(base, values=replace(base.values, **updates), dimensions=len(p))


def oracle(p, d, order):
    elapsed = total = 0
    for j in order:
        elapsed += p[j]
        if elapsed > d[j]:
            total += elapsed - d[j]
    return total


@pytest.mark.parametrize('p,d', [([3, 2], [3, 5]), ([3, 2], [10, 10]),
                                  ([3, 2, 4], [1, 2, 3]), ([], [])])
def test_schedule_accumulation(p, d):
    prob = synthetic(p, d)
    order = list(range(len(p)))
    result = schedule(prob, order)
    assert objective(prob, order) == oracle(p, d, order)
    assert objective(synthetic(p, d, 900), order) == objective(prob, order)
    elapsed = 0
    for row, duration, due in zip(result['schedule'], p, d):
        assert row['start'] == elapsed
        elapsed += duration
        assert row['completion'] == elapsed
        assert row['pickup'] == due
        assert row['tardiness'] == max(0, elapsed - due)
        assert row['completion_wall_minutes'] == 360 + elapsed


@pytest.mark.parametrize('bad', [[0]*8, list(range(7)), list(range(9)),
                                  [-1]+list(range(1,8)), [8]+list(range(1,8)),
                                  [0.5]+list(range(1,8)), [float('nan')]+list(range(1,8)),
                                  [[i] for i in range(8)], ['0']+list(range(1,8)),
                                  [False]+list(range(1,8))])
def test_reject_invalid_permutations(bad):
    with pytest.raises(ValueError):
        objective(problem(), bad)


def test_dp_against_independent_exhaustive_oracle():
    rng = np.random.default_rng(187)
    for n in range(7):
        for _ in range(4):
            p = rng.integers(1, 12, n).tolist()
            d = rng.integers(0, 35, n).tolist()
            order, value = solve(p, d)
            assert sorted(order) == list(range(n))
            assert value == min(oracle(p, d, pi) for pi in permutations(range(n)))
            assert value == objective(synthetic(p, d), order)
            assert solve(p, d) == (order, value)


def test_charter_instance_against_exhaustive_oracle():
    p = [40, 30, 25, 60, 20, 15, 35, 20]
    d = [185, 230, 150, 175, 240, 140, 45, 135]
    order, value = solve(p, d)
    assert value == min(oracle(p, d, pi) for pi in permutations(range(8)))
    assert objective(problem(), order) == value


def test_data_length_validation():
    base = problem()
    with pytest.raises(ValueError):
        objective(replace(base, values=replace(base.values, n_orders=7)), list(range(8)))
