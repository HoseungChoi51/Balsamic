"""A standalone Python project generated from a charter revision: the data, the harness, the tests, and two files to fill.

``scaffold()`` is pure: the same charter revision always gives the same bytes. No generated file imports Balsamic, so the
project runs with numpy and pytest alone. The coding agent (or the researcher, with their own tools) writes the
objective in ``<pkg>/objective.py`` and the methods in ``<pkg>/methods.py``; the rest is generated. A charter whose
candidate is ``structured`` (N12) gets a third file to fill, ``<pkg>/structure.py``: how a candidate is canonicalized and
which of its rules it breaks, with an example the tests check.

``scaffold(..., balsamic=True)`` also makes the project an installable Balsamic library (roadmap F3): ``<pkg>/adapter.py``
offers its problem and its methods through the two entry points, importing Balsamic only inside its functions, and
``tests/test_contract.py`` checks the library against Balsamic's contract where Balsamic is installed. The Balsamic side
of the glue is ``problem_charter/library.py``.
"""
from __future__ import annotations

import json
import keyword
import math
import pprint
import re
import zipfile
from importlib import resources
from io import BytesIO
from types import SimpleNamespace

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problem_charter import ProblemCharter

from .charter import DIMENSIONLESS, bound, parse, render, resolve, size
from .expressions import ExpressionError

REPRESENTATIONS = ("binary", "discrete", "continuous", "permutation", "structured")
TYPES = {"number": "float", "integer": "int", "text": "str", "boolean": "bool", "data": "list | dict"}


def package_name(charter: ProblemCharter, name: str | None = None) -> str:
    """The import name: ``name`` if given, else the evaluator's problem id, else the title, as a Python identifier."""
    source = name or (charter.evaluator.problem_id if charter.evaluator else charter.title)
    text = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")
    if not text or not text[0].isalpha():
        text = "problem_" + text
    return text[:64] + ("_" if keyword.iskeyword(text[:64]) else "")


def scaffold(charter, revision: int, *, name: str | None = None, charter_id: str | None = None,
             balsamic: bool = False) -> dict[str, bytes]:
    """The project's files by relative path. Raises ValueError for a charter that cannot give a runnable problem.

    With ``balsamic``, the project is also a Balsamic library: an adapter, both entry points and a contract test. The
    charter must then name its evaluator, whose problem id the library's problem takes."""
    charter = parse(charter)
    document = charter.model_dump(mode="json")
    if charter.objective is None:
        raise ValueError("The charter has no objective")
    if not charter.variables:
        raise ValueError("The charter has no decision variables")
    unsupported = sorted({v.representation for v in charter.variables} - set(REPRESENTATIONS))
    if unsupported:
        raise ValueError(f"The project generator does not support the {', '.join(unsupported)} representation yet")
    if balsamic and charter.evaluator is None:
        raise ValueError("The charter names no evaluator, so a Balsamic library has no problem id to provide")
    pkg = package_name(charter, name)
    project = pkg.replace("_", "-")
    tables = {key: [list(point) for point in table.points] for key, table in charter.tables.items()}
    instances = charter.instances or [None]
    data = {
        "CHARTER_ID": charter_id, "REVISION": revision, "CONTENT_HASH": content_hash(document), "TITLE": charter.title,
        "PROBLEM_ID": charter.evaluator.problem_id if charter.evaluator else pkg,
        "OBJECTIVE": {"name": charter.objective.name, "direction": charter.objective.direction, "units": charter.objective.units},
        "DETERMINISTIC": charter.evaluator.deterministic if charter.evaluator else True,
        "REPRESENTATION": charter.variables[0].representation,
        "QUANTITIES": {key: {"description": q.description, "kind": q.kind, "units": q.units, "role": q.role}
                       for key, q in charter.quantities.items()},
        "TABLES": tables,
        "INSTANCES": {(instance.name if instance else "default"): _instance(charter, instance, tables) for instance in instances},
        "REFERENCES": [{"statement": r.statement, "value": r.value, "units": r.units, "holds_at": r.holds_at}
                       for r in charter.references],
        **({"CHARTER": document} if balsamic else {}),
    }
    values = resolve(charter)["values"]
    files = {
        "pyproject.toml": _pyproject(project, pkg, charter.title, charter if balsamic else None),
        "charter.json": json.dumps({"charter_id": charter_id, "revision": revision, "content_hash": data["CONTENT_HASH"],
                                    "charter": document}, indent=2, ensure_ascii=False) + "\n",
        "README.md": _readme(charter, values, pkg, data),
        f"{pkg}/__init__.py": f'"""{_doc(charter.title)}: a project generated by Balsamic from its problem charter."""\n',
        f"{pkg}/data.py": _data(charter, revision, data),
        f"{pkg}/objective.py": _objective(charter, values),
        f"{pkg}/methods.py": _template("methods.py", pkg),
        f"{pkg}/problem.py": _template("problem.py", pkg).replace("__VALUES__", _values_class(charter)),
        f"{pkg}/harness.py": _template("harness.py", pkg),
        f"{pkg}/compare.py": _template("compare.py", pkg),
        "tests/test_problem.py": _template("test_problem.py", pkg),
        "tests/test_methods.py": _template("test_methods.py", pkg),
    }
    if data["REPRESENTATION"] == "structured":
        files[f"{pkg}/structure.py"] = _structure(charter, values)
    if balsamic:
        files[f"{pkg}/adapter.py"] = _template("adapter.py", pkg)
        files["tests/test_contract.py"] = _template("test_contract.py", pkg)
    return {path: text.encode() for path, text in files.items()}


