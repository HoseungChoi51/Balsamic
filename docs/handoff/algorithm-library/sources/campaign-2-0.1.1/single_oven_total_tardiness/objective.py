"""Raw total positive lateness in minutes, with all charter diagnostics."""
from math import isfinite
import numpy as np

from .core import inputs

ORDER_NAMES = ('bread', 'baguette', 'croissant', 'cake', 'muffin', 'cookie', 'tart', 'bagel')


def parameters(problem):
    v = problem.values
    if v.n_orders != len(ORDER_NAMES):
        raise ValueError("n_orders must equal the eight configured orders")
    return inputs([v[name + '_duration'] for name in ORDER_NAMES],
                  [v[name + '_due'] for name in ORDER_NAMES])


def permutation(candidate, n):
    try:
        a = np.asarray(candidate, dtype=float)
        if a.shape != (n,) or not np.all(np.isfinite(a)):
            raise ValueError("invalid permutation shape or nonfinite index")
        if sorted(a.tolist()) != list(range(n)):
            raise ValueError("candidate must contain every integer order index exactly once")
        return [int(j) for j in a]
    except (TypeError, OverflowError) as exc:
        raise ValueError("invalid permutation") from exc


def details(problem, candidate):
    p, d = parameters(problem)
    order = permutation(candidate, len(p))
    t, rows, waits = 0, [], [0] * len(p)
    for position, j in enumerate(order):
        start = t
        t += p[j]
        waits[j] = max(0, t - d[j])
        rows.append(dict(order_index=j, order_name=ORDER_NAMES[j], position=position,
                         start_min=start, completion_min=t, pickup_min=d[j], wait_min=waits[j]))
    metrics = dict(total_customer_wait=sum(waits), late_order_count=sum(w > 0 for w in waits),
                   max_customer_wait=max(waits, default=0))
    metrics.update({name + '_wait': waits[j] for j, name in enumerate(ORDER_NAMES)})
    if not all(isfinite(value) for value in metrics.values()):
        raise ValueError("nonfinite schedule result")
    return metrics, rows


def objective(problem, candidate):
    return details(problem, candidate)[0]['total_customer_wait']
