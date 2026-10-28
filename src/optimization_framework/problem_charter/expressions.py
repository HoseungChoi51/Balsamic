"""A small, whitelisted expression language for relations between quantities.

Expressions are parsed with ``ast`` and walked node by node; nothing is passed to ``eval``. Only
arithmetic, comparisons, boolean logic, conditional expressions, named quantities and the functions
below are allowed. Numbers are computed as floats, so no expression can build a huge integer.

A name can hold a vector (a list), such as a decision variable with several entries in a design constraint (N9).
Arithmetic and comparisons act entry by entry (a number pairs with every entry), the one-argument functions map over
the entries, and the vector functions reduce one: ``sum``, ``min``, ``max``, ``count`` (the entries that are not 0 or
false), ``len``, ``all``, ``any``, ``at(v, i)`` (entry i, from 0) and ``diff`` (each entry minus the one before). A
comparison of vectors gives one true/false per entry; ``all`` or ``any`` makes it one.
"""
from __future__ import annotations

import ast
import bisect
import math
import operator

MAX_LENGTH = 1000
MAX_NODES = 400


class ExpressionError(ValueError):
    pass


def _real(value):
    if isinstance(value, complex):
        raise ExpressionError("the result is not a real number")
    return value


FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh, "hypot": math.hypot,
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log10": math.log10, "log2": math.log2,
    "abs": abs, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil, "round": round,
    "rad": math.radians, "deg": math.degrees,
}
VECTOR = {"sum", "count", "len", "all", "any", "at", "diff"}
CONSTANTS = {"pi": math.pi, "e": math.e}
TRIGONOMETRIC = {"sin", "cos", "tan"}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
           ast.Eq: operator.eq, ast.NotEq: operator.ne}
ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Constant,
           ast.Load, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, *BINARY, *COMPARE)


def parse(expression: str) -> ast.Expression:
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("the expression is empty")
    if len(expression) > MAX_LENGTH:
        raise ExpressionError(f"the expression is longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"cannot read the expression: {exc.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExpressionError("the expression is too long")
    for node in nodes:
        if not isinstance(node, ALLOWED):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in an expression")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or (node.func.id not in FUNCTIONS and node.func.id not in VECTOR
                                                     and node.func.id != "table"):
                name = node.func.id if isinstance(node.func, ast.Name) else "this call"
                raise ExpressionError(f"unknown function {name}")
            if node.keywords:
                raise ExpressionError("functions take positional arguments only")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool)):
            raise ExpressionError("only numbers, text and true/false are allowed as constants")
    return tree


def _table_name(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    raise ExpressionError("table() takes the table's name first")


def names(expression: str) -> set[str]:
    """The quantity names an expression reads (not functions, constants or table names)."""
    tree = parse(expression)
    skip = {id(node.args[0]) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "table" and node.args}
    callees = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
            and id(node) not in skip and id(node) not in callees and node.id not in CONSTANTS}


