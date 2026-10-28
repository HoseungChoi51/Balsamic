"""Independent recalculation facade; not a registered campaign evaluator."""
from .common import recalculate


def objective(p, d, order):
    return recalculate(p, d, order).total_tardiness
