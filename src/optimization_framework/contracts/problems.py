"""Problem, proposal, and trusted evaluation contracts (scalar objectives, v1)."""
from __future__ import annotations

import bisect
import json
import math
import re
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


PROBLEM_ID = r"^[a-z][a-z0-9_]{1,99}$"


class Structure(BaseModel):
    """A candidate the problem's own code owns (N12): a JSON value (an order per machine, several orders, a sequence of
    variable length, a graph) that the problem's library canonicalizes and checks. ``owner`` is the problem's id; the
    library registers its rules under it (``register_structure``). ``meaning`` and ``layout`` say, in prose, what the
    value is and how it is laid out; ``fields`` are the names the library derives from a candidate (``fields()``), which
    design constraints may read; ``context`` is the instance's public configuration, which the rules are given."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    owner: str = Field(pattern=PROBLEM_ID)
    meaning: str = Field(min_length=1, max_length=500)
    layout: str = Field(min_length=1, max_length=300)
    fields: list[str] = Field(default_factory=list, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def field_names(self):
        bad = [name for name in self.fields if not re.fullmatch(VARIABLE_NAME, name)]
        if bad or len(set(self.fields)) != len(self.fields):
            raise ValueError("A structure's fields need distinct names of lowercase letters, digits and _")
        return self

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        for name in ("fields", "context"):
            if not getattr(self, name):
                result.pop(name, None)
        return result


@runtime_checkable
class StructureRules(Protocol):
    """What a problem's library provides for its ``structured`` candidates (N12). ``context`` is the instance's public
    configuration. ``canonicalize`` gives the one form of a candidate (raising ``ValueError`` if it cannot read it);
    ``is_valid`` the rules a canonical candidate breaks, empty when it breaks none. ``describe(candidate, context)`` (a
    line for pages) and ``fields(candidate, context)`` (named numbers or vectors for design constraints) are optional."""
    def canonicalize(self, candidate: Any, context: dict) -> Any: ...
    def is_valid(self, candidate: Any, context: dict) -> list[str]: ...


_STRUCTURES: dict[str, StructureRules] = {}


def register_structure(owner: str, rules: StructureRules) -> None:
    """Make a problem's rules for its structured candidates known in this process; the last registration wins."""
    if not callable(getattr(rules, "canonicalize", None)) or not callable(getattr(rules, "is_valid", None)):
        raise ValueError(f"The rules of {owner} need canonicalize(candidate, context) and is_valid(candidate, context)")
    _STRUCTURES[owner] = rules


def structure_rules(owner: str) -> StructureRules:
    """The registered rules of a problem's structured candidates. A problem not registered in this process is looked up
    among the installed problems, whose adapter registers its rules when asked (``structure()``)."""
    if owner not in _STRUCTURES:
        try:
            from optimization_framework.evaluation.registry import problems
            adapter = problems.get(owner) if owner in problems.ids() else None
        except Exception:   # noqa: BLE001 - a registry that cannot load says only that the rules are not here
            adapter = None
        if adapter is not None and callable(getattr(adapter, "structure", None)):
            register_structure(owner, adapter.structure())
    if owner not in _STRUCTURES:
        raise ValueError(f"The candidates of {owner} are structured, and its library's rules for them are not loaded here; "
                         "the problem's library checks them")
    return _STRUCTURES[owner]


