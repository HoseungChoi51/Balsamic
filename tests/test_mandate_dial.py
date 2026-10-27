"""The mandate dial in the chat (roadmap R7): the researcher grants a request's mandate with the message that opens it, sees the
mandate above the chat and closes it; the campaign's default template, where the dial starts, is a setting that the old autonomy
maps onto, and the confirmation scheduler reads it with the same effect."""
import pytest

from optimization_framework.campaigns import mandates
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, StudyInput, TaskInput, TrialInput
from optimization_framework.execution.service import Workspace
from test_mandate_guard import operator_for, trial
from test_mandate_propose import MAIN, propose, root, say, state, team, version  # noqa: F401  (team is a fixture)
from support import command, submitted  # noqa: E402

SCREEN = {"template": "screen", "worker_seconds": 1800, "coding_workspaces": 1, "model_usd": 2, "deadline_minutes": 60}


def send(env, text, mandate, **extra):
    """The researcher's message in the main thread with the dial set: the run of the request it opens."""
    receipt = command(env.client, "agent.message", "demo", {"message": text, "thread_id": MAIN, "mandate": mandate, **extra}, version(env),
                      origin={"thread_id": MAIN})
    return submitted(env.workspace, "pi_run_" + receipt["id"])


def bar(env, thread_id=MAIN):
    response = env.client.get(f"/api/v1/threads/{thread_id}/mandate")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_message_sent_with_screen_grants_its_request_a_mandate_and_after_the_researcher_closes_it_the_next_command_is_refused(team):
    run = send(team, "Screen coordinate search with longer runs.", SCREEN)
    asked = root(team, run)
    assert asked == {"thread_id": MAIN, "message_id": "message_" + run["id"].removeprefix("pi_run_"), "run_id": run["id"]}
    mandate = mandates.governing(team.workspace, "demo", asked)
    # Granted with the message, for that request: the researcher's resolved decision, and a consent as its compute part.
    decision = team.workspace.store.get(mandate.granted_by, "decision")
    [consent] = team.workspace.store.list("compute_consent", "demo")
    assert (mandate.template, mandate.status, mandate.consent_id, mandate.model_usd) == ("screen", "active", consent["id"], 2)
    assert (mandate.compute.worker_seconds, mandate.compute.coding_workspaces, mandate.deadline_at is not None) == (1800, 1, True)
    assert mandate.plan == "Screen coordinate search with longer runs."
    assert (decision["status"], decision["choice"], decision["requested_by"], decision["approval_request"]["kind"]) == ("resolved", "0", "researcher", "mandate")
    assert mandates.same_root(decision["request_root"], asked) and consent["decision_id"] == decision["id"] and consent["request_root"] == decision["request_root"]
    assert decision["outcome"] == {"mandate_id": mandate.id, "template": "screen", "consent_id": consent["id"]}
    # The lead has not proposed one: its state block names the mandate, and work past the go-ahead threshold starts under it.
    assert [row for row in team.workspace.store.list("agent_tool_receipt", "demo") if row["tool"] == "mandate_propose"] == []
    assert f"Mandate: screen ({mandate.id}); model spend $2.00 left of $2.00; worker time 30 min left, 1 coding workspace; deadline " in state(team, run=run)
    operator, asked_run = operator_for(team, run=run)
    started = trial(team, operator, asked_run, "long", wall=1200)
    assert started["status"] == "completed", started
    assert team.workspace.store.get(consent["id"], "compute_consent")["used_seconds"] == 1200
    # Above the chat: the request's mandate, what is left of it, its deadline, granted with the researcher's message.
    shown = bar(team)
    assert shown["request"] == asked and shown["others"] == []
    assert {key: shown["current"][key] for key in ("id", "template", "label", "status", "granted", "closable", "deadline_at")} == \
        {"id": mandate.id, "template": "screen", "label": "Screen", "status": "active", "granted": "message", "closable": True, "deadline_at": mandate.deadline_at}
    assert shown["current"]["left"] == {"worker_seconds": 600, "coding_workspaces": 1, "model_usd": 2}
    # The researcher closes it: the next agent command in that request is refused, and the agent cannot grant itself Explore again.
    closed = command(team.client, "mandate.close", "demo", {"mandate_id": mandate.id}, version(team), origin={"thread_id": MAIN})
    assert closed["outcome"] == {"mandate_id": mandate.id, "template": "screen", "status": "closed"}
    assert team.workspace.store.get(consent["id"], "compute_consent")["closed_by"] == "researcher"
    refused = trial(team, operator, asked_run, "after")
    assert refused["executed"] is False and f"this request's Screen mandate ({mandate.id}) has ended: it was closed" in refused["error"]
    again = propose(team, "again", run=run, template="explore", plan="A few more probes")
    assert again["executed"] is False and "The researcher closed this request's Screen mandate" in again["error"]
    assert len(team.workspace.store.list("trial", "demo")) == 1
    shown = bar(team)["current"]
    assert (shown["status"], shown["closable"], shown["closed_by"]) == ("closed", False, "researcher")


