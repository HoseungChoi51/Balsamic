"""A campaign is removed whole, keeps on disk only what the researcher chose, and takes nothing of another campaign with it."""
import json
import time

from fastapi.testclient import TestClient
import pytest

from balsamic.app import create_app
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, ControlInput, TaskInput, TrialInput
from optimization_framework.execution.service import ACTIVE, Workspace, alive


class Harness:
    """The agent service as the workspace sees it."""
    def __init__(self):
        self.forgotten, self.down = [], False

    def status(self):
        if self.down:
            raise ValueError("Pi service is unavailable; work is saved and will reconnect")
        return {"configured": True}

    def inspect(self, agent_id, after=0):
        return None

    def forget(self, agent_id):
        self.status()
        self.forgotten.append(agent_id)
        return {"removed": True}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    instance = Workspace(tmp_path / "workspace", max_workers=2)
    instance.pi.client = Harness()
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


def command(workspace, campaign_id, identity, operation, payload):
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, operation=operation,
        expected_revision=workspace.store.get(campaign_id, "campaign")["version"], payload=payload))["outcome"]


def campaign_with_a_run(workspace, name, *, steps=80, identity=None):
    """A campaign with one finished and catalogued run, an idea, and a finding that cites the run."""
    created = workspace.create_campaign(CampaignInput(name=name, compute_budget_seconds=600, validation_reserve_seconds=30, llm_budget_usd=0,
        tasks=[TaskInput(name="Grating", physics={"n_cells": 160, "fourier_order": 1})]), campaign_id=identity)
    cid, task = created["id"], workspace.current_tasks(created["id"])[0]
    idea = command(workspace, cid, f"{cid}-idea", "hypothesis.create", {"title": "Random search", "algorithm": "random",
        "mechanism": "Independent samples.", "rationale": "A baseline."})["hypothesis"]
    trial = workspace.create_trial(TrialInput(campaign_id=cid, task_id=task["id"], hypothesis_id=idea["id"], algorithm="random", seed=3,
        max_steps=steps, wall_seconds=60))
    trial = waited(lambda: workspace.store.get(trial["id"], "trial"), lambda row: row["status"] not in ACTIVE and row.get("evidence_committed_at"))
    finding = command(workspace, cid, f"{cid}-finding", "finding.record", {"content": "Random search reached its best design early.",
        "source_ids": [trial["id"]], "interpretation": "observation", "publish": True, "problem_scope": "The 160-cell grating.",
        "limitations": ["One seed."], "study_ids": [created["active_study_id"]]})
    return cid, trial, finding


def rows_of(workspace, campaign_id):
    with workspace.store.connection() as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {"records": db.execute("SELECT COUNT(*) FROM records WHERE campaign_id=? OR id=?", (campaign_id, campaign_id)).fetchone()[0],
                  "cost_positions": db.execute("SELECT COUNT(*) FROM cost_positions WHERE source_id IN "
                      "(SELECT json_extract(data,'$.source_id') FROM records WHERE kind='cost_event' AND campaign_id=?)", (campaign_id,)).fetchone()[0]}
        for table in ("events", "agent_events", "agent_log_offsets", "agent_log_projection", "manager_search", "llm_usage"):
            if table in tables:
                counts[table] = db.execute(f"SELECT COUNT(*) FROM {table} WHERE campaign_id=?", (campaign_id,)).fetchone()[0]
    return counts