def json_value(value: Any, what: str = "Candidate") -> Any:
    """``value`` as plain JSON data (arrays and tuples become lists, numpy scalars Python numbers), or ValueError."""
    def plain(item):
        if hasattr(item, "tolist"):
            return item.tolist()
        raise TypeError(f"{type(item).__name__} is not JSON")
    try:
        return json.loads(json.dumps(plain(value) if hasattr(value, "tolist") else value, allow_nan=False, default=plain))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be a JSON value of finite numbers, strings, lists and objects ({exc})") from None


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
    conditions on them (N9). Both are left out of the dump while empty, so schemas made before them keep their digests.

    A ``structured`` candidate (N12) is one JSON value whose rules the problem's library owns (``structure``): the schema
    stores and hashes the value the library canonicalizes and checks nothing else, beyond its design constraints over the
    fields the library names. Its dimensions are 1."""
    representation: Literal["binary", "discrete", "continuous", "permutation", "structured"]
    dimensions: int = Field(ge=1, le=1000000)
    bounds: list[tuple[float, float]] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    variables: list[SchemaVariable] = Field(default_factory=list, max_length=100)
    design: list[DesignConstraint] = Field(default_factory=list, max_length=100)
    structure: Structure | None = None

    @model_validator(mode="after")
    def valid_domain(self):
        if (self.representation == "structured") != (self.structure is not None):
            raise ValueError("A structured candidate, and only one, names the structure its problem owns")
        if self.representation == "structured":
            if self.dimensions != 1 or self.bounds or self.values or self.constraints or self.variables:
                raise ValueError("A structured candidate is one value: it takes no bounds, permitted values, linear "
                                 "constraints or variables")
            known = set(self.structure.fields)
            for constraint in self.design:
                read = constraint.names()
                if unknown := sorted(read - known - set(constraint.constants)):
                    raise ValueError(f"Design constraint {constraint.name} reads {', '.join(unknown)}, which are not "
                                     "fields of the structure")
                if not read & known:
                    raise ValueError(f"Design constraint {constraint.name} reads no field of the structure")
            if len({c.name for c in self.design}) != len(self.design):
                raise ValueError("Constraint names must be distinct")
            return self
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
        for name in ("variables", "design", "structure"):
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

    def named(self, candidate: Any) -> dict[str, Any]:
        """The candidate by variable name: a number for a variable of one entry, a list otherwise. A structured
        candidate's fields, as its library derives them."""
        if self.representation == "structured":
            fields = getattr(self.rules(), "fields", None)
            named = json_value(fields(candidate, self.structure.context), "A structure's fields") if callable(fields) else {}
            if not isinstance(named, dict) or set(named) != set(self.structure.fields):
                raise ValueError(f"The library of {self.structure.owner} gives fields {sorted(named) if isinstance(named, dict) else named}, "
                                 f"not {sorted(self.structure.fields)}")
            return named
        return {variable.name: candidate[offset] if variable.size == 1 else list(candidate[offset:offset + variable.size])
                for offset, variable in self._parts()}

    def design_failures(self, candidate: list) -> list[str]:
        """The design constraints a candidate (already in the schema's domain) breaks, each with why."""
        if not self.design:
            return []
        named = self.named(candidate)
        return [failure for constraint in self.design if (failure := constraint.failure(named)) is not None]

    def rules(self) -> StructureRules:
        """The library's rules of a structured candidate."""
        if self.structure is None:
            raise ValueError(f"A {self.representation} candidate has no library rules")
        return structure_rules(self.structure.owner)

    def broken(self, candidate: Any) -> list[str]:
        """Why ``canonicalize`` refuses a candidate, as a list of reasons; empty when it accepts it."""
        try:
            self.canonicalize(candidate)
        except ValueError as exc:
            return [str(exc)]
        return []

    def describe(self, candidate: Any) -> str:
        """One line about a candidate for pages: the library's own for a structured candidate, else the values."""
        describe = getattr(self.rules(), "describe", None) if self.representation == "structured" else None
        return str(describe(candidate, self.structure.context)) if callable(describe) else json.dumps(json_value(candidate))

    def feasible(self, candidate: Any) -> bool:
        """Whether ``canonicalize`` accepts the candidate: a method's check for its own proposals."""
        try:
            self.canonicalize(candidate)
        except ValueError:
            return False
        return True

    def canonicalize(self, candidate: Any) -> Any:
        if self.representation == "structured":
            return self._structured(candidate)
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

    def _structured(self, candidate: Any) -> Any:
        """The library's canonical value of a structured candidate, refused when it breaks one of the library's rules or a
        design constraint over its fields."""
        rules, context = self.rules(), self.structure.context
        value = json_value(rules.canonicalize(json_value(candidate), context), "A canonical structured candidate")
        broken = rules.is_valid(value, context)
        if not isinstance(broken, (list, tuple)) or not all(isinstance(rule, str) for rule in broken):
            raise ValueError(f"The library of {self.structure.owner} must give is_valid() as a list of the broken rules")
        if broken:
            raise ValueError("Candidate breaks the problem's rules: " + "; ".join(broken))
        if self.design:
            named = self.named(value)
            failed = [failure for constraint in self.design if (failure := constraint.failure(named)) is not None]
            if failed:
                raise ValueError("Candidate violates constraints: " + ", ".join(failed))
        return value

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
