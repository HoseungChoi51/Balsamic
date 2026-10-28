"""Problem, proposal, and trusted evaluation contracts (scalar objectives, v1)."""
from __future__ import annotations

import bisect
import math
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .base import Contract, content_hash

# How a method may reach the objective (decision 22): ``white_box`` lets it compute the objective itself from the
# problem's code, as often as it likes; ``oracle`` lets it reach the objective only through ``evaluate``.
Access = Literal["white_box", "oracle"]
# What a comparison charges a method for (decision 23). None is the default: ``worker_seconds`` on a fixed worker
# class, ``core_seconds`` (threads × wall time) when a method uses more than one thread.
CostAxis = Literal["worker_seconds", "core_seconds", "evaluations", "solver_calls"]


def without_unset(result: dict, *names: str) -> dict:
    """A dump without the named fields while they are None, so records made before they existed keep their digests."""
    for name in names:
        if result.get(name) is None:
            result.pop(name, None)
    return result


class ProblemSize(BaseModel):
    """Where an instance sits on its problem's size ladder (N14): a quantity whose value grows across the instances,
    such as the number of jobs. The comparison groups tasks by it and reports how methods scale."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    name: str = Field(min_length=1, max_length=64)
    value: float


class Objective(Contract):
    name: str
    direction: Literal["minimize", "maximize"]
    units: str = "dimensionless"

    def utility(self, value: float) -> float:
        """Frozen sign transform for maximization-only legacy optimizers."""
        if not math.isfinite(value):
            raise ValueError("An objective value must be finite")
        return value if self.direction == "maximize" else -value

    def better(self, left: float, right: float | None) -> bool:
        return right is None or self.utility(left) > self.utility(right)


class Constraint(Contract):
    """A public linear feasibility constraint; adapters can supply named checks."""
    name: str
    coefficients: list[float]
    relation: Literal["le", "ge", "eq"] = "le"
    bound: float
    tolerance: float = Field(default=1e-9, ge=0)

    def satisfied(self, values: list[float]) -> bool:
        total = sum(a * b for a, b in zip(self.coefficients, values, strict=True))
        if self.relation == "eq":
            return abs(total - self.bound) <= self.tolerance
        return total <= self.bound + self.tolerance if self.relation == "le" else total >= self.bound - self.tolerance


VARIABLE_NAME = r"^[a-z][a-z0-9_]{0,63}$"


class SchemaVariable(BaseModel):
    """A named part of the candidate (N9): ``size`` consecutive entries, in the order the variables are listed. A variable
    of one entry is a number in a design expression, a larger one a vector. ``values`` are the permitted values of its
    entries: in a discrete schema they take the place of the shared list, so each variable keeps its own; in a
    continuous schema they are a grid within its bounds (a whole number of fins), and ``canonicalize`` takes the nearest
    one, the rounding a declared evaluator used to do itself."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    name: str = Field(pattern=VARIABLE_NAME)
    size: int = Field(ge=1, le=1000000)
    values: list[float] = Field(default_factory=list, max_length=1000)

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        if not self.values:
            result.pop("values", None)
        return result


class DesignConstraint(BaseModel):
    """A condition on the candidate's variables by name (N9): a true/false expression in the charter's expression
    language, with its vector functions (``sum``, ``min``, ``max``, ``count``, ``at``, ``diff``, ``all``, ``any``).
    ``constants`` are the charter's quantities it reads, at this instance. A candidate that breaks it is not feasible:
    ``canonicalize`` refuses it, as it refuses one that breaks a linear constraint."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    name: str = Field(min_length=1, max_length=64)
    expression: str = Field(min_length=1, max_length=1000)
    constants: dict[str, float | int | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def readable(self):
        from optimization_framework.problem_charter.expressions import ExpressionError, names
        try:
            names(self.expression)
        except ExpressionError as exc:
            raise ValueError(f"Design constraint {self.name}: {exc}") from None
        return self

    def names(self) -> set[str]:
        from optimization_framework.problem_charter.expressions import names
        return names(self.expression)

    def failure(self, named: dict) -> str | None:
        """None when the named candidate meets the condition, else why not."""
        from optimization_framework.problem_charter.expressions import ExpressionError, evaluate
        try:
            result = evaluate(self.expression, {**self.constants, **named})
        except ExpressionError as exc:
            return f"{self.name} ({exc})"
        if not isinstance(result, bool):
            return f"{self.name} (it does not give one true or false)"
        return None if result else self.name


class OutcomeConstraint(DesignConstraint):
    """A condition on what the evaluator measured (N10): a true/false expression over the objective and the metrics it
    reports, by name, and number quantities (``constants``). A floor on a second metric, a cap on a measured cost. An
    observation that breaks it is infeasible: it is kept, but it never counts as a run's best."""

    def failure(self, named: dict) -> str | None:
        missing = sorted(self.names() - set(self.constants) - set(named))
        if missing:
            return f"{self.name} (the evaluator did not report {', '.join(missing)})"
        return super().failure(named)


