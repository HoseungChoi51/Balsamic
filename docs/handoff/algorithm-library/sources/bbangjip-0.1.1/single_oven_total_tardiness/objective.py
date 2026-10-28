"""Serial, nonpreemptive, no-idle total tardiness, in minutes from start.

Every order occurs exactly once. Early completion earns no credit. Wall-clock
origin is used only for display, never in the objective or DP recurrence.
"""
from __future__ import annotations

import math
from numbers import Real

import numpy as np

ORDER_KEYS = ('bread', 'baguette', 'croissant', 'cake', 'muffin', 'cookie', 'tart', 'bagel')


def order_data(values):
    """Read charter quantities in their declared index order (also public descriptors)."""
    def get(key):
        return values[key]
    n = get('n_orders')
    names = get('order_names')
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or not 0 <= n <= len(ORDER_KEYS):
        raise ValueError('n_orders must be an integer in the declared order catalog')
    if not isinstance(names, (list, tuple)) or len(names) != n:
        raise ValueError('n_orders and order_names length differ')
    p = [get('p_' + key) for key in ORDER_KEYS[:n]]
    d = [get('d_' + key) for key in ORDER_KEYS[:n]]
    origin = get('start_minutes')
    if any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) for x in [*p, *d, origin]):
        raise ValueError('order times must be finite numbers')
    if any(x < 0 for x in p):
        raise ValueError('processing times must be nonnegative')
    return names, p, d, origin


def permutation(candidate, n):
    raw = np.asarray(candidate, dtype=object)
    if raw.shape != (n,):
        raise ValueError(f'expected permutation of length {n}')
    if any(isinstance(x, (bool, np.bool_)) or not isinstance(x, Real)
           or not math.isfinite(x) or x != int(x) for x in raw):
        raise ValueError('permutation indices must be integer-valued numbers')
    result = [int(x) for x in raw]
    if sorted(result) != list(range(n)):
        raise ValueError('permutation has duplicate, missing or out-of-range indices')
    return result


def schedule(problem, candidate):
    """Full schedule, relative minutes and explicitly labeled wall-clock minutes."""
    names, p, d, origin = order_data(problem.values)
    order = permutation(candidate, len(names))
    elapsed, total, rows = 0, 0, []
    for j in order:
        start = elapsed
        elapsed += p[j]
        tardiness = max(0, elapsed - d[j])
        total += tardiness
        rows.append({'order_index': j, 'order_key': ORDER_KEYS[j], 'order_name': names[j],
                     'start': start, 'completion': elapsed, 'pickup': d[j],
                     'processing_time': p[j], 'tardiness': tardiness,
                     'start_wall_minutes': origin + start,
                     'completion_wall_minutes': origin + elapsed,
                     'pickup_wall_minutes': origin + d[j]})
    return {'baking_order': order, 'order_names': [names[j] for j in order],
            'schedule': rows, 'total_pickup_tardiness': total,
            'makespan': elapsed, 'start_minutes': origin}


def objective(problem, candidate) -> float:
    """Sum max(0, cumulative completion - pickup) for a valid full permutation."""
    return float(schedule(problem, candidate)['total_pickup_tardiness'])
