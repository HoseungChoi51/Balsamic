"""The lead's first act on a request is its mandate (roadmap R2): mandate_propose grants Answer and Explore at once and turns Screen and
Run the campaign into one inbox card with three choices; a request with none has Explore from its first work-starting command; the
state block names the request's mandate and what is left of it."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from support import QUADRATIC, activate_team, command, submitted  # noqa: E402

from optimization_framework.agents.tools import PiTools  # noqa: E402
from optimization_framework.campaigns import mandates  # noqa: E402
from optimization_framework.campaigns.compute_consent import request_root  # noqa: E402

MAIN = "thread_main_demo"


@pytest.fixture
def team(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        workspace = app.state.workspace
        campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Find a better optimizer", "tasks": [QUADRATIC],
                                                               "compute_budget_seconds": 20000, "delegated_trial_seconds": 1500, "llm_budget_usd": 1}, 0)["outcome"]["campaign"]
        lead = activate_team(client, workspace, campaign, monkeypatch)
        env = SimpleNamespace(client=client, workspace=workspace, lead=lead, tools=PiTools(workspace.pi))
        env.run = say(env, "Screen the restart idea against coordinate search.")
        yield env


def version(env):
    return env.workspace.store.get("demo", "campaign")["version"]


def say(env, text, page_agent=None):
    payload = {"message": text, **({"page_agent": page_agent} if page_agent else {"thread_id": MAIN})}
    receipt = command(env.client, "agent.message", "demo", payload, version(env), **({} if page_agent else {"origin": {"thread_id": MAIN}}))
    return submitted(env.workspace, "pi_run_" + receipt["id"])


def propose(env, call_id, agent=None, run=None, **args):
    return env.tools.call((agent or env.lead)["id"], (run or env.run)["id"], call_id, "mandate_propose", args)


def resolve(env, decision, choice):
    command(env.client, "decision.resolve", "demo", {"decision_id": decision["id"], "choice": choice, "comment": "",
            "expected_resolution_revision": decision.get("resolution_revision", 0)}, version(env))
    return env.workspace.store.get(decision["id"], "decision")


def root(env, run=None):
    return request_root(env.workspace, {"run_id": (run or env.run)["id"]})


def hypothesis(env, identity):
    env.workspace.store.put("hypothesis", {"id": identity, "campaign_id": "demo", "title": identity, "status": "proposed"})


def state(env, agent=None, run=None):
    return env.tools.turn_state((agent or env.lead)["id"], (run or env.run)["id"])["text"]


def test_an_explore_mandate_under_the_threshold_is_granted_at_once_and_named_in_the_receipt(team):
    assert "mandate_propose" in team.tools.names(team.lead)
    assert "Mandate: none, Explore by default" in state(team)
    receipt = propose(team, "explore", template="explore", plan="Two short probes of coordinate search, to size the screen", worker_seconds=120,
                      stop_when={"text": "Both probes finished", "machine": "all_runs_terminal"})
    assert receipt["status"] == "active" and receipt["granted_by"] == "automatic"
    assert receipt["mandate"].startswith("Explore (active), left: 5 min of worker time")
    mandate = mandates.active(team.workspace, "demo", root(team))
    assert (mandate.id, mandate.template, mandate.plan, mandate.stop_when.machine) == (receipt["mandate_id"], "explore", "Two short probes of coordinate search, to size the screen", "all_runs_terminal")
    assert mandate.root.thread_id == MAIN and team.workspace.store.list("decision", "demo") == []
    # The receipt is the tool's: the reply names the mandate from it.
    [saved] = [row for row in team.workspace.store.list("agent_tool_receipt", "demo") if row["tool"] == "mandate_propose"]
    assert saved["result"]["mandate_id"] == mandate.id
    assert f"Mandate: explore ({mandate.id}); model spend without an envelope of its own (the campaign's cap applies); worker time 5 min left; no deadline." in state(team)
    # A request never narrows its own mandate (R3): Answer is within its Explore, so nothing new is granted. Explore over the
    # threshold, or with a coding workspace, is not Explore.
    kept = propose(team, "answer", template="answer", plan="Answer from the records")
    assert kept["mandate_id"] == mandate.id and kept["mandate"].startswith("Explore (active)") and "nothing new was granted" in kept["next"]
    for call_id, extra in (("long", {"worker_seconds": 900}), ("coding", {"coding_workspaces": 1})):
        refused = propose(team, call_id, template="explore", plan="More", **extra)
        assert refused["executed"] is False and "Propose screen" in refused["error"]
    assert [m.template for m in mandates.mandates(team.workspace, "demo")] == ["explore"]


def test_a_screen_mandate_becomes_one_card_and_approving_it_records_the_mandate_with_the_decision(team):
    hypothesis(team, "H1")
    receipt = propose(team, "screen", template="screen", plan="Build H1 and screen it against coordinate search, two seeds each",
                      hypothesis_ids=["H1"], worker_seconds=2400, coding_workspaces=1, wall_seconds=900, deadline_minutes=120, model_usd=2,
                      stop_when={"text": "Both screens finished"}, meanwhile="Read the proposal's review")
    assert receipt["status"] == "proposed" and receipt["page"] == "#inbox"
    [decision] = team.workspace.store.list("decision", "demo")
    assert decision["id"] == receipt["outcome"]["decision_id"] and decision["approval_request"]["kind"] == "mandate"
    assert [option["label"] for option in decision["options"]] == ["Approve", "Approve as Explore only", "Decline"]
    assert decision["title"] == "Approve a Screen mandate for this request? About 15 min until results"
    for words in ("Build H1 and screen it", "up to 40 min of worker time and opens 1 coding workspace and $2 of model spend",
                  "Deadline: 120 min after you approve", "It stops when: Both screens finished", "Meanwhile: Read the proposal's review",
                  "It covers only the work for H1"):
        assert words in decision["proposal"]
    assert mandates.same_root(decision["request_root"], root(team))
    assert mandates.active(team.workspace, "demo", root(team)) is None   # proposed, not granted
    resolved = resolve(team, decision, "0")
    mandate = mandates.active(team.workspace, "demo", root(team))
    assert (mandate.template, mandate.granted_by, mandate.hypothesis_ids, mandate.model_usd) == ("screen", decision["id"], ["H1"], 2)
    assert (mandate.compute.worker_seconds, mandate.compute.coding_workspaces, mandate.deadline_at is not None) == (2400, 1, True)
    [consent] = team.workspace.store.list("compute_consent", "demo")
    assert mandate.consent_id == consent["id"] and resolved["outcome"] == {"mandate_id": mandate.id, "template": "screen", "consent_id": consent["id"]}
    assert team.workspace.store.get("H1", "hypothesis")["approved_by"]["decision_id"] == decision["id"]
    assert f"Mandate: screen ({mandate.id}); model spend $2.00 left of $2.00; worker time 40 min left, 1 coding workspace; deadline " in state(team)


def test_a_screen_mandate_names_the_hosts_its_coding_workspaces_may_reach_and_its_consent_keeps_them(team):
    # The box's egress allowlist (roadmap H5): hosts beyond the model and the package index are approved with the go-ahead.
    hypothesis(team, "H1")
    propose(team, "hosts", template="screen", plan="Build H1 from the reference code on github.com", hypothesis_ids=["H1"],
            worker_seconds=2400, coding_workspaces=1, egress_hosts=["github.com"])
    [decision] = team.workspace.store.list("decision", "demo")
    assert decision["approval_request"]["egress_hosts"] == ["github.com"]
    assert "Its coding workspaces may also reach github.com, beyond their model and the package index." in decision["proposal"]
    resolve(team, decision, "0")
    [consent] = team.workspace.store.list("compute_consent", "demo")
    assert consent["egress_hosts"] == ["github.com"] and mandates.active(team.workspace, "demo", root(team)).consent_id == consent["id"]


def test_approve_as_explore_only_records_explore_and_decline_records_nothing(team):
    hypothesis(team, "H1")
    propose(team, "screen", template="screen", plan="Screen H1", hypothesis_ids=["H1"], worker_seconds=2400)
    [decision] = team.workspace.store.list("decision", "demo")
    resolved = resolve(team, decision, "1")
    mandate = mandates.active(team.workspace, "demo", root(team))
    assert (mandate.template, mandate.granted_by, mandate.consent_id, mandate.compute.worker_seconds) == ("explore", decision["id"], None, 300)
    assert resolved["outcome"] == {"mandate_id": mandate.id, "template": "explore"} and team.workspace.store.list("compute_consent", "demo") == []
    assert not team.workspace.store.get("H1", "hypothesis").get("approved_by")
    other = say(team, "Then run the whole campaign by tonight.")
    propose(team, "campaign", run=other, template="run_campaign", plan="Every stage for H1", worker_seconds=7200, deadline_minutes=600)
    declined = resolve(team, team.workspace.store.list("decision", "demo")[-1], "2")
    assert declined["status"] == "resolved" and declined["outcome"] is None
    assert mandates.active(team.workspace, "demo", root(team, other)) is None and len(mandates.mandates(team.workspace, "demo")) == 1


def test_a_request_with_no_mandate_gets_explore_at_its_first_work_starting_command(team):
    hypotheses = lambda: mandates.mandates(team.workspace, "demo")
    asked = team.tools.call(team.lead["id"], team.run["id"], "worker", "campaign_command", {"operation": "approval.request", "request_key": "w",
        "payload": {"kind": "worker_ceiling", "workers": 3, "rationale": "Room for two seeds"}})
    assert asked["status"] == "completed" and hypotheses() == []          # asking starts no work
    created = team.tools.call(team.lead["id"], team.run["id"], "create", "campaign_command", {"operation": "hypothesis.create", "request_key": "h1",
        "payload": {"title": "Restarts", "mechanism": "restart from the best", "rationale": "cheap"}})
    assert created["status"] == "completed"
    [mandate] = hypotheses()
    assert (mandate.template, mandate.granted_by, mandate.status) == ("explore", "automatic", "active")
    assert mandates.same_root(mandate.root.model_dump(), root(team))
    team.tools.call(team.lead["id"], team.run["id"], "again", "campaign_command", {"operation": "hypothesis.create", "request_key": "h2",
        "payload": {"title": "Annealing", "mechanism": "anneal the step", "rationale": "cheap"}})
    assert len(hypotheses()) == 1                                         # one default per request


def test_a_page_agent_asked_on_its_page_proposes_its_own_mandate_and_its_runs_are_charged_to_it(team):
    operator = team.workspace.pi.page_agent("demo", "experiment_operator")
    run = say(team, "Run two short probes of coordinate search.", page_agent="experiment_operator")
    operator = team.workspace.store.get(operator["id"], "agent_session")
    assert "Mandate: none, Explore by default" in state(team, operator, run)
    receipt = propose(team, "probe", agent=operator, run=run, template="explore", plan="Two short probes", worker_seconds=240)
    mandate = mandates.active(team.workspace, "demo", root(team, run))
    assert mandate.id == receipt["mandate_id"] and mandate.root.thread_id == "desk_experiment_operator" and mandate.root.run_id == run["id"]
    task = team.workspace.current_tasks("demo")[0]
    started = team.tools.call(operator["id"], run["id"], "trial", "campaign_command", {"operation": "trial.create", "request_key": "t1",
        "payload": {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 120}})
    assert started.get("status") == "completed", started
    used = mandates.active(team.workspace, "demo", root(team, run))
    assert used.used.worker_seconds == 120 and "worker time 3 min left" in state(team, operator, run)
    # Asked by the lead, it works under the lead's mandate: what it proposes is for the lead's request.
    team.tools.call(team.lead["id"], team.run["id"], "ask", "page_agent_message", {"page_agent": "experiment_operator", "message": "Probe once more."})
    operator = team.workspace.store.get(operator["id"], "agent_session")
    asked = submitted(team.workspace, sorted(team.workspace.store.list_agent_runs(operator["id"]), key=lambda r: r["created_at"])[-1]["id"])
    for_lead = propose(team, "lead", agent=operator, run=asked, template="explore", plan="Probe once more")
    assert mandates.active(team.workspace, "demo", root(team)).id == for_lead["mandate_id"]
    assert mandates.same_root(mandates.active(team.workspace, "demo", root(team)).root.model_dump(), root(team))


def test_an_agent_asks_for_compute_with_a_mandate_not_with_kind_compute(team):
    refused = team.tools.call(team.lead["id"], team.run["id"], "old", "campaign_command", {"operation": "approval.request", "request_key": "c",
        "payload": {"kind": "compute", "plan": "Screen", "rationale": "Screen", "wall_seconds": 600, "worker_seconds": 600, "meanwhile": "Read"}})
    assert refused["executed"] is False and "mandate_propose" in refused["error"]
    assert team.workspace.store.list("decision", "demo") == []
