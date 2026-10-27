"""Deterministic benchmark instances: bounded quadratic and Rosenbrock minimization, and the lead evals' trap problems
(`fidelity_trap`, whose cheap fidelity shows a peak the fine one does not have, and `knapsack_dp`, a 0/1 knapsack a dynamic
program solves exactly)."""
from __future__ import annotations

import math
import random
from types import SimpleNamespace
from typing import Literal

from pydantic import Field, model_validator

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.contracts.problems import (CandidateSchema, Constraint, Evaluation,
    Objective, ProblemDefinition, ProblemInstance)


class BenchmarkConfig(Contract):
    function: Literal["quadratic", "rosenbrock"] = "quadratic"
    dimensions: int = Field(default=2, ge=1, le=10000)
    bounds: list[tuple[float, float]] = Field(default_factory=list)
    center: list[float] = Field(default_factory=list)
    weights: list[float] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)

    @model_validator(mode="after")
    def dimensions_match(self):
        if self.function == "rosenbrock" and self.dimensions < 2:
            raise ValueError("Rosenbrock requires at least two dimensions")
        for values in (self.bounds, self.center, self.weights):
            if values and len(values) != self.dimensions:
                raise ValueError("Configuration vectors must match dimensions")
        if any(x <= 0 for x in self.weights):
            raise ValueError("Quadratic weights must be positive")
        return self


class ContinuousProblem:
    def study_templates(self):
        from .templates import registered
        return registered()

    def describe(self):
        return ProblemDefinition(id="bounded_continuous", version="1", name="Bounded continuous benchmarks",
            evaluator_id="analytic_scalar", evaluator_version="1", configuration_schema=BenchmarkConfig.model_json_schema(),
            capabilities=["continuous", "scalar_objective", "linear_constraints"],
            validation_recipes=["analytic_fixtures:v1"], renderer="continuous",
            recipe_schemas={"analytic_fixtures:v1": {"title": "Known-value evaluator fixtures", "assertion_kind": "evaluator_correctness", "type": "object", "properties": {
                "tolerance": {"title": "Absolute tolerance", "type": "number", "default": 1e-12, "exclusiveMinimum": 0, "maximum": 1e-6}}}})

    def resolve(self, configuration, fidelity=None):
        if fidelity:
            raise ValueError("Analytic benchmarks do not have approximate fidelity settings")
        config = BenchmarkConfig(**configuration)
        values = config.model_dump(mode="json", exclude={"schema_version"})
        values["bounds"] = values["bounds"] or [[-5., 5.]] * config.dimensions
        values["center"] = values["center"] or [0.] * config.dimensions
        values["weights"] = values["weights"] or [1.] * config.dimensions
        schema = CandidateSchema(representation="continuous", dimensions=config.dimensions,
            bounds=values["bounds"], constraints=config.constraints)
        definition = self.describe()
        objective = Objective(name="value", direction="minimize")
        return ProblemInstance(definition_id=definition.id, definition_version=definition.version,
            evaluator_id=definition.evaluator_id, evaluator_version=definition.evaluator_version,
            configuration=values, candidate_schema=schema, primary_objective=objective,
            public_descriptor={"function": config.function, "dimensions": config.dimensions},
            capabilities=definition.capabilities, fidelity={},
            scientific_identity=content_hash({"definition": definition.id, "configuration": values, "objective": objective.model_dump()}))

    def evaluator(self, instance):
        return AnalyticEvaluator(instance)

    def implementation_fixture(self, configuration, dimensions):
        return self.resolve({**configuration, "dimensions": dimensions})

    def plan_recipe(self, instance, recipe_id, parameters, subjects):
        if recipe_id != "analytic_fixtures:v1":
            raise ValueError("Unknown analytic benchmark recipe")
        if set(parameters) - {"tolerance"}:
            raise ValueError("Analytic fixtures accept only an absolute tolerance")
        import math
        tolerance = parameters.get("tolerance", 1e-12)
        if type(tolerance) not in {int, float} or not math.isfinite(tolerance) or not 0 < tolerance <= 1e-6:
            raise ValueError("Fixture tolerance must be positive and at most 1e-6")
        config = instance.configuration
        if config["function"] == "quadratic":
            fixtures = [(config["center"], 0.)]
            for index in range(min(4, len(config["center"]))):
                for offset in (-1., 1.):
                    candidate = list(config["center"])
                    candidate[index] += offset
                    fixtures.append((candidate, config["weights"][index]))
        else:
            size = instance.candidate_schema.dimensions
            fixtures = [([1.] * size, 0.), ([0.] * size, float(size - 1))]
        cases = []
        for candidate, expected in fixtures:
            try:
                candidate = instance.candidate_schema.canonicalize(candidate)
            except ValueError:
                continue
            cases.append({"candidate": candidate, "problem": instance.model_dump(mode="json"),
                          "expected_value": expected, "tolerance": tolerance})
        if not cases:
            raise ValueError("No registered analytic fixture is feasible in this instance; a compatible evaluator check is required")
        return {"cases": cases, "subjects": [], "validation_rule": {"kind": "evaluator_correctness", "subject": "evaluator",
            "evidence_requirements": ["Every admissible registered known-value fixture satisfies the declared tolerance"]}}

    def summarize_recipe(self, recipe, observations):
        rows = [{"candidate": case["candidate"], "expected_value": case["expected_value"],
                 "observed_value": observed["objectives"]["value"],
                 "absolute_error": abs(observed["objectives"]["value"] - case["expected_value"]),
                 "tolerance": case["tolerance"], "observation_id": observed["id"]}
                for case, observed in zip(recipe["cases"], observations)]
        complete = len(rows) == len(recipe["cases"])
        passed = complete and all(row["absolute_error"] <= row["tolerance"] for row in rows)
        return {"kind": "evaluator_correctness", "recipe_id": recipe["recipe_id"], "complete": complete, "measurements": rows,
                "verdict": "passed" if passed else "failed" if complete else "inconclusive",
                "rationale": "Registered analytic fixtures agree." if passed else "The declared analytic fixture checks have not passed.",
                "limitations": "These finite fixtures check evaluator behavior; they do not establish optimizer effectiveness."}


