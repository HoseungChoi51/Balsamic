"""Subset values and one last-job pointer per subset, not partial permutations."""
from array import array
import math
from .common import inputs, recalculate

MAX_JOBS = 20


def solve(p, d):
    p, d = inputs(p, d)
    n = len(p)
    if n > MAX_JOBS:
        raise ValueError(f'subset DP supports at most {MAX_JOBS} jobs')
    size = 1 << n
    sums = array('d', [0.0])*size
    values = array('d', [0.0])*size
    last = array('i', [-1])*size
    for mask in range(1, size):
        bit = mask & -mask
        sums[mask] = sums[mask ^ bit] + p[bit.bit_length()-1]
        best, chosen = math.inf, -1
        bits = mask
        while bits:
            bit = bits & -bits
            j = bit.bit_length()-1
            value = values[mask ^ bit] + max(0.0, sums[mask]-d[j])
            if value < best:  # ascending j means exact equality keeps smallest last index
                best, chosen = value, j
            bits ^= bit
        if not math.isfinite(best):
            raise OverflowError('DP arithmetic overflow')
        values[mask], last[mask] = best, chosen
    order, mask = [], size-1
    while mask:
        j = last[mask]
        order.append(j)
        mask ^= 1 << j
    result = recalculate(p, d, reversed(order))
    if not math.isclose(result.total_tardiness, values[-1], rel_tol=1e-10, abs_tol=1e-10):
        raise ArithmeticError('DP/recalculation disagreement')
    return result


def create_optimizer(context):
    from .lifecycle import Optimizer
    return Optimizer(context, 'dp')
