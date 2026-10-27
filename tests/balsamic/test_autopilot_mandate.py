"""Autopilot is a standing mandate (roadmap R4): the researcher's switch grants Run the campaign for autopilot's request, with the
cap as its worker seconds and the report date as its deadline; every round carries that request, so the bus's mandate guard checks
its commands, by the rule the cap guard had; switching it off closes the mandate."""
from datetime import datetime, timedelta, timezone

import pytest

from optimization_framework.agents.models import NOTICE
from optimization_framework.campaigns import mandates
from optimization_framework.campaigns.compute_consent import request_root

from support import activate_team, command, state_of, submitted, tool_call
from balsamic.autopilot import rounds


@pytest.fixture
def team(client, workspace, campaign, monkeypatch):
    return activate_team(client, workspace, campaign, monkeypatch)


def version(workspace):
    return workspace.store.get("demo", "campaign")["version"]


def switch(client, workspace, enabled=True, **values):
    return command(client, "autopilot.set", "demo", {"enabled": enabled, "rationale": "overnight", **values}, version(workspace))["outcome"]["autopilot"]


def round_run(workspace):
    rounds.tick(workspace)
    return submitted(workspace, [run for run in workspace.store.list("agent_run", "demo") if run.get("autopilot")][-1]["id"])


def runnable(workspace, identity):
    workspace.store.put("hypothesis", {"id": identity, "campaign_id": "demo", "title": identity, "mechanism": "m", "rationale": "r",
        "parent_ids": [], "algorithm": "coordinate", "algorithm_config": {}, "algorithm_chosen": True, "status": "proposed", "executable": True})


def act(workspace, team, run, key, operation, payload):
    return tool_call(workspace, team, run, "campaign_command", {"operation": operation, "request_key": key, "rationale": "the frontier", "payload": payload},
                     call_id=key)


def allocate(identity, seconds):
    return {"hypothesis_id": identity, "worker_seconds": seconds, "rationale": "promising"}


def test_the_switch_grants_a_standing_mandate_every_round_carries_and_switching_off_closes_it(client, workspace, campaign, team):
    report_by = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    settings = switch(client, workspace, compute_cap_seconds=600, report_by=report_by)
    mandate = mandates.governing(workspace, "demo", settings["mandate_root"])
    assert mandate.id == settings["mandate_id"] and (mandate.template, mandate.status) == ("run_campaign", "active")
    assert mandate.root.thread_id == "thread_autopilot_demo" and mandate.compute.worker_seconds == 600 and mandate.deadline_at == report_by
    # The researcher's switch is the go-ahead the mandate names: a decision of theirs, already resolved; nothing waits in the inbox.
    switched = workspace.store.get(mandate.granted_by, "decision")
    assert (switched["status"], switched["requested_by"], switched["title"]) == ("resolved", "researcher", "Autopilot on: a compute cap of 10 min, "
        f"the report by {report_by[:16].replace('T', ' ')} UTC")
    assert [found for found in workspace.store.list("decision", "demo") if found["status"] == "pending"] == []
    # Every round carries autopilot's request: the mandate governs it, the state block states the cap's remainder and the date, and
    # the round's prompt no longer restates them.
    run = round_run(workspace)
    assert mandates.governing(workspace, "demo", request_root(workspace, {"run_id": run["id"]})).id == mandate.id
    state = state_of(workspace, team, run)
    assert f"Mandate: run campaign ({mandate.id})" in state and f"worker time 10 min left; deadline {report_by[:16].replace('T', ' ')} UTC." in state
    assert "Autopilot: on, cap 600 worker seconds, 600 left" in state
    assert "worker seconds" not in run["input"] and "cap" not in run["input"] and "Every command states its rationale" in run["input"]
    # A change while on: the same request, under a mandate on the new terms; the round at work goes on under it.
    changed = switch(client, workspace, compute_cap_seconds=900, report_by=report_by)
    assert changed["mandate_root"] == settings["mandate_root"] and changed["mandate_id"] != mandate.id
    assert {found.id: found.status for found in mandates.mandates(workspace, "demo")} == {mandate.id: "closed", changed["mandate_id"]: "active"}
    assert mandates.governing(workspace, "demo", request_root(workspace, {"run_id": run["id"]})).id == changed["mandate_id"]
    # Off: the mandate closes, and a round's command after that is refused; the mandate guard refuses the work of a notice that
    # continues the round, which runs as the lead, not as autopilot.
    switch(client, workspace, enabled=False)
    assert mandates.governing(workspace, "demo", request_root(workspace, {"run_id": run["id"]})).status == "closed"
    refused = act(workspace, team, run, "after_off", "hypothesis.allocate", allocate("H1", 10))
    assert refused["executed"] is False and "Autopilot is off" in refused["error"]
    lead = workspace.store.get(team["id"], "agent_session")
    notice = submitted(workspace, workspace.pi.enqueue(lead, "notice_after_off", NOTICE + "Runs ended.", root=request_root(workspace, {"run_id": run["id"]}))["id"])
    refused = tool_call(workspace, team, notice, "campaign_command", {"operation": "hypothesis.allocate", "request_key": "notice", "payload": allocate("H1", 10)},
                        call_id="notice")
    assert refused["executed"] is False
    assert f"hypothesis.allocate is new work, and this request's Run the campaign mandate ({changed['mandate_id']}) has ended: it was closed" in refused["error"]
    # Switched on again: a new request, under a new mandate.
    again = switch(client, workspace, compute_cap_seconds=300)
    assert again["mandate_root"] != settings["mandate_root"] and mandates.governing(workspace, "demo", again["mandate_root"]).deadline_at is None


