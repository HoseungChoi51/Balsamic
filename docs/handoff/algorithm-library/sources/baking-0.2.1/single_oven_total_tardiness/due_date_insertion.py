"""Constructive insertion only; no search on the completed order."""
from .common import inputs, partial_score, recalculate


def construct(p, d):
    """Yield (new job, chosen position, resulting prefix) for optional diagnostics."""
    p, d = inputs(p, d)
    order = []
    for j in sorted(range(len(p)), key=lambda j: (d[j], p[j], j)):
        trials = [order[:pos]+[j]+order[pos:] for pos in range(len(order)+1)]
        pos = min(range(len(trials)), key=lambda pos: partial_score(p, d, trials[pos]))
        order = trials[pos]
        yield j, pos, tuple(order)


def solve(p, d):
    p, d = inputs(p, d)
    order = ()
    for _, _, order in construct(p, d):
        pass
    return recalculate(p, d, order)


def create_optimizer(context):
    from .lifecycle import Optimizer
    return Optimizer(context, 'insertion')
