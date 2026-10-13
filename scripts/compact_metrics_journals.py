#!/usr/bin/env python
"""Rewrite finished trials' metrics journals without the designs every row used to repeat.

A worker once wrote its whole archive and its best design on every row: over a megabyte per
row for a 32,768-cell design. A rewritten journal is what a worker writes now: no archive, and
the best design only on an attempt's first row and where it changed. Rows, their order and
every other field are unchanged, so each old row except its archive can still be rebuilt.

A journal is replaced only after the new file has been read back and every row rebuilt from
it matches the old one. A trial whose worker is running is left alone.

    python scripts/compact_metrics_journals.py runs/workspace/workspace/trials [--dry-run]
"""
import argparse
import fcntl
import json
import os
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from pathlib import Path

BEST = ("best_candidate", "best_design")
EXACT_EVERY = 1000   # rows whose whole text must be reproduced, to prove the writer's format


def dumps(row):
    return json.dumps(row, allow_nan=False, separators=(",", ":")).encode() + b"\n"


def parsed(line):
    """The row a line holds, or None for an unfinished write, which is kept as it is."""
    if not line.endswith(b"\n"):
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def compacted(lines):
    """The journal's lines without designs that an earlier row of the same attempt gave."""
    attempt = best = None
    for number, line in enumerate(lines):
        row = parsed(line)
        if row is None:
            yield line
            continue
        if number % EXACT_EVERY == 0 and dumps(row) != line:
            raise ValueError(f"Row {number + 1} is not in the worker's format")
        given = {key: row[key] for key in BEST if key in row}
        repeated = bool(given) and row.get("attempt_id") == attempt and given == best
        if given:
            attempt, best = row.get("attempt_id"), given
        dropped = {"archive", *BEST} if repeated else {"archive"}
        yield dumps({key: value for key, value in row.items() if key not in dropped}) if dropped & row.keys() else line


def digest(lines):
    """Identify every row with its best design restored and its archive left out."""
    attempt, best, state, rows = None, {}, sha256(), 0
    for line in lines:
        row = parsed(line)
        if row is None:
            state.update(sha256(line).digest())
            continue
        if row.get("attempt_id") != attempt:
            attempt, best = row.get("attempt_id"), {}
        best = {**best, **{key: row[key] for key in BEST if key in row}}
        full = {**{key: value for key, value in row.items() if key != "archive"}, **best}
        state.update(sha256(json.dumps(full, sort_keys=True).encode()).digest())
        rows += 1
    return state.hexdigest(), rows


def compact(path, dry_run=False):
    path = Path(path)
    temporary = path.with_name(path.name + ".compacting")
    with (path.parent / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"path": str(path), "skipped": "a worker is running"}
        fcntl.flock(lock, fcntl.LOCK_UN)
        before = path.stat()
        try:
            with path.open("rb") as source, temporary.open("wb") as target:
                for line in compacted(source):
                    target.write(line)
                target.flush()
                os.fsync(target.fileno())
            with path.open("rb") as source:
                expected = digest(source)
            with temporary.open("rb") as target:
                if digest(target) != expected:
                    raise ValueError("The rewritten journal does not rebuild the original rows")
            result = {"path": str(path), "rows": expected[1], "before": before.st_size, "after": temporary.stat().st_size}
            if dry_run or result["after"] >= result["before"]:
                return result
            # A worker that started meanwhile has appended to the journal: leave it alone.
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"path": str(path), "skipped": "a worker started"}
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                return {"path": str(path), "skipped": "the journal changed"}
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return {**result, "replaced": True}
        except ValueError as error:
            return {"path": str(path), "skipped": str(error)}
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trials", type=Path, help="A workspace's trials directory")
    parser.add_argument("--dry-run", action="store_true", help="Report the sizes without replacing any journal")
    parser.add_argument("--processes", type=int, default=6)
    arguments = parser.parse_args()
    journals = sorted(arguments.trials.glob("*/metrics.jsonl"), key=lambda path: path.stat().st_size)
    before = after = 0
    with ProcessPoolExecutor(arguments.processes) as pool:
        for result in pool.map(compact, journals, [arguments.dry_run] * len(journals)):
            name = Path(result["path"]).parent.name
            if "skipped" in result:
                print(f"{name}: left alone, {result['skipped']}", flush=True)
                continue
            before, after = before + result["before"], after + result["after"]
            print(f"{name}: {result['rows']} rows, {result['before'] / 2**20:.1f} MiB -> {result['after'] / 2**20:.1f} MiB"
                  + ("" if result.get("replaced") else " (not replaced)"), flush=True)
    print(f"Total: {before / 2**30:.2f} GiB -> {after / 2**30:.2f} GiB")


if __name__ == "__main__":
    main()