def archive(charter, revision: int, *, name: str | None = None, charter_id: str | None = None) -> tuple[str, bytes]:
    """The project as a zip under ``<project-name>/``, and the file name: the problem and the revision. Pure, like
    ``scaffold()``: fixed timestamps and sorted paths, so the same revision always gives the same bytes."""
    files = scaffold(charter, revision, name=name, charter_id=charter_id)
    project = package_name(parse(charter), name).replace("_", "-")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            entry = zipfile.ZipInfo(f"{project}/{path}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.external_attr = 0o644 << 16
            bundle.writestr(entry, files[path], compress_type=zipfile.ZIP_DEFLATED)
    return f"{project}-r{revision}.zip", buffer.getvalue()


def instance_data(charter, overrides: dict | None = None, *, name: str = "configuration") -> dict:
    """One problem's data as ``data.py`` holds an instance: its resolved values and candidate schema, for these input
    values. A Balsamic library uses it for a configuration that is none of the charter's instances."""
    charter = parse(charter)
    tables = {key: [list(point) for point in table.points] for key, table in charter.tables.items()}
    return _instance(charter, SimpleNamespace(name=name, values=overrides or {}, split="development"), tables)


# The data -----------------------------------------------------------------------------------------------
def _number(value, what: str) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        raise ValueError(f"{what} is not finite")
    return float(value)


def _instance(charter: ProblemCharter, instance, tables) -> dict:
    """One instance's resolved values and candidate schema."""
    label = f"instance {instance.name!r}" if instance else "the charter"
    resolved = resolve(charter, instance.values if instance else None)
    values = resolved["values"]
    variables, offset = [], 0
    for variable in charter.variables:
        try:
            count = size(variable, values)
            shape = [part if isinstance(part, int) else values[part] for part in variable.shape]
            if variable.representation == "permutation" and len(shape) != 1:
                raise ValueError(f"the order {variable.name} needs a one-entry shape, the number of items")
            continuous = variable.representation == "continuous"
            lower = _number(bound(variable.lower, values, tables), f"the lower bound of {variable.name}") if continuous else None
            upper = _number(bound(variable.upper, values, tables), f"the upper bound of {variable.name}") if continuous else None
        except (ExpressionError, ValueError) as exc:
            raise ValueError(f"{label}: {exc}") from exc
        if variable.representation == "discrete" and not variable.values:
            raise ValueError(f"{label}: the discrete variable {variable.name} lists no values")
        variables.append({"name": variable.name, "representation": variable.representation, "shape": shape, "size": count,
                          "offset": offset, "lower": lower, "upper": upper,
                          "values": list(variable.values) if variable.representation == "discrete" else [],
                          "units": variable.units, "meaning": variable.meaning, "layout": variable.layout,
                          **({"fields": list(variable.fields)} if variable.representation == "structured" else {})})
        offset += count
    sizes = {v["name"]: v["size"] for v in variables}
    constraints = []
    for constraint in charter.constraints:
        if constraint.form != "linear":
            continue
        terms = []
        for term in constraint.terms:
            if term.variable not in sizes:
                raise ValueError(f"Constraint {constraint.id} uses {term.variable}, which is not a decision variable")
            n = sizes[term.variable]
            if term.weights is not None and len(term.weights) != n:
                raise ValueError(f"Constraint {constraint.id} gives {term.variable} {len(term.weights)} weights for {n} elements")
            weight = None if term.weights is not None else 1.0 if term.weight == "sum" else 1.0 / n if term.weight == "mean" \
                else float(term.weight)
            terms.append({"variable": term.variable, "weight": weight, "weights": term.weights})
        try:
            limit = _number(bound(constraint.bound, values, tables), f"the bound of constraint {constraint.id}")
        except ExpressionError as exc:
            raise ValueError(f"{label}: constraint {constraint.id}'s bound: {exc}") from exc
        constraints.append({"id": constraint.id, "statement": render(constraint.statement, values, charter),
                            "kind": constraint.kind, "relation": constraint.relation, "bound": limit, "terms": terms})
    return {"split": instance.split if instance else "development", "values": values,
            "candidate": {"representation": charter.variables[0].representation, "dimensions": offset,
                          "variables": variables, "constraints": constraints}}


def _literal(value) -> str:
    return pprint.pformat(value, width=110, sort_dicts=False)


def _data(charter, revision, data) -> str:
    lines = [f'"""The data of charter revision {revision}: {_doc(charter.title)}. Generated by Balsamic: do not edit.',
             "",
             "Every value is resolved: derived quantities are computed, and each instance's own values replace the charter's.",
             "Balsamic refuses a library whose data no longer matches its charter revision; regenerate it instead.",
             '"""', ""]
    for key, value in data.items():
        lines.append(f"{key} = {_literal(value)}")
    return "\n".join(lines) + "\n"


def _values_class(charter: ProblemCharter) -> str:
    lines = ["@dataclass(frozen=True)", "class Values:",
             '    """Each quantity of the charter, resolved for one instance. `values["name"]` works as well."""']
    for key, quantity in charter.quantities.items():
        units = "" if quantity.units.strip() in DIMENSIONLESS else f" ({quantity.units})"
        lines.append(f"    {_attribute(key)}: {TYPES[quantity.kind]} | None   # {_comment(quantity.description + units)}")
    lines += ["",
              "    @classmethod",
              "    def of(cls, values: dict) -> Values:",
              f"        return cls(**{{NAMES.get(key, key): value for key, value in values.items()}})",
              "",
              "    def __getitem__(self, name: str):",
              "        return getattr(self, NAMES.get(name, name))",
              "",
              "",
              f"NAMES = {_literal({key: _attribute(key) for key in charter.quantities if _attribute(key) != key})}"
              "   # quantity names that are Python keywords"]
    if not charter.quantities:
        lines.insert(3, "    pass")
    return "\n".join(lines)


def _attribute(key: str) -> str:
    return key + "_" if keyword.iskeyword(key) or key in {"of"} else key


# The files the agent fills ------------------------------------------------------------------------------
def _objective(charter: ProblemCharter, values: dict) -> str:
    objective = charter.objective
    units = "" if objective.units.strip() in DIMENSIONLESS else f" ({objective.units})"
    lines = [f"The objective: {objective.name}{units}, to {objective.direction}. Write `objective` below.", "",
             render(objective.definition, values, charter), "",
             "Values above are the charter's; an instance may have its own (`problem.values`)."]
    if charter.constraints:
        lines += ["", "Constraints:"]
        where = {"linear": "checked by Problem.is_valid", "quantities": "a condition on the charter's values, checked by the charter",
                 "design": "a condition on the design, checked by the framework before each evaluation",
                 "evaluator": "the objective must account for it", "qualitative": "recorded, not checked"}
        for constraint in charter.constraints:
            lines.append(f"- {constraint.id} ({constraint.kind}; {where[constraint.form]}): "
                         f"{render(constraint.statement, values, charter)}")
    if charter.evaluator and charter.evaluator.notes:
        lines += ["", "From the charter's evaluator notes:", "", charter.evaluator.notes]
    docstring = _doc("\n".join(lines))
    given = ("the candidate's canonical value, as `structure.canonicalize` gives it (a JSON value: lists, objects, numbers)"
             if charter.variables[0].representation == "structured" else "a numpy array of `problem.dimensions` numbers")
    return f'''"""{docstring}
"""
from __future__ import annotations

from .problem import Problem


def objective(problem: Problem, candidate) -> float:
    """{_doc(objective.name)} of `candidate` ({given}) on `problem`.

    `problem.unpack(candidate)` gives each decision variable in its shape; `problem.values` holds the instance's
    quantities, and `problem.table(name, x)` reads a table of the charter.
    """
    raise NotImplementedError("Write the objective in objective.py: {_doc(objective.name).replace('"', "'")}")
'''


def _structure(charter: ProblemCharter, values: dict) -> str:
    """``structure.py`` for a structured candidate: the stubs the agent fills, with the variable's meaning and layout."""
    variable = charter.variables[0]
    rules = [f"- {c.id} ({c.form}): {render(c.statement, values, charter)}" for c in charter.constraints
             if c.form in {"evaluator", "design"}]
    lines = [f"The candidate: {variable.name}, {variable.description.rstrip('.')}.", "",
             f"Meaning: {variable.meaning}", f"Layout: {variable.layout}", "",
             "Balsamic stores and compares a candidate in the form `canonicalize` gives and checks nothing else: the rules",
             "below are this file's to check, in `is_valid`."]
    if rules:
        lines += ["", "The charter's rules:", *rules]
    docstring = _doc("\n".join(lines))
    fields = ""
    if variable.fields:
        fields = f'''

def fields(problem: Problem, candidate) -> dict:
    """The numbers or vectors the charter's design constraints read, by name: {", ".join(variable.fields)}."""
    raise NotImplementedError("Write fields in structure.py")
'''
    return f'''"""{docstring}
"""
from __future__ import annotations

import json

from .problem import Problem

# A valid candidate of each instance, by instance name: the tests check that it passes canonicalize and is_valid.
EXAMPLES: dict = {{}}


def canonicalize(problem: Problem, candidate):
    """The one form of `candidate`: a JSON value (lists, objects, numbers, strings) two equal candidates share, e.g. with
    an order that does not matter sorted. Raise ValueError if the candidate cannot be read."""
    raise NotImplementedError("Write canonicalize in structure.py")


def is_valid(problem: Problem, candidate) -> list[str]:
    """The rules a canonical candidate breaks, one line each; empty when it breaks none."""
    raise NotImplementedError("Write is_valid in structure.py")


def describe(problem: Problem, candidate) -> str:
    """One line about a candidate, for pages."""
    return json.dumps(candidate)


def random_candidate(problem: Problem, rng):
    """A valid candidate drawn with `rng` (a numpy Generator), for methods that sample; optional."""
    raise NotImplementedError("Write random_candidate in structure.py to sample candidates")
{fields}'''


def _template(name: str, pkg: str) -> str:
    return resources.files(__package__).joinpath("scaffold_files", name + ".tmpl").read_text(encoding="utf-8").replace("__PKG__", pkg)


# The project files --------------------------------------------------------------------------------------
def _pyproject(project: str, pkg: str, title: str, charter: ProblemCharter | None = None) -> str:
    """The project; with ``charter``, a Balsamic library: its problem (a declared evaluator's) and its methods."""
    entry_points = ""
    if charter is not None:
        if charter.evaluator.kind == "declared":
            entry_points += f"""
[project.entry-points."optimization_framework.problems"]
{charter.evaluator.problem_id} = "{pkg}.adapter:problem_adapter"
"""
        entry_points += f"""
[project.entry-points."optimization_framework.optimizers"]
{pkg} = "{pkg}.adapter:method_plugin"
"""
    return f"""[project]
name = "{project}"
version = "0.1.0"
description = {json.dumps(title, ensure_ascii=False)}
requires-python = ">=3.11"
dependencies = ["numpy"]

[project.optional-dependencies]
test = ["pytest"]
{entry_points}
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{pkg}"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
"""


def _readme(charter: ProblemCharter, values: dict, pkg: str, data: dict) -> str:
    objective = charter.objective
    units = "" if objective.units.strip() in DIMENSIONLESS else f" ({objective.units})"
    summary = render(charter.summary, values, charter).strip()
    text = render(charter.text, values, charter).strip()
    instances = "\n".join(f"- {name} ({row['split']}): {row['candidate']['dimensions']} decision values"
                          for name, row in data["INSTANCES"].items())
    revision = f"revision {data['REVISION']} of charter `{data['CHARTER_ID']}`" if data["CHARTER_ID"] else f"revision {data['REVISION']}"
    return f"""# {charter.title}

{summary + chr(10) + chr(10) if summary else ""}{text + chr(10) + chr(10) if text else ""}**Objective:** {objective.direction} {objective.name}{units}.

Generated by Balsamic from {revision}. `charter.json` holds the charter, and `{pkg}/data.py` its values; neither is
edited by hand.

## Instances

{instances}

## What to write

1. `{pkg}/objective.py`: `objective(problem, candidate)`. Its docstring states the charter's definition and constraints.
2. `{pkg}/methods.py`: one function per method, each listed in `METHODS` with its name and description. Its comment
   shows the signature and an example.

## Running

```bash
pip install -e ".[test]"        # or: uv sync --extra test
pytest                          # the data, the objective and every method
python -m {pkg}.compare --seconds 10 --seeds 2
```

`compare` runs every method on every instance and prints the runs ranked by the objective's direction ({objective.direction}),
with each run's time and evaluations. A method marked `@deterministic` runs once.
"""


# Text helpers -------------------------------------------------------------------------------------------
def _doc(text: str) -> str:
    """Text safe inside a triple-quoted docstring."""
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return text + " " if text.endswith('"') else text


def _comment(text: str) -> str:
    return " ".join(text.split())
