"""Give stored tasks and trials that never recorded a problem the problem they were on (roadmap N7).

Records written before problems were declared describe their problem only by its settings. The core resolves none of
them itself: each installed problem pack may offer a ``legacy.problem`` hook that recognises its own records. A record
no hook resolves keeps no problem, is reported by id, and is refused where a problem is needed. Running it again
changes nothing, so the workspace runs it at every start.

    python -m optimization_framework.execution.problem_migration <workspace directory>

runs it on a copy of a store and prints what it did; it exits with 1 when a record could not be resolved.
"""
from __future__ import annotations

import json
import sys

from optimization_framework.evaluation.registry import problems


KINDS = ("task", "trial")


def without_problem(store):
    """(kind, id) of the tasks and trials that have no problem, in the store's order."""
    with store.connection() as db:
        return [(row["kind"], row["id"]) for row in db.execute(
            "SELECT kind, id FROM records WHERE kind IN ('task','trial') AND json_extract(data,'$.problem') IS NULL ORDER BY rowid")]


def resolve(record, hooks):
    """The problem the first pack that recognises the record gives it, or None."""
    for hook in hooks:
        try:
            instance = hook(record)
        except (ValueError, TypeError, KeyError):
            continue
        if instance is not None:
            return instance
    return None


def migrate(store, registry=problems):
    """Store a resolved problem on every task and trial without one. Returns the ids migrated and the ids refused."""
    pending = without_problem(store)
    result = {"tasks": [], "trials": [], "unresolved": []}
    if not pending:
        return result
    hooks = registry.legacy("problem")
    with store.transaction():
        for kind, record_id in pending:
            record = store.get(record_id, kind)
            if record.get("problem") is not None:
                continue
            instance = resolve(record, hooks)
            if instance is None and kind == "trial" and record.get("task_id"):
                # A trial runs on its task's problem; the task may have been migrated a moment ago.
                try:
                    instance = store.get(record["task_id"], "task").get("problem")
                except KeyError:
                    instance = None
            if instance is None:
                result["unresolved"].append(record_id)
                continue
            record["problem"] = instance if isinstance(instance, dict) else instance.model_dump(mode="json")
            store.put(kind, record, f"{kind}.problem_migrated")
            result[kind + "s"].append(record_id)
    if result["unresolved"]:
        store.event(None, "problem.migration_unresolved", {"record_ids": result["unresolved"]})
    return result


def required(record):
    """A record's problem, refused with its id when it has none: the migration could not resolve it."""
    if not record.get("problem"):
        kind = "task" if str(record.get("id", "")).startswith("task") else "experiment"
        raise ValueError(f"The {kind} {record.get('id')} records no problem, and no installed problem recognises it; "
                         "it can be read but not run or evaluated")
    return record["problem"]


def main(argv=None):
    from optimization_framework.storage.sqlite import Store
    from pathlib import Path
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1 or not (Path(arguments[0]) / "workspace.sqlite3").is_file():
        print("usage: python -m optimization_framework.execution.problem_migration <workspace directory>", file=sys.stderr)
        return 2
    result = migrate(Store(arguments[0]))
    print(json.dumps({"tasks_migrated": len(result["tasks"]), "trials_migrated": len(result["trials"]),
                      "unresolved": result["unresolved"]}, indent=2))
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
