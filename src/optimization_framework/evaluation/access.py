"""How methods reach a problem's objective and what they are compared on (N11, decisions 22 and 23).

A problem is ``white_box`` unless it declares ``oracle``: a method may then compute the objective from the problem's code
as often as it likes, and is judged by its time. An ``oracle`` problem's objective is reached only through ``evaluate``.
The declaration comes from, first to last: the charter's evaluator binding, the problem's definition, its pack's ``cost``
section, the default. A task records the result when it is created; a task or a manifest made before this existed has
none and is read as ``oracle``, the rule it was built under.
"""
from __future__ import annotations

ACCESS = ("white_box", "oracle")
COST_AXES = ("worker_seconds", "core_seconds", "evaluations", "solver_calls")
# A declared axis by the name the comparison report gives it.
REPORT_AXES = {"worker_seconds": "worker_seconds", "core_seconds": "core_seconds",
               "evaluations": "evaluation_requests", "solver_calls": "solver_executions"}
LEGACY = {"access": "oracle", "cost_axis": None}


def declared(problem_id: str, registry=None) -> dict:
    """An installed problem's own access and cost axis: its definition's, else its pack's, else white_box and unset."""
    from optimization_framework.evaluation.registry import problems
    registry = registry or problems
    definition = registry.get(problem_id).describe()
    pack = registry.pack(problem_id)
    cost = pack.cost if pack is not None else None
    return {"access": definition.access or (cost.access if cost else None) or "white_box",
            "cost_axis": definition.cost_axis or (cost.cost_axis if cost else None)}


def of_task(task: dict) -> dict:
    """A task record's access and cost axis; a task created before N11 is an oracle task."""
    return {key: task.get(key) or default for key, default in LEGACY.items()}