def test_the_cap_counts_every_allocation_since_the_switch_and_refuses_what_it_refused_before(client, workspace, campaign, team):
    task = workspace.current_tasks("demo")[0]
    for identity in ("H1", "H2"):
        runnable(workspace, identity)
    settings = switch(client, workspace, compute_cap_seconds=100)
    # The researcher's own run counts against the cap, as the cap always counted: every allocation since the switch.
    trial = command(client, "trial.create", "demo", {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 50},
                    version(workspace))["outcome"]["trial"]
    workspace.store.put("trial", {**workspace.store.get(trial["id"], "trial"), "status": "completed", "execution_seconds": 50, "result": {"elapsed_seconds": 50}})
    assert mandates.governing(workspace, "demo", settings["mandate_root"]).used.worker_seconds == 50 == rounds.spent_since_baseline(workspace, "demo", settings)
    run = round_run(workspace)
    # A batch is checked by its items' seconds together, as the cap guard checked them: each fits, both do not.
    batch = act(workspace, team, run, "batch", "intervention.batch", {"rationale": "both", "items": [
        {"operation": "hypothesis.allocate", "payload": allocate("H1", 30)}, {"operation": "hypothesis.allocate", "payload": allocate("H2", 30)}]})
    assert batch["executed"] is False
    assert "intervention.batch would reserve 60 s of worker time, and this request's Run the campaign mandate" in batch["error"]
    assert "has 50 s left of its compute cap of 100 s. Start nothing beyond the cap; only the researcher raises it." in batch["error"]
    over = act(workspace, team, run, "over", "hypothesis.allocate", allocate("H1", 51))
    assert over["executed"] is False and "would reserve 51 s of worker time" in over["error"]
    within = act(workspace, team, run, "within", "hypothesis.allocate", allocate("H1", 50))
    assert within["status"] == "completed", within
    # The cap is spent: the mandate has ended (decision 11), so new work is refused, a stop too; the state block says so, and the
    # next round is the last, for the report.
    mandate = mandates.governing(workspace, "demo", settings["mandate_root"])
    assert mandate.status == "exhausted" and mandate.used.worker_seconds == 100
    stop = act(workspace, team, run, "stop", "hypothesis.status", {"hypothesis_id": "H2", "status": "archived", "expected_status_revision": 0, "stop_reason": "Dominated"})
    assert stop["executed"] is False and "has ended: its envelope is spent" in stop["error"]
    assert "; exhausted, new work is refused;" in state_of(workspace, team, run)
    assert rounds.round_state(workspace, "demo")["remaining_seconds"] == 0


