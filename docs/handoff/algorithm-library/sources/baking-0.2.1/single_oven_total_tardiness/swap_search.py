"""Bounded solve and public access to unchanged bundled NumPy search core."""
from ._swap_core import SwapSearch, moves, apply
from .common import inputs, recalculate


def solve(p, d, *, seed=0, evaluations=100):
    p, d = inputs(p, d)
    if type(evaluations) is not int or evaluations < 1:
        raise ValueError('evaluations must be a positive integer')
    search = SwapSearch(len(p), seed)
    for _ in range(evaluations):
        order = search.ask()
        result = recalculate(p, d, order)
        search.tell(order, -result.total_tardiness)
    return recalculate(p, d, search.best)


def create_optimizer(context):
    from .lifecycle import Optimizer
    return Optimizer(context, 'swap')
