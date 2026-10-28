"""Generic elapsed-time single-machine objective; vectors indexed by original job."""
from dataclasses import dataclass
import math
from numbers import Integral


def inputs(p, d):
    try:
        p, d = tuple(float(x) for x in p), tuple(float(x) for x in d)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('p and d must be numeric vectors') from exc
    if len(p) != len(d) or any(not math.isfinite(x) or x < 0 for x in p) or any(not math.isfinite(x) for x in d):
        raise ValueError('aligned finite p>=0 and finite elapsed d required')
    return p, d


def permutation(order, n, partial=False):
    order = tuple(order)
    if any(isinstance(j, bool) or not isinstance(j, Integral) for j in order):
        raise ValueError('job indices must be integers')
    if len(set(order)) != len(order) or any(j < 0 or j >= n for j in order) or (not partial and len(order) != n):
        raise ValueError('invalid permutation')
    return tuple(int(j) for j in order)


@dataclass(frozen=True)
class Result:
    order: tuple[int, ...]
    total_tardiness: float
    completion: tuple[float, ...]
    wait: tuple[float, ...]


def recalculate(p, d, order):
    p, d = inputs(p, d)
    order = permutation(order, len(p))
    completion, wait = [0.0]*len(p), [0.0]*len(p)
    elapsed = total = 0.0
    for j in order:
        elapsed += p[j]
        completion[j] = elapsed
        wait[j] = max(0.0, elapsed-d[j])
        total += wait[j]
    if not math.isfinite(elapsed) or not math.isfinite(total):
        raise OverflowError('schedule arithmetic overflow')
    return Result(order, total, tuple(completion), tuple(wait))


def partial_score(p, d, order):
    elapsed = total = 0.0
    for j in order:
        elapsed += p[j]
        total += max(0.0, elapsed-d[j])
    if not math.isfinite(elapsed) or not math.isfinite(total):
        raise OverflowError('schedule arithmetic overflow')
    return total