class CandidateSchema(Contract):
    """A permutation candidate is an order of the items 0 … dimensions−1 (indices into the instance's data), each exactly once.

    ``variables`` name the parts of the candidate and may give each its own permitted values; ``design`` holds the
    conditions on them (N9). Both are left out of the dump while empty, so schemas made before them keep their digests."""
    representation: Literal["binary", "discrete", "continuous", "permutation"]
    dimensions: int = Field(ge=1, le=1000000)
    bounds: list[tuple[float, float]] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    variables: list[SchemaVariable] = Field(default_factory=list, max_length=100)
    design: list[DesignConstraint] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_domain(self):
        if self.representation == "continuous":
            if len(self.bounds) != self.dimensions or any(a >= b for a, b in self.bounds):
                raise ValueError("Continuous candidates need one finite increasing bound per dimension")
        if self.representation == "permutation" and (self.bounds or self.values or self.constraints):
            raise ValueError("Permutation candidates take no bounds, permitted values or linear constraints")
        if any(len(c.coefficients) != self.dimensions for c in self.constraints):
            raise ValueError("Constraint dimension does not match candidate schema")
        if self.variables:
            if sum(variable.size for variable in self.variables) != self.dimensions:
                raise ValueError("The candidate's variables must add up to its dimensions")
            if len({variable.name for variable in self.variables}) != len(self.variables):
                raise ValueError("Each candidate variable needs a distinct name")
            graded = [variable.name for variable in self.variables if variable.values]
            if graded and self.representation in {"binary", "permutation"}:
                raise ValueError(f"{self.representation.capitalize()} candidates take no permitted values: {', '.join(graded)}")
        if self.representation == "discrete" and not self.values and not (
                self.variables and all(variable.values for variable in self.variables)):
            raise ValueError("Discrete candidates require permitted values")
        if self.representation == "continuous":
            for offset, variable in self._parts():
                if variable.values and any(not all(lo <= value <= hi for value in variable.values)
                                           for lo, hi in self.bounds[offset:offset + variable.size]):
                    raise ValueError(f"The permitted values of {variable.name} must lie within its bounds")
        if self.design:
            if not self.variables:
                raise ValueError("Design constraints need the candidate's variables by name")
            known = {variable.name for variable in self.variables}
            for constraint in self.design:
                read = constraint.names()
                unknown = sorted(read - known - set(constraint.constants))
                if unknown:
                    raise ValueError(f"Design constraint {constraint.name} reads {', '.join(unknown)}, which are not "
                                     "variables of the candidate")
                if not read & known:
                    raise ValueError(f"Design constraint {constraint.name} reads no variable of the candidate")
        names = [c.name for c in self.constraints] + [c.name for c in self.design]
        if len(set(names)) != len(names):
            raise ValueError("Constraint names must be distinct")
        return self

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        for name in ("variables", "design"):
            if not getattr(self, name):
                result.pop(name, None)
        return result

    @property
    def restricted(self) -> bool:
        """The schema has explicit feasibility conditions: linear or design constraints."""
        return bool(self.constraints or self.design)

    def _parts(self):
        offset = 0
        for variable in self.variables:
            yield offset, variable
            offset += variable.size

    def domains(self) -> list[tuple[int, int, list[float]]]:
        """``(offset, size, permitted values)`` for each run of entries; the values are empty where the representation
        alone says what an entry may be (binary, permutation, a continuous entry without a grid)."""
        shared = list(self.values) if self.representation == "discrete" else []
        if not self.variables:
            return [(0, self.dimensions, shared)]
        return [(offset, variable.size, list(variable.values) or shared) for offset, variable in self._parts()]

    def element_values(self) -> list[list[float]]:
        """Each entry's permitted values: 0 and 1 for binary, the variable's own or the shared list for discrete, a
        continuous entry's grid. Empty for an entry with no list (continuous without a grid, permutation)."""
        if self.representation == "binary":
            return [[0, 1]] * self.dimensions
        out = []
        for _, size, values in self.domains():
            out.extend([values] * size)
        return out

    def named(self, candidate: list) -> dict[str, Any]:
        """The candidate by variable name: a number for a variable of one entry, a list otherwise."""
        return {variable.name: candidate[offset] if variable.size == 1 else list(candidate[offset:offset + variable.size])
                for offset, variable in self._parts()}

    def design_failures(self, candidate: list) -> list[str]:
        """The design constraints a candidate (already in the schema's domain) breaks, each with why."""
        if not self.design:
            return []
        named = self.named(candidate)
        return [failure for constraint in self.design if (failure := constraint.failure(named)) is not None]

    def feasible(self, candidate: Any) -> bool:
        """Whether ``canonicalize`` accepts the candidate: a method's check for its own proposals."""
        try:
            self.canonicalize(candidate)
        except ValueError:
            return False
        return True

    def canonicalize(self, candidate: Any) -> list[int | float]:
        if hasattr(candidate, "tolist"):
            candidate = candidate.tolist()
        if not isinstance(candidate, (list, tuple)) or len(candidate) != self.dimensions:
            raise ValueError(f"Candidate must be a vector of length {self.dimensions}")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in candidate):
            raise ValueError("Candidate entries must be finite numbers")
        if self.representation == "binary":
            if any(x not in (0, 1) for x in candidate):
                raise ValueError("Candidate entries must be binary 0 or 1")
            result = [int(x) for x in candidate]
        elif self.representation == "discrete":
            for offset, size, values in self.domains():
                permitted = set(values)
                if any(x not in permitted for x in candidate[offset:offset + size]):
                    raise ValueError("Candidate contains a value outside the declared discrete domain"
                                     + (f" of {self._name_at(offset)}" if self.variables else ""))
            result = list(candidate)
        elif self.representation == "permutation":
            if any(x != int(x) for x in candidate) or sorted(int(x) for x in candidate) != list(range(self.dimensions)):
                raise ValueError(f"Candidate must be an order of the items 0 to {self.dimensions - 1}, each exactly once")
            result = [int(x) for x in candidate]
        else:
            if any(x < lo or x > hi for x, (lo, hi) in zip(candidate, self.bounds, strict=True)):
                raise ValueError("Candidate is outside the declared bounds")
            result = [float(x) for x in candidate]
            for offset, size, values in self.domains():
                if values:
                    grid = sorted(values)
                    result[offset:offset + size] = [nearest(grid, x) for x in result[offset:offset + size]]
        failed = [c.name for c in self.constraints if not c.satisfied(result)] + self.design_failures(result)
        if failed:
            raise ValueError("Candidate violates constraints: " + ", ".join(failed))
        return result

    def _name_at(self, offset: int) -> str:
        return next(variable.name for start, variable in self._parts() if start == offset)


