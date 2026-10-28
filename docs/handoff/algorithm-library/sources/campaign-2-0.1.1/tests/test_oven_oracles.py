"""Independent specification tests, not scientific campaign runs."""
import itertools
import json
import math
import random

import pytest

from single_oven_total_tardiness.core import subset_dp, modified_due_date, DP_SIZE_LIMIT
from single_oven_total_tardiness.objective import details, objective, ORDER_NAMES
from single_oven_total_tardiness.problem import problem


def oracle_score(order, p, d):
    return sum(max(0, sum(p[k] for k in order[:i + 1]) - d[j]) for i, j in enumerate(order))


@pytest.mark.parametrize('n', range(7))
def test_exhaustive_permutation_oracle(n):
    rng = random.Random(n)
    for _ in range(8):
        p = [rng.choice([0, .25, 1.5, 3]) for _ in range(n)]
        d = [rng.choice([-3, .5, 2, 1000000]) for _ in range(n)]
        orders = list(itertools.permutations(range(n)))
        # Recursive smallest-LAST tie rule equals lexicographic reverse-order tie comparison.
        best = min(orders, key=lambda o: (oracle_score(o, p, d), tuple(reversed(o))))
        result = subset_dp(p, d)
        assert result['order'] == list(best)
        assert result['objective'] == oracle_score(best, p, d)
        assert result['states'] == 2 ** n
        assert result['transitions'] == (n * 2 ** (n - 1) if n else 0)
        assert result['elapsed_seconds'] >= 0


def test_all_small_binary_inputs():
    for p in itertools.product([0, .5], repeat=3):
        for d in itertools.product([-1, 0, 2], repeat=3):
            orders = itertools.permutations(range(3))
            best = min(orders, key=lambda o: (oracle_score(o, p, d), tuple(reversed(o))))
            assert subset_dp(p, d)['order'] == list(best)


def test_dp_last_not_lexicographic_and_size_limit():
    assert subset_dp([1] * 4, [100] * 4)['order'] == [3, 2, 1, 0]
    with pytest.raises(ValueError, match='at most'):
        subset_dp([0] * (DP_SIZE_LIMIT + 1), [0] * (DP_SIZE_LIMIT + 1))


@pytest.mark.parametrize('p,d', [([0, .5, 1.25], [-1, 100, .2]), ([4, 1, 1], [0, 4, 4]),
                                ([2, 2, 1], [100, 100, 100]), ([], [])])
def test_mdd_dynamic_and_ties(p, d):
    result = modified_due_date(p, d)
    remaining, t, expected = set(range(len(p))), 0, []
    while remaining:
        priorities = [(max(d[j], t + p[j]), p[j], j) for j in remaining]
        j = sorted(priorities)[0][-1]
        remaining.remove(j)
        expected.append(j)
        t += p[j]
    assert result['order'] == expected
    assert result['objective'] == oracle_score(expected, p, d)
    assert result['priority_calculations'] == len(p) * (len(p) + 1) // 2
    assert result['elapsed_seconds'] >= 0
    assert modified_due_date([4, 1, 1], [0, 4, 4])['order'] == [1, 2, 0]
    # Recomputing priorities changes the second choice versus sorting once at t=0.
    assert modified_due_date([1, 1, 2], [0, 3, 0])['order'] == [0, 1, 2]


@pytest.mark.parametrize('fn', [subset_dp, modified_due_date])
@pytest.mark.parametrize('p,d', [([1], []), ([-.1], [0]), ([math.inf], [0]), ([0], [math.nan])])
def test_bad_core_inputs(fn, p, d):
    with pytest.raises(ValueError):
        fn(p, d)


def test_supplied_permutation_schedule():
    pr = problem()
    order = [6, 5, 7, 2, 3, 0, 1, 4]
    p = [40, 30, 25, 60, 20, 15, 35, 20]
    d = [185, 230, 150, 175, 240, 140, 45, 135]
    metrics, rows = details(pr, order)
    waits = [0] * 8
    for pos, j in enumerate(order):
        completion = sum(p[k] for k in order[:pos + 1])
        wait = max(0, completion - d[j])
        waits[j] = wait
        assert rows[pos] == dict(order_index=j, order_name=ORDER_NAMES[j], position=pos,
            start_min=completion - p[j], completion_min=completion, pickup_min=d[j], wait_min=wait)
    assert metrics['total_customer_wait'] == sum(waits) == objective(pr, order)
    assert metrics['late_order_count'] == sum(w > 0 for w in waits)
    assert metrics['max_customer_wait'] == max(waits)
    assert all(metrics[name + '_wait'] == waits[j] for j, name in enumerate(ORDER_NAMES))


@pytest.mark.parametrize('bad', [[0] * 8, list(range(7)), list(range(9)), [.1] + list(range(1, 8)),
                               [math.nan] + list(range(1, 8)), [[j] for j in range(8)],
                               [-1] + list(range(1, 8)), [math.inf] + list(range(1, 8))])
def test_invalid_permutations(bad):
    with pytest.raises(ValueError):
        objective(problem(), bad)