def test_answer_and_explore_are_granted_with_the_message_and_an_agent_does_not_widen_the_researchers_answer(team):
    answer = send(team, "Which methods are installed?", {"template": "answer"})
    granted = mandates.governing(team.workspace, "demo", root(team, answer))
    assert (granted.template, granted.granted_by, granted.status) == ("answer", "automatic", "active")
    assert team.workspace.store.get(granted.id, "mandate")["message_id"] == "message_" + answer["id"].removeprefix("pi_run_")
    assert team.workspace.store.list("decision", "demo") == []
    refused = trial(team, *operator_for(team, run=answer), "probe")
    assert refused["executed"] is False and f"this request's Answer mandate ({granted.id}) does not allow" in refused["error"]
    widened = propose(team, "explore", run=answer, template="explore", plan="Two probes")
    assert widened["executed"] is False and "The researcher chose Answer for this request with their message" in widened["error"]
    card = propose(team, "screen", run=answer, template="screen", plan="Screen it", worker_seconds=1200)
    assert card["status"] == "proposed"             # more goes to the researcher as one card
    assert bar(team)["current"]["granted"] == "message"
    # Explore with the message is granted at once, as by default; the dial's choice shows above the chat.
    explore = send(team, "Run two short probes.", {"template": "explore"})
    assert mandates.governing(team.workspace, "demo", root(team, explore)).template == "explore"
    assert trial(team, *operator_for(team, run=explore), "probe2")["status"] == "completed"
    shown = bar(team)
    assert shown["current"]["template"] == "explore" and [other["template"] for other in shown["others"]] == ["answer"]
    # Answer and Explore take their template's envelope; Screen states one; a mandate opens a request in a thread.
    for mandate, why in (({"template": "explore", "worker_seconds": 600}, "take their template's envelope"),
                         ({"template": "screen"}, "states the worker time of its envelope"),
                         ({"template": "screen", "worker_seconds": 600, "hypothesis_ids": ["H404"]}, "H404 is not a proposal of this campaign")):
        response = team.client.post("/api/v1/commands", json={"id": "ui_bad_" + why[:5].replace(" ", "_"), "campaign_id": "demo", "operation": "agent.message",
            "expected_revision": version(team), "payload": {"message": "Go", "thread_id": MAIN, "mandate": mandate}})
        assert response.status_code == 409 and why in response.json()["detail"], response.text
    unthreaded = command(team.client, "agent.message", "demo", {"message": "Go", "mandate": {"template": "answer"}}, version(team), expect=409)
    assert "with a message in a thread" in unthreaded["detail"]


def test_only_the_researcher_grants_a_mandate_with_a_message_or_closes_one(team):
    run = send(team, "Screen it.", SCREEN)
    mandate = mandates.governing(team.workspace, "demo", root(team, run))
    campaign = team.workspace.store.get("demo", "campaign")
    pins = {"expected_guidance_revision": team.workspace.memory.state("demo")["guidance_revision"],
            "expected_authority_hash": team.workspace.commands.authority_hash(campaign)}
    for operation, payload in (("mandate.close", {"mandate_id": mandate.id}),
                               ("agent.message", {"message": "Go", "thread_id": MAIN, "mandate": {"template": "run_campaign", "worker_seconds": 9000}})):
        with pytest.raises(ValueError, match="needs researcher authorization"):
            team.workspace.commands.execute(Command(id="agent_" + operation.replace(".", "_"), campaign_id="demo", expected_revision=campaign["version"],
                                                    operation=operation, payload=payload, **pins), actor="manager")
    assert mandates.governing(team.workspace, "demo", root(team, run)).status == "active"
    assert "mandate.close" not in team.workspace.commands.delegated and mandates.CLASSES["mandate.close"] == "configure"


