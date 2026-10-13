"""Evaluated designs leave a finished experiment's journals only on the researcher's confirmation, and its numbers stay."""
import json
import time

import pytest

from optimization_framework.campaigns.commands import DELEGATED
from optimization_framework.contracts.commands import Command, EquivalenceInput
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.contracts.requests import CampaignInput, ControlInput, TaskInput, TrialInput
from optimization_framework.execution.compaction import JOURNALS, KEPT_BEST, KEPT_SPREAD, REMOVED, compact_trial
from optimization_framework.execution.service import ACTIVE, Workspace, alive
from optimization_framework.execution.worker import read_journal, run
from test_framework_worker import prepare


def numbers(rows):
    return [{key: value for key, value in row.items() if key != "candidate"} for row in rows]


def test_compaction_keeps_every_row_and_number_and_a_spread_of_designs(tmp_path):
    spec = prepare(tmp_path, problem_id="meent_grating", algorithm="random", max_steps=150, config={"n_cells": 160, "fourier_order": 1})
    result = run(tmp_path)
    assert result["step"] == 150
    with (tmp_path / "observations.jsonl").open("ab") as stream:
        stream.write(b'{"id": "torn')   # an unfinished last write stays as it is
    before = {name: read_journal(tmp_path / name) for name in JOURNALS}
    sizes = {name: (tmp_path / name).stat().st_size for name in JOURNALS}
    objective = ProblemInstance(**spec["problem"]).primary_objective
    utility = lambda objectives: objective.utility(objectives[objective.name])
    requests, observations = compact_trial(tmp_path, utility)
    after = {name: read_journal(tmp_path / name) for name in JOURNALS}
    assert all(numbers(after[name]) == numbers(before[name]) for name in JOURNALS)
    assert (tmp_path / "observations.jsonl").read_bytes().endswith(b'{"id": "torn')
    held = {row["id"]: row for row in after["observations.jsonl"] if row["candidate"] != REMOVED}
    # What stays: the archive, the best evaluations and an even spread; each with the design it was recorded with.
    assert {entry["observation_id"] for entry in result["archive"]} <= set(held) and len(result["archive"]) <= len(held) <= 10 + KEPT_BEST + KEPT_SPREAD
    ranked = sorted(before["observations.jsonl"], key=lambda row: utility(row["objectives"]), reverse=True)
    assert {row["id"] for row in ranked[:KEPT_BEST]} <= set(held)
    assert all(held[row["id"]]["candidate"] == row["candidate"] for row in before["observations.jsonl"] if row["id"] in held)
    assert result["best_candidate"] in [row["candidate"] for row in held.values()]
    assert {row["id"] for row in after["requests.jsonl"] if row["candidate"] != REMOVED} == {row["request_id"] for row in held.values()}
    assert observations["rows"] == requests["rows"] == 150 and observations["designs_removed"] == requests["designs_removed"] == 150 - len(held)
    assert all(summary["bytes_after"] == (tmp_path / summary["journal"]).stat().st_size < sizes[summary["journal"]] for summary in (requests, observations))
    # Compacting again changes nothing.
    again = compact_trial(tmp_path, utility)
    assert [summary["designs_removed"] for summary in again] == [0, 0]
    assert {name: read_journal(tmp_path / name) for name in JOURNALS} == after and not list(tmp_path.glob("*.compacting"))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    instance = Workspace(tmp_path / "workspace", max_workers=2)
    instance.start()
    yield instance
    for trial in instance.store.list("trial"):
        if trial["status"] in ACTIVE:
            instance.control(trial["id"], ControlInput(action="stop"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(trial) for trial in instance.store.list("trial")):
        time.sleep(.05)
    instance.close()


def waited(read, done, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if done(value):
            return value
        time.sleep(.05)
    pytest.fail("Timed out")


def test_the_lead_asks_and_only_the_researchers_approval_compacts(workspace):
    assert "journal.compaction_request" in DELEGATED and "journal.compact" not in DELEGATED
    created = workspace.create_campaign(CampaignInput(name="Cleaned up", compute_budget_seconds=600, validation_reserve_seconds=30, llm_budget_usd=0,
        tasks=[TaskInput(name="Grating", physics={"n_cells": 160, "fourier_order": 1})]))
    cid, task = created["id"], workspace.current_tasks(created["id"])[0]
    command = lambda identity, operation, payload: workspace.commands.execute(Command(id=identity, campaign_id=cid, operation=operation,
        expected_revision=workspace.store.get(cid, "campaign")["version"], payload=payload))["outcome"]
    trial = workspace.create_trial(TrialInput(campaign_id=cid, task_id=task["id"], algorithm="random", seed=3, max_steps=120, wall_seconds=60))
    trial = waited(lambda: workspace.store.get(trial["id"], "trial"), lambda row: row["status"] not in ACTIVE)
    journal = workspace.job_dir(trial["id"]) / "observations.jsonl"
    recorded = read_journal(journal)
    # An open experiment is not compacted, and a request says which experiments no finding cites yet.
    workspace.store.put("trial", {**trial, "id": "trial_open", "status": "running"})
    with pytest.raises(ValueError, match="still open: trial_open"):
        command("early", "journal.compaction_request", {"trial_ids": ["trial_open"], "rationale": "Too early."})
    workspace.store.put("trial", {**trial, "id": "trial_open", "status": "stopped"})   # nothing on disk: not part of any plan
    kept = command("keep", "journal.compaction_request", {"rationale": "The results are recorded."})
    assert kept["trial_ids"] == kept["not_cited_by_a_finding"] == [trial["id"]]
    decision = workspace.store.get(kept["decision_id"], "decision")
    assert decision["status"] == "pending" and decision["recommendation"] == "1" and "not cited by any recorded finding" in decision["proposal"]
    command("decline", "decision.resolve", {"decision_id": decision["id"], "choice": "1", "comment": "Not yet", "expected_resolution_revision": 0})
    assert read_journal(journal) == recorded and not workspace.store.list("journal_compaction", cid)
    # Once a finding cites the experiment the request recommends itself, and approval carries it out.
    command("finding", "finding.record", {"content": "Random search reached its best design early.", "source_ids": [trial["id"]], "interpretation": "observation"})
    asked = command("ask", "journal.compaction_request", {"trial_ids": [trial["id"]], "rationale": "Its result is recorded as a finding."})
    decision = workspace.store.get(asked["decision_id"], "decision")
    assert asked["not_cited_by_a_finding"] == [] and decision["recommendation"] == "0" and decision["journal_compaction"]["bytes"] == asked["bytes"] > 0
    command("approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "Go ahead", "expected_resolution_revision": 0})
    job = waited(lambda: workspace.store.list("journal_compaction", cid)[0], lambda row: row["status"] in {"completed", "failed"})
    assert job["status"] == "completed" and job["authority"] == "researcher" and job["bytes_after"] < job["bytes_before"] == asked["bytes"]
    compacted = read_journal(journal)
    held = [row for row in compacted if row["candidate"] != REMOVED]
    assert numbers(compacted) == numbers(recorded) and 0 < len(held) < len(recorded) == 120
    assert workspace.store.get(trial["id"], "trial")["journal_compaction_id"] == job["id"]
    # A design that stayed can still be replayed against the current evaluator; one that was removed cannot be snapshotted.
    check = workspace.equivalence.start(cid, EquivalenceInput(trial_id=trial["id"], sample=4))
    check = waited(lambda: workspace.store.get(check["id"], "evaluator_equivalence"), lambda row: row["status"] != "running")
    assert (check["verdict"], check["candidates"]) == ("passed", 4)
    gone = next(row for row in compacted if row["candidate"] == REMOVED and row["status"] == "ok")
    with pytest.raises(ValueError, match="exact successful observation|journals were compacted"):
        command("snapshot", "asset.snapshot", {"trial_id": trial["id"], "observation_id": gone["id"]})
    with pytest.raises(ValueError, match="journals left to compact"):
        command("twice", "journal.compaction_request", {"trial_ids": [trial["id"]], "rationale": "Again."})
