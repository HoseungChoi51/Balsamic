"""Mechanical work on a problem charter: values, texts, findings, differences, changes and compilation.

Nothing here knows a particular problem. Values come from the charter's inputs and relations;
evaluator facts come from the installed problem registry or the charter's own declaration.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from optimization_framework.contracts.problem_charter import REFERENCE, ProblemCharter

from .expressions import ExpressionError, degree_arguments, evaluate, names

DEGREES = {"deg", "degree", "degrees", "°"}
DIMENSIONLESS = {"", "1", "dimensionless"}
# Findings that a researcher may waive with a reason. The others would make the charter impossible to compile.
WAIVABLE = {"constraint.qualitative", "constraint.violated", "constraint.infeasible", "question.open", "quantity.range",
            "text.literal_mismatch"}
LP_ELEMENT_LIMIT = 20000


def parse(charter) -> ProblemCharter:
    return charter if isinstance(charter, ProblemCharter) else ProblemCharter.model_validate(charter)


# Values ----------------------------------------------------------------------------------------------
def coerce(value, kind: str):
    """A value of the quantity's kind, or ValueError."""
    if kind == "data":
        if isinstance(value, (list, dict)):
            return value
        raise ValueError("is not a list or an object")
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        raise ValueError("is not true or false")
    if kind == "text":
        if isinstance(value, str):
            return value
        raise ValueError("is not text")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("is not a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("is not finite")
    if kind == "integer":
        if isinstance(value, int):
            return value
        if abs(value - round(value)) <= 1e-9 * max(1.0, abs(value)):
            return int(round(value))
        raise ValueError("is not a whole number")
    return value


def resolve(charter, overrides: dict | None = None) -> dict:
    """Every quantity's value: inputs as given (or overridden), derived ones computed in dependency order."""
    charter = parse(charter)
    overrides = overrides or {}
    tables = {name: table.points for name, table in charter.tables.items()}
    values, errors = {}, {}
    for name, quantity in charter.quantities.items():
        if quantity.role != "input":
            continue
        value = overrides.get(name, quantity.value)
        if value is None:
            values[name] = None
            continue
        try:
            values[name] = coerce(value, quantity.kind)
        except ValueError as exc:
            values[name], errors[name] = None, f"{name} {exc}"
    derived = {name: q for name, q in charter.quantities.items() if q.role == "derived"}
    needs = {}
    for name, quantity in derived.items():
        try:
            needs[name] = names(quantity.expression)
        except ExpressionError as exc:
            errors[name] = f"{name}: {exc}"
    known = set(charter.quantities)
    for name, used in needs.items():
        unknown = sorted(used - known)
        if unknown:
            errors[name] = f"{name}: unknown name {', '.join(unknown)}"
    order, state = [], {}

    def visit(name, path):
        if state.get(name) == "done":
            return
        if state.get(name) == "visiting":
            cycle = path[path.index(name):] + [name]
            for member in cycle[:-1]:
                errors.setdefault(member, "the relations form a cycle: " + " → ".join(cycle))
            return
        state[name] = "visiting"
        for dependency in sorted(needs.get(name, ())):
            if dependency in derived:
                visit(dependency, path + [name])
        state[name] = "done"
        order.append(name)

    for name in derived:
        visit(name, [])
    for name in order:
        values[name] = None
        if name in errors:
            continue
        missing = sorted(d for d in needs[name] if values.get(d) is None)
        if missing:
            errors[name] = f"{name}: needs {', '.join(missing)}, which {'has' if len(missing) == 1 else 'have'} no value"
            continue
        try:
            values[name] = coerce(evaluate(derived[name].expression, values, tables), derived[name].kind)
        except (ExpressionError, ValueError) as exc:
            errors[name] = f"{name}: {exc}"
    return {"values": values, "errors": errors}


def show(value, units: str = "", spec: str | None = None) -> str:
    if value is None:
        return "—"
    if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
        # A table in prose reads as what it is; its rows are on the Charter page.
        return f"a table of {len(value)} rows ({', '.join(dict.fromkeys(key for row in value for key in row))})"
    if isinstance(value, (list, dict)):
        import json
        text = json.dumps(value, ensure_ascii=False)
        return text if len(text) <= 80 else text[:77] + "…"
    if isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, float):
        text = format(value, spec) if spec else format(value, ".6g")
    elif isinstance(value, int) and spec:
        text = format(value, spec)
    else:
        text = str(value)
    units = (units or "").strip()
    if units.lower() in DEGREES:
        return text + "°"
    return text if units in DIMENSIONLESS else f"{text} {units}"


def render(text: str, values: dict, charter) -> str:
    """A text with each {name} (or {name:.3g}) replaced by the current value and its units."""
    charter = parse(charter)

    def replace(match):
        name, spec = match.group(1), match.group(2)
        if name not in charter.quantities:
            return match.group(0)
        try:
            return show(values.get(name), charter.quantities[name].units, spec)
        except ValueError:
            return show(values.get(name), charter.quantities[name].units)
    return REFERENCE.sub(replace, text or "")


def texts(charter) -> dict[str, str]:
    """Every prose field of a charter that may hold {name} references, by location."""
    charter = parse(charter)
    found = {"text": charter.text, "summary": charter.summary}
    if charter.objective:
        found["objective"] = charter.objective.definition
    for constraint in charter.constraints:
        found[f"constraint {constraint.id}"] = constraint.statement
    for metric in charter.metrics:
        if metric.definition:
            found[f"metric {metric.name}"] = metric.definition
    return found


def size(variable, values) -> int:
    total = 1
    for part in variable.shape:
        count = part if isinstance(part, int) else values.get(part)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError(f"shape entry {part!r} of {variable.name} is not a positive whole number")
        total *= count
    return total


def bound(value, values, tables):
    if value is None or isinstance(value, (int, float)):
        return value
    result = evaluate(value, values, tables)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ExpressionError("a bound must be a number")
    return float(result)


# Findings --------------------------------------------------------------------------------------------
def finding(code, severity, subject, message, about=()):
    return {"key": f"{code}:{subject}", "code": code, "severity": severity, "message": message,
            "about": list(about), "waivable": severity == "blocking" and code in WAIVABLE}


NUMBER = r"(?<![\w.{:])(-?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?)"


# Units -----------------------------------------------------------------------------------------------
# A unit is read as a factor and a base, so that one thing counted at two scales ("token" and "Mtok", "s" and "ms") is
# caught: a number written for one is off by the factor in the other. Nothing here knows a field. A scale word ("million
# tokens") is always read; a one-letter prefix ("Mtok", "ms") only when what follows is itself a unit in use.
SCALE_WORDS = {"thousand": 1e3, "kilo": 1e3, "million": 1e6, "mn": 1e6, "mega": 1e6, "billion": 1e9, "bn": 1e9, "giga": 1e9,
               "trillion": 1e12, "tera": 1e12, "milli": 1e-3, "micro": 1e-6, "nano": 1e-9}
SCALE_LETTERS = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "B": 1e9, "T": 1e12, "m": 1e-3, "µ": 1e-6, "u": 1e-6, "n": 1e-9}
SPELLINGS = {"tok": "token", "tkn": "token"}


def unit_word(text: str) -> str:
    """A unit word in one spelling: lowercase and singular ("Tokens" and "tok" are "token")."""
    text = text.strip().lower()
    if len(text) > 3 and text.endswith("s") and not text.endswith("ss"):
        text = text[:-1]
    return SPELLINGS.get(text, text)


