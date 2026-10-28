"""A locked confirmation stays out of every agent read until it is released (roadmap V4).

A confirmation protocol with two finished cells and no release: no read tool returns the cells' ids, results or
measurements, a trial reads as its status, and after release() every read path returns them."""
import json

import pytest

from optimization_framework.agents.tools import EXTRA_TOOLS, TOOLS, WITHHELD, PiTools
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import StudyInput, TrialInput
from optimization_framework.execution.worker import run as run_worker

from support import QUADRATIC, activate_team, command

HELDOUT = {"name": "Heldout", "problem_id": "bounded_continuous", "configuration": {"center": [1., 1.]}, "split": "test"}

# Every agent tool, by whether it returns campaign records. A read is called below before and after release;
# a tool that returns no campaign record says why. A new tool is in neither and fails test_every_tool_is_checked.
READS = {"campaign_inspect", "evidence_search", "evidence_read", "experiment_progress", "file_list", "file_read", "file_search",
         "analysis_run", "campaign_command", "lab_events"}
NO_RECORDS = {
    "resource_inspect": "processes and seconds of running jobs: no result, score or measurement",
    "source_search": "literature from outside the lab", "source_ingest": "literature from outside the lab",
    "source_read": "saved literature, read through record()",
    "artifact_save": "writes; its evidence ids are read through record()", "mask_create": "a generated mask; its task through record()",
    "proposal_review": "writes a review; the hypothesis through record()",
    "review_synthesis": "writes a synthesis; each proposal through record(), and returns only ids",
    "delegate": "starts an assistant; its evidence ids through record()",
    "agent_message": "a message to an assistant", "agent_cancel": "stops an assistant", "command_schema": "a command's schema",
    "implementation_workspace_create": "a coding workspace", "implementation_workspace_inspect": "a coding workspace's own events",
    "implementation_workspace_message": "a message to a coding workspace", "implementation_workspace_validate": "a validation job",
    "page_agent_message": "a request to a page agent; its evidence ids through record()", "config_suggest": "computed from its arguments",
    "compute": "a number computed from literals and record values read through record()",
    "lead_ask": "a question", "mandate_propose": "a mandate card for the researcher", "researcher_ask": "a question", "report_write": "the writer's job; its evidence is frozen without locked results (INV-17)",
    "report_answer": "the writer's job", "yield_work": "ends the turn; its evidence ids through record()",
    "workspace_list": "the agent's own files", "workspace_read": "the agent's own files", "workspace_write": "the agent's own files",
    "workspace_run": "the agent's own script", "submit_output": "the agent's result",
    "library_search": "published strategies of earlier campaigns", "merge_note_draft": "a note the agent writes",
    "thread_pin": "ids the agent names; the context shows only their kind and status", "panel_render": "a panel the researcher's page resolves",
    "render_visual": "a visual the agent writes", "problem_note_draft": "the problem note", "problem_note_skip": "the problem note",
    "problem_note_propose": "the problem note", "procedure_read": "the procedure catalog",
    "charter_write": "the problem charter the lead writes", "charter_read": "the problem charter: the problem, no result or measurement",
}


@pytest.fixture
def locked(client, workspace, monkeypatch):
    """Two finished confirmation cells on a heldout task, not released, and a lead agent with a turn to call tools from."""
    campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Find a better optimizer", "tasks": [QUADRATIC, HELDOUT],
                                                           "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)["outcome"]["campaign"]
    lead = activate_team(client, workspace, campaign, monkeypatch)
    development, heldout = workspace.current_tasks(campaign["id"])
    request = TrialInput(campaign_id=campaign["id"], task_id=development["id"], algorithm="coordinate", max_steps=3, wall_seconds=5)
    prototype = workspace.create_trial(request)
    finish(workspace, prototype)
    study = workspace.create_study(campaign["id"], StudyInput(goal="A fixed procedure on an unseen condition", scope="confirmation",
        confirmation_kind="unseen_instance", prototype_trial_ids=[prototype["id"]], task_ids=[heldout["id"]], seeds=[17, 18]))
    request = request.model_copy(update={"task_id": heldout["id"], "confirmation_protocol_id": study["confirmation"]["id"]})
    cells = [finish(workspace, workspace.create_trial(request.model_copy(update={"seed": seed}))) for seed in (17, 18)]
    for cell in cells:
        workspace.store.put("message", {"id": "message_done_" + cell["id"], "campaign_id": campaign["id"], "role": "assistant", "origin": "lab_event",
                                        "content": f"Seed {cell['seed']} finished at {cell['result']['best_objective']}", "trial_id": cell["id"], "created_at": cell["created_at"]})
    workspace.pi._request(campaign["id"], True)
    turn = workspace.pi.enqueue(lead, "pi_run_locked", "How is the confirmation going? Which method is winning?")
    turn["status"] = "submitted"
    workspace.store.put("agent_run", turn)
    return workspace, campaign, workspace.store.get(lead["id"], "agent_session"), turn, prototype, cells, study["confirmation"]["id"]


