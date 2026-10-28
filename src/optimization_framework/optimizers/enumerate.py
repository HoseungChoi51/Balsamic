"""Built-in ``enumerate`` (N13): every candidate of a binary, discrete or permutation problem, in a fixed order.

It is the exact baseline every problem small enough has, and the check of other methods' claims of optimality. The
order is lexicographic (``itertools.product`` over the values, ``itertools.permutations`` of the items), infeasible
candidates are skipped, and a problem with more than ``max_candidates`` (default 10⁶) is refused with its count. On an
oracle problem every feasible candidate is one evaluation. On a white-box problem (N11) it enumerates through
``problem.objective`` and records only the optimum, with one evaluation. Once it has seen every candidate it reports the
optimum as its ``bound`` with ``proved_optimal`` and finishes (A3).
"""
from itertools import islice, permutations, product
import math

MAX_CANDIDATES = 10**6


def count(schema):
    if schema.representation == "binary":
        return 2 ** schema.dimensions
    if schema.representation == "discrete":   # each entry its own variable's values (N9), else the shared list
        return math.prod(len(values) for values in schema.element_values())
    if schema.representation == "permutation":
        return math.factorial(schema.dimensions)
    return None


def refusal(schema, parameters):
    """Why this problem is too large to enumerate, with its count; None when it is not."""
    cap = parameters.get("max_candidates", MAX_CANDIDATES)
    total = count(schema)
    if total is not None and total > cap:
        return (f"enumerate would visit {total:,} candidates, more than max_candidates ({cap:,}); "
                "enumerate a smaller instance, or raise max_candidates if the time allows")
    return None


class Enumeration:
    def __init__(self, schema, objective, parameters):
        if (reason := refusal(schema, parameters)) is not None:
            raise ValueError(reason)
        self.schema, self.objective = schema, objective
        self.total = count(schema)
        self.index = 0                      # candidates taken from the order so far
        self.best, self.best_value = None, None
        self.white_box = None               # problem.objective on a white-box problem
        self.proposed = False               # white box: the optimum has been sent for its one evaluation
        self.finished = False
        self._order = None

    def open_objective(self, objective):
        self.white_box = objective

    def _candidates(self):
        if self._order is None:
            n = self.schema.dimensions
            order = (permutations(range(n)) if self.schema.representation == "permutation"
                     else product(*self.schema.element_values()))
            self._order = islice(order, self.index, None)
        return self._order

    def _feasible(self):
        """The next feasible candidate of the order, or None once every one has been taken."""
        for candidate in self._candidates():
            self.index += 1
            try:
                return self.schema.canonicalize(list(candidate))
            except ValueError:
                continue
        return None

    def _finish(self):
        self.finished = True
        if self.best is None:
            raise StopIteration("No candidate of the problem is feasible")
        raise StopIteration(f"Enumerated all {self.total:,} candidates; the optimum is proved")

    def ask(self):
        if self.finished:
            self._finish()
        if self.white_box is None:
            candidate = self._feasible()
            if candidate is None:
                self._finish()
            return candidate
        if self.proposed:
            self._finish()
        while (candidate := self._feasible()) is not None:
            try:
                value = float(self.white_box(candidate))
            except ValueError:
                continue
            if math.isfinite(value) and self.objective.better(value, self.best_value):
                self.best, self.best_value = candidate, value
        if self.best is None:
            self._finish()
        self.proposed = True
        return list(self.best)

    def tell(self, candidate, utility):
        value = utility if self.objective.direction == "maximize" else -utility
        if self.white_box is not None:
            self.best_value = float(value)   # the recorded evaluation of the optimum is the value it proves
            return
        if self.objective.better(value, self.best_value):
            self.best, self.best_value = candidate.tolist() if hasattr(candidate, "tolist") else list(candidate), float(value)

    def diagnostics(self):
        done = self.finished and self.best is not None
        return {"decisions": self.index, "enumerated": self.index, "candidates": self.total,
                **({"bound": self.best_value, "proved_optimal": True} if done else {})}

    def state_dict(self):
        return {"index": self.index, "best": self.best, "best_value": self.best_value, "proposed": self.proposed, "finished": self.finished}

    def load_state_dict(self, state):
        self.index, self.best, self.best_value = state["index"], state["best"], state["best_value"]
        self.proposed, self.finished = state["proposed"], state["finished"]
        self._order = None