def test_the_default_template_is_a_setting_that_autonomy_maps_onto(team):
    assert {autonomy: mandates.default_template({"autonomy": autonomy}) for autonomy in ("manual", "guided", "delegated")} == \
        {"manual": "answer", "guided": "explore", "delegated": "screen"}
    assert mandates.default_template({"autonomy": "delegated", "default_template": "explore"}) == "explore"
    # The team's start delegates the campaign, so until the researcher chooses, the dial starts at Screen.
    row = lambda: next(found for found in team.client.get("/api/v1/campaigns").json()["campaigns"] if found["id"] == "demo")
    assert (row()["autonomy"], row()["default_template"]) == ("delegated", "screen")
    command(team.client, "campaign.update", "demo", {"default_template": "explore", "rationale": "Set on the Resources page"}, version(team))
    campaign = team.workspace.store.get("demo", "campaign")
    assert (campaign["default_template"], campaign["autonomy"], row()["default_template"]) == ("explore", "delegated", "explore")
    assert bar(team)["default_template"] == "explore"
    # Only the researcher sets it: campaign.update is not an agent's.
    refused = team.tools.call(team.lead["id"], team.run["id"], "setting", "campaign_command", {"operation": "campaign.update", "request_key": "u",
        "payload": {"default_template": "run_campaign"}})
    assert refused["executed"] is False and team.workspace.store.get("demo", "campaign")["default_template"] == "explore"


def confirmation(tmp_path, autonomy, template, validation=None):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Dial", autonomy=autonomy, compute_budget_seconds=500, validation_reserve_seconds=0,
                                                       tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    if template:
        workspace.store.put("campaign", {**workspace.store.get(campaign["id"], "campaign"), "default_template": template})
    task = workspace.current_tasks(campaign["id"])[0]
    prototype = workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm="coordinate", max_steps=3, wall_seconds=5))
    study = workspace.create_study(campaign["id"], StudyInput(goal="Fixed seed replication", scope="confirmation", confirmation_kind="seed_replication",
                                                              prototype_trial_ids=[prototype["id"]], seeds=[17], validation_policy=validation or {}))
    return workspace, study["confirmation"]["id"]


@pytest.mark.parametrize("autonomy, template, allowed", [
    ("manual", None, False), ("guided", None, False), ("delegated", None, True),            # as autonomy decided before
    ("delegated", "explore", False), ("guided", "screen", True), ("manual", "run_campaign", True),   # the researcher's template decides
])
def test_the_confirmation_scheduler_reads_the_default_template_with_the_effect_autonomy_had(tmp_path, autonomy, template, allowed):
    workspace, protocol = confirmation(tmp_path, autonomy, template)
    assert workspace.store.get(protocol, "confirmation_protocol").get("contract_version") != 2   # the path that reads the template
    if allowed:
        assert len(workspace.confirmations.schedule(workspace, protocol, authority="manager")["created_trial_ids"]) == 1
    else:
        with pytest.raises(ValueError, match="The frozen roster exceeds the manager's delegated per-experiment allowance"):
            workspace.confirmations.schedule(workspace, protocol, authority="manager")
    lab, checked = confirmation(tmp_path / "checks", autonomy, template, {"required_recipes": ["analytic_fixtures:v1"], "validation_wall_seconds": 5})
    if allowed:
        assert lab.confirmations.schedule_checks(lab, checked, authority="manager")["created_trial_ids"] == []   # no finished cell to check yet
    else:
        with pytest.raises(ValueError, match="Required validation exceeds the manager's delegated per-experiment allowance"):
            lab.confirmations.schedule_checks(lab, checked, authority="manager")
    # The researcher's own scheduling is never checked against it.
    assert workspace.confirmations.schedule(workspace, protocol)["protocol_id"] == protocol
