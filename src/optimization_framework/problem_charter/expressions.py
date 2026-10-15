"""A small, whitelisted expression language for relations between quantities.

Expressions are parsed with ``ast`` and walked node by node; nothing is passed to ``eval``. Only
arithmetic, comparisons, boolean logic, conditional expressions, named quantities and the functions
below are allowed. Numbers are computed as floats, so no expression can build a huge integer.
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
            if not isinstance(node.func, ast.Name) or (node.func.id not in FUNCTIONS and node.func.id != "table"):
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


def evaluate(expression: str, values: dict, tables: dict | None = None):
    """The value of an expression, given computed values by name and tables by name (lists of points)."""
    tables = tables or {}
    tree = parse(expression)

    def run(node):
        if isinstance(node, ast.Expression):
            return run(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value) if isinstance(node.value, int) and not isinstance(node.value, bool) else node.value
        if isinstance(node, ast.Name):
            if node.id in values:
                value = values[node.id]
                if value is None:
                    raise ExpressionError(f"{node.id} has no value")
                return float(value) if isinstance(value, int) and not isinstance(value, bool) else value
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise ExpressionError(f"unknown name {node.id}")
        if isinstance(node, ast.BinOp):
            return _real(BINARY[type(node.op)](run(node.left), run(node.right)))
        if isinstance(node, ast.UnaryOp):
            operand = run(node.operand)
            return not operand if isinstance(node.op, ast.Not) else (-operand if isinstance(node.op, ast.USub) else +operand)
        if isinstance(node, ast.BoolOp):
            results = [run(value) for value in node.values]
            return all(results) if isinstance(node.op, ast.And) else any(results)
        if isinstance(node, ast.Compare):
            left = run(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = run(comparator)
                if not COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return run(node.body) if run(node.test) else run(node.orelse)
        if isinstance(node, ast.Call):
            if node.func.id == "table":
                if len(node.args) != 2:
                    raise ExpressionError("table() takes a table name and one value")
                name = _table_name(node.args[0])
                if name not in tables:
                    raise ExpressionError(f"unknown table {name}")
                return interpolate(tables[name], run(node.args[1]), name)
            return _real(FUNCTIONS[node.func.id](*[run(argument) for argument in node.args]))
        raise ExpressionError(f"'{type(node).__name__}' is not allowed in an expression")

    try:
        result = run(tree)
    except ExpressionError:
        raise
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ExpressionError(str(exc) or type(exc).__name__) from None
    if isinstance(result, float) and not math.isfinite(result):
        raise ExpressionError("the result is not finite")
    return result