class AnalyticEvaluator:
    def __init__(self, instance):
        self.instance = instance
        self.requests = self.solves = self.hits = 0
        self.cache = {}

    def evaluate(self, candidate):
        x = self.instance.candidate_schema.canonicalize(candidate)
        key = content_hash(x)
        self.requests += 1
        hit = key in self.cache
        if hit:
            self.hits += 1
            value = self.cache[key]
        else:
            self.solves += 1
            value = self.cache[key] = self.value(x)
        return Evaluation(objectives={self.instance.primary_objective.name: value}, solver_executions=int(not hit), cache_hit=hit,
                          constraints={c.name: True for c in self.instance.candidate_schema.constraints})

    def value(self, x):
        config = self.instance.configuration
        if config["function"] == "quadratic":
            return sum(w * (v - c)**2 for w, v, c in zip(config["weights"], x, config["center"], strict=True))
        return sum(100 * (b - a*a)**2 + (1-a)**2 for a, b in zip(x[:-1], x[1:]))

    def checkpoint(self):
        return {"identity": self.instance.evaluation_identity, "requests": self.requests,
                "solves": self.solves, "hits": self.hits, "cache": self.cache.copy()}

    def restore(self, state):
        if state["identity"] != self.instance.evaluation_identity:
            raise ValueError("Evaluator checkpoint belongs to a different instance or version")
        self.requests, self.solves, self.hits = state["requests"], state["solves"], state["hits"]
        self.cache = state["cache"].copy()


class FidelityTrapConfig(Contract):
    """The trap has one shape; the configuration only states it."""


# A broad hill, the same at both resolutions, and a narrow peak that only the coarse resolution shows (an aliasing artefact):
# the coarse optimum scores well above the true one and collapses when it is evaluated finely.
HILL, HILL_HEIGHT, HILL_WIDTH = (0.3, 0.3), 0.6, 0.25
SPURIOUS, SPURIOUS_HEIGHT, SPURIOUS_WIDTH = (0.8, 0.75), 0.9, 0.06
RESOLUTIONS = ("coarse", "fine")


def bump(x, centre, height, width):
    return height * math.exp(-sum((a - b)**2 for a, b in zip(x, centre)) / (2 * width**2))