@pytest.mark.meent
def test_removal_deletes_everything_of_the_campaign_and_nothing_of_another(workspace):
    gone, trial, _ = campaign_with_a_run(workspace, "To be removed", identity="campaign_gone")
    stays, other, _ = campaign_with_a_run(workspace, "To stay")
    command(workspace, gone, "start-team", "agent.activate", {})
    lead = workspace.store.list("agent_session", gone)[0]["id"]
    work = workspace.directory / "agents" / lead / "work"
    work.mkdir(parents=True)
    (work / "analysis.py").write_text("print('medians')\n")
    waited(lambda: workspace.agent_log.status(gone), lambda status: status["lag"] == 0 and status["latest_seq"] > 0)
    before, positions = rows_of(workspace, stays), rows_of(workspace, gone)["cost_positions"]
    directories = [workspace.job_dir(trial["id"]), workspace.directory / "campaigns" / gone, workspace.directory / "agents" / lead]
    assert all(path.is_dir() for path in directories) and positions > 0

    # A request the campaign manager answered long ago keeps its status for good; it is not work in progress.
    workspace.store.put("research_run", {"id": "research_old", "campaign_id": gone, "status": "partial", "request": {}, "usage": {}})
    workspace.store.put("manager_command", {"id": "turn_old", "campaign_id": gone, "status": "dispatched", "research_run_id": "research_old"})
    plan = workspace.removal.plan(gone)
    assert plan["blockers"] == [] and plan["holds"]["experiments"] == 1 and plan["holds"]["findings"] == 1 and plan["holds"]["agents"] == 1
    assert plan["bytes"]["files"] >= plan["bytes"]["experiment_files"] > 0 and [option["keep"] for option in plan["options"]] == ["nothing", "summary", "records"]

    removed = workspace.removal.remove(gone, "nothing")
    assert removed["status"] == "completed" and removed["keep"] == "nothing" and removed["folder"] is None and removed["name"] == "To be removed"
    assert removed["files_bytes"] == plan["bytes"]["files"] and removed["rows"]["records"] == plan["holds"]["records"]
    assert not any(rows_of(workspace, gone).values()) and not any(path.exists() for path in directories)
    assert workspace.pi.client.forgotten == [lead] and not (workspace.directory / "removed").exists()
    with workspace.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM cost_positions").fetchone()[0] == before["cost_positions"]
    with pytest.raises(KeyError):
        workspace.store.get(gone, "campaign")
    # The other campaign is as it was, and still reads and writes.
    assert rows_of(workspace, stays) == before and workspace.job_dir(other["id"]).is_dir()
    assert [row["id"] for row in workspace.store.list("campaign")] == [stays]
    assert workspace.metrics(other["id"], fields=("best_objective",)) and workspace.assets.availability(
        workspace.store.get(other["output_asset_ids"][0], "asset"))["status"] != "unavailable"
    # A pass that read one of the removed campaign's records beforehand cannot write it back.
    with pytest.raises(ValueError, match="was removed"):
        workspace.store.put("trial", trial)
    assert [item["removed_campaign_id"] for item in workspace.removal.removed()] == [gone]
    # The identity is free again.
    workspace.create_campaign(CampaignInput(name="Second life", tasks=[TaskInput(name="Grating", physics={"n_cells": 160, "fourier_order": 1})]),
                              campaign_id=gone)
    assert workspace.store.get(gone, "campaign")["name"] == "Second life" and len(workspace.current_tasks(gone)) == 1