def unit_scale(units: str, known=frozenset()) -> tuple[float, str] | None:
    """(factor, base) of a unit: "Mtok" is (1e6, "token") when "token" is known, "million tokens/day" is (1e6, "token/day");
    None for a pure number or degrees."""
    units = (units or "").strip()
    if units in DIMENSIONLESS or units.lower() in DEGREES:
        return None
    top, _, per = units.partition("/")
    words = top.replace("·", " ").replace("*", " ").split()
    factor = 1.0
    if len(words) > 1:
        first, power = words[0], re.fullmatch(r"10\^(-?\d+)", words[0])
        if first.lower().rstrip("s") in SCALE_WORDS:
            factor, words = SCALE_WORDS[first.lower().rstrip("s")], words[1:]
        elif first in "kKMGBT":
            factor, words = SCALE_LETTERS[first], words[1:]
        elif power:
            factor, words = 10.0 ** int(power.group(1)), words[1:]
        elif re.fullmatch(r"\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?", first) and float(first.replace(",", "")) > 0:
            factor, words = float(first.replace(",", "")), words[1:]
        if words and words[0].lower() == "of":
            words = words[1:]
    head = " ".join(words)
    for prefix, scale in SCALE_WORDS.items():
        if len(prefix) > 2 and head.lower().startswith(prefix) and len(head) > len(prefix) + 1:
            factor, head = factor * scale, head[len(prefix):]
            break
    else:
        if len(head) > 1 and head[0] in SCALE_LETTERS and unit_word(head[1:]) in known:
            factor, head = factor * SCALE_LETTERS[head[0]], head[1:]
    base = "/".join([unit_word(head)] + [unit_word(part) for part in per.split("/") if per])
    return factor, base


def unit_rows(charter) -> list[tuple[str, str, Any]]:
    """Every number-valued quantity and decision variable with its units and its stated value (None for a variable)."""
    rows = [(name, q.units, q.value if q.role == "input" else None) for name, q in charter.quantities.items()
            if q.kind in {"number", "integer"}]
    return rows + [(v.name, v.units, None) for v in charter.variables]


def known_units(*row_lists) -> frozenset:
    """The unit words in use, read without prefixes: what a one-letter prefix may stand before. A word that two units in
    use share after different prefixes ("nm" and "um") counts too."""
    found, after = set(), {}
    for rows in row_lists:
        for _, units, _ in rows:
            scaled = unit_scale(units)
            if scaled:
                head = scaled[1].split("/")[0]
                found.add(head)
                if len(head) > 1 and units.strip()[0] in SCALE_LETTERS:
                    after.setdefault(unit_word(head[1:]), set()).add(head)
    return frozenset(found | {rest for rest, heads in after.items() if len(heads) > 1})


def ratio(number: float) -> str:
    return f"{number:,.0f}" if number >= 1 and float(number).is_integer() else format(number, ".6g")


def scale_findings(charter) -> list[dict]:
    """One thing counted at two scales in one charter ("token" and "Mtok"): a number typed for one is off by the factor in
    the other."""
    rows = unit_rows(charter)
    known = known_units(rows)
    groups: dict[str, dict[float, list[tuple[str, str]]]] = {}
    for name, units, _ in rows:
        scaled = unit_scale(units, known)
        if scaled:
            groups.setdefault(scaled[1], {}).setdefault(scaled[0], []).append((name, units.strip()))
    out = []
    for base, scales in groups.items():
        if len(scales) < 2:
            continue
        smallest = min(scales)
        unit_of = lambda members: " or ".join(dict.fromkeys(units for _, units in members))
        least = unit_of(scales[smallest])
        parts = [f"{', '.join(name for name, _ in members)} in {unit_of(members)}"
                 + (f" (1 {unit_of(members)} = {ratio(factor / smallest)} {least})" if factor != smallest else "")
                 for factor, members in sorted(scales.items())]
        out.append(finding("units.scale", "warning", base, f"{base} is counted at {len(scales)} scales: {'; '.join(parts)}. "
            "A number written for one is off by that factor in the other: count it in one unit throughout, or derive one "
            "from the other.", [name for members in scales.values() for name, _ in members]))
    return out


def units_elsewhere(charter, others: list[dict]) -> list[dict]:
    """Where the charters of other campaigns count a thing this charter counts in another unit: at another scale ("Mtok"
    against "token"), or in a unit of their own ("token/TU", with quantities in TU). Each row says which names here it is
    about, so a number carried over from one charter is not read in the other's unit. `others` holds {title, campaign,
    charter} each."""
    charter = parse(charter)
    mine = unit_rows(charter)
    mine_known = known_units(mine)
    out = []
    for other in others:
        theirs = unit_rows(parse(other["charter"]))
        known = known_units(mine, theirs)
        here: dict[str, list[tuple[float, str, str, str]]] = {}   # by the thing counted: (factor, base, units, name)
        for name, units, _ in mine:
            scaled = unit_scale(units, known)
            if scaled:
                here.setdefault(scaled[1].split("/")[0], []).append((*scaled, units.strip(), name))
        bare: dict[str, int] = {}
        for _, units, _ in theirs:
            scaled = unit_scale(units, known)
            if scaled and scaled[0] == 1 and "/" not in scaled[1]:
                bare[scaled[1]] = bare.get(scaled[1], 0) + 1
        found: dict[tuple, dict] = {}
        for name, units, value in theirs:
            scaled = unit_scale(units, known)
            top, _, per = scaled[1].partition("/") if scaled else ("", "", "")
            if top not in here:
                continue
            factor, base = scaled
            same = [row for row in here[top] if row[1] == base]
            stated = name if value is None else f"{name} = {ratio(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value} {units.strip()}"
            if same and all(row[0] != factor for row in same):
                mine_factor, _, mine_units, _ = same[0]
                row = found.setdefault(("scale", base, factor), {"about": [row[3] for row in same], "names": [],
                    "note": f"1 {units.strip()} there is {ratio(factor / mine_factor)} {mine_units} here"})
            elif not same and per and per in bare and per not in mine_known:
                written = units.split("/", 1)[1].strip()
                row = found.setdefault(("per", base), {"about": [row[3] for row in here[top]], "names": [],
                    "note": f"{here[top][0][2]} is counted in {written} there, and {bare[per]} of its parameters are in {written}"})
            else:
                continue
            row["names"].append(stated)
        for row in found.values():
            names = ", ".join(row["names"][:3]) + (" …" if len(row["names"]) > 3 else "")
            out.append({"charter_id": other.get("charter_id"), "title": other["title"], "campaign": other["campaign"], "about": row["about"],
                        "message": f"In “{other['title']}” (campaign {other['campaign']}), {names}: {row['note']}."})
    return out


def literal_findings(text: str, location: str, charter, values) -> list[dict]:
    """Numbers stated in a text with the units of a quantity: the text should refer to the quantity instead."""
    units = {}
    for name, quantity in charter.quantities.items():
        if quantity.kind in {"number", "integer"} and quantity.units.strip() not in DIMENSIONLESS:
            units.setdefault(quantity.units.strip(), []).append(name)
    found = []
    stripped = REFERENCE.sub("", text or "")
    for unit, owners in units.items():
        written = "°|deg|degrees?" if unit.lower() in DEGREES else re.escape(unit)
        for match in re.finditer(NUMBER + r"\s*(?:" + written + r")(?![\w])", stripped):
            number = float(match.group(1).replace(",", ""))
            same = [name for name in owners if isinstance(values.get(name), (int, float))
                    and math.isclose(number, values[name], rel_tol=5e-3, abs_tol=1e-12)]
            if same:
                found.append(finding("text.literal", "warning", f"{location}:{match.group(0)}",
                    f"The {location} states {match.group(0).strip()}; write {{{same[0]}}} so it follows the value.", same))
            else:
                found.append(finding("text.literal_mismatch", "blocking", f"{location}:{match.group(0)}",
                    f"The {location} states {match.group(0).strip()}, but no quantity in {unit} has that value "
                    f"({', '.join(f'{n} = {show(values.get(n), unit)}' for n in owners[:4])}). Refer to the quantity, "
                    f"or move a reported number to the reference results.", owners))
    return found


