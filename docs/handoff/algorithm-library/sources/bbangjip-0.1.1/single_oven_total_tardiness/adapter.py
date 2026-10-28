"""Balsamic's way into this library: its problem and its methods, named by the entry points in pyproject.toml. Generated
by Balsamic.

`problem_adapter()` is the problem the charter declares: its id is the charter's problem id, its definition and
instances are what Balsamic's charter gives for the same values, and evaluating a candidate calls
`objective.objective(problem, candidate)`. `method_plugin()` offers the functions in `methods.py` as Balsamic methods,
each given this library's own `Problem`. Balsamic is imported only inside these functions, so `import single_oven_total_tardiness` works
without it; the library's own code (the objective, the problem, the methods) is imported only where a run evaluates.
"""
from __future__ import annotations

from . import data


def _code():
    """The library's problem module and objective module, for a worker that evaluates."""
    from . import objective, problem
    return problem, objective


def problem_adapter():
    """The `optimization_framework.problems` entry point: the charter's problem, evaluated by this library."""
    from optimization_framework.problem_charter.library import CharterProblem
    class ScheduledProblem(CharterProblem):
        def evaluator(self, instance):
            base = super().evaluator(instance)
            original = base.evaluate

            def evaluate(candidate):
                from .objective import schedule
                result = original(candidate)
                metrics = schedule(base.problem, candidate)
                metrics['baseline'] = schedule(base.problem, list(range(base.problem.dimensions)))
                return result.model_copy(update={'metadata': metrics})

            base.evaluate = evaluate
            return base

    return ScheduledProblem(data, _code)


def method_plugin():
    """The `optimization_framework.optimizers` entry point: the methods listed in METHODS."""
    from optimization_framework.optimizers.packaged import PackagedPlugin
    from . import subset_dp
    from .methods import METHODS

    class Methods(PackagedPlugin):
        REPRESENTATIONS = [data.REPRESENTATION]

        def validate(self, name, instance, parameters):
            if name not in self.METHODS or parameters:
                raise ValueError('unknown method or unsupported parameters')

    Methods.METHODS = {name: {**entry, 'module': subset_dp, 'stochastic': False,
                              'problem_ids': [data.PROBLEM_ID]}
                      for name, entry in METHODS.items()}
    return Methods()
