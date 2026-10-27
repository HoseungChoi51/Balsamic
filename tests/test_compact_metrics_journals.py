"""Old metrics journals are rewritten to what a worker writes now: no archive and no designs, each row naming its best
design's observation."""
import importlib.util
import json
from pathlib import Path

import pytest

from optimization_framework.execution.worker import read_journal, run
from optimization_framework.storage.artifacts import atomic_json
from test_framework_worker import prepare

pytestmark = pytest.mark.meent   # what scripts/install-meent installs; skipped where it is not installed

spec = importlib.util.spec_from_file_location("compact_metrics_journals", Path(__file__).parents[1] / "scripts/compact_metrics_journals.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def old_journal(directory):
    """A two-attempt run, with its journal as a worker wrote it before: archive and best design on every row."""
    prepare(directory, problem_id="meent_grating", algorithm="hillclimb", max_steps=8)
    run(directory)
    atomic_json(directory / "control.json", {"command": "run", "max_steps": 12, "revision": 1})
    result = run(directory)
    designs = {row["id"]: row["candidate"] for row in read_journal(directory / "observations.jsonl")}
    rows = read_journal(directory / "metrics.jsonl")
    for row in rows:
        best = designs[row.pop(tool.NAMED)]
        row.update(best_candidate=best, best_design=best, archive=[{"candidate": best, "objective": row["best_objective"]}])
    (directory / "metrics.jsonl").write_bytes(b"".join(map(tool.dumps, rows)))
    return rows, result


def test_rewritten_journal_is_what_a_worker_writes_now(tmp_path):
    old, result = old_journal(tmp_path / "old")
    prepare(tmp_path / "new", problem_id="meent_grating", algorithm="hillclimb", max_steps=8)
    run(tmp_path / "new")
    atomic_json(tmp_path / "new/control.json", {"command": "run", "max_steps": 12, "revision": 1})
    run(tmp_path / "new")
    path = tmp_path / "old/metrics.jsonl"
    with path.open("ab") as stream:
        stream.write(b'{"step": 13')   # an unfinished write is kept
    outcome = tool.compact(path)
    assert outcome["replaced"] and outcome["rows"] == 12 and outcome["after"] < outcome["before"]
    assert path.read_bytes().endswith(b'\n{"step": 13')
    rows = read_journal(path)
    volatile = {"attempt_id", "elapsed_seconds", "updated_at", "checkpoint_id", tool.NAMED}   # observation ids are per run
    stable = lambda journal: [{key: value for key, value in row.items() if key not in volatile} for row in journal]
    assert stable(rows) == stable(read_journal(tmp_path / "new/metrics.jsonl"))
    assert [{key: value for key, value in row.items() if key not in {"archive", *tool.BEST}} for row in old] == [
        {key: value for key, value in row.items() if key != tool.NAMED} for row in rows]
    designs = {row["id"]: row["candidate"] for row in read_journal(tmp_path / "old/observations.jsonl")}
    assert [designs[row[tool.NAMED]] for row in rows] == [row["best_candidate"] for row in old]
    assert designs[rows[-1][tool.NAMED]] == result["best_candidate"]
    # A second pass finds nothing to remove and leaves the file as it is.
    text = path.read_bytes()
    assert "replaced" not in tool.compact(path) and path.read_bytes() == text


def test_a_running_trial_and_a_foreign_journal_are_left_alone(tmp_path):
    import fcntl
    old_journal(tmp_path)
    path = tmp_path / "metrics.jsonl"
    text = path.read_bytes()
    with (tmp_path / "worker.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert tool.compact(path) == {"path": str(path), "skipped": "a worker is running"}
    assert tool.compact(path, dry_run=True)["after"] < len(text) and path.read_bytes() == text
    path.write_text(json.dumps({"step": 1, "archive": [1]}) + "\n")   # not the worker's compact text
    assert "format" in tool.compact(path)["skipped"] and json.loads(path.read_text()) == {"step": 1, "archive": [1]}
    assert not list(tmp_path.glob("*.compacting"))