def evaluator_facts(charter, values, registry):
    """The installed adapter's description and resolved problem for given values, or the error."""
    binding = charter.evaluator
    configuration = {field: values.get(name) for field, name in binding.configuration.items()}
    fidelity = {field: values.get(name) for field, name in binding.fidelity.items()}
    return registry.resolve(binding.problem_id, configuration, fidelity)


def findings(charter, registry=None) -> list[dict]:
    from optimization_framework.evaluation.registry import problems
    registry = registry or problems
    charter = parse(charter)
    resolved = resolve(charter)
    values, errors = resolved["values"], resolved["errors"]
    tables = {name: table.points for name, table in charter.tables.items()}
    units = {name: quantity.units for name, quantity in charter.quantities.items()}
    cited = {citation.id for citation in charter.citations}
    out = []
    # Quantities and relations
    for name, quantity in charter.quantities.items():
        if quantity.role == "input" and quantity.value is None:
            out.append(finding("quantity.no_value", "blocking", name, f"{name} has no value. Give one, or state how it follows from others.", [name]))
        if name in errors:
            code = "relation.error" if quantity.role == "derived" else "quantity.kind"
            out.append(finding(code, "blocking", name, errors[name], [name]))
        if quantity.kind in {"number", "integer"} and not quantity.units.strip():
            out.append(finding("quantity.no_units", "warning", name, f"{name} has no units; write '1' if it has none.", [name]))
        value = values.get(name)
        if quantity.range and isinstance(value, (int, float)) and not isinstance(value, bool):
            low, high = quantity.range
            if (low is not None and value < low) or (high is not None and value > high):
                out.append(finding("quantity.range", "blocking", name, f"{name} = {show(value, quantity.units)} is outside its range "
                    f"[{'' if low is None else show(low)}, {'' if high is None else show(high)}].", [name]))
        if quantity.role == "derived" and name not in errors:
            for argument in degree_arguments(quantity.expression, units):
                out.append(finding("relation.degrees", "warning", f"{name}:{argument}", f"{name} passes {argument}, in degrees, "
                    f"straight to a trigonometric function, which takes radians; use rad({argument}).", [name, argument]))
        if quantity.citation is not None and quantity.citation not in cited:
            out.append(finding("citation.unknown", "warning", name, f"{name} cites source {quantity.citation}, which is not listed.", [name]))
        if quantity.origin == "assumed" and not quantity.accepted:
            out.append(finding("assumption.unaccepted", "blocking", name, f"{name} = {show(value, quantity.units)} is an assumption"
                f"{': ' + quantity.note.rstrip('.') if quantity.note else ''}. Accept it, change it, or ask for a change.", [name]))
    for index, assumption in enumerate(charter.assumptions):
        if not assumption.accepted:
            out.append(finding("assumption.unaccepted", "blocking", f"statement{index}", f"Assumption: {assumption.statement}", assumption.about))
    inputs =[(name, q) for name, q in charter.quantities.items() if q.role == "input" and q.kind == "number"
              and q.units.strip() not in DIMENSIONLESS and isinstance(values.get(name), (int, float))]
    for i, (left, a) in enumerate(inputs):
        for right, b in inputs[i + 1:]:
            if a.units.strip() == b.units.strip() and math.isclose(values[left], values[right], rel_tol=1e-9):
                out.append(finding("duplicate.value", "warning", f"{left}:{right}", f"{left} and {right} are both "
                    f"{show(values[left], a.units)}. If they are the same quantity, keep one and refer to it.", [left, right]))
    out.extend(scale_findings(charter))
    # Texts
    for location, text in texts(charter).items():
        for match in REFERENCE.finditer(text or ""):
            if match.group(1) not in charter.quantities:
                out.append(finding("text.reference", "blocking", f"{location}:{match.group(1)}",
                    f"The {location} refers to {{{match.group(1)}}}, which is not a quantity.", []))
        out.extend(literal_findings(text, location, charter, values))
    out.extend(unused_findings(charter))
    # Decision variables
    sizes = {}
    for variable in charter.variables:
        try:
            sizes[variable.name] = size(variable, values)
        except ValueError as exc:
            out.append(finding("variable.shape", "blocking", variable.name, str(exc).capitalize() + ".", [variable.name]))
            continue
        if variable.representation == "continuous":
            try:
                low, high = bound(variable.lower, values, tables), bound(variable.upper, values, tables)
            except ExpressionError as exc:
                out.append(finding("variable.bounds", "blocking", variable.name, f"The bounds of {variable.name}: {exc}.", [variable.name]))
                continue
            if low is None or high is None:
                out.append(finding("variable.bounds", "blocking", variable.name, f"{variable.name} is continuous and needs a lower and an upper bound.", [variable.name]))
            elif low >= high:
                out.append(finding("variable.bounds", "blocking", variable.name, f"{variable.name}'s lower bound is not below its upper bound.", [variable.name]))
        if variable.representation == "discrete" and not variable.values:
            out.append(finding("variable.values", "blocking", variable.name, f"{variable.name} is discrete and needs its permitted values.", [variable.name]))
    if not charter.variables:
        out.append(finding("variable.missing", "blocking", "variables", "No decision variable: state what the optimizer changes.", []))
    # Constraints
    out.extend(constraint_findings(charter, values, tables, sizes))
    # Objective and evaluator
    if charter.objective is None:
        out.append(finding("objective.missing", "blocking", "objective", "No objective: state the one number to improve, its direction and units.", []))
    settled = not any(row["code"].startswith("variable.") and row["severity"] == "blocking" for row in out)
    out.extend(evaluator_findings(charter, values, errors, sizes, registry, settled=settled))
    # Instances
    if not charter.instances:
        out.append(finding("instance.missing", "blocking", "instances", "No instance: name at least one condition to optimize.", []))
    for instance in charter.instances:
        unknown = [name for name in instance.values if name not in charter.quantities or charter.quantities[name].role != "input"]
        if unknown:
            out.append(finding("instance.unknown_input", "blocking", instance.name, f"Instance {instance.name} sets {', '.join(unknown)}, "
                "which are not inputs.", unknown))
            continue
        if instance.values:
            other = resolve(charter, instance.values)
            for name, message in other["errors"].items():
                if name not in errors:
                    out.append(finding("instance.relation", "blocking", f"{instance.name}:{name}", f"In instance {instance.name}: {message}", [name]))
    # Questions
    for question in charter.questions:
        if question.answer is None:
            out.append(finding("question.open", "blocking" if question.blocking else "warning", question.id,
                (f"Left to the formulator to decide: {question.question}" if question.sent else f"Open question: {question.question}"),
                question.about))
    waived = {waiver.key: waiver.reason for waiver in charter.waivers}
    for row in out:
        if row["key"] in waived and row["waivable"]:
            row["waived"] = waived[row["key"]]
        if row["severity"] == "blocking" and row["code"] != "question.open":
            row["suggestions"] = suggestions(row, charter)
    return out


