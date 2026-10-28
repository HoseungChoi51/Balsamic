"""Instance size as an axis of the comparison (roadmap N14).

Exact methods win on small instances and run out of time on large ones; where that happens is often the finding. A task
sits on a size ladder when its charter instance names a ``size`` (recorded on the task), or when its problem's pack
declares a size ladder in its ``racing`` section and the task's configuration has that key. A task on neither is compared
per task, as before.
"""
from __future__ import annotations

from .packs import task_racing


def of_task(task: dict | None) -> dict | None:
    """A task's size, ``{"name", "value"}``: the one its charter instance named, else its pack's size key in its
    configuration; None for a task on no ladder."""
    task = task or {}
    if task.get("size"):
        return {"name": task["size"]["name"], "value": float(task["size"]["value"])}
    racing = task_racing(task)
    key = racing.size_key() if racing is not None else None
    value = ((task.get("problem") or {}).get("configuration") or {}).get(key) if key else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"name": key, "value": float(value)}
    return None


def finished_on_its_own(trial: dict) -> bool:
    """The run's method ended by itself (an exact method's answer), not at its budget."""
    return bool((trial.get("result") or trial.get("progress") or {}).get("method_finished"))


def next_size(trials: list[dict], tasks: dict) -> dict | None:
    """For a strategy whose runs finished on their own on a deterministic problem, the smallest current task larger
    than the largest size it finished on: more budget would change nothing there, the next size might. None otherwise."""
    reached = {}
    for trial in trials:
        task = tasks.get(trial.get("task_id")) or {}
        size = of_task(task)
        deterministic = (task.get("evaluator_manifest") or {}).get("deterministic", True)
        if size and deterministic and finished_on_its_own(trial):
            reached.setdefault(size["name"], []).append((size["value"], task))
    best = None
    for name, rows in reached.items():
        largest, task = max(rows, key=lambda row: row[0])
        definition = (task.get("problem") or {}).get("definition_id")
        for other in tasks.values():
            size = of_task(other)
            if other.get("archived") or other.get("superseded_by_task_id") or not size or size["name"] != name or size["value"] <= largest:
                continue
            if (other.get("problem") or {}).get("definition_id") != definition or other.get("split") == "test":
                continue
            if best is None or size["value"] < best["value"]:
                best = {"task_id": other["id"], "task_name": other.get("name"), "name": name, "value": size["value"], "after": largest}
    return best
