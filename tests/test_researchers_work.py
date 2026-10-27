"""Outcomes belong to the mandate that started the work (roadmap R6): a run the researcher started directly is under no agent's
mandate, so its end wakes nobody and it does not hold the lead's request open; the researcher follows it on the pages. A run an
agent started, or Balsamic started under an agent's mandate, still wakes that agent and holds its request open."""
from optimization_framework.campaigns.plan_runs import launch_ready
from test_mandate_guard import approve_screen, operator_for, runnable
from test_mandate_propose import team, version  # noqa: F401  (team is a fixture)
from support import command


def researchers_run(env, key):
    """A run the researcher starts with their own command, as the pages and the API do."""
    task = env.workspace.current_tasks("demo")[0]
    receipt = command(env.client, "trial.create", "demo", {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5,
                      "wall_seconds": 30, "question": key}, version(env))
    assert receipt["actor"] == "researcher"
    return receipt["outcome"]["trial_id"]


def planned_run(env):
    """A run Balsamic starts under the Screen mandate the lead proposed and the researcher approved."""
    runnable(env, "H01")
    task = env.workspace.current_tasks("demo")[0]
    approve_screen(env, "screen", plan="Run H01 once", hypothesis_ids=["H01"], worker_seconds=600, wall_seconds=60,
                   runs=[{"task_id": task["id"], "hypothesis_id": "H01", "seeds": [0], "wall_seconds": 30}])
    [launched] = launch_ready(env.workspace, "demo")["launched"]
    return launched["trial_id"]


def finish(env, *trial_ids):
    for identity in trial_ids:
        env.workspace.store.put("trial", {**env.workspace.store.get(identity, "trial"), "status": "completed"}, "trial.evidence_cataloged")


def notices(env):
    return {run["id"]: (run["agent_id"], run["input"]) for run in env.workspace.store.list("agent_run", "demo") if run["id"].startswith("pi_events_")}


def complete(env, key):
    return env.tools.call(env.lead["id"], env.run["id"], key, "yield_work", {"disposition": "complete", "summary": "Answered",
                          "report": "The request is answered.", "evidence_ids": []})


def test_a_run_the_researcher_started_finishes_without_waking_the_lead_and_an_agents_run_still_wakes_its_agent(team):
    assert team.workspace.pi.configuration("demo")["request_open"]
    planned = planned_run(team)
    operator, run = operator_for(team)
    task = team.workspace.current_tasks("demo")[0]
    asked = team.tools.call(operator["id"], run["id"], "probe", "campaign_command", {"operation": "trial.create", "request_key": "probe", "payload": {
        "task_id": task["id"], "hypothesis_id": "H01", "algorithm": "coordinate", "seed": 1, "max_steps": 5, "wall_seconds": 30}})["outcome"]["trial_id"]
    mine = researchers_run(team, "mine")
    team.workspace.pi._campaign_events("demo")   # the researcher's go-ahead, an answer to the lead, goes first
    before = notices(team)
    # The researcher's run ends while the lead's request is open: nobody is woken.
    finish(team, mine)
    team.workspace.pi._campaign_events("demo")
    assert notices(team) == before
    # The run Balsamic started under the lead's mandate wakes the lead, the run the operator started for it wakes the operator.
    finish(team, planned, asked)
    team.workspace.pi._campaign_events("demo")
    woken = {identity: found for identity, found in notices(team).items() if identity not in before}
    assert sorted(agent for agent, _ in woken.values()) == sorted([team.lead["id"], operator["id"]])
    by_agent = {agent: text for agent, text in woken.values()}
    assert planned in by_agent[team.lead["id"]] and asked in by_agent[operator["id"]]
    assert not any(mine in text for _, text in notices(team).values())


def test_the_researchers_own_run_does_not_hold_the_leads_request_open_and_a_run_under_its_mandate_does(team):
    mine = researchers_run(team, "mine")
    assert team.workspace.store.get(mine, "trial")["status"] == "queued"
    assert complete(team, "done")["saved"] is True
    planned = planned_run(team)
    assert team.workspace.store.get(planned, "trial")["status"] == "queued"
    refused = complete(team, "again")
    assert refused["executed"] is False and "Outstanding assignments or experiments remain" in refused["error"]