def suggestions(row, charter) -> list[dict]:
    """Best-effort ways out of a blocking finding, from what the charter itself holds, so that a researcher with little
    background still has something to choose from (as the formulator's questions come with options). Each is one click on
    the Charter page: a waiver records the reason and keeps the charter as it is; a request asks the formulator in words,
    and it answers with options; an edit applies computed changes to the charter (the researcher's own, with a rationale).
    Nothing here invents a number: when a value is missing, the suggestion is to ask for it."""
    code, subject, about = row["code"], row["key"].split(":", 1)[1], row["about"]
    name = about[0] if about else None
    quantity = charter.quantities.get(name) if name else None
    units = f" in {quantity.units}" if quantity and quantity.units.strip() not in DIMENSIONLESS else ""
    ask = lambda label, text: {"label": label, "action": "request", "text": text}
    keep = lambda label, reason: {"label": label, "action": "waive", "reason": reason}
    out = []
    if code == "constraint.qualitative":
        constraint = next((c for c in charter.constraints if c.id == subject), None)
        statement = constraint.statement if constraint else subject
        out.append(keep("Keep it as a recorded criterion (not checked)",
            "Stated in words; kept as a recorded criterion the lab does not check or enforce."))
        out.append(ask("Ask the formulator for a checkable condition",
            f"Constraint {subject} (“{statement}”) is words only. Propose conditions the lab can check and offer them as options: "
            "a true/false test on named quantities (a limit a quantity must stay within), or a linear condition on the decision "
            "variables, with the thresholds the sources support; or say why it has to stay in words."))
    elif code == "quantity.no_value" and quantity:
        out.append(ask(f"Ask the formulator for the value of {name}",
            f"{name} ({quantity.description}) has no value. Give the value the sources state{units}, or the relation by which it "
            "follows from other quantities; if the sources disagree or are silent, offer each candidate as an option and say so."))
    elif code == "variable.bounds" and name:
        out.append(ask(f"Ask the formulator for the bounds of {name}",
            f"{name} needs a lower and an upper bound. Take them from the sources (physical, operational or budget limits), "
            "say which source each comes from, and offer alternatives as options if the sources leave room."))
    elif code == "variable.values" and name:
        out.append(ask(f"Ask the formulator for the permitted values of {name}",
            f"{name} is discrete and needs its permitted values. List them from the sources, with the source for each."))
    elif code == "quantity.range" and quantity:
        out.append(keep("Keep the value; the range was advisory", "The value stands; the range was advisory."))
        out.append(ask(f"Ask whether the value or the range of {name} is right",
            f"{row['message']} Say which is right, the value or the range, with the source, and offer both as options."))
    elif code == "constraint.violated":
        out.append(ask("Ask which to change: the values or the constraint",
            f"{row['message']} Say which input to change or whether the constraint should be relaxed, and offer the choices as options."))
        out.append(keep("Keep both and record the violation", "Recorded; the values stand for this campaign."))
    elif code == "constraint.infeasible":
        out.append(ask("Ask which constraint to relax", f"{row['message']} Propose which constraint to relax and by how much, as options."))
        out.append(keep("Keep them and record that no design meets all", "Recorded as it stands."))
    elif code == "text.literal_mismatch":
        out.append(ask("Ask the formulator to fix the text", f"{row['message']} Rewrite the text so it refers to the quantity by name, "
            "or move the number to the reference results; offer the rewrites as options."))
        out.append(keep("Keep the text as written", "The number in the text is kept as written."))
    elif code == "assumption.unaccepted" and not quantity:
        out.append(ask("Ask the formulator to ground or replace the assumption",
            f"{row['message']} Say what the sources support instead, or why the assumption is needed, and offer the choices as options."))
    elif code == "evaluator.mixed_values":
        out.append(ranges_edit(charter))
        out.append(ask("Ask the formulator for another way to encode them",
            f"{row['message']} Propose another encoding of the discrete variables that the lab accepts (one shared list of values, "
            "or ranges the evaluator rounds), as options with what each implies."))
    elif code.startswith("evaluator."):
        out.append(ask("Ask the formulator to repair how the charter feeds the evaluator", f"{row['message']} Repair how the charter "
            "feeds the evaluator (which quantity each of its fields takes, the objective, the decision variables) and offer the fixes as options."))
    if not any(item["action"] == "request" for item in out):
        out.append(ask("Ask the formulator to resolve it", f"Resolve this finding from the sources and offer the choices as options: {row['message']}"))
    return out


def grid(values) -> str:
    """A list of permitted values in words: "1, 2, 3, 4, 5" or "0.5 to 1.5 in 11 steps"."""
    shown = [f"{v:g}" for v in values]
    return ", ".join(shown) if len(shown) <= 6 else f"{shown[0]} to {shown[-1]} in {len(shown)} steps"


def ranges_edit(charter) -> dict:
    """One click: every discrete variable becomes a range from its lowest to its highest permitted value, the grid is kept in
    its description and in the evaluator's notes, and the evaluator to be built rounds to the nearest permitted value."""
    changes, kept = [], []
    for index, variable in enumerate(charter.variables):
        if variable.representation != "discrete" or not variable.values:
            continue
        values = sorted(variable.values)
        note = f"Permitted values: {grid(values)}; the evaluator rounds to the nearest."
        changes += [{"op": "set", "path": f"variables.{index}.representation", "value": "continuous"},
                    {"op": "set", "path": f"variables.{index}.lower", "value": values[0]},
                    {"op": "set", "path": f"variables.{index}.upper", "value": values[-1] if values[-1] > values[0] else values[0] + 1},
                    {"op": "set", "path": f"variables.{index}.values", "value": []},
                    {"op": "set", "path": f"variables.{index}.description", "value": f"{variable.description.rstrip('.')}. {note}"[:1000]}]
        kept.append(f"{variable.name}: {grid(values)}")
    notes = charter.evaluator.notes.rstrip() if charter.evaluator else ""
    rounding = "Round each of these to its nearest permitted value before evaluating: " + "; ".join(kept) + "."
    if rounding not in notes:
        changes.append({"op": "set", "path": "evaluator.notes", "value": (notes + "\n" + rounding).strip()[:20000]})
    return {"label": "Write them as ranges; the evaluator rounds to each grid", "action": "edit", "changes": changes,
            "rationale": "Discrete variables written as ranges the evaluator rounds, since the lab takes one list of values for all of them",
            "text": "Each discrete variable becomes a range from its lowest to its highest permitted value; its grid stays in its "
                    "description and in the evaluator's notes, so the evaluator rounds to it. Nothing about the problem changes."}


def unused_findings(charter) -> list[dict]:
    """Quantities that reach nothing: no evaluator field takes them and no relation, bound, shape or test uses them."""
    used = set()
    if charter.evaluator is not None:
        used |= set(charter.evaluator.configuration.values()) | set(charter.evaluator.fidelity.values())
    expressions = [q.expression for q in charter.quantities.values() if q.role == "derived"]
    expressions += [c.test for c in charter.constraints if c.test] + [c.bound for c in charter.constraints if isinstance(c.bound, str)]
    for variable in charter.variables:
        used |= {part for part in variable.shape if isinstance(part, str)}
        expressions += [bound for bound in (variable.lower, variable.upper) if isinstance(bound, str)]
    for expression in expressions:
        try:
            used |= names(expression)
        except ExpressionError:
            pass
    return [finding("quantity.unused", "warning", name, f"{name} reaches nothing: no evaluator field takes it, and no relation, bound, "
                    "shape or test uses it. Give it to the evaluator, or remove it.", [name])
            for name in charter.quantities if name not in used]


