"""Stalls inside Balsamic: an open request with nothing in progress wakes the lead once, then tells the researcher; an agent
turn with no reply for a long time is reported; both clear themselves when work moves again."""
from datetime import datetime, timedelta, timezone

import pytest

from support import activate_team, command, finish_run
from balsamic.monitor import stalls
from balsamic.monitor.rows import monitor_view


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def backdate(workspace, **fields):
    watch = workspace.store.get("stall_watch_demo", "stall_watch")
    workspace.store.put("stall_watch", {**watch, **{key: ago(value) for key, value in fields.items()}})


def pending_issues(workspace, code):
    return [issue for issue in workspace.store.list("manager_issue", "demo") if issue["code"] == code and issue["status"] == "pending"]


@pytest.fixture
def lead(client, workspace, campaign, monkeypatch):
    lead = activate_team(client, workspace, campaign, monkeypatch)
    config = workspace.pi.configuration("demo")
    workspace.store.put("agent_campaign", {**config, "provider": {"configured": True}})
    return lead


def ask(client, workspace, campaign, text):
    receipt = command(client, "agent.message", "demo", {"message": text, "thread_id": "thread_main_demo"}, campaign["version"],
                      origin={"thread_id": "thread_main_demo", "actor": "researcher"})
    return next(run for run in workspace.store.list("agent_run", "demo") if run["status"] == "queued" and text in run["input"])


def test_an_open_request_with_nothing_in_progress_wakes_the_lead_then_tells_the_researcher(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Run the screening")
    stalls.check(workspace, "demo")
    assert workspace.store.list("stall_watch", "demo") == []   # the lead's turn is work in progress
    finish_run(workspace, run["id"], "Asked the operator to launch the runs.", disposition="handoff")
    assert workspace.pi.configuration("demo")["request_open"]
    stalls.check(workspace, "demo")
    assert not [r for r in workspace.store.list("agent_run", "demo") if r["id"].startswith(stalls.NOTICE_PREFIX)]
    backdate(workspace, idle_since=stalls.IDLE_SECONDS + 60)
    assert "nothing has been in progress for 6 min" in monitor_view(workspace, "demo")["pill"]["text"]

    stalls.check(workspace, "demo")
    notice = next(r for r in workspace.store.list("agent_run", "demo") if r["id"].startswith(stalls.NOTICE_PREFIX))
    assert notice["agent_id"] == lead["id"] and "nothing has been in progress for 6 minutes" in notice["input"]
    stalls.check(workspace, "demo")   # the lead's turn on the notice holds the clock: no second notice, no issue
    assert len([r for r in workspace.store.list("agent_run", "demo") if r["id"].startswith(stalls.NOTICE_PREFIX)]) == 1
    finish_run(workspace, notice["id"], "Still waiting.", disposition="handoff")
    backdate(workspace, notified_at=stalls.ESCALATE_SECONDS + 60)
    stalls.check(workspace, "demo")
    [issue] = pending_issues(workspace, "request_stalled")
    assert "a notice to the lead did not get it moving" in issue["message"]
    assert any(m.get("issue_id") == issue["id"] for m in workspace.store.list("message", "demo"))

    ask(client, workspace, campaign, "Launch them now")   # work moves again: the issue clears itself
    stalls.check(workspace, "demo")
    assert pending_issues(workspace, "request_stalled") == []
    assert workspace.store.get(issue["id"], "manager_issue")["resolution_basis"].startswith("Work is in progress again")


def test_a_closed_request_or_an_open_question_is_not_a_stall(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Summarize the results")
    finish_run(workspace, run["id"], "Done.", disposition="complete")
    assert not workspace.pi.configuration("demo")["request_open"]
    assert stalls.idle_request(workspace, "demo") is None
    run = ask(client, workspace, campaign, "Pick a seed")
    finish_run(workspace, run["id"], "Asked the researcher.", disposition="handoff")
    workspace.store.put("agent_question", {"id": "question_1", "campaign_id": "demo", "status": "pending", "question": "Which seed?"})
    assert stalls.idle_request(workspace, "demo") is None


def test_a_turn_with_no_reply_for_long_is_reported_and_clears_when_it_moves(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Design the checks")
    run.update(status="running", dispatched_at=ago(stalls.WAIT_SECONDS + 300))
    workspace.store.put("agent_run", run)
    agent = workspace.store.get(lead["id"], "agent_session")
    workspace.store.put("agent_session", {**agent, "reasoning_effort": "max", "last_activity_at": ago(stalls.WAIT_SECONDS + 120)})
    stalls.check(workspace, "demo")
    [issue] = pending_issues(workspace, "agent_long_wait")
    assert run["id"] in issue["message"] and "at max effort" in issue["message"] and "Models page" in issue["message"]
    assert "has waited 22 min" in " ".join(entry["text"] for entry in monitor_view(workspace, "demo")["attention"])
    stalls.check(workspace, "demo")
    assert len(workspace.store.list("manager_issue", "demo")) == 1   # reported once per turn
    workspace.store.put("agent_session", {**workspace.store.get(lead["id"], "agent_session"), "last_activity_at": ago(5)})
    stalls.check(workspace, "demo")
    assert pending_issues(workspace, "agent_long_wait") == []


def test_a_quiet_coding_workspace_tells_the_lead_then_the_researcher_and_clears_when_it_moves(client, workspace, campaign, lead):
    workspace.store.put("development_workspace", {"id": "development_quiet", "campaign_id": "demo", "hypothesis_id": "hypothesis_x",
        "title": "Subset DP", "status": "running", "desired_status": "running", "created_at": ago(3000), "last_activity_at": ago(1000),
        "cursor": 0, "usage": {}})
    stalls.check(workspace, "demo")
    notice = next(r for r in workspace.store.list("agent_run", "demo") if r["id"].startswith("pi_development_"))
    assert notice["agent_id"] == lead["id"] and 'coding agent for "Subset DP"' in notice["input"] and "said nothing while working" in notice["input"]
    assert any("quiet for 16 min" in text for _, text in stalls.attention(workspace, "demo"))
    stalls.check(workspace, "demo")
    assert not pending_issues(workspace, "coding_quiet")
    watch = workspace.store.get("stall_watch_demo", "stall_watch")
    watch["quiet"]["development_quiet"]["notified_at"] = ago(stalls.ESCALATE_SECONDS + 60)
    workspace.store.put("stall_watch", watch)
    stalls.check(workspace, "demo")
    [issue] = pending_issues(workspace, "coding_quiet")
    assert "notice to the lead did not get it moving" in issue["message"] and "Implementations page" in issue["message"]
    # It moves again: the issue clears. Settled after delivering, it is not quiet.
    record = workspace.store.get("development_quiet", "development_workspace")
    workspace.store.put("development_workspace", {**record, "status": "idle", "last_activity_at": ago(5000)})
    workspace.store.put("development_submission", {"id": "development_submission_q", "campaign_id": "demo", "workspace_id": "development_quiet",
        "commit": "a" * 40, "status": "submitted", "created_at": ago(5000)})
    stalls.check(workspace, "demo")
    assert not pending_issues(workspace, "coding_quiet") and stalls.quiet_workspaces(workspace, "demo") == []
