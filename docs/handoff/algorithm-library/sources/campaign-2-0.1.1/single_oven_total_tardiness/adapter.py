"""Lazy Balsamic entry points; charter identity and metric directions are unchanged."""
from . import data


def _code():
    from . import objective, problem
    return problem, objective


def problem_adapter():
    from optimization_framework.problem_charter.library import CharterProblem, CharterEvaluator
    from optimization_framework.contracts.problems import Evaluation

    class OvenEvaluator(CharterEvaluator):
        def evaluate(self, candidate):
            from .objective import details
            # Strict validation occurs before charging this evaluator's diagnostic count.
            metrics, schedule = details(self.problem, candidate)
            result = Evaluation(objectives=metrics,
                constraints={c.name: True for c in self.instance.candidate_schema.constraints},
                metadata={'schedule': schedule, 'start_clock_min': self.problem.values.start_clock_min,
                          'metric_directions': {m.name: m.direction for m in self.instance.extra_metrics},
                          'metric_direction_caveat': 'Per-order wait metrics retain the charter-declared maximize directions; these are descriptive raw waits, not utility or tie breakers.'})
            self.evaluations += 1
            return result

    class OvenProblem(CharterProblem):
        def evaluator(self, instance):
            base = super().evaluator(instance)
            return OvenEvaluator(base.instance, base.problem, base.objective)

    return OvenProblem(data, _code)


def method_plugin():
    from optimization_framework.optimizers.functions import FunctionPlugin

    class Methods(FunctionPlugin):
        MODULE = 'single_oven_total_tardiness.methods'
        REPRESENTATIONS = [data.REPRESENTATION]

        def problem(self, instance):
            return problem_adapter().problem(instance)

        def create(self, name, instance, parameters, seed):
            from .optimizer import OneShot
            self.validate(name, instance, parameters)
            return OneShot(name, instance, self.problem(instance))

    return Methods()