def constraint_findings(charter, values, tables, sizes):
    out, linear = [], []
    variables = {variable.name: variable for variable in charter.variables}
    for constraint in charter.constraints:
        if constraint.form == "qualitative":
            out.append(finding("constraint.qualitative", "blocking", constraint.id, f"“{constraint.statement}” is stated in words only: "
                "there is no condition the lab can evaluate, so no design can be checked against it and the optimizer cannot enforce it. "
                "Keep it as a recorded criterion that is not checked, or give it a checkable form.", []))
        elif constraint.form == "quantities":
            try:
                result = evaluate(constraint.test, values, tables)
            except ExpressionError as exc:
                out.append(finding("constraint.test", "blocking", constraint.id, f"Constraint {constraint.id}: {exc}.", []))
                continue
            if not isinstance(result, bool):
                out.append(finding("constraint.test", "blocking", constraint.id, f"Constraint {constraint.id}'s test does not give true or false.", []))
            elif not result:
                out.append(finding("constraint.violated", "blocking", constraint.id, f"The values break constraint {constraint.id}: "
                    f"{render(constraint.statement, values, charter)}", sorted(names(constraint.test))))
        elif constraint.form == "linear":
            missing = [term.variable for term in constraint.terms if term.variable not in variables]
            if missing:
                out.append(finding("constraint.variable", "blocking", constraint.id, f"Constraint {constraint.id} uses {', '.join(missing)}, "
                    "which are not decision variables.", missing))
                continue
            wrong = [term.variable for term in constraint.terms
                     if term.weights is not None and term.variable in sizes and len(term.weights) != sizes[term.variable]]
            if wrong:
                out.append(finding("constraint.weights", "blocking", constraint.id, f"Constraint {constraint.id} gives {', '.join(wrong)} "
                    "a number of weights different from its size.", wrong))
                continue
            try:
                limit = bound(constraint.bound, values, tables)
            except ExpressionError as exc:
                out.append(finding("constraint.test", "blocking", constraint.id, f"Constraint {constraint.id}'s bound: {exc}.", []))
                continue
            linear.append((constraint, limit))
    if linear and all(term.variable in sizes for constraint, _ in linear for term in constraint.terms):
        out.extend(feasibility(linear, variables, sizes, values, tables))
    return out


def element_bounds(variable, values, tables):
    if variable.representation == "binary":
        return 0.0, 1.0
    if variable.representation == "discrete":
        return (min(variable.values), max(variable.values)) if variable.values else (None, None)
    return bound(variable.lower, values, tables), bound(variable.upper, values, tables)


def feasibility(linear, variables, sizes, values, tables):
    """Whether the linear constraints together admit any design, even allowing fractional values."""
    from scipy.optimize import linprog
    used = sorted({term.variable for constraint, _ in linear for term in constraint.terms})
    uniform = all(term.weights is None for constraint, _ in linear for term in constraint.terms)
    try:
        limits = {name: element_bounds(variables[name], values, tables) for name in used}
    except ExpressionError:
        return []
    if uniform:   # Only each variable's total matters, so one aggregated column per variable is exact.
        columns = {name: index for index, name in enumerate(used)}
        bounds = [(None if limits[n][0] is None else limits[n][0] * sizes[n], None if limits[n][1] is None else limits[n][1] * sizes[n]) for n in used]
        def row(constraint):
            line = [0.0] * len(used)
            for term in constraint.terms:
                weight = 1.0 if term.weight == "sum" else 1.0 / sizes[term.variable] if term.weight == "mean" else float(term.weight)
                line[columns[term.variable]] += weight
            return line
    else:
        total = sum(sizes[name] for name in used)
        if total > LP_ELEMENT_LIMIT:
            return [finding("constraint.untested", "warning", "linear", f"The linear constraints act on {total} elements with "
                "individual weights; that is too many to test for feasibility here.", [])]
        offsets, at = {}, 0
        for name in used:
            offsets[name], at = at, at + sizes[name]
        bounds = [limits[name] for name in used for _ in range(sizes[name])]
        def row(constraint):
            line = [0.0] * total
            for term in constraint.terms:
                n = sizes[term.variable]
                weights = term.weights or [1.0 if term.weight == "sum" else 1.0 / n if term.weight == "mean" else float(term.weight)] * n
                for index, weight in enumerate(weights):
                    line[offsets[term.variable] + index] += weight
            return line
    upper_rows, upper_values, equal_rows, equal_values = [], [], [], []
    for constraint, limit in linear:
        line = row(constraint)
        if constraint.relation == "eq":
            equal_rows.append(line); equal_values.append(limit)
        elif constraint.relation == "le":
            upper_rows.append(line); upper_values.append(limit)
        else:
            upper_rows.append([-value for value in line]); upper_values.append(-limit)
    result = linprog([0.0] * len(bounds), A_ub=upper_rows or None, b_ub=upper_values or None,
                     A_eq=equal_rows or None, b_eq=equal_values or None, bounds=bounds, method="highs")
    if result.status == 2:
        ids = [constraint.id for constraint, _ in linear]
        return [finding("constraint.infeasible", "blocking", "+".join(ids), "No design can meet the linear constraints "
            f"{', '.join(ids)} together, even with fractional values. Relax one of them.", ids)]
    return []