def finish(workspace, trial):
    result = run_worker(workspace.job_dir(trial["id"]))
    assert result["scientific_complete"]
    trial.update(result=result, progress=result, status=result["status"], attempt=1)
    workspace.store.put("trial", trial)
    workspace.capture_evidence(trial)
    return workspace.store.get(trial["id"], "trial")


def calls(locked, prefix="before"):
    """One call of each read tool, as an agent would make it about the cells."""
    workspace, campaign, lead, turn, prototype, cells, _ = locked
    cell = cells[0]["id"]
    tools, counter = PiTools(workspace.pi), iter(range(10**6))
    workspace_dir = workspace.directory / "agents" / lead["id"] / "work"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "read.py").write_text("import os\nprint(sorted(os.listdir('/data')))\n")

    def call(name, args):
        return tools.call(lead["id"], turn["id"], f"{prefix}_{next(counter)}", name, args)
    return {
        "campaign_inspect": lambda: call("campaign_inspect", {}),
        "evidence_search": lambda: call("evidence_search", {"limit": 50}),
        "evidence_read": lambda: call("evidence_read", {"record_id": cell}),
        "experiment_progress": lambda: call("experiment_progress", {"finished": 40}),
        "file_list": lambda: call("file_list", {"root": "experiment", "trial_id": cell}),
        "file_read": lambda: call("file_read", {"root": "experiment", "trial_id": cell, "path": "spec.json"}),
        "file_search": lambda: call("file_search", {"root": "experiment", "trial_id": cell, "query": "seed"}),
        "analysis_run": lambda: call("analysis_run", {"path": "read.py", "trial_ids": [cell], "seconds": 5}),
        "campaign_command": lambda: call("campaign_command", {"operation": "comparison.report", "payload": {}, "request_key": f"{prefix}_compare"}),
        "lab_events": lambda: call("lab_events", {}),
    }


def scores(cells):
    return {json.dumps(cell["result"]["best_objective"]) for cell in cells}


def test_every_tool_is_checked(workspace):
    """A new agent tool fails here until it is a read checked below, or says why it returns no campaign record."""
    tools = set(TOOLS) | set(EXTRA_TOOLS)
    assert not READS & set(NO_RECORDS)
    assert tools - READS - set(NO_RECORDS) == set(), "an agent tool that is not checked against protected_ids()"
    # A problem pack's tool (mask_create is MEENT's) is registered only where the pack is installed.
    assert READS <= tools


