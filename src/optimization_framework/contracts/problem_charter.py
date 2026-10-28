"""The problem charter: one document that states an optimization problem, every value once.

The contract is deliberately general. It names no field of science and no particular evaluator:
inputs, derived quantities (expressions over other quantities, optionally through tables of data),
decision variables, constraints, an objective, recorded metrics, and the binding of quantities to
an evaluator's configuration and fidelity fields. Structure is validated here; whether the content
is complete and consistent is reported as findings by ``problem_charter.checks``, so an incomplete
draft can still be saved, shown and discussed.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .base import Contract
from .problems import Access, CostAxis, without_unset


class Part(BaseModel):
    """A part of a charter; the version is the charter's own."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

NAME = r"^[a-z][a-z0-9_]{0,63}$"
Value = float | int | str | bool | list[Any] | dict[str, Any]
REFERENCE = re.compile(r"\{([a-z][a-z0-9_]{0,63})(?::([^{}]{1,12}))?\}")


class Citation(Part):
    id: int = Field(ge=1, le=10000)
    source: str = Field(min_length=1, max_length=300, description="A document, file or person the value comes from")
    location: str = Field(default="", max_length=200, description="Page, section, figure, table or line range")
    quote: str = Field(default="", max_length=600)


class Quantity(Part):
    """An input (a value typed in) or a derived quantity (computed from an expression)."""
    description: str = Field(min_length=1, max_length=500)
    kind: Literal["number", "integer", "text", "boolean", "data"] = Field(default="number",
        description="'data' holds a structured value (a list or an object) an evaluator takes as it is")
    role: Literal["input", "derived"] = "input"
    value: Value | None = Field(default=None, description="Inputs only")
    expression: str | None = Field(default=None, max_length=1000, description="Derived quantities only")
    units: str = Field(default="", max_length=40, description="'1' for a dimensionless number; empty only for text, booleans and data")
    range: tuple[float | None, float | None] | None = Field(default=None, description="Inclusive lower and upper limits; null for open")
    origin: Literal["researcher", "source", "assumed", "computed"] = "source"
    citation: int | None = None
    accepted: bool = Field(default=False, description="An assumed value the researcher has accepted")
    note: str = Field(default="", max_length=1000, description="Why the value or relation is what it is")

    @model_validator(mode="after")
    def role_fields(self):
        if self.role == "input" and self.expression is not None:
            raise ValueError("An input has a value, not an expression")
        if self.role == "derived" and (self.value is not None or not self.expression):
            raise ValueError("A derived quantity has an expression and no value")
        if self.role == "derived" and self.origin != "computed":
            object.__setattr__(self, "origin", "computed")
        return self


class Table(Part):
    """Tabulated data, such as a measured material property, read by ``table(name, x)``."""
    description: str = Field(min_length=1, max_length=500)
    x_units: str = Field(min_length=1, max_length=40)
    y_units: str = Field(min_length=1, max_length=40)
    points: list[tuple[float, float]] = Field(min_length=2, max_length=5000)
    citation: int | None = None

    @model_validator(mode="after")
    def increasing(self):
        xs = [x for x, _ in self.points]
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise ValueError("Table points must be ordered by strictly increasing x")
        return self


class DecisionVariable(Part):
    """What the optimizer changes. Its size is the product of ``shape`` (numbers or integer quantities)."""
    name: str = Field(pattern=NAME)
    description: str = Field(min_length=1, max_length=1000)
    representation: Literal["binary", "discrete", "continuous", "permutation", "structured"] = Field(description=(
        "structured: one JSON value whose form and rules the problem's library owns (an order per machine, several orders, "
        "a sequence of variable length, a graph); it is the only decision variable, and its meaning and layout say what it is"))
    shape: list[int | str] = Field(default_factory=list, max_length=6,
                                   description="Empty for a single value; for a permutation, one entry: the number of items")
    lower: float | str | None = Field(default=None, description="A number or an expression; continuous variables")
    upper: float | str | None = None
    values: list[float] = Field(default_factory=list, max_length=1000, description="Permitted values of a discrete variable")
    units: str = Field(default="1", max_length=40)
    meaning: str = Field(default="", max_length=500, description="What a value stands for, e.g. what 1 and 0 mean")
    layout: str = Field(default="", max_length=300, description="How elements are ordered, e.g. row by row")
    fields: list[str] = Field(default_factory=list, max_length=100, description=(
        "structured only: the names of the numbers or vectors the library derives from a candidate (e.g. a load per machine), "
        "which design constraints may read"))

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        result = handler(self)
        if not self.fields:
            result.pop("fields", None)
        return result