@pytest.mark.meent
def test_a_summary_or_most_records_stay_when_asked_for(workspace):
    first, trial, _ = campaign_with_a_run(workspace, "Summary only", steps=90)
    recorded = workspace.metrics(trial["id"], fields=("best_objective", "evaluations"))
    removed = workspace.removal.remove(first, "summary")
    folder = workspace.directory / "removed" / first
    assert removed["folder"] == str(folder) and removed["kept_bytes"] > 0
    assert sorted(path.name for path in folder.iterdir()) == ["summary.json", "summary.md"]
    summary = json.loads((folder / "summary.json").read_text())
    run, = summary["runs"]
    assert (run["id"], run["method"], run["seed"], run["purpose"], run["hypothesis"]) == (trial["id"], "random", 3, "optimization", "Random search")
    assert run["evaluations"] == 90 and run["best"] == trial["result"]["best_objective"] == recorded[-1]["best_objective"]
    # The course: the first evaluation, each improvement, the end.
    course = run["course"]
    assert course[0][:2] == [recorded[0]["evaluations"], recorded[0]["best_objective"]] and course[-1][1] == run["best"]
    improvements = {row["best_objective"] for row in recorded}
    assert {point[1] for point in course} == improvements and len(course) <= len(improvements) + 1 < len(recorded)
    assert summary["campaign"]["name"] == "Summary only" and summary["findings"][0]["content"].startswith("Random search reached")
    text = (folder / "summary.md").read_text()
    assert "# Summary only" in text and trial["id"] in text and "Random search reached its best design early." in text and "Only this summary was kept" in text
    assert json.loads((workspace.directory / "removed" / "index.jsonl").read_text())["folder"] == str(folder)
    assert not workspace.job_dir(trial["id"]).exists()

    second, trial, _ = campaign_with_a_run(workspace, "Most records", steps=70)
    scores = (workspace.job_dir(trial["id"]) / "metrics.jsonl").read_bytes()
    stored = workspace.store.get(trial["id"], "trial")
    command(workspace, second, "note", "context.edit", {"content": "# Guidance\nKeep the random baseline.", "expected_revision": workspace.memory.state(second)["revision"]})
    removed = workspace.removal.remove(second, "records")
    folder = workspace.directory / "removed" / second
    kinds = {path.stem for path in (folder / "records").iterdir()}
    assert {"campaign", "trial", "hypothesis", "task", "study", "manager_note", "work_command", "asset"} <= kinds and "cost_event" not in kinds
    kept = json.loads((folder / "records" / "trial.jsonl").read_text())
    assert kept["id"] == trial["id"] and kept["result"]["best_objective"] == stored["result"]["best_objective"] and kept["algorithm"] == "random"
    assert "archive" not in kept["result"] and "experiment_spec" not in kept and "progress" not in kept
    design = json.loads((folder / "best-designs.jsonl").read_text())
    assert design["trial_id"] == trial["id"] and design["design"] == stored["result"]["best_design"] and design["best"] == stored["result"]["best_objective"]
    assert (folder / "experiments" / trial["id"] / "metrics.jsonl").read_bytes() == scores
    guidance = json.loads((folder / "records" / "manager_state.jsonl").read_text())
    assert "Keep the random baseline." in guidance["guidance"] and "Kept beside this file" in (folder / "summary.md").read_text()
    assert any("Keep the random baseline." in line for line in (folder / "records" / "manager_note.jsonl").read_text().splitlines())
    assert removed["kept_bytes"] >= len(scores) and not workspace.job_dir(trial["id"]).exists() and not rows_of(workspace, second)["records"]
    assert [json.loads(line)["keep"] for line in (workspace.directory / "removed" / "index.jsonl").read_text().splitlines()] == ["summary", "records"]


@pytest.mark.meent
def test_a_campaign_with_work_in_progress_or_evidence_in_use_is_not_removed(workspace):
    source, trial, finding = campaign_with_a_run(workspace, "Source of a finding")
    user, _, _ = campaign_with_a_run(workspace, "Reader of the finding")
    command(workspace, user, "reference", "asset.reuse", {"asset_id": finding["asset_id"], "study_id": workspace.store.get(user, "campaign")["active_study_id"],
        "decision": "reference", "intended_use": "manager_evidence", "rationale": "Plan with the earlier lesson in view."})
    rows = rows_of(workspace, source)
    assert any("Reader of the finding" in text and "Remove that campaign first" in text for text in workspace.removal.plan(source)["blockers"])
    with pytest.raises(ValueError, match="uses 1 finding"):
        workspace.removal.remove(source, "summary")
    # Refused: nothing was deleted, and no summary of a campaign that still exists is left behind.
    assert rows_of(workspace, source) == rows and workspace.job_dir(trial["id"]).is_dir() and not list((workspace.directory / "removed").glob("*"))
    # A run that is still going holds its campaign.
    task = workspace.current_tasks(user)[0]
    running = workspace.create_trial(TrialInput(campaign_id=user, task_id=task["id"], algorithm="random", seed=5, max_steps=100000, wall_seconds=120))
    with pytest.raises(ValueError, match="1 experiment is queued or running. Stop or finish every experiment first."):
        workspace.removal.remove(user, "nothing")
    workspace.control(running["id"], ControlInput(action="stop"))
    waited(lambda: workspace.store.get(running["id"], "trial"), lambda row: row["status"] not in ACTIVE and not alive(row))
    waited(lambda: workspace.removal.blockers(user), lambda blockers: not blockers)
    # An agent's saved session can only go while the agent service is there to drop it.
    command(workspace, user, "start-team", "agent.activate", {})
    workspace.pi.client.down = True
    with pytest.raises(ValueError, match="agent service is not reachable"):
        workspace.removal.remove(user, "nothing")
    workspace.pi.client.down = False
    assert workspace.removal.remove(user, "nothing")["status"] == "completed"
    # With its reader gone, the source can go too.
    assert workspace.removal.plan(source)["blockers"] == [] and workspace.removal.remove(source, "nothing")["status"] == "completed"
    assert workspace.store.list("campaign") == [] and workspace.store.list("asset") == [] and not list((workspace.directory / "trials").iterdir())


