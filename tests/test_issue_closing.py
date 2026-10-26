"""An agent closes an inbox issue whose condition no longer holds, saying why; deferring an issue and taking its actions stay the
researcher's. The closing is not researcher guidance, and the researcher sees it and can reopen the issue."""
import pytest

from balsamic.monitor.rows import inbox_view
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace


@pytest.fixture
def lab(tmp_path):
    from balsamic.commands import register
    workspace = Workspace(tmp_path)
    register(workspace)
    campaign = workspace.create_campaign(CampaignInput(name="Inbox", autonomy="delegated", compute_budget_seconds=2000,
        validation_reserve_seconds=0, delegated_trial_seconds=100, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign["id"]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def test_the_lead_closes_an_issue_that_no_longer_holds_and_the_researcher_can_reopen_it(lab):
    workspace, cid = lab
    issue = workspace.memory.issue(cid, "implementation_job", "Candidate attempts exhausted.", affected="grant_old")
    reason = "Superseded: the method is now built as a library and bound to H12."
    with pytest.raises(ValueError, match="Deferring an issue and taking one of its actions are the researcher's"):
        send(workspace, cid, "defer", "issue.resolve", {"issue_id": issue["id"], "expected_revision": issue["revision"], "choice": "deferred", "comment": reason})
    with pytest.raises(ValueError, match="says what superseded or fixed it"):
        send(workspace, cid, "terse", "issue.resolve", {"issue_id": issue["id"], "expected_revision": issue["revision"], "choice": "resolved"})

    guidance = workspace.memory.state(cid)["guidance_revision"]
    send(workspace, cid, "close", "issue.resolve", {"issue_id": issue["id"], "expected_revision": issue["revision"], "choice": "resolved", "comment": reason})
    closed = workspace.store.get(issue["id"], "manager_issue")
    assert closed["status"] == "resolved" and closed["resolved_by"] == "lead" and closed["comment"] == reason
    assert workspace.memory.state(cid)["guidance_revision"] == guidance, "the lead's closing is not researcher guidance"
    [note] = [row for row in workspace.store.list("manager_note", cid) if row["kind"] == "decision"]
    assert note["author"] == "lead" and "Closed by the lead as no longer holding" in note["content"]
    view = inbox_view(workspace, cid)
    assert view["issues"] == [] and [row["id"] for row in view["closed_by_lead"]] == [issue["id"]]

    with pytest.raises(ValueError, match="needs researcher authorization"):
        send(workspace, cid, "agent_reopen", "issue.reopen", {"issue_id": issue["id"]})
    send(workspace, cid, "reopen", "issue.reopen", {"issue_id": issue["id"]}, actor="researcher")
    reopened = workspace.store.get(issue["id"], "manager_issue")
    assert reopened["status"] == "pending" and "resolved_by" not in reopened and reopened["revision"] == closed["revision"] + 1
    assert [row["id"] for row in inbox_view(workspace, cid)["issues"]] == [issue["id"]] and inbox_view(workspace, cid)["closed_by_lead"] == []