class LinearTerm(Part):
    variable: str = Field(pattern=NAME)
    weight: float | Literal["sum", "mean"] = "sum"
    weights: list[float] | None = Field(default=None, max_length=1000000, description="One weight per element instead")


class Constraint(Part):
    id: str = Field(pattern=NAME)
    statement: str = Field(min_length=1, max_length=1000)
    kind: Literal["hard", "soft"] = "hard"
    form: Literal["quantities", "linear", "design", "outcome", "evaluator", "qualitative"] = Field(description=(
        "quantities: a true/false test on the charter's values; linear: a weighted sum of decision variables against a "
        "bound; design: a true/false expression over the decision variables by name (non-linear, a ratio, a minimum "
        "width), checked on every candidate; outcome: a true/false expression over the objective and metrics the "
        "evaluator reports (a floor on a second metric, a cap on a measured cost), checked on every result; evaluator: "
        "the evaluator accounts for it; qualitative: a policy rule no code can judge, words only"))
    test: str | None = Field(default=None, max_length=1000, description=(
        "form 'quantities', 'design' or 'outcome': a true/false expression. A design expression reads decision variables "
        "by name (a variable of several entries is a vector) and number quantities, with sum, min, max, count, len, at(v, i), "
        "diff, all and any; e.g. all(diff(edges) >= min_gap) or max(widths) <= 3 * min(widths). An outcome expression "
        "reads the objective and metrics by name and number quantities; e.g. pressure_drop <= max_pressure_drop"))
    terms: list[LinearTerm] = Field(default_factory=list, max_length=20, description="form 'linear'")
    relation: Literal["le", "ge", "eq"] | None = None
    bound: float | str | None = None
    citation: int | None = None

    @model_validator(mode="after")
    def form_fields(self):
        if self.form == "quantities" and not self.test:
            raise ValueError(f"Constraint {self.id}: a test on quantities needs an expression")
        if self.form == "design" and not self.test:
            raise ValueError(f"Constraint {self.id}: a design constraint needs an expression over the decision variables")
        if self.form == "outcome" and not self.test:
            raise ValueError(f"Constraint {self.id}: an outcome constraint needs an expression over the measured metrics")
        if self.form == "linear" and (not self.terms or self.relation is None or self.bound is None):
            raise ValueError(f"Constraint {self.id}: a linear constraint needs terms, a relation and a bound")
        return self


class Objective(Part):
    name: str = Field(min_length=1, max_length=100)
    direction: Literal["minimize", "maximize"]
    units: str = Field(min_length=1, max_length=60)
    definition: str = Field(min_length=1, max_length=3000, description="How it is computed; may use {name} references")
    citation: int | None = None


class Metric(Part):
    name: str = Field(min_length=1, max_length=100)
    units: str = Field(min_length=1, max_length=60)
    direction: Literal["minimize", "maximize"] | None = None
    definition: str = Field(default="", max_length=2000)


class EvaluatorBinding(Part):
    """Which evaluator computes the objective and which quantity fills each of its fields."""
    kind: Literal["installed", "declared"]
    problem_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")
    configuration: dict[str, str] = Field(default_factory=dict, description="evaluator field -> quantity name")
    fidelity: dict[str, str] = Field(default_factory=dict, description="fidelity field -> quantity name")
    deterministic: bool = True
    notes: str = Field(default="", max_length=20000, description="Declared problems: what the evaluator must compute and from which code")
    access: Access | None = Field(default=None, description=(
        "white_box: a method may compute the objective from the problem's code; oracle: only through evaluate (an "
        "expensive evaluator, or a black-box comparison the researcher wants). Unset: the installed problem's own "
        "declaration, white_box for a declared problem"))
    cost_axis: CostAxis | None = Field(default=None, description=(
        "What methods are compared on. Unset: worker_seconds, or core_seconds when a method uses several threads"))

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        return without_unset(handler(self), "access", "cost_axis")