@pytest.mark.meent
def test_files_that_could_not_be_cleared_are_cleared_when_the_service_starts_again(workspace):
    cid, trial, _ = campaign_with_a_run(workspace, "Interrupted removal")
    command(workspace, cid, "start-team", "agent.activate", {})
    directory = workspace.job_dir(trial["id"])
    workspace.pi.client.down = True
    with workspace.lock, workspace.store.transaction():   # as if the service stopped right after the rows were deleted
        record = {"id": "removal_" + cid, "removed_campaign_id": cid, "name": "Interrupted removal", "removed_at": "2026-10-13T00:00:00+00:00",
                  "keep": "nothing", "folder": None, "kept_bytes": 0, "status": "clearing", "paths": [str(path) for path in workspace.removal.paths(cid)],
                  "agents": [row["id"] for row in workspace.store.list("agent_session", cid)], "blob_digests": workspace.removal._blob_digests(cid)}
        workspace.store.delete_campaign(cid)
        workspace.store.put("campaign_removal", record, "campaign.removed")
    workspace.removal.recover()
    left = workspace.store.get(record["id"], "campaign_removal")
    assert left["status"] == "incomplete" and "agent session" in left["left"][0] and not directory.exists()
    workspace.pi.client.down = False
    workspace.removal.recover()
    done = workspace.store.get(record["id"], "campaign_removal")
    assert done["status"] == "completed" and "paths" not in done and "left" not in done and workspace.pi.client.forgotten == record["agents"]


def test_the_interface_asks_what_to_keep_and_the_removed_campaign_leaves_the_list(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    workspace.pi.client = Harness()
    kept = workspace.create_campaign(CampaignInput(name="Kept", tasks=[TaskInput(name="Grating", physics={"n_cells": 160, "fourier_order": 1})]))
    gone = workspace.create_campaign(CampaignInput(name="Gone", tasks=[TaskInput(name="Grating", physics={"n_cells": 160, "fourier_order": 1})]))
    with TestClient(app) as client:
        assert [row["name"] for row in client.get("/api/v1/campaigns").json()["campaigns"]] == ["Kept", "Gone"]
        plan = client.get(f"/api/v1/campaigns/{gone['id']}/removal").json()
        assert plan["campaign"]["name"] == "Gone" and plan["blockers"] == [] and plan["folder"].endswith("/removed/" + gone["id"])
        # The choice is the researcher's: there is no default.
        assert client.post(f"/api/v1/campaigns/{gone['id']}/removal", json={}).status_code == 422
        assert client.post(f"/api/v1/campaigns/{gone['id']}/removal", json={"keep": "everything"}).status_code == 422
        removed = client.post(f"/api/v1/campaigns/{gone['id']}/removal", json={"keep": "summary"})
        assert removed.status_code == 200 and removed.json()["status"] == "completed" and removed.json()["folder"] == plan["folder"]
        assert "# Gone" in (tmp_path / "removed" / gone["id"] / "summary.md").read_text()
        assert [row["name"] for row in client.get("/api/v1/campaigns").json()["campaigns"]] == ["Kept"]
        assert client.get(f"/api/v1/campaigns/{gone['id']}/summary").status_code == 404
        assert client.get(f"/api/v1/campaigns/{gone['id']}/removal").status_code == 404
        assert client.post(f"/api/v1/campaigns/{gone['id']}/removal", json={"keep": "nothing"}).status_code == 404
        assert [row["name"] for row in client.get("/api/v1/removed-campaigns").json()] == ["Gone"]
        # A refusal is answered with its reasons and is not filed as an issue of the campaign.
        workspace.store.put("trial", {"id": "trial_open", "campaign_id": kept["id"], "status": "running"})
        refused = client.post(f"/api/v1/campaigns/{kept['id']}/removal", json={"keep": "nothing"})
        assert refused.status_code == 409 and "queued or running" in refused.json()["detail"] and workspace.store.list("manager_issue", kept["id"]) == []
