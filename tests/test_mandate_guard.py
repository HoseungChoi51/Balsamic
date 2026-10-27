"""The bus refuses an agent's work outside its request's mandate (roadmap R3): a class the mandate does not allow, a proposal a Screen
mandate does not name, work past Explore's envelope, and new work once the mandate has ended (decision 11), while work already
running goes on. A page agent the lead asked works under the lead's mandate; the researcher's commands are never checked. A
mandate whose runs have all ended closes and tells the lead once; a closed one starts nothing more, Balsamic's planned runs included."""
from datetime import datetime, timedelta, timezone

import pytest

from optimization_framework.campaigns import mandates
from optimization_framework.campaigns.plan_runs import command_id, launch_ready
from optimization_framework.contracts.commands import Command, CommandOrigin
from test_mandate_propose import MAIN, propose, resolve, root, say, state, team, version  # noqa: F401  (team is a fixture)
from support import command, submitted  # noqa: E402


def runnable(env, identity):
    env.workspace.store.put("hypothesis", {"id": identity, "campaign_id": "demo", "title": identity, "mechanism": "m", "rationale": "r",
        "parent_ids": [], "algorithm": "coordinate", "algorithm_config": {}, "algorithm_chosen": True, "status": "proposed", "executable": True})


def operator_for(env, run=None, text="Run what the request needs."):
    """The experiment operator asked by the lead in this turn: it works for the lead's request."""
    env.tools.call(env.lead["id"], (run or env.run)["id"], "ask_" + str(len(env.workspace.store.list("message", "demo"))), "page_agent_message",
                   {"page_agent": "experiment_operator", "message": text})
    operator = env.workspace.pi.page_agent("demo", "experiment_operator")
    latest = sorted(env.workspace.store.list_agent_runs(operator["id"]), key=lambda found: found["created_at"])[-1]
    return env.workspace.store.get(operator["id"], "agent_session"), submitted(env.workspace, latest["id"])


def notice(env, key):
    """A platform notice to the lead that continues its first request: a turn of the same request, on the current guidance."""
    from optimization_framework.agents.models import NOTICE
    return submitted(env.workspace, env.workspace.pi.enqueue(env.lead, "notice_" + key, NOTICE + "Outcomes.", root=root(env))["id"])


def trial(env, agent, run, key, hypothesis_id=None, wall=60):
    task = env.workspace.current_tasks("demo")[0]
    payload = {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": wall,
               **({"hypothesis_id": hypothesis_id} if hypothesis_id else {})}
    return env.tools.call(agent["id"], run["id"], key, "campaign_command", {"operation": "trial.create", "request_key": key, "payload": payload})


def approve_screen(env, call_id, run=None, **args):
    receipt = propose(env, call_id, run=run, template="screen", **args)
    return resolve(env, env.workspace.store.get(receipt["outcome"]["decision_id"], "decision"), "0")


def test_a_screen_mandate_for_four_proposals_refuses_a_run_of_a_fifth_and_allows_theirs(team):
    for identity in ("H01", "H02", "H03", "H04", "H05"):
        runnable(team, identity)
    approve_screen(team, "screen", plan="Screen H01 to H04 against each other", hypothesis_ids=["H01", "H02", "H03", "H04"],
                   worker_seconds=2400, wall_seconds=900)
    operator, run = operator_for(team)
    refused = trial(team, operator, run, "h05", "H05")
    assert refused["executed"] is False
    assert "covers the work for H01, H02, H03, H04 only, and trial.create is for H05" in refused["error"]
    assert "mandate_propose (template screen)" in refused["error"]
    allowed = trial(team, operator, run, "h02", "H02")
    assert allowed["status"] == "completed", allowed
    assert [t["hypothesis_id"] for t in team.workspace.store.list("trial", "demo")] == ["H02"]