class Instance(Part):
    name: str = Field(min_length=1, max_length=200)
    split: Literal["development", "selection", "test"] = "development"
    values: dict[str, Value] = Field(default_factory=dict, description="Input values that differ from the charter's")
    note: str = Field(default="", max_length=1000)
    size: str | None = Field(default=None, pattern=NAME, description=(
        "The number or integer quantity whose value grows across the instances, such as the number of jobs; every "
        "instance names the same one. The comparison then reports the largest size each method finishes at and where "
        "one overtakes another"))

    @model_serializer(mode="wrap")
    def compatible_serialization(self, handler):
        return without_unset(handler(self), "size")


class ReferenceResult(Part):
    statement: str = Field(min_length=1, max_length=1000)
    value: float | None = None
    units: str = Field(default="", max_length=60)
    holds_at: dict[str, Value] = Field(default_factory=dict, description="Input values the result was reported at")
    citation: int | None = None


class Assumption(Part):
    statement: str = Field(min_length=1, max_length=1000)
    about: list[str] = Field(default_factory=list, max_length=20)
    accepted: bool = False


class Question(Part):
    id: str = Field(pattern=NAME)
    question: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=6)
    unrunnable_options: list[int] = Field(default_factory=list, max_length=6,
        description="Indices of options under which nothing can run until something outside the charter changes; never recommended")
    about: list[str] = Field(default_factory=list, max_length=20)
    blocking: bool = True
    answer: str | None = Field(default=None, max_length=5000)
    answered_at: str | None = None
    sent: bool = Field(default=False, description="The answer has been given to the formulator")


class Waiver(Part):
    key: str = Field(min_length=1, max_length=300, description="The finding's key")
    reason: str = Field(min_length=1, max_length=2000)
    at: str = ""


class Fork(Part):
    charter_id: str
    revision: int = Field(ge=1)
    changes: dict[str, tuple[Value | None, Value | None]] = Field(default_factory=dict)


class ProblemCharter(Contract):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=3000)
    text: str = Field(default="", max_length=20000, description="The problem in prose; values only as {name} references")
    quantities: dict[str, Quantity] = Field(default_factory=dict)
    tables: dict[str, Table] = Field(default_factory=dict)
    variables: list[DecisionVariable] = Field(default_factory=list, max_length=20)
    constraints: list[Constraint] = Field(default_factory=list, max_length=100)
    objective: Objective | None = None
    metrics: list[Metric] = Field(default_factory=list, max_length=30)
    evaluator: EvaluatorBinding | None = None
    instances: list[Instance] = Field(default_factory=list, max_length=20)
    references: list[ReferenceResult] = Field(default_factory=list, max_length=50)
    citations: list[Citation] = Field(default_factory=list, max_length=200)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=100)
    questions: list[Question] = Field(default_factory=list, max_length=100)
    waivers: list[Waiver] = Field(default_factory=list, max_length=100)
    forked_from: Fork | None = None

    @model_validator(mode="after")
    def names(self):
        for group, names in (("quantity", self.quantities), ("table", self.tables)):
            bad = [name for name in names if not re.fullmatch(NAME, name)]
            if bad:
                raise ValueError(f"Invalid {group} names (lowercase letters, digits and _): {', '.join(bad[:5])}")
        for label, items in (("decision variable", [v.name for v in self.variables]), ("constraint", [c.id for c in self.constraints]),
                             ("question", [q.id for q in self.questions]), ("instance", [i.name for i in self.instances]),
                             ("citation", [c.id for c in self.citations])):
            if len(set(items)) != len(items):
                raise ValueError(f"Each {label} needs a distinct name")
        clash = set(self.quantities) & {v.name for v in self.variables}
        if clash:
            raise ValueError(f"A decision variable and a quantity share a name: {', '.join(sorted(clash))}")
        return self
