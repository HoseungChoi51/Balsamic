"""Deterministic one-candidate constructions; the host owns evaluation budgets."""
from .core import subset_dp, modified_due_date
from .objective import parameters
from .harness import deterministic

METHODS = {
    'oven_subset_dp': {'name': 'Subset dynamic programming', 'description': 'Last-job subset recurrence, smallest last-job ties.', 'hypothesis_id': 'hypothesis_pi_command_0b42ea54006b2c2a5b485550fad5b0f2', 'stochastic': False},
    'oven_mdd': {'name': 'Modified due date', 'description': 'Dynamic modified-due-date construction.', 'hypothesis_id': 'hypothesis_pi_command_e8ed11294c079e0ad59272cdc7964f46', 'stochastic': False},
}


def construct(name, problem):
    return (subset_dp if name == 'oven_subset_dp' else modified_due_date)(*parameters(problem))


@deterministic
def oven_subset_dp(problem, evaluate, rng):
    result = construct('oven_subset_dp', problem)
    evaluate(result['order'])
    return 'subset DP complete'


@deterministic
def oven_mdd(problem, evaluate, rng):
    evaluate(construct('oven_mdd', problem)['order'])
    return 'construction complete'