def evaluator_findings(charter, values, errors, sizes, registry, settled=True):
    binding, out = charter.evaluator, []
    if binding is None:
        return [finding("evaluator.missing", "blocking", "evaluator", "No evaluator: name an installed problem, or declare one to be built.", [])]
    for field, name in {**binding.configuration, **binding.fidelity}.items():
        if name not in charter.quantities:
            out.append(finding("evaluator.unknown_quantity", "blocking", field, f"Evaluator field {field} takes {name}, which is not a quantity.", []))
    if set(binding.configuration) & set(binding.fidelity):
        out.append(finding("evaluator.field_twice", "blocking", "fields", "A field is listed both as configuration and as fidelity.", []))
    if out:
        return out
    if binding.kind == "declared":
        if binding.problem_id in registry.ids():
            out.append(finding("evaluator.declared_id", "blocking", binding.problem_id, f"{binding.problem_id} is an installed problem; "
                "a declared problem needs a new identifier, or use the installed one.", []))
        kinds = {variable.representation for variable in charter.variables}
        if len(kinds) > 1:
            out.append(finding("evaluator.mixed_variables", "blocking", "variables", "A declared problem's decision variables must share "
                "one representation (binary, discrete or continuous); encode the others, or ask for an evaluator that accepts them.", []))
        discrete = [variable for variable in charter.variables if variable.representation == "discrete"]
        if len({tuple(variable.values) for variable in discrete}) > 1:
            grids = "; ".join(f"{variable.name} takes {grid(variable.values)}" for variable in discrete)
            out.append(finding("evaluator.mixed_values", "blocking", "variables", "The lab can give an evaluator that is still to be built "
                f"only one list of permitted values, shared by every discrete variable, and these have different lists: {grids}. This is "
                "a limit of the lab, not of your problem. The usual way out is to write each as a range from its lowest to its highest "
                "value and have the evaluator round to the nearest permitted value.", [variable.name for variable in discrete]))
        if not binding.notes.strip():
            out.append(finding("evaluator.notes", "warning", "notes", "Say what the evaluator to be built must compute, and from which code.", []))
        ready = (settled and charter.objective is not None and charter.variables and len(sizes) == len(charter.variables)
                 and not any(row["severity"] == "blocking" for row in out)
                 and not any(name in errors or values.get(name) is None for name in {**binding.configuration, **binding.fidelity}.values()))
        if ready:
            try:
                manifest(charter, values)
            except Exception as exc:   # noqa: BLE001 - whatever fails here is a finding for the formulator or a developer, never a dead page
                out.append({**finding("evaluator.declared_invalid", "blocking", binding.problem_id, "The declared problem cannot be assembled "
                    "for an evaluator from the charter as it stands: a technical check of its variables, bounds and constraints failed. "
                    "This is for the formulator or a developer to fix, not a scientific decision.", []), "detail": str(exc)})
        return out
    if binding.problem_id not in registry.ids():
        return [finding("evaluator.unknown_problem", "blocking", binding.problem_id, f"{binding.problem_id} is not an installed problem.", [])]
    definition = registry.get(binding.problem_id).describe()
    for kind, schema, fields in (("configuration", definition.configuration_schema, binding.configuration),
                                 ("fidelity", definition.fidelity_schema, binding.fidelity)):
        declared = set((schema or {}).get("properties", {}))
        required = set((schema or {}).get("required", []))
        for field in sorted(required - set(fields)):
            out.append(finding("evaluator.unmapped", "blocking", f"{kind}:{field}", f"The evaluator's {kind} field {field} takes no quantity.", []))
        if declared and (schema or {}).get("additionalProperties", True) is False:
            for field in sorted(set(fields) - declared):
                out.append(finding("evaluator.unknown_field", "blocking", f"{kind}:{field}", f"The evaluator has no {kind} field {field}.", []))
    if out or any(name in errors or values.get(name) is None for name in {**binding.configuration, **binding.fidelity}.values()):
        return out
    try:
        problem = evaluator_facts(charter, values, registry)
    except (ValueError, TypeError) as exc:
        return [finding("evaluator.rejects", "blocking", binding.problem_id, f"The evaluator refuses these values: {exc}", [])]
    if charter.objective is not None:
        primary = problem.primary_objective
        if (charter.objective.name, charter.objective.direction) != (primary.name, primary.direction):
            out.append(finding("evaluator.objective", "blocking", "objective", f"{binding.problem_id} {primary.direction}s {primary.name}, "
                f"not {charter.objective.direction} {charter.objective.name}. Use its objective, or declare a problem whose evaluator computes the one wanted.", []))
    reported = {objective.name for objective in [problem.primary_objective, *problem.extra_metrics]}
    for metric in charter.metrics:
        if metric.name not in reported:
            out.append(finding("evaluator.metric", "warning", metric.name, f"{binding.problem_id} does not report {metric.name}.", []))
    if sizes and len(sizes) == len(charter.variables):
        total = sum(sizes.values())
        kinds = {variable.representation for variable in charter.variables}
        schema = problem.candidate_schema
        if total != schema.dimensions or kinds != {schema.representation}:
            out.append(finding("evaluator.variables", "blocking", "variables", f"The decision variables add up to {total} "
                f"{'/'.join(sorted(kinds))} values; {binding.problem_id} takes {schema.dimensions} {schema.representation} values "
                "for these inputs.", [variable.name for variable in charter.variables]))
    return out


def blocking(rows) -> list[dict]:
    return [row for row in rows if row["severity"] == "blocking" and not row.get("waived")]


# Views -------------------------------------------------------------------------------------------------
def describe(charter, registry=None) -> dict:
    """What a page or an agent needs to read a charter: values, texts with values, findings, references."""
    charter = parse(charter)
    resolved = resolve(charter)
    values = resolved["values"]
    rows = findings(charter, registry)
    return {"values": values, "errors": resolved["errors"],
            "rendered": {location: render(text, values, charter) for location, text in texts(charter).items()},
            "references": [{"applies": applies(reference, values)} for reference in charter.references],
            "findings": rows, "blocking": len(blocking(rows)),
            "instances": [{"name": instance.name, "values": resolve(charter, instance.values)["values"] if instance.values else values}
                          for instance in charter.instances]}


def applies(reference, values) -> bool:
    for name, value in reference.holds_at.items():
        current = values.get(name)
        if isinstance(value, (int, float)) and isinstance(current, (int, float)) and not isinstance(value, bool):
            if not math.isclose(value, current, rel_tol=1e-9, abs_tol=1e-12):
                return False
        elif value != current:
            return False
    return True


# Differences -------------------------------------------------------------------------------------------
def diff(before, after) -> list[dict]:
    """What changed between two charters, values computed for both: one row per change."""
    before, after = parse(before), parse(after)
    old, new = resolve(before)["values"], resolve(after)["values"]
    rows = []
    for name in sorted(set(before.quantities) | set(after.quantities)):
        a, b = before.quantities.get(name), after.quantities.get(name)
        if a is None or b is None:
            quantity = a or b
            rows.append({"part": "quantity", "name": name, "change": "removed" if b is None else "added",
                         "before": show(old.get(name), quantity.units) if a else None, "after": show(new.get(name), quantity.units) if b else None,
                         "role": quantity.role})
            continue
        if a.role != b.role or a.expression != b.expression:
            rows.append({"part": "relation", "name": name, "change": "changed", "before": a.expression or "typed in",
                         "after": b.expression or "typed in", "role": b.role})
        if old.get(name) != new.get(name):
            rows.append({"part": "value", "name": name, "change": "changed", "before": show(old.get(name), a.units),
                         "after": show(new.get(name), b.units), "role": b.role})
        elif a.units != b.units or a.range != b.range or a.kind != b.kind or a.description != b.description:
            rows.append({"part": "quantity", "name": name, "change": "changed", "before": a.description, "after": b.description, "role": b.role})
    for part, key in (("variables", "name"), ("constraints", "id"), ("metrics", "name"), ("instances", "name"),
                      ("references", "statement"), ("questions", "id"), ("assumptions", "statement")):
        a = {getattr(item, key): item for item in getattr(before, part)}
        b = {getattr(item, key): item for item in getattr(after, part)}
        for name in sorted(set(a) | set(b), key=str):
            if name not in b:
                rows.append({"part": part[:-1], "name": name, "change": "removed"})
            elif name not in a:
                rows.append({"part": part[:-1], "name": name, "change": "added"})
            elif a[name] != b[name]:
                rows.append({"part": part[:-1], "name": name, "change": "changed"})
    for part in ("objective", "evaluator", "title", "tables"):
        if getattr(before, part) != getattr(after, part):
            rows.append({"part": part, "name": part, "change": "changed"})
    for location in ("text", "summary"):
        a, b = render(getattr(before, location), old, before), render(getattr(after, location), new, after)
        if getattr(before, location) != getattr(after, location):
            rows.append({"part": location, "name": location, "change": "changed", "before": a, "after": b})
    return rows


# Changes -----------------------------------------------------------------------------------------------
def _container(document, path: list[str], create=False):
    node = document
    for segment in path:
        node = _child(node, segment, create)
    return node


def _child(node, segment, create=False):
    if isinstance(node, dict):
        if segment not in node:
            if not create:
                raise ValueError(f"no {segment}")
            node[segment] = {}
        return node[segment]
    if isinstance(node, list):
        index = _index(node, segment)
        return node[index]
    raise ValueError(f"cannot step into {segment}")