class FidelityTrapProblem:
    """Lead-eval trap S13: a deterministic two-dimensional maximisation whose cheap `coarse` resolution (the default) has a
    narrow spurious peak that `fine` does not have. It declares the generic `fidelity_comparison:v1` recipe."""
    RECIPE = "fidelity_comparison:v1"
    # What the generic recipes ask of a commissioned evaluator's manifest: this evaluator is deterministic.
    manifest = SimpleNamespace(deterministic=True)

    def describe(self):
        from optimization_framework.evaluation.registered_recipes import FidelityComparison
        descriptor = FidelityComparison().describe()
        schema = {**descriptor.parameter_schema, "title": descriptor.title, "assertion_kind": descriptor.assertion_kind}
        schema["properties"] = {**schema["properties"], "fidelities": {**schema["properties"]["fidelities"],
                                "default": [{"resolution": name} for name in RESOLUTIONS]}}
        return ProblemDefinition(id="fidelity_trap", version="1", name="Fidelity trap (lead evals)",
            evaluator_id="fidelity_trap", evaluator_version="1", configuration_schema=FidelityTrapConfig.model_json_schema(),
            capabilities=["continuous", "scalar_objective"],
            fidelity_schema={"type": "object", "properties": {"resolution": {"type": "string", "enum": list(RESOLUTIONS), "default": "coarse"}}},
            validation_recipes=[self.RECIPE], recipe_schemas={self.RECIPE: schema}, renderer="continuous")

    def resolve(self, configuration, fidelity=None):
        FidelityTrapConfig(**configuration)
        settings = dict(fidelity or {})
        if set(settings) - {"resolution"} or settings.get("resolution", "coarse") not in RESOLUTIONS:
            raise ValueError("The fidelity trap's fidelity is resolution: coarse or fine")
        definition = self.describe()
        objective = Objective(name="value", direction="maximize")
        return ProblemInstance(definition_id=definition.id, definition_version=definition.version,
            evaluator_id=definition.evaluator_id, evaluator_version=definition.evaluator_version, configuration={},
            candidate_schema=CandidateSchema(representation="continuous", dimensions=2, bounds=[[0., 1.]] * 2), primary_objective=objective,
            public_descriptor={"dimensions": 2, "fidelity": "resolution: coarse (cheap, the default) or fine"},
            capabilities=definition.capabilities, fidelity={"resolution": settings.get("resolution", "coarse")},
            scientific_identity=content_hash({"definition": definition.id, "objective": objective.model_dump()}))

    def evaluator(self, instance):
        return FidelityTrapEvaluator(instance)

    def implementation_fixture(self, configuration, dimensions):
        return self.resolve(configuration)

    def recipe_parameters(self, instance, recipe_id, parameters):
        from optimization_framework.evaluation.registered_recipes import FidelityComparison
        return FidelityComparison().parameters(self, instance, parameters)

    def plan_recipe(self, instance, recipe_id, parameters, subjects):
        from optimization_framework.evaluation.registered_recipes import FidelityComparison
        return FidelityComparison().plan(self, instance, parameters, subjects)

    def summarize_recipe(self, recipe, observations):
        from optimization_framework.evaluation.registered_recipes import FidelityComparison
        return {"kind": "solution_fidelity", "recipe_id": recipe["recipe_id"], **FidelityComparison().summarize(recipe, observations)}


class FidelityTrapEvaluator(AnalyticEvaluator):
    def value(self, x):
        hill = bump(x, HILL, HILL_HEIGHT, HILL_WIDTH)
        return hill + bump(x, SPURIOUS, SPURIOUS_HEIGHT, SPURIOUS_WIDTH) if self.instance.fidelity["resolution"] == "coarse" else hill


class KnapsackConfig(Contract):
    items: int = Field(default=200, ge=2, le=2000)
    capacity: int = Field(default=1000, ge=1)
    seed: int = Field(default=0, ge=0)


def knapsack_items(items, seed):
    """(weights, values): integer weights 5-30, each value its weight plus 0-10, so the value-to-weight ratios are close and
    filling by the best ratio stops short of the optimum."""
    rng = random.Random(seed)
    weights = [rng.randint(5, 30) for _ in range(items)]
    return weights, [weight + rng.randint(0, 10) for weight in weights]


class KnapsackProblem:
    """Lead-eval trap S17: a 0/1 knapsack (binary, one linear capacity constraint, integer weights), which a dynamic program
    over the capacity solves exactly and fast. Nobody has to say so: the problem's class is the clue."""
    def describe(self):
        return ProblemDefinition(id="knapsack_dp", version="1", name="0/1 knapsack",
            evaluator_id="knapsack_value", evaluator_version="1", configuration_schema=KnapsackConfig.model_json_schema(),
            capabilities=["binary", "scalar_objective", "linear_constraints"])

    def resolve(self, configuration, fidelity=None):
        if fidelity:
            raise ValueError("The knapsack has no fidelity settings")
        config = KnapsackConfig(**configuration)
        weights, values = knapsack_items(config.items, config.seed)
        resolved = {"items": config.items, "capacity": config.capacity, "seed": config.seed, "weights": weights, "values": values}
        definition = self.describe()
        objective = Objective(name="value", direction="maximize")
        return ProblemInstance(definition_id=definition.id, definition_version=definition.version,
            evaluator_id=definition.evaluator_id, evaluator_version=definition.evaluator_version, configuration=resolved,
            candidate_schema=CandidateSchema(representation="binary", dimensions=config.items,
                constraints=[Constraint(name="capacity", coefficients=weights, bound=config.capacity)]),
            primary_objective=objective,
            public_descriptor={"items": config.items, "capacity": config.capacity, "weights": weights, "values": values,
                               "objective": "the total value of the chosen items; their total weight is at most the capacity"},
            capabilities=definition.capabilities,
            scientific_identity=content_hash({"definition": definition.id, "configuration": resolved, "objective": objective.model_dump()}))

    def evaluator(self, instance):
        return KnapsackEvaluator(instance)

    def implementation_fixture(self, configuration, dimensions):
        return self.resolve({**configuration, "items": dimensions})


class KnapsackEvaluator(AnalyticEvaluator):
    def value(self, x):
        return float(sum(value for value, chosen in zip(self.instance.configuration["values"], x) if chosen))
