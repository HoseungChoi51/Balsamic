"""A journal too large to load is served as scalar columns, read only where it has grown."""
import json

from optimization_framework.execution import metrics
from optimization_framework.execution.metrics import LargeJournalScalars
from optimization_framework.execution.service import Workspace


def record(step, cells=64):
    return {"step": step, "best_objective": step / 10, "elapsed_seconds": float(step), "status": "running",
            "best_candidate": [1] * cells, "archive": [{"candidate": [0] * cells}], "diagnostics": {"decisions": step}}


def append(path, *rows, end="\n"):
    with path.open("a") as stream:
        for row in rows:
            stream.write(json.dumps(row) + end)


def test_large_journal_rows_are_scalar_incremental_and_sampled(tmp_path, monkeypatch):
    path = tmp_path / "metrics.jsonl"
    append(path, *(record(step) for step in range(1, 6)))
    reader = LargeJournalScalars(max_rows=4)
    assert reader.read(path, ("step", "best_objective")) == [{"step": s, "best_objective": s / 10} for s in range(1, 6)]
    sample = reader.read(path)
    assert [row["step"] for row in sample] == [1, 2, 4, 5] and "best_candidate" not in sample[0] and "archive" not in sample[0]
    # Only appended bytes are parsed again, and an unfinished record waits for its newline.
    parsed = []
    original = metrics.json.loads
    monkeypatch.setattr(metrics.json, "loads", lambda line: parsed.append(1) or original(line))
    append(path, record(6))
    append(path, record(7), end="")
    assert [row["step"] for row in reader.read(path, ("step",))] == [1, 2, 3, 4, 5, 6] and len(parsed) == 1
    append(path, {}, end="\n")   # completes record 7's line with trailing text, which is then unreadable
    path.write_text(json.dumps(record(9)) + "\n")   # a replaced journal starts over
    assert [row["step"] for row in reader.read(path, ("step",))] == [9]


def test_workspace_serves_large_journals_without_loading_designs(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    workspace.store.put("trial", {"id": "trial", "campaign_id": "campaign"})
    path = workspace.job_dir("trial") / "metrics.jsonl"
    path.parent.mkdir(parents=True)
    rows = [record(step) for step in range(1, 4)]
    append(path, *rows)
    assert workspace.metrics("trial") == rows                      # an ordinary journal is returned whole
    monkeypatch.setattr(metrics, "LARGE_JOURNAL_BYTES", 10)
    assert workspace.metrics("trial") == [{k: v for k, v in row.items() if k in {"step", "best_objective", "elapsed_seconds", "status"}} for row in rows]
    assert workspace.metrics("trial", fields=("step", "elapsed_seconds")) == [{"step": s, "elapsed_seconds": float(s)} for s in (1, 2, 3)]
    assert workspace.metrics("trial", fields=("step", "best_candidate")) == [{"step": r["step"], "best_candidate": r["best_candidate"]} for r in rows]
    assert workspace.metrics("trial", limit=1) == rows[-1:]


def test_scalar_record_drops_only_the_repeated_binary_designs():
    from optimization_framework.execution.metrics import scalar_record

    design = [index % 2 for index in range(4096)]
    record = {"evaluations": 3, "best_objective": 0.25, "updated_at": "2026-10-12T00:00:00+00:00", "reason": None,
              "best_candidate": design, "archive": [{"candidate": design, "design": design, "objective": 0.25}],
              "diagnostics": {"decisions": 3, "short": [0, 1, 1, 0]}}
    parsed = scalar_record(json.dumps(record, separators=(",", ":")).encode())
    assert {key: value for key, value in parsed.items() if not isinstance(value, (list, dict))} == \
        {key: value for key, value in record.items() if not isinstance(value, (list, dict))}
    assert parsed["best_candidate"] == [] and parsed["archive"][0]["objective"] == 0.25
    assert parsed["diagnostics"] == record["diagnostics"]
