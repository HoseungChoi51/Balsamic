"""The Balsamic side of a library generated from a charter (roadmap F3): its problem as a problem adapter.

A generated library's ``adapter.py`` hands ``CharterProblem`` its ``data`` module and a function that imports its own
code. The definition and every instance come from the charter the library holds (``data.CHARTER``) through the same
``manifest()`` that declares the problem, so the installed problem is, field for field, the one the charter declares;
``compare_provided()`` finds no difference by construction, and a charter whose data was edited is refused. Describing
and resolving read only ``data.py``; the library's own problem and objective are imported when an evaluator or a
method's problem is wanted, which happens in the worker.

A structured candidate (N12) is the library's own: ``structure.py`` canonicalizes and checks it. ``CharterProblem``
registers those rules under the problem's id when its code is first wanted (``structure()``), so the candidate schema
can check a candidate wherever the library's code runs.
"""
from __future__ import annotations

import hashlib
import math
from importlib.util import find_spec
from pathlib import Path

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problems import Evaluation, ProblemInstance, register_structure

from .charter import manifest, parse, resolve
from .scaffold import instance_data


class CharterProblem:
    """A generated library's problem: ``data`` is its data module, ``code()`` returns its problem and objective modules."""

    def __init__(self, data, code):
        self.data, self.code = data, code
        if content_hash(data.CHARTER) != data.CONTENT_HASH:
            raise ValueError(f"{data.__name__} no longer holds the charter revision it was generated from; regenerate it")
        self.charter = parse(data.CHARTER)
        self.binding = self.charter.evaluator
        self.package = data.__name__.rpartition(".")[0]
        self.version = f"r{data.REVISION}-{source_hash(self.package)}"

    def values(self, configuration=None, fidelity=None) -> tuple[dict, dict]:
        """The charter's inputs for an evaluator's fields, and every quantity resolved from them."""
        given = {**(configuration or {}), **(fidelity or {})}
        fields = {**self.binding.configuration, **self.binding.fidelity}
        unknown = sorted(set(given) - set(fields))
        if unknown:
            raise ValueError(f"{self.binding.problem_id} has no field {', '.join(unknown)}")
        inputs = {fields[field]: value for field, value in given.items()}
        resolved = resolve(self.charter, inputs)
        values = resolved["values"]
        for field, value in given.items():
            quantity = fields[field]
            if quantity in resolved.get("errors", {}):
                raise ValueError(resolved["errors"][quantity])
            if values.get(quantity) != value:
                raise ValueError(f"{field} = {value!r}, but the charter computes {quantity} = {values.get(quantity)!r}")
        return inputs, values

    def manifest(self, configuration=None, fidelity=None):
        return manifest(self.charter, self.values(configuration, fidelity)[1])

    def describe(self):
        return self.manifest().describe(self.version)

    def resolve(self, configuration, fidelity=None) -> ProblemInstance:
        return self.manifest(configuration, fidelity).resolve(self.version, configuration, fidelity)

    @property
    def structured(self) -> bool:
        return self.data.REPRESENTATION == "structured"

    def structure(self):
        """The library's rules for its structured candidates (N12), registered under the problem's id."""
        if not self.structured:
            raise ValueError(f"{self.binding.problem_id} has no structured candidates")
        rules = CharterStructure(self)
        register_structure(self.binding.problem_id, rules)
        return rules

    def problem(self, instance):
        """The library's own ``Problem`` for an instance: the charter's instance of the same values when there is one."""
        if self.structured:
            self.structure()
        return self.problem_at(instance.configuration, instance.fidelity)

    def problem_at(self, configuration, fidelity=None):
        problems, _ = self.code()
        inputs, values = self.values(configuration, fidelity)
        for name, row in self.data.INSTANCES.items():
            if row["values"] == values:
                return problems.PROBLEMS[name]
        return problems._problem("configuration", instance_data(self.charter, inputs))

    def evaluator(self, instance):
        instance = instance if isinstance(instance, ProblemInstance) else ProblemInstance.model_validate(instance)
        if not self.resolve(instance.configuration, instance.fidelity).same_evaluation(instance):
            raise ValueError("The library does not resolve this instance as it was frozen")
        return CharterEvaluator(instance, self.problem(instance), self.code()[1].objective)


class CharterStructure:
    """A generated library's ``structure.py`` as the rules a candidate schema calls: each is given the library's
    ``Problem`` at the instance's configuration (the schema's ``context``)."""

    def __init__(self, library: CharterProblem):
        self.library, self.problems = library, {}

    def problem(self, context):
        key = content_hash(context)
        if key not in self.problems:
            self.problems[key] = self.library.problem_at(context)
        return self.problems[key]

    def module(self):
        from importlib import import_module
        return import_module(f"{self.library.package}.structure")

    def canonicalize(self, candidate, context):
        try:
            return self.module().canonicalize(self.problem(context), candidate)
        except (TypeError, KeyError, IndexError) as exc:
            raise ValueError(f"The library cannot read the candidate ({type(exc).__name__}: {exc})") from None

    def is_valid(self, candidate, context):
        return [str(rule) for rule in self.module().is_valid(self.problem(context), candidate)]

    def describe(self, candidate, context):
        return self.module().describe(self.problem(context), candidate)

    def fields(self, candidate, context):
        fields = getattr(self.module(), "fields", None)
        return fields(self.problem(context), candidate) if callable(fields) else {}


class CharterEvaluator:
    """Evaluates a candidate with the library's ``objective(problem, candidate)``."""

    def __init__(self, instance, problem, objective):
        self.instance, self.problem, self.objective = instance, problem, objective
        self.evaluations = 0

    def evaluate(self, candidate):
        import copy
        import numpy as np
        candidate = self.instance.candidate_schema.canonicalize(candidate)
        given = copy.deepcopy(candidate) if self.instance.candidate_schema.representation == "structured" else np.asarray(candidate, dtype=float)
        value = float(self.objective(self.problem, given))
        if not math.isfinite(value):
            raise ValueError(f"The objective gave {value} for a valid candidate")
        self.evaluations += 1
        return Evaluation(objectives={self.instance.primary_objective.name: value},
                          constraints={c.name: True for c in self.instance.candidate_schema.constraints})

    def checkpoint(self):
        return {"identity": self.instance.evaluation_identity, "evaluations": self.evaluations}

    def restore(self, state):
        if state.get("identity") != self.instance.evaluation_identity:
            raise ValueError("The evaluator checkpoint belongs to another instance or version")
        self.evaluations = state["evaluations"]


def source_hash(package: str) -> str:
    """The library's code besides its methods, read without importing it: a changed objective is another evaluator."""
    spec = find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f"{package} is not an installed package")
    root = Path(next(iter(spec.submodule_search_locations)))
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if path.name == "methods.py" and path.parent == root or "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]