def test_autopilot_works_only_under_its_own_mandate_and_no_card_is_filed_for_its_request(client, workspace, campaign, team):
    runnable(workspace, "H1")
    settings = switch(client, workspace, compute_cap_seconds=600)
    run = round_run(workspace)
    card = tool_call(workspace, team, run, "mandate_propose", {"template": "screen", "plan": "Screen H1 for an hour", "hypothesis_ids": ["H1"],
                                                                 "worker_seconds": 3600, "wall_seconds": 1800, "meanwhile": "Read the frontier"}, call_id="card")
    assert card["executed"] is False
    assert f"Autopilot's request works under the standing mandate its switch granted ({settings['mandate_id']})" in card["error"]
    assert [d for d in workspace.store.list("decision", "demo") if d["status"] == "pending"] == []
    # Asking for Explore while the mandate lasts grants nothing: the request's mandate already allows it.
    explore = tool_call(workspace, team, run, "mandate_propose", {"template": "explore", "plan": "Two probes"}, call_id="explore")
    assert explore["mandate_id"] == settings["mandate_id"] and "nothing new was granted" in explore["next"]
    # Any other mandate for the request (here one recorded by hand) does not let autopilot past its own.
    other = mandates.grant(workspace, "demo", "explore", root=request_root(workspace, {"run_id": run["id"]}))
    refused = act(workspace, team, run, "other", "hypothesis.allocate", allocate("H1", 10))
    assert refused["executed"] is False
    assert f"Autopilot works only under the standing mandate its switch granted ({settings['mandate_id']}); this turn is under another ({other.id})" in refused["error"]


@pytest.mark.parametrize("operation, payload", [
    ("trial.create", {"wall_seconds": 90}), ("trial.create", {}), ("trial.create", {"wall_seconds": 0, "worker_seconds": 40}),
    ("trial.continue", {"wall_seconds": 70}), ("trial.continue", {"trial_id": "trial_x", "worker_seconds": 50}),
    ("hypothesis.allocate", {"worker_seconds": 30}), ("hypothesis.allocate", {"wall_seconds": 400, "worker_seconds": 30}),
    ("intervention.batch", {"items": [{"operation": "hypothesis.allocate", "payload": {"worker_seconds": 30}},
                                      {"operation": "hypothesis.create", "payload": {"wall_seconds": 25}},
                                      {"operation": "hypothesis.status", "payload": {"hypothesis_id": "H1"}}]}),
    ("hypothesis.status", {"hypothesis_id": "H1"}), ("research.generate", {}),
])
def test_the_charge_estimate_never_reserves_less_than_the_cap_guard_did(workspace, operation, payload):
    """The rule of the cap guard R4 removed, as it was: the mandate's charge estimate is never below it, so nothing it refused is allowed."""
    def reservation(operation, payload):
        if operation in {"trial.create", "trial.continue", "hypothesis.allocate"}:
            return float(payload.get("wall_seconds") or payload.get("worker_seconds") or 0)
        if operation == "intervention.batch":
            return sum(float((item.get("payload") or {}).get("worker_seconds") or (item.get("payload") or {}).get("wall_seconds") or 0)
                       for item in payload.get("items") or [])
        return 0.0
    charged = mandates.estimate(workspace, operation, payload)
    assert reservation(operation, payload) == mandates.stated(operation, payload)
    assert (charged or 0.0) >= reservation(operation, payload)


def test_an_autopilot_switched_on_before_it_was_a_mandate_gets_one_at_its_next_round(client, workspace, campaign, team):
    """Settings saved before R4 name no mandate: the next round grants it, on the terms the researcher set then, under their switch."""
    stored = workspace.store.get("demo", "campaign")
    workspace.store.put("campaign", {**stored, "autonomy": "delegated", "autopilot": {"enabled": True, "compute_cap_seconds": 600, "report_by": None,
        "requested": None, "baseline_allocated_seconds": 0.0, "enabled_at": "2026-10-26T00:00:00+00:00", "command_id": "ui_before_r4",
        "rounds_completed": 0, "rationale": "overnight", "report_requested": False, "last_round_run_id": None}})
    assert mandates.mandates(workspace, "demo") == []
    run = round_run(workspace)
    settings = workspace.store.get("demo", "campaign")["autopilot"]
    mandate = mandates.governing(workspace, "demo", request_root(workspace, {"run_id": run["id"]}))
    assert mandate.id == settings["mandate_id"] and mandate.template == "run_campaign" and mandate.compute.worker_seconds == 600
    assert workspace.store.get(mandate.granted_by, "decision")["command_id"] == "ui_before_r4"
    assert act(workspace, team, run, "big", "hypothesis.allocate", allocate("H1", 601))["error"].endswith("only the researcher raises it.")
