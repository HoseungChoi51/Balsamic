"""Partnership metrics (roadmap J3): per researcher request, the researcher's actions, the time to the lead's report and to a
ranked result, the worker time and model dollars spent under it, and the best objective by then in the objective's direction."""
from datetime import datetime, timedelta, timezone

import pytest

from support import activate_team, command, finish_run
from optimization_framework.agents import usage
from balsamic.monitor.partnership import requests

T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)


def at(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def lead(client, workspace, campaign, monkeypatch):
    lead = activate_team(client, workspace, campaign, monkeypatch)
    config = workspace.pi.configuration("demo")
    workspace.store.put("agent_campaign", {**config, "provider": {"configured": True}})
    for row in workspace.store.list("work_command", "demo"):   # creating and activating the campaign came before T0
        edit(workspace, "work_command", row["id"], created_at=at(-60))
    return lead


def edit(workspace, kind, identity, **fields):
    record = workspace.store.get(identity, kind)
    workspace.store.put(kind, {**record, **fields})


def ask(client, workspace, campaign, text, seconds):
    """The researcher writes to the lead at T0 + seconds: the message, its command and the lead's turn are dated then."""
    receipt = command(client, "agent.message", "demo", {"message": text, "thread_id": "thread_main_demo"}, campaign["version"],
                      origin={"thread_id": "thread_main_demo", "actor": "researcher"})
    edit(workspace, "work_command", receipt["id"], created_at=at(seconds))
    edit(workspace, "message", "message_" + receipt["id"], created_at=at(seconds))
    edit(workspace, "agent_run", "pi_run_" + receipt["id"], created_at=at(seconds))
    return workspace.store.get("pi_run_" + receipt["id"], "agent_run")


def end(workspace, run, seconds, disposition):
    finish_run(workspace, run["id"], "Done." if disposition == "complete" else "Working on it.", disposition=disposition)
    edit(workspace, "agent_run", run["id"], finished_at=at(seconds))


def sent(workspace, run, identity, operation, seconds, outcome=None, actor="manager"):
    """A command an agent sent during a turn (its origin names the turn), or, with actor researcher, one the researcher sent."""
    origin = {"run_id": run["id"], "actor": "lead", "thread_id": "thread_main_demo"} if run else None
    workspace.store.put("work_command", {"id": identity, "campaign_id": "demo", "actor": actor, "origin": origin,
        "request": {"operation": operation, "payload": {}}, "status": "completed", "outcome": outcome or {}, "created_at": at(seconds)})


def trial(workspace, identity, best, execution_seconds, finished, **fields):
    workspace.store.put("trial", {"id": identity, "campaign_id": "demo", "status": "completed", "execution_seconds": execution_seconds,
        "result": {"best_objective": best, "objective_definition": {"name": "value", "direction": "minimize"}},
        "finished_at": at(finished), **fields})


def call(workspace, agent, key, seconds, cost, billing="api"):
    usage.record(workspace.store, "demo", agent, key, {"usage": {"cost_usd": cost}, "billing": billing, "occurred_at": at(seconds)})


def test_two_requests_give_their_own_actions_times_costs_and_best_so_far(client, workspace, campaign, lead):
    first = ask(client, workspace, campaign, "Screen two methods", 0)
    call(workspace, lead, "c1", 10, 0.10)
    sent(workspace, first, "launch_1", "trial.create", 20, {"trial_id": "trial_1"})
    sent(workspace, first, "race_1", "study.race.create", 30, {"race_id": "race_1"})
    sent(workspace, None, "resolve_1", "decision.resolve", 100, actor="researcher")
    sent(workspace, None, "control_1", "trial.control", 200, actor="researcher")
    sent(workspace, None, "decision_action_x", "trial.control", 201, actor="researcher")   # the decision's own effect
    end(workspace, first, 350, "waiting")
    # A notice turn continues the request: its calls and commands are the request's, and its report closes it.
    notice = workspace.pi.enqueue(lead, "notice_1", "The runs finished.", root=workspace.pi.request_root(first))
    edit(workspace, "agent_run", notice["id"], created_at=at(400))
    call(workspace, lead, "c2", 410, 0.05)
    call(workspace, lead, "c3", 420, 0.02, billing="subscription")
    sent(workspace, notice, "compare_1", "comparison.report", 500)
    end(workspace, notice, 600, "complete")
    trial(workspace, "trial_1", 2.0, 40, 250)
    trial(workspace, "trial_2", 3.0, 25, 300, race_id="race_1")
    trial(workspace, "trial_3", 1.5, 10, 550)    # the researcher's own run: not the request's cost, but the best by its report
    trial(workspace, "trial_4", 0.5, 10, 700)    # finished after the report

    second = ask(client, workspace, campaign, "Summarize the results", 1000)
    call(workspace, lead, "c4", 1010, 0.30)

    rows = {row["run_id"]: row for row in requests(workspace, "demo")}
    assert list(rows) == [first["id"], second["id"]]
    one, two = rows[first["id"]], rows[second["id"]]
    assert one["researcher_actions"] == {"messages": 1, "decisions": 1, "commands": 1, "total": 3}
    assert one["closed"] and one["seconds_to_report"] == 600 and one["seconds_to_first_ranked"] == 500
    assert one["runs"] == 2 and one["worker_seconds"] == 65
    assert one["model_calls"] == 3 and one["model_usd"] == pytest.approx(0.17) and one["model_charged_usd"] == pytest.approx(0.15)
    assert one["best"] == {"value": 1.5, "direction": "minimize", "trial_id": "trial_3"}

    assert two["researcher_actions"]["total"] == 1 and two["text"] == "Summarize the results"
    assert not two["closed"] and two["seconds_to_report"] is None and two["seconds_to_first_ranked"] is None
    assert two["runs"] == 0 and two["worker_seconds"] == 0
    assert two["model_calls"] == 1 and two["model_usd"] == pytest.approx(0.30)
    assert two["best"]["value"] == 0.5   # open: the best by now, the lowest since the problem is minimized


def test_a_maximize_problem_reports_the_highest_value_and_autopilot_or_notices_open_no_request(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Run it", 0)
    edit(workspace, "agent_run", run["id"], autopilot=False)
    for identity, best in (("trial_a", 0.4), ("trial_b", 0.9)):
        workspace.store.put("trial", {"id": identity, "campaign_id": "demo", "status": "completed", "finished_at": at(10),
            "result": {"best_objective": best, "objective_definition": {"name": "value", "direction": "maximize"}}})
    workspace.pi.enqueue(lead, "autopilot_1", "Next round.", autopilot=True, origin={"thread_id": "thread_main_demo", "actor": "autopilot"})
    [row] = requests(workspace, "demo")
    assert row["best"] == {"value": 0.9, "direction": "maximize", "trial_id": "trial_b"}
    assert row["model_calls"] == 0 and row["model_usd"] == 0 and row["seconds_to_report"] is None


def test_a_turn_from_before_finished_at_takes_its_end_from_the_event_log(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Answer a question", 0)
    finish_run(workspace, run["id"], "Here it is.", disposition="complete")
    record = workspace.store.get(run["id"], "agent_run")
    assert record["finished_at"]   # the controller stamps the end of a turn
    record.pop("finished_at")
    workspace.store.put("agent_run", record)
    [row] = requests(workspace, "demo")
    assert row["closed"] and row["seconds_to_report"] == pytest.approx(7200, abs=120)


def test_the_monitor_route_serves_the_table(client, workspace, campaign, lead):
    run = ask(client, workspace, campaign, "Run it", 0)
    body = client.get("/api/v1/campaigns/demo/partnership").json()
    assert [row["run_id"] for row in body["requests"]] == [run["id"]] and "best" in body["basis"]
    assert client.get("/api/v1/campaigns/missing/partnership").status_code == 404
