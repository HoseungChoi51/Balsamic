"""Pure deterministic constructions. Subset DP supports at most 20 jobs.

Time O(n*2**n), space O(2**n); the limit is checked before table allocation.
All times are minutes relative to the schedule start. No integer conversion of times.
"""
from math import isfinite, isclose
from time import perf_counter

DP_SIZE_LIMIT = 20


def inputs(durations, due):
    p, d = list(durations), list(due)
    if len(p) != len(d):
        raise ValueError("durations and due must have equal lengths")
    if any(not isfinite(x) or x < 0 for x in p) or any(not isfinite(x) for x in d):
        raise ValueError("finite nonnegative durations and finite due dates required")
    return p, d


def score(order, p, d):
    t = total = 0
    for j in order:
        t += p[j]
        total += max(0, t - d[j])
    return total


def subset_dp(durations, due):
    start = perf_counter()
    p, d = inputs(durations, due)
    n = len(p)
    if n > DP_SIZE_LIMIT:
        raise ValueError(f"subset DP supports at most {DP_SIZE_LIMIT} jobs")
    size = 1 << n
    times, costs, last = [0] * size, [0] * size, [-1] * size
    transitions = 0
    # Integer mask order is topological: removing any bit decreases the mask.
    for mask in range(1, size):
        bit = mask & -mask
        times[mask] = times[mask ^ bit] + p[bit.bit_length() - 1]
        best = None
        bits = mask
        while bits:
            bit = bits & -bits
            j = bit.bit_length() - 1
            value = costs[mask ^ bit] + max(0, times[mask] - d[j])
            transitions += 1
            # Ascending j and strict improvement give smallest LAST job ties.
            if best is None or value < best:
                best, last[mask] = value, j
            bits ^= bit
        costs[mask] = best
    order, mask = [], size - 1
    while mask:
        j = last[mask]
        order.append(j)
        mask ^= 1 << j
    order.reverse()
    verified = score(order, p, d)
    if not isclose(verified, costs[-1], rel_tol=1e-12, abs_tol=1e-12):
        raise ArithmeticError("DP reconstruction disagrees with independent prefix scoring")
    return dict(order=order, objective=verified, states=size, transitions=transitions,
                elapsed_seconds=perf_counter() - start)


def modified_due_date(durations, due):
    start = perf_counter()
    p, d = inputs(durations, due)
    remaining, order, t, calculations = list(range(len(p))), [], 0, 0
    while remaining:
        calculations += len(remaining)
        j = min(remaining, key=lambda j: (max(d[j], t + p[j]), p[j], j))
        order.append(j)
        remaining.remove(j)
        t += p[j]
    return dict(order=order, objective=score(order, p, d),
                priority_calculations=calculations, elapsed_seconds=perf_counter() - start)