def _index(items: list, segment: str) -> int:
    for index, item in enumerate(items):
        if isinstance(item, dict) and segment in (item.get("id"), item.get("name")):
            return index
    if segment.isdigit() and int(segment) < len(items):
        return int(segment)
    raise ValueError(f"no item {segment}")


def apply_changes(charter, changes: list[dict], *, origin: str | None = None) -> dict:
    """A new charter with changes applied in order. Values are only ever computed here, never taken on trust.

    ``set`` (path + value, or path + expression evaluated once against the current values), ``add`` (append to a
    list), ``remove`` (path), and ``solve`` (an input chosen so that a derived quantity takes a wanted value).
    ``origin`` marks inputs whose value changed (the researcher's, once a proposal is accepted).
    """
    document = copy.deepcopy(parse(charter).model_dump(mode="json"))
    changed = set()
    for number, change in enumerate(changes, 1):
        op = change.get("op")
        try:
            if op == "solve":
                name = change["input"]
                document["quantities"][name]["value"] = solve(document, name, change["target"], change["value"])
                changed.add(name)
                continue
            path = [part for part in str(change.get("path", "")).split(".") if part]
            if not path:
                raise ValueError("a change needs a path")
            if path[0] == "quantities" and len(path) >= 3 and path[2] in {"value", "expression", "role"}:
                quantity = document["quantities"].get(path[1])
                if quantity and quantity["role"] == "derived" and path[2] == "value":
                    raise ValueError(f"{path[1]} is derived; change its inputs, its expression, or use solve")
            parent, last = _container(document, path[:-1], create=op == "set"), path[-1]
            if op == "set":
                if "expression" in change and "value" not in change:
                    current = resolve(document)["values"]
                    tables = {key: table["points"] for key, table in document.get("tables", {}).items()}
                    value = evaluate(change["expression"], current, tables)
                else:
                    value = change.get("value")
                if isinstance(parent, list):
                    parent[_index(parent, last)] = value
                else:
                    parent[last] = value
                if path[0] == "quantities" and (len(path) == 2 or path[2:] == ["value"]):
                    changed.add(path[1])
            elif op == "add":
                target = _child(parent, last) if isinstance(parent, list) else parent.setdefault(last, [])
                if not isinstance(target, list):
                    raise ValueError(f"{'.'.join(path)} is not a list")
                target.append(change.get("value"))
            elif op == "remove":
                if isinstance(parent, list):
                    parent.pop(_index(parent, last))
                elif last in parent:
                    del parent[last]
                else:
                    raise ValueError(f"no {last}")
            else:
                raise ValueError("op must be set, add, remove or solve")
        except (KeyError, ValueError, TypeError, ExpressionError) as exc:
            raise ValueError(f"Change {number} ({op} {change.get('path') or change.get('input') or ''}): {exc}") from None
    if origin:
        for name in changed:
            quantity = document["quantities"].get(name)
            if quantity and quantity.get("role") == "input":
                quantity["origin"], quantity["accepted"] = origin, False
    return ProblemCharter.model_validate(document).model_dump(mode="json")


def solve(document, name: str, target: str, wanted: float, samples: int = 801) -> float:
    """The value of input ``name`` that makes derived ``target`` equal ``wanted``: a bracketed root, nearest the current value."""
    from scipy.optimize import brentq
    charter = ProblemCharter.model_validate(document)
    quantity, goal = charter.quantities.get(name), charter.quantities.get(target)
    if quantity is None or quantity.role != "input" or quantity.kind != "number":
        raise ValueError(f"{name} is not a number input")
    if goal is None or goal.role != "derived":
        raise ValueError(f"{target} is not a derived quantity")
    current = float(quantity.value) if isinstance(quantity.value, (int, float)) else 0.0
    span = 100 * max(abs(current), 1.0)
    low, high = quantity.range or (None, None)
    low = current - span if low is None else float(low)
    high = current + span if high is None else float(high)

    def gap(x):
        result = resolve(charter, {name: x})
        value = result["values"].get(target)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return value - float(wanted)

    xs = [low + (high - low) * i / (samples - 1) for i in range(samples)]
    gaps = [gap(x) for x in xs]
    roots = [x for x, g in zip(xs, gaps) if g == 0]
    for (a, ga), (b, gb) in zip(zip(xs, gaps), zip(xs[1:], gaps[1:])):
        if ga is not None and gb is not None and ga * gb < 0:
            roots.append(brentq(lambda x: gap(x), a, b, xtol=1e-13, rtol=4 * 2.220446049250313e-16, maxiter=200))
    if not roots:
        raise ValueError(f"no value of {name} between {show(low)} and {show(high)} gives {target} = {show(wanted, goal.units)}")
    root = min(roots, key=lambda x: abs(x - current))
    # The shortest decimal that still gives the wanted value, so 3.000000000000014 is stored as 3.
    for digits in (6, 8, 10, 12):
        candidate = float(f"{root:.{digits}g}")
        miss = gap(candidate)
        if miss is not None and abs(miss) <= 1e-9 * max(1.0, abs(float(wanted))):
            return candidate
    return root


# Compilation -------------------------------------------------------------------------------------------
def compile_setups(charter, registry=None) -> list[dict]:
    """Today's campaign task input, one per instance. Refused while a blocking finding is open."""
    charter = parse(charter)
    open_rows = blocking(findings(charter, registry))
    if open_rows:
        raise ValueError("The charter has blocking findings: " + "; ".join(row["message"] for row in open_rows[:5]))
    from optimization_framework.contracts.problem_imports import ProblemSetup
    binding, setups = charter.evaluator, []
    for instance in charter.instances:
        values = resolve(charter, instance.values)["values"]
        configuration = {field: values[name] for field, name in binding.configuration.items()}
        fidelity = {field: values[name] for field, name in binding.fidelity.items()}
        if binding.kind == "installed":
            setup = ProblemSetup(name=instance.name, split=instance.split, problem_id=binding.problem_id,
                                 configuration=configuration, fidelity=fidelity, rationale=instance.note)
        else:
            setup = ProblemSetup(name=instance.name, split=instance.split, configuration=configuration, fidelity=fidelity,
                                 evaluator_manifest=manifest(charter, values), rationale=instance.note)
        setup.task_input()
        setups.append(setup.model_dump(mode="json"))
    return setups