def degree_arguments(expression: str, units: dict[str, str]) -> list[str]:
    """Quantities in degrees passed straight to sin, cos or tan, which take radians."""
    found = []
    for node in ast.walk(parse(expression)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in TRIGONOMETRIC:
            for argument in node.args:
                if isinstance(argument, ast.Name) and units.get(argument.id, "").strip().lower() in {"deg", "degree", "degrees", "°"}:
                    found.append(argument.id)
    return found


def interpolate(points, x: float, name: str = "table") -> float:
    xs = [p[0] for p in points]
    if not xs[0] <= x <= xs[-1]:
        raise ExpressionError(f"{x:g} is outside table {name} ({xs[0]:g} to {xs[-1]:g}); tables are not extrapolated")
    index = bisect.bisect_left(xs, x)
    if xs[index] == x:
        return float(points[index][1])
    (x0, y0), (x1, y1) = points[index - 1], points[index]
    return float((y1 - y0) / (x1 - x0) * (x - x0) + y0)


def _number(value):
    return float(value) if isinstance(value, int) and not isinstance(value, bool) else value


def _vector(value) -> bool:
    return isinstance(value, list)


def _entries(value, what: str) -> list:
    if not _vector(value):
        raise ExpressionError(f"{what} takes a vector")
    return value


def _pairwise(function, left, right):
    """A binary operation, entry by entry when either side is a vector; a number pairs with every entry."""
    if not _vector(left) and not _vector(right):
        return function(left, right)
    if _vector(left) and _vector(right) and len(left) != len(right):
        raise ExpressionError(f"the vectors have {len(left)} and {len(right)} entries")
    size = len(left) if _vector(left) else len(right)
    pick = lambda side, index: side[index] if _vector(side) else side
    return [function(pick(left, index), pick(right, index)) for index in range(size)]


def _flat(arguments) -> list:
    return [entry for argument in arguments for entry in (argument if _vector(argument) else [argument])]


def _vector_call(name, arguments):
    if name in {"sum", "count", "len", "all", "any", "diff"}:
        if len(arguments) != 1:
            raise ExpressionError(f"{name}() takes one vector")
        entries = _entries(arguments[0], f"{name}()")
        if name == "sum":
            return float(sum(float(entry) for entry in entries))
        if name == "count":
            return float(sum(1 for entry in entries if entry))
        if name == "len":
            return float(len(entries))
        if name == "diff":
            return [b - a for a, b in zip(entries, entries[1:])]
        return all(bool(entry) for entry in entries) if name == "all" else any(bool(entry) for entry in entries)
    if len(arguments) != 2:
        raise ExpressionError("at() takes a vector and an index")
    entries, index = _entries(arguments[0], "at()"), arguments[1]
    if _vector(index) or isinstance(index, bool) or not isinstance(index, (int, float)) or index != int(index):
        raise ExpressionError("at() takes a whole-number index")
    if not 0 <= int(index) < len(entries):
        raise ExpressionError(f"index {int(index)} is outside a vector of {len(entries)} entries")
    return entries[int(index)]


def evaluate(expression: str, values: dict, tables: dict | None = None):
    """The value of an expression, given computed values by name and tables by name (lists of points).

    A value that is a list is a vector (see the module's note); the result can be one too."""
    tables = tables or {}
    tree = parse(expression)

    def run(node):
        if isinstance(node, ast.Expression):
            return run(node.body)
        if isinstance(node, ast.Constant):
            return _number(node.value)
        if isinstance(node, ast.Name):
            if node.id in values:
                value = values[node.id]
                if value is None:
                    raise ExpressionError(f"{node.id} has no value")
                if isinstance(value, (list, tuple)):
                    return [_number(entry) for entry in value]
                return _number(value)
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise ExpressionError(f"unknown name {node.id}")
        if isinstance(node, ast.BinOp):
            function = BINARY[type(node.op)]
            return _pairwise(lambda a, b: _real(function(a, b)), run(node.left), run(node.right))
        if isinstance(node, ast.UnaryOp):
            operand = run(node.operand)
            if _vector(operand):
                if isinstance(node.op, ast.Not):
                    raise ExpressionError("'not' takes one true/false; use all() or any() on a vector")
                return [-entry if isinstance(node.op, ast.USub) else +entry for entry in operand]
            return not operand if isinstance(node.op, ast.Not) else (-operand if isinstance(node.op, ast.USub) else +operand)
        if isinstance(node, ast.BoolOp):
            results = [run(value) for value in node.values]
            if any(_vector(result) for result in results):
                raise ExpressionError("'and' and 'or' take one true/false each; use all() or any() on a vector")
            return all(results) if isinstance(node.op, ast.And) else any(results)
        if isinstance(node, ast.Compare):
            left, result = run(node.left), True
            for op, comparator in zip(node.ops, node.comparators):
                right = run(comparator)
                step = _pairwise(COMPARE[type(op)], left, right)
                result = _pairwise(lambda a, b: bool(a and b), result, step) if _vector(step) or _vector(result) else result and step
                left = right
            return result
        if isinstance(node, ast.IfExp):
            test = run(node.test)
            if _vector(test):
                raise ExpressionError("a condition takes one true/false; use all() or any() on a vector")
            return run(node.body) if test else run(node.orelse)
        if isinstance(node, ast.Call):
            if node.func.id == "table":
                if len(node.args) != 2:
                    raise ExpressionError("table() takes a table name and one value")
                name = _table_name(node.args[0])
                if name not in tables:
                    raise ExpressionError(f"unknown table {name}")
                return interpolate(tables[name], run(node.args[1]), name)
            arguments = [run(argument) for argument in node.args]
            if node.func.id in VECTOR:
                return _vector_call(node.func.id, arguments)
            function = FUNCTIONS[node.func.id]
            if node.func.id in {"min", "max"} and any(_vector(argument) for argument in arguments):
                entries = _flat(arguments)
                if not entries:
                    raise ExpressionError(f"{node.func.id}() of an empty vector")
                return function(entries)
            if len(arguments) == 1 and _vector(arguments[0]):
                return [_real(function(entry)) for entry in arguments[0]]
            if any(_vector(argument) for argument in arguments):
                raise ExpressionError(f"{node.func.id}() takes numbers, not a vector")
            return _real(function(*arguments))
        raise ExpressionError(f"'{type(node).__name__}' is not allowed in an expression")

    try:
        result = run(tree)
    except ExpressionError:
        raise
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ExpressionError(str(exc) or type(exc).__name__) from None
    for entry in result if _vector(result) else [result]:
        if isinstance(entry, float) and not math.isfinite(entry):
            raise ExpressionError("the result is not finite")
    return result