def test_no_read_returns_a_locked_cell_before_release_and_every_read_does_after(locked):
    workspace, campaign, lead, turn, prototype, cells, protocol = locked
    withheld = workspace.memory.protected_ids(campaign["id"])
    assert {cell["id"] for cell in cells} <= withheld and prototype["id"] not in withheld
    reads = calls(locked)
    assert set(reads) == READS
    before = {name: read() for name, read in reads.items()}
    for name, result in before.items():
        text = json.dumps(result)
        # The status view of the cell read by id is status_<id>; nothing else names a cell.
        assert not any(cell["id"] in text for cell in (cells[1:] if name == "evidence_read" else cells)), name
        assert not scores(cells) & set(text.replace(",", " ").replace("}", " ").replace("]", " ").split()), name
    for name in ("file_list", "file_read", "file_search", "analysis_run"):
        assert WITHHELD in before[name]["error"], name
    assert set(before["evidence_read"]) == {"id", "campaign_id", "status", "study_execution_id", "protected_evidence", "message"}
    assert before["evidence_read"]["status"] == "completed"
    progress = [row for row in before["experiment_progress"]["recently_finished"] if row.get("protected_evidence")]
    assert len(progress) == 2 and all(row["status"] == "completed" and "best" not in row for row in progress)
    outcome = before["campaign_command"]["outcome"]
    assert outcome["withheld_runs"] == 2 and prototype["id"] in json.dumps(outcome)

    workspace.confirmations.release(protocol, authority="manager")
    assert not {cell["id"] for cell in cells} & workspace.memory.protected_ids(campaign["id"])
    after = {name: read() for name, read in calls(locked, "after").items()}
    for name in ("file_list", "file_read", "file_search", "analysis_run"):
        assert "error" not in after[name], (name, after[name])
    assert after["analysis_run"]["mounted"] == ["/data/" + cells[0]["id"]] and after["file_search"]["matches"]
    assert after["evidence_read"]["record_id"] == cells[0]["id"]
    best = PiTools(workspace.pi).call(lead["id"], turn["id"], "after_best", "evidence_read", {"record_id": cells[0]["id"], "pointer": "/result/best_objective"})
    assert json.dumps(best) == json.dumps(cells[0]["result"]["best_objective"])
    assert all(cell["id"] in json.dumps(after["evidence_search"]) for cell in cells)
    assert all(cell["id"] in json.dumps(after["experiment_progress"]) for cell in cells)
    assert all(cell["id"] in json.dumps(after["campaign_command"]) for cell in cells)
    assert "withheld_runs" not in after["campaign_command"]["outcome"]
    assert all(cell["id"] in json.dumps(after["lab_events"]) for cell in cells)


def test_records_that_name_a_locked_cell_are_withheld_and_a_comparison_naming_one_is_refused(locked):
    workspace, campaign, lead, turn, prototype, cells, _ = locked
    tools = PiTools(workspace.pi)
    # A tool receipt is outside the visibility walk: one saved before this change, holding the cell, is withheld because it names it.
    workspace.store.put("agent_tool_receipt", {"id": "pi_tool_old", "campaign_id": campaign["id"], "agent_id": lead["id"], "run_id": turn["id"],
                                               "tool": "evidence_read", "request_hash": "old", "result": cells[0], "created_at": cells[0]["created_at"]})
    with pytest.raises(ValueError, match=WITHHELD):
        tools.record(lead, "pi_tool_old")
    # Today's receipt of that read holds the status view only, and stays readable.
    assert tools.call(lead["id"], turn["id"], "read_cell", "evidence_read", {"record_id": cells[0]["id"]})["protected_evidence"]
    # The cell's captured evidence refers to it, and is withheld from the walk.
    assets = [row["id"] for row in workspace.store.list("asset", campaign["id"]) if row.get("producer_id") == cells[0]["id"]]
    assert assets and set(assets) <= workspace.memory.protected_ids(campaign["id"])
    # A finding that refers to a cell stays withheld, as before.
    workspace.store.put("manager_note", {"id": "finding_cell", "campaign_id": campaign["id"], "kind": "finding", "claim": "The method wins",
                                         "source_ids": [cells[0]["id"]], "created_at": cells[0]["created_at"]})
    with pytest.raises(ValueError, match=WITHHELD):
        tools.record(lead, "finding_cell")
    refused = tools.call(lead["id"], turn["id"], "compare_cell", "campaign_command",
                         {"operation": "comparison.report", "payload": {"trial_ids": [cells[0]["id"]]}, "request_key": "compare_cell"})
    assert "withheld until the confirmation is released" in refused["error"]
    # The researcher's own comparison has them.
    researcher = workspace.commands.execute(Command(id="researcher_compare", campaign_id=campaign["id"], expected_revision=workspace.store.get(campaign["id"], "campaign")["version"],
                                                    operation="comparison.report", payload={"trial_ids": [cells[0]["id"]]}))
    assert cells[0]["id"] in json.dumps(researcher["outcome"])


def test_protected_ids_are_cached_until_the_campaign_changes(locked):
    workspace, campaign, lead, turn, prototype, cells, protocol = locked
    calls_made = []
    walk = workspace.memory._walk
    workspace.memory._walk = lambda campaign_id: calls_made.append(campaign_id) or walk(campaign_id)
    first = workspace.memory.protected_ids(campaign["id"])
    assert workspace.memory.protected_ids(campaign["id"]) is first and len(calls_made) == 1
    workspace.confirmations.release(protocol, authority="manager")
    assert not {cell["id"] for cell in cells} & workspace.memory.protected_ids(campaign["id"]) and len(calls_made) == 2