def manifest(charter, values):
    """The declared problem a charter describes, for an evaluator to be built."""
    from optimization_framework.contracts.evaluators import EvaluatorManifest
    from optimization_framework.contracts.problems import CandidateSchema, Constraint, Objective
    tables = {name: table.points for name, table in charter.tables.items()}
    sizes = {variable.name: size(variable, values) for variable in charter.variables}
    representation = charter.variables[0].representation
    bounds, offsets, at = [], {}, 0
    for variable in charter.variables:
        offsets[variable.name], at = at, at + sizes[variable.name]
        if representation == "continuous":
            bounds += [(bound(variable.lower, values, tables), bound(variable.upper, values, tables))] * sizes[variable.name]
    linear = []
    for constraint in charter.constraints:
        if constraint.form != "linear":
            continue
        line = [0.0] * at
        for term in constraint.terms:
            n = sizes[term.variable]
            weights = term.weights or [1.0 if term.weight == "sum" else 1.0 / n if term.weight == "mean" else float(term.weight)] * n
            for index, weight in enumerate(weights):
                line[offsets[term.variable] + index] += weight
        linear.append(Constraint(name=constraint.id, coefficients=line, relation=constraint.relation,
                                 bound=bound(constraint.bound, values, tables)))
    discrete = charter.variables[0].values if representation == "discrete" else []
    candidate = CandidateSchema(representation=representation, dimensions=at, bounds=bounds, values=discrete, constraints=linear)

    def schema(fields):
        properties = {}
        for field, name in fields.items():
            quantity = charter.quantities[name]
            rule = {"description": (quantity.description + (f" ({quantity.units})" if quantity.units.strip() not in DIMENSIONLESS else ""))[:500]}
            if quantity.kind == "data":   # a table or a structure: typed by what it holds, any JSON otherwise
                value = values.get(name)
                if isinstance(value, list):
                    rule["type"] = "array"
                elif isinstance(value, dict):
                    rule["type"] = "object"
            else:
                rule["type"] = {"number": "number", "integer": "integer", "text": "string", "boolean": "boolean"}[quantity.kind]
            if quantity.kind in {"number", "integer"} and quantity.range:
                low, high = quantity.range
                if low is not None:
                    rule["minimum"] = low
                if high is not None:
                    rule["maximum"] = high
            properties[field] = rule
        return {"type": "object", "properties": properties, "required": sorted(fields), "additionalProperties": False}

    binding, objective = charter.evaluator, charter.objective
    return EvaluatorManifest(id=binding.problem_id, name=charter.title[:300], candidate_schema=candidate,
        primary_objective=Objective(name=objective.name, direction=objective.direction, units=objective.units),
        extra_metrics=[Objective(name=m.name, direction=m.direction or "maximize", units=m.units) for m in charter.metrics],
        configuration_schema=schema(binding.configuration), configuration={f: values[n] for f, n in binding.configuration.items()},
        fidelity_schema=schema(binding.fidelity), fidelity={f: values[n] for f, n in binding.fidelity.items()},
        deterministic=binding.deterministic)


# Conversion --------------------------------------------------------------------------------------------
def from_setups(title: str, setups: list[dict], *, text: str = "", summary: str = "", origin: str = "source", registry=None) -> dict:
    """A charter for setups made before charters existed: every field becomes an input, without relations.

    The configuration and fidelity of the first setup are the charter's inputs; later setups become
    instances that differ from it. Units are not known and are left for the formulator to add.
    """
    from optimization_framework.contracts.problem_imports import ProblemSetup
    from optimization_framework.evaluation.registry import problems
    registry = registry or problems
    parsed = [ProblemSetup.model_validate(setup) for setup in setups]
    first = parsed[0]
    declared = first.evaluator_manifest
    if declared is not None:
        configuration_schema, fidelity_schema = declared.configuration_schema, declared.fidelity_schema
        problem = declared.resolve("unresolved", first.configuration, first.fidelity)
        problem_id = declared.id
    else:
        definition = registry.get(first.problem_id).describe()
        configuration_schema, fidelity_schema = definition.configuration_schema, definition.fidelity_schema
        problem = registry.resolve(first.problem_id, first.configuration, first.fidelity)
        problem_id = first.problem_id

    def name_for(field, taken):
        name = re.sub(r"[^a-z0-9_]", "_", field.lower()).strip("_") or "value"
        name = name if re.match(r"^[a-z]", name) else "q_" + name
        return name if name not in taken else "fidelity_" + name

    def resolve_with(configuration, fidelity):
        if declared is not None:
            return declared.resolve("unresolved", configuration, fidelity)
        return registry.resolve(problem_id, configuration, fidelity)

    def derived_by_evaluator(kind, field):
        """A structured field the evaluator fills in itself, to the same value, when it is left out."""
        configuration, fidelity = dict(problem.configuration), dict(problem.fidelity)
        (configuration if kind == "configuration" else fidelity).pop(field)
        try:
            return resolve_with(configuration, fidelity) == problem
        except (ValueError, TypeError):
            return False

    quantities, configuration, fidelity = {}, {}, {}
    for kind, schema, values, target in (("configuration", configuration_schema, problem.configuration, configuration),
                                         ("fidelity", fidelity_schema, problem.fidelity, fidelity)):
        properties = (schema or {}).get("properties", {})
        for field, value in values.items():
            rule = properties.get(field, {})
            if isinstance(value, (list, dict)):
                if derived_by_evaluator(kind, field):
                    continue
                quantity_kind = "data"
            else:
                quantity_kind = {"integer": "integer", "number": "number", "boolean": "boolean", "string": "text"}.get(rule.get("type")) or (
                    "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "text")
            name = name_for(field, quantities)
            quantities[name] = {"description": rule.get("description") or rule.get("title") or f"{kind.capitalize()} field {field}",
                                "kind": quantity_kind, "role": "input", "value": value, "units": "", "origin": origin}
            target[field] = name
    schema = problem.candidate_schema
    # The size follows the integer inputs whose value (or product of two) is the candidate's size, when the values show it.
    whole = [name for name, q in quantities.items() if q["kind"] == "integer" and isinstance(q["value"], int) and q["value"] > 1]
    single = [name for name in whole if quantities[name]["value"] == schema.dimensions]
    pairs = [[a, b] for i, a in enumerate(whole) for b in whole[i + 1:] if quantities[a]["value"] * quantities[b]["value"] == schema.dimensions]
    shape = [single[0]] if len(single) == 1 else pairs[0][::-1] if len(pairs) == 1 and not single else [schema.dimensions]
    variable = {"name": "design", "description": f"The candidate {problem_id} evaluates", "representation": schema.representation,
                "shape": shape}
    if schema.representation == "continuous" and schema.bounds:
        lows, highs = {low for low, _ in schema.bounds}, {high for _, high in schema.bounds}
        if len(lows) == 1 and len(highs) == 1:
            variable.update(lower=lows.pop(), upper=highs.pop())
    if schema.representation == "discrete":
        variable["values"] = list(schema.values)
    instances = []
    by_field = {**{f: n for f, n in configuration.items()}, **{f: n for f, n in fidelity.items()}}
    for setup in parsed:
        resolved = (setup.evaluator_manifest.resolve("unresolved", setup.configuration, setup.fidelity) if setup.evaluator_manifest
                    else registry.resolve(setup.problem_id, setup.configuration, setup.fidelity))
        given = {**resolved.configuration, **resolved.fidelity}
        differs = {by_field[field]: value for field, value in given.items()
                   if field in by_field and quantities[by_field[field]]["value"] != value}
        instances.append({"name": setup.name, "split": setup.split, "values": differs, "note": setup.rationale})
    objective = problem.primary_objective
    document = {"title": title[:200], "summary": summary[:3000], "text": text[:20000], "quantities": quantities,
                "variables": [variable],
                "objective": {"name": objective.name, "direction": objective.direction, "units": objective.units,
                              "definition": f"As computed by the evaluator of {problem_id}."},
                "metrics": [{"name": metric.name, "units": metric.units, "direction": metric.direction} for metric in problem.extra_metrics],
                "evaluator": {"kind": "declared" if declared else "installed", "problem_id": problem_id,
                              "configuration": configuration, "fidelity": fidelity,
                              "deterministic": declared.deterministic if declared else True},
                "instances": instances}
    return ProblemCharter.model_validate(document).model_dump(mode="json")


def same(left: Any, right: Any) -> bool:
    return parse(left).model_dump(mode="json") == parse(right).model_dump(mode="json")
