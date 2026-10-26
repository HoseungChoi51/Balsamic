#!/usr/bin/env python
"""Rewrite finished trials' metrics journals to what a worker writes now: no designs.

A worker once wrote its whole archive and its best design on every row (over a megabyte per row
for a 32,768-cell design), and later its best design wherever it changed (130 kB per improvement).
A row now names its best design by the observation that evaluated it (best_observation_id); the
observation journal beside it holds every evaluated design. Rows, their order and every other
field are unchanged, so each old row except its archive can still be rebuilt.

A journal is replaced only after the new file has been read back and every row's best design,
rebuilt from the observation it names, matches the old one. A journal whose best design is not
among its observations is left alone, and so is a trial whose worker is running.

    python scripts/compact_metrics_journals.py runs/workspace/workspace/trials [--dry-run]
"""
import argparse
import fcntl
import json
import os
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from pathlib import Path

from optimization_framework.execution.metrics import PACKED, pack_candidate

BEST = ("best_candidate", "best_design")
NAMED = "best_observation_id"
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


def fingerprint(candidate):
    """A design's identity, the same whether a journal holds it as a list or packed."""
    packed = candidate if isinstance(candidate, dict) and PACKED in candidate else pack_candidate(candidate)
    return sha256(json.dumps(packed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def observed(path):
    """The observation journal's designs: fingerprint by observation id, and observation ids by fingerprint."""
    by_id, by_design = {}, {}
    if path.exists():
        with path.open("rb") as stream:
            for line in stream:
                row = parsed(line)
                if row is None or "id" not in row or "candidate" not in row:
                    continue
                design = fingerprint(row["candidate"])
                by_id[row["id"]] = design
                by_design.setdefault(design, []).append(row["id"])
    return by_id, by_design


def given(row):
    """(whether the row states its best design, the design): older rows state it, maybe as None before any best."""
    for key in BEST:
        if key in row:
            return True, row[key]
    return False, None


def compacted(lines, by_design):
    """The journal's lines as a worker writes them now: each row names its best design's observation."""
    attempt = named = None
    for number, line in enumerate(lines):
        row = parsed(line)
        if row is None:
            yield line
            continue
        if number % EXACT_EVERY == 0 and dumps(row) != line:
            raise ValueError(f"Row {number + 1} is not in the worker's format")
        if row.get("attempt_id") != attempt:
            attempt, named = row.get("attempt_id"), None
        stated, design = given(row)
        if not stated and "archive" not in row and NAMED in row:
            named = row[NAMED]
            yield line
            continue
        if stated:
            if design is None:
                named = None
            else:
                found = by_design.get(fingerprint(design))
                if not found:
                    raise ValueError(f"The best design of row {number + 1} is not among the run's observations")
                named = found[0]
        yield dumps({**{key: value for key, value in row.items() if key not in {"archive", *BEST, NAMED}}, NAMED: named})


def digest(lines, by_id):
    """Identify every row by its fields, without archive or designs, and its best design's fingerprint."""
    attempt, best, state, rows = None, None, sha256(), 0
    for line in lines:
        row = parsed(line)
        if row is None:
            state.update(sha256(line).digest())
            continue
        if row.get("attempt_id") != attempt:
            attempt, best = row.get("attempt_id"), None
        stated, design = given(row)
        if stated:
            best = None if design is None else fingerprint(design)
        elif NAMED in row:
            best = by_id.get(row[NAMED]) if row[NAMED] else None
        fields = {key: value for key, value in row.items() if key not in {"archive", *BEST, NAMED}}
        state.update(sha256(json.dumps({**fields, "best": best}, sort_keys=True).encode()).digest())
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
            by_id, by_design = observed(path.parent / "observations.jsonl")
            with path.open("rb") as source, temporary.open("wb") as target:
                for line in compacted(source, by_design):
                    target.write(line)
                target.flush()
                os.fsync(target.fileno())
            with path.open("rb") as source:
                expected = digest(source, by_id)
            with temporary.open("rb") as target:
                if digest(target, by_id) != expected:
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