def nearest(grid: list[float], x: float) -> float:
    """The value of a sorted grid nearest to x; the lower one on a tie."""
    index = bisect.bisect_left(grid, x)
    if index == 0:
        return float(grid[0])
    if index == len(grid):
        return float(grid[-1])
    below, above = grid[index - 1], grid[index]
    return float(below if x - below <= above - x else above)


class PromotionCheck(Contract):
    """A validation recipe, with the parameters it must have run with, that a score passes before it counts for promotion."""
    recipe_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProblemDefinition(Contract):
    id: str
    version: str
    name: str
    evaluator_id: str
    evaluator_version: str
    configuration_schema: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    fidelity_schema: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=lambda: {"cpu_threads": 1})
    validation_recipes: list[str] = Field(default_factory=list)
    recipe_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    renderer: str | None = None
    # Choosing a finalist and publishing to the library need these checks on the score (roadmap V3); none leaves the gate open.
    promotion_validation: list[PromotionCheck] = Field(default_factory=list)
    # None: not declared here; the problem's pack may declare it, else it is white_box (decision 22).
    access: Access | None = None
    cost_axis: CostAxis | None = None

    @model_validator(mode="after")
    def declared_promotion_recipes(self):
        if set(check.recipe_id for check in self.promotion_validation) - set(self.validation_recipes):
            raise ValueError("A promotion check must name one of the problem's validation recipes")
        return self

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        if not self.promotion_validation:
            result.pop("promotion_validation", None)
        return without_unset(result, "access", "cost_axis")