def test_after_the_deadline_a_new_run_is_refused_the_running_one_goes_on_and_the_researcher_is_told_once(team):
    runnable(team, "H01")
    task = team.workspace.current_tasks("demo")[0]
    approve_screen(team, "screen", plan="Screen H01", hypothesis_ids=["H01"], worker_seconds=2400, wall_seconds=900, deadline_minutes=30,
                   runs=[{"task_id": task["id"], "hypothesis_id": "H01", "seeds": [5], "wall_seconds": 30}])
    operator, run = operator_for(team)
    first = trial(team, operator, run, "first", "H01")
    assert first["status"] == "completed", first
    mandate = mandates.governing(team.workspace, "demo", root(team))
    row = team.workspace.store.get(mandate.id, "mandate")
    row["deadline_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    team.workspace.store.put("mandate", row)
    refused = trial(team, operator, run, "second", "H01")
    assert refused["executed"] is False and "has ended: its deadline passed" in refused["error"] and "Work already running goes on" in refused["error"]
    [running] = team.workspace.store.list("trial", "demo")
    assert running["status"] in {"queued", "running"}            # nothing is stopped
    # Recording what the work found is still allowed; the state block says new work is refused.
    recorded = team.tools.call(team.lead["id"], notice(team, "record")["id"], "finding", "campaign_command", {"operation": "finding.record", "request_key": "f",
        "payload": {"content": "H01's first run is queued", "source_ids": [running["id"]], "statement": "evidence"}})
    assert recorded.get("status") == "completed", recorded
    assert "; expired, new work is refused;" in state(team)
    # The researcher is told once, in the inbox; Balsamic starts nothing more under it.
    assert mandates.settle(team.workspace, "demo") == [] and mandates.settle(team.workspace, "demo") == []
    [issue] = [found for found in team.workspace.store.list("manager_issue", "demo") if found["code"] == "mandate_ended"]
    assert issue["affected"] == mandate.id and "has ended: its deadline passed" in issue["message"] and issue["occurrences"] == 1
    assert "1 of its approved runs did not start" in issue["message"]
    # The lead, waiting for the planned run, is told once that it will not start.
    [told] = [found for found in team.workspace.store.list_agent_runs(team.lead["id"]) if found["id"].startswith("mandate_ended_")]
    assert "before 1 of its approved runs started" in told["input"] and mandates.same_root(told["origin"]["root"], root(team))
    assert launch_ready(team.workspace, "demo") == {"launched": [], "waiting": []}
    campaign = team.workspace.store.get("demo", "campaign")
    with pytest.raises(ValueError, match="that this planned run is approved under has ended"):
        team.workspace.commands.execute(Command(id=command_id(mandate.consent_id, 0, 5), campaign_id="demo", expected_revision=campaign["version"],
            operation="trial.create", payload={"task_id": task["id"], "hypothesis_id": "H01", "algorithm": "coordinate", "seed": 5, "wall_seconds": 30},
            origin=CommandOrigin(actor="balsamic", consent_id=mandate.consent_id, mandate_id=mandate.id)), actor="balsamic")
    assert len(team.workspace.store.list("trial", "demo")) == 1


def test_a_page_agent_asked_by_the_lead_is_checked_against_the_leads_mandate_and_on_its_page_against_its_own(team):
    granted = propose(team, "answer", template="answer", plan="Answer from the records")
    assert granted["status"] == "active"
    operator, run = operator_for(team)
    refused = trial(team, operator, run, "probe")
    assert refused["executed"] is False
    assert f"trial.create is run work, which this request's Answer mandate ({granted['mandate_id']}) does not allow" in refused["error"]
    assert "template explore" in refused["error"] and team.workspace.store.list("trial", "demo") == []
    # Asked on its page by the researcher, it works under its own request: Explore by default.
    asked = say(team, "Run one short probe of coordinate search.", page_agent="experiment_operator")
    operator = team.workspace.store.get(operator["id"], "agent_session")
    started = trial(team, operator, asked, "own")
    assert started["status"] == "completed", started
    assert mandates.governing(team.workspace, "demo", root(team, asked)).template == "explore"


def test_the_researchers_commands_pass_with_no_mandate_and_explore_refuses_decisions_and_work_past_its_envelope(team):
    runnable(team, "H01")
    task = team.workspace.current_tasks("demo")[0]
    for operation, payload in (("trial.create", {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 1200}),
                               ("hypothesis.status", {"hypothesis_id": "H01", "status": "investigating", "expected_status_revision": 0})):
        assert command(team.client, operation, "demo", payload, version(team))["status"] == "completed"
    assert mandates.mandates(team.workspace, "demo") == []
    # The lead's request has the default, Explore: a decision is not Explore's.
    refused = team.tools.call(team.lead["id"], notice(team, "stop")["id"], "stop", "campaign_command", {"operation": "hypothesis.status", "request_key": "s",
        "payload": {"hypothesis_id": "H01", "status": "archived", "expected_status_revision": 1, "stop_reason": "Slow"}})
    assert refused["executed"] is False
    assert "hypothesis.status is decide work, which this request's default mandate, Explore, does not allow" in refused["error"]
    assert "template screen, which goes to the researcher as one card" in refused["error"]
    # Explore covers the go-ahead threshold (5 min) in total: two 2-minute runs, not a third.
    operator, run = operator_for(team)
    for key in ("one", "two"):
        assert trial(team, operator, run, key, wall=120)["status"] == "completed"
    third = trial(team, operator, run, "three", wall=120)
    assert third["executed"] is False and "has 60 s of worker time left of 5 min in total" in third["error"]
    # A request has one Explore: asking again returns it while it lasts, and is refused once it is spent.
    again = propose(team, "explore", template="explore", plan="More probes")
    assert again["mandate_id"] == mandates.governing(team.workspace, "demo", root(team)).id and "nothing new was granted" in again["next"]
    explore = mandates.governing(team.workspace, "demo", root(team))
    mandates.charge(team.workspace, explore.id, 60)
    spent = propose(team, "explore2", template="explore", plan="Even more probes")
    assert spent["executed"] is False and "has had its Explore" in spent["error"]


def test_when_every_run_of_a_mandate_ends_it_closes_and_the_lead_is_told_once_then_nothing_more_starts(team):
    granted = propose(team, "explore", template="explore", plan="Two probes", worker_seconds=240,
                      stop_when={"text": "Both probes finished", "machine": "all_runs_terminal"})
    operator, run = operator_for(team)
    for key in ("one", "two"):
        assert trial(team, operator, run, key)["status"] == "completed"
    trials = team.workspace.store.list("trial", "demo")
    assert set(team.workspace.store.get(granted["mandate_id"], "mandate")["launched"]) == {t["id"] for t in trials}
    assert mandates.settle(team.workspace, "demo") == []          # the runs have not ended
    for found in trials:
        team.workspace.store.put("trial", {**found, "status": "completed"})
    assert mandates.settle(team.workspace, "demo") == [granted["mandate_id"]]
    assert mandates.settle(team.workspace, "demo") == []
    notices = [found for found in team.workspace.store.list_agent_runs(team.lead["id"]) if found["id"].startswith("mandate_stop_")]
    assert len(notices) == 1 and "Both probes finished" in notices[0]["input"] and "is closed" in notices[0]["input"]
    assert mandates.same_root(notices[0]["origin"]["root"], root(team))
    refused = trial(team, operator, run, "three")
    assert refused["executed"] is False and "has ended: it was closed" in refused["error"]


def test_a_closed_mandate_refuses_the_next_agent_command_and_balsamic_starts_none_of_its_planned_runs(team):
    for identity in ("H01", "H02"):
        runnable(team, identity)
    task = team.workspace.current_tasks("demo")[0]
    plan = lambda h: [{"task_id": task["id"], "hypothesis_id": h, "seeds": [0], "wall_seconds": 30}]
    approve_screen(team, "first", plan="Run H01 once", hypothesis_ids=["H01"], runs=plan("H01"), worker_seconds=600, wall_seconds=60)
    first = mandates.governing(team.workspace, "demo", root(team))
    other = say(team, "And run H02 once.")
    approve_screen(team, "second", run=other, plan="Run H02 once", hypothesis_ids=["H02"], runs=plan("H02"), worker_seconds=600, wall_seconds=60)
    closed = mandates.close(team.workspace, first.id, by="researcher", reason="Enough")
    assert closed.status == "closed" and team.workspace.store.get(first.consent_id, "compute_consent")["closed_at"]
    launched = launch_ready(team.workspace, "demo")["launched"]
    assert [row["hypothesis_id"] for row in launched] == ["H02"]
    receipt = team.workspace.store.get(launched[0]["command_id"], "work_command")
    assert receipt["origin"]["mandate_id"] == mandates.governing(team.workspace, "demo", root(team, other)).id
    operator, run = operator_for(team)
    refused = trial(team, operator, run, "after", "H01")
    assert refused["executed"] is False and "has ended: it was closed" in refused["error"]
    assert [t["hypothesis_id"] for t in team.workspace.store.list("trial", "demo")] == ["H02"]