class ProblemInstance(Contract):
    definition_id: str
    definition_version: str
    evaluator_id: str
    evaluator_version: str
    configuration: dict[str, Any]
    candidate_schema: CandidateSchema
    primary_objective: Objective
    extra_metrics: list[Objective] = Field(default_factory=list)
    public_descriptor: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    fidelity: dict[str, Any] = Field(default_factory=dict)
    scientific_identity: str
    # Conditions on the measured objectives (N10); left out of the dump while empty, so older instances keep their digests.
    # They decide which observations count, not what an evaluation computes: the evaluation identity leaves them out.
    outcomes: list[OutcomeConstraint] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def distinct_outcomes(self):
        names = [c.name for c in self.outcomes]
        if len(set(names)) != len(names):
            raise ValueError("Outcome constraint names must be distinct")
        return self

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        if not self.outcomes:
            result.pop("outcomes", None)
        return result

    def same_evaluation(self, other: "ProblemInstance") -> bool:
        """Whether an adapter resolves the same problem: equal but for the outcome constraints, which a charter adds to an
        installed problem's instance and which decide only which observations count (N10)."""
        return self.model_copy(update={"outcomes": []}) == other.model_copy(update={"outcomes": []})

    def outcome_checks(self, objectives: dict[str, float]) -> dict[str, str | None]:
        """Each outcome constraint on a measured observation: None when it holds, else why not."""
        return {constraint.name: constraint.failure(dict(objectives)) for constraint in self.outcomes}

    def outcome_failures(self, objectives: dict[str, float]) -> list[str]:
        """The outcome constraints a measured observation breaks, each with why; empty when it is feasible."""
        return [failure for failure in self.outcome_checks(objectives).values() if failure is not None]

    @property
    def evaluation_identity(self) -> str:
        return content_hash({"instance": self.scientific_identity, "fidelity": self.fidelity,
                             "evaluator": [self.evaluator_id, self.evaluator_version]})

    def descriptor(self) -> dict:
        """Only declared public information is sent to optimizer packages."""
        return {"scientific_identity": self.scientific_identity,
                "candidate_schema": self.candidate_schema.model_dump(mode="json"),
                "primary_objective": self.primary_objective.model_dump(mode="json"),
                "capabilities": self.capabilities, "public": self.public_descriptor}


class Proposal(Contract):
    id: str
    candidate: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evaluation(Contract):
    objectives: dict[str, float]
    constraints: dict[str, bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    solver_executions: int = Field(default=1, ge=0)
    cache_hit: bool = False


class Observation(Contract):
    id: str
    experiment_id: str
    attempt_id: str
    request_id: str
    proposal_id: str
    candidate: Any
    status: Literal["ok", "invalid_candidate", "evaluation_failed", "uncertain"]
    objectives: dict[str, float] = Field(default_factory=dict)
    constraints: dict[str, bool] = Field(default_factory=dict)
    fidelity: dict[str, Any] = Field(default_factory=dict)
    evaluator_identity: str
    costs: dict[str, float | None] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class Evaluator(Protocol):
    def evaluate(self, candidate: list[int | float]) -> Evaluation: ...
    def checkpoint(self) -> dict: ...
    def restore(self, state: dict) -> None: ...


class ProblemAdapter(Protocol):
    def describe(self) -> ProblemDefinition: ...
    def resolve(self, configuration: dict, fidelity: dict | None = None) -> ProblemInstance: ...
    def evaluator(self, instance: ProblemInstance) -> Evaluator: ...
