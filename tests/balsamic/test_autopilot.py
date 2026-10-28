"""Autopilot: rounds only while enabled and within the cap; its commands carry a rationale and a badge; the away digest; the monitor pill; merge drafts; the GPU row."""
from datetime import datetime, timedelta, timezone

import pytest

from optimization_framework.storage.sqlite import now

from support import activate_team, command, finish_run, submitted, tool_call
from balsamic.autopilot import rounds
from balsamic.monitor import digest as digests
from balsamic.monitor.rows import gpu_row, monitor_view

MAIN = "thread_main_demo"


@pytest.fixture
def team(client, workspace, campaign, monkeypatch):
    return activate_team(client, workspace, campaign, monkeypatch)


def enable(client, campaign, cap=300, **extra):
    return command(client, "autopilot.set", campaign["id"], {"enabled": True, "compute_cap_seconds": cap, "rationale": "overnight", **extra}, campaign["version"])["outcome"]["autopilot"]


def test_autopilot_rounds_run_only_while_enabled_and_within_the_cap(client, workspace, campaign, team):
    assert rounds.round_state(workspace, "demo")["enabled"] is False
    rounds.tick(workspace)
    assert not [r for r in workspace.store.list("agent_run", "demo") if r.get("autopilot")]
    command(client, "autopilot.set", campaign["id"], {"enabled": True, "rationale": "no cap"}, campaign["version"], expect=409)
    settings = enable(client, campaign, cap=300)
    assert settings["enabled"] and settings["baseline_allocated_seconds"] == 0 and workspace.store.get("demo", "campaign")["autonomy"] == "delegated"
    state = rounds.round_state(workspace, "demo")
    assert state["can_start"] and state["remaining_seconds"] == 300 and state["final"] is False
    rounds.tick(workspace)
    run = next(r for r in workspace.store.list("agent_run", "demo") if r.get("autopilot"))
    # The round is a turn of autopilot's request: the root of the standing mandate its switch granted (R4).
    assert run["origin"] == {"thread_id": "thread_autopilot_demo", "message_id": "message_" + run["id"], "actor": "autopilot",
                             "root": {**settings["mandate_root"], "run_id": run["id"]}} and "Autopilot round 1" in run["input"]
    assert workspace.store.get("thread_autopilot_demo", "thread")["system"] is True
    assert workspace.pi.configuration("demo")["request_open"] is True
    # No second round while the first is in its turn; a researcher message takes precedence afterwards.
    rounds.tick(workspace)
    assert len([r for r in workspace.store.list("agent_run", "demo") if r.get("autopilot")]) == 1
    assert rounds.round_state(workspace, "demo")["reason"] in {"a request is open: researcher messages come first", "the lead is in a turn"}
    # Its commands are checked against the cap, by the mandate guard: a run past the remaining compute is refused with the reason.
    run = submitted(workspace, run["id"])
    refused = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.allocate", "request_key": "big", "rationale": "more",
                        "payload": {"hypothesis_id": "nope", "worker_seconds": 301, "rationale": "x"}})
    assert refused["executed"] is False and "compute cap" in refused["error"]
    finish_run(workspace, run["id"], "Round done.", entry_ids={"parent": None, "last": "e1"}, disposition="complete")
    rounds.tick(workspace)
    assert workspace.store.get("demo", "campaign")["autopilot"]["rounds_completed"] == 1
    # Off again: no further round, delegation restored.
    command(client, "autopilot.set", campaign["id"], {"enabled": False, "rationale": "enough"}, campaign["version"])
    before = len(workspace.store.list("agent_run", "demo"))
    rounds.tick(workspace)
    assert len(workspace.store.list("agent_run", "demo")) == before and workspace.store.get("demo", "campaign")["autonomy"] == "delegated"


def test_autopilot_commands_carry_a_rationale_and_an_agent_badge(client, workspace, campaign, team):
    enable(client, campaign, cap=1000)
    rounds.tick(workspace)
    run = submitted(workspace, next(r["id"] for r in workspace.store.list("agent_run", "demo") if r.get("autopilot")))
    missing = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "r", "payload": {"title": "Auto", "mechanism": "m", "rationale": "r"}})
    assert missing["executed"] is False and "rationale" in missing["error"]
    receipt = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "r2", "rationale": "the frontier is thin", "payload": {"title": "Auto", "mechanism": "m", "rationale": "r"}}, call_id="r2")
    assert receipt["actor"] == "autopilot" and receipt["origin"]["actor"] == "autopilot" and receipt["origin"]["rationale"] == "the frontier is thin"
    row = next(r for r in client.get("/api/v1/campaigns/demo/evolution").json()["nodes"] if r["id"] == receipt["outcome"]["hypothesis_id"])
    assert row["autonomous"] is True and row["actor"] == "autopilot"
    # The final round: the report date within a day.
    tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    finish_run(workspace, run["id"], "Done.", entry_ids={"parent": None, "last": "e2"}, disposition="complete")
    command(client, "autopilot.set", campaign["id"], {"enabled": True, "compute_cap_seconds": 1000, "report_by": tomorrow, "rationale": "deadline"}, campaign["version"])
    state = rounds.round_state(workspace, "demo")
    assert state["can_start"] and state["final"] is True
    rounds.tick(workspace)
    final = [r for r in workspace.store.list("agent_run", "demo") if r.get("autopilot")][-1]
    assert "report_write" in final["input"] and workspace.store.get("demo", "campaign")["autopilot"]["report_requested"] is True
    assert rounds.round_state(workspace, "demo")["can_start"] is False


def test_away_digest_counts_rounds_stops_promotions_and_waiting_decisions(client, workspace, campaign, team, monkeypatch):
    a = command(client, "hypothesis.create", campaign["id"], {"title": "A", "mechanism": "m", "rationale": "r"}, campaign["version"])["outcome"]["hypothesis"]
    with workspace.store.connection() as db:
        since = db.execute("SELECT MAX(id) FROM events WHERE campaign_id='demo'").fetchone()[0]
    # The researcher goes away; autopilot runs a round that stops A and asks for an extension.
    enable(client, campaign, cap=1000)
    rounds.tick(workspace)
    run = submitted(workspace, next(r["id"] for r in workspace.store.list("agent_run", "demo") if r.get("autopilot")))
    workspace.store.put("trial", {"id": "trial_a", "campaign_id": "demo", "hypothesis_id": a["id"], "status": "completed", "created_at": now()})
    tool_call(workspace, team, run, "campaign_command", {"operation": "intervention.batch", "request_key": "b", "rationale": "dominated", "payload": {"rationale": "dominated", "items": [
        {"operation": "hypothesis.status", "payload": {"hypothesis_id": a["id"], "status": "archived", "expected_status_revision": 0, "stop_reason": "dominated",
                                                       "outcome": "under_evaluated", "evidence_ids": ["trial_a"]}}]}})
    workspace.store.put("decision", {"id": "approval_x", "campaign_id": "demo", "title": "Change limits?", "status": "pending", "options": [{"id": "0", "label": "Yes"}, {"id": "1", "label": "No"}],
                                     "created_at": now(), "charter_version": campaign["version"]}, "decision.created")
    finish_run(workspace, run["id"], "Stopped A.", entry_ids={"parent": None, "last": "e3"}, disposition="complete")
    later = datetime.now(timezone.utc) + timedelta(minutes=45)
    monkeypatch.setattr(digests, "away_for", lambda ws, cid, clock=None: timedelta(minutes=45))
    rounds.tick(workspace)
    assert workspace.store.get("demo", "campaign")["autopilot"]["rounds_completed"] == 1
    body = client.get("/api/v1/campaigns/demo/away-digest").json()
    digest = body["digest"]
    assert digest and digest["rounds_completed"] == 1 and digest["away_minutes"] == 45
    # One run is not an adequate assessment (V2), so the honest stop is under-evaluated.
    assert digest["stopped"] == [{"hypothesis_id": a["id"], "reason": "dominated", "outcome": "under_evaluated",
                                  "outcome_words": "under-evaluated", "by": "autopilot"}] and digest["promoted"] == []
    assert [d["id"] for d in digest["decisions_waiting"]] == ["approval_x"]
    assert any(c["operation"] == "intervention.batch" and c["by"] == "autopilot" for c in digest["commands"])
    monitor = client.get("/api/v1/campaigns/demo/monitor").json()
    assert monitor["pill"] == {"state": "digest", "text": "Away digest", "row": "digest"} and monitor["digest_id"] == digest["id"]
    assert client.post(f"/api/v1/campaigns/demo/away-digest/{digest['id']}/seen").json()["seen_at"]
    assert client.get("/api/v1/campaigns/demo/monitor").json()["pill"]["state"] == "attention", "the pending decision still needs attention"
    assert client.get("/api/v1/campaigns/demo/away-digest", params={"since": since}).json()["stopped"][0]["hypothesis_id"] == a["id"]
    assert later > datetime.now(timezone.utc)


def test_monitor_pill_reads_all_clear_unless_a_row_needs_attention(client, workspace, campaign):
    view = monitor_view(workspace, "demo")
    assert view["pill"] == {"state": "clear", "text": "All clear", "row": None} and view["attention"] == []
    worker = view["rows"]["budget"]["worker"]
    assert worker["budget_seconds"] == 600 and worker["allocated_seconds"] == 0 and worker["forecast_basis"].startswith("measured use")
    assert view["rows"]["budget"]["llm"]["cap_usd"] == 1 and view["rows"]["compute"]["limit"] == 2 and view["rows"]["autopilot"]["enabled"] is False
    workspace.memory.issue("demo", "worker_lost", "A worker died")
    view = monitor_view(workspace, "demo")
    assert view["pill"]["state"] == "attention" and view["pill"]["text"] == "1 waiting for you" and view["pill"]["row"] == "needs_you"


def test_merge_note_is_drafted_by_the_lead_and_edited_by_the_researcher(client, workspace, campaign, team):
    run1 = "pi_run_" + command(client, "agent.message", campaign["id"], {"message": "Start.", "thread_id": MAIN}, campaign["version"], origin={"thread_id": MAIN})["id"]
    finish_run(workspace, run1, "Ok.", entry_ids={"parent": None, "last": "e2"})
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_"), "title": "Side"}, campaign["version"])["outcome"]["thread"]
    run2 = "pi_run_" + command(client, "agent.message", campaign["id"], {"message": "Try annealing.", "thread_id": fork["id"]}, campaign["version"], origin={"thread_id": fork["id"]})["id"]
    finish_run(workspace, run2, "Annealing loses by 3 %.", entry_ids={"parent": "e2", "last": "e5"})
    asked = command(client, "thread.merge_draft", campaign["id"], {"thread_id": fork["id"], "into_thread_id": MAIN}, campaign["version"])["outcome"]
    run = submitted(workspace, asked["run_id"])
    assert run["origin"]["thread_id"] == fork["id"] and run["leaf_entry_id"] == "e5" and "merge_note_draft" in run["input"]
    drafted = tool_call(workspace, team, run, "merge_note_draft", {"text": "Annealing loses by 3 % at 60 s; drop it and keep restarts."})
    assert drafted["into_thread_id"] == MAIN
    thread = workspace.store.get(fork["id"], "thread")
    assert thread["merge_draft"]["text"].startswith("Annealing loses") and thread["status"] == "active", "a draft merges nothing by itself"
    finish_run(workspace, run["id"], "Drafted.", entry_ids={"parent": "e5", "last": "e6"}, disposition="complete")
    merged = command(client, "thread.merge", campaign["id"], {"thread_id": fork["id"], "into_thread_id": MAIN, "note": "Annealing loses by 3 % at 60 s; drop it. (Edited: keep one seed for the record.)"}, campaign["version"])["outcome"]
    note = workspace.store.get(merged["message_id"], "message")
    assert "Edited" in note["content"] and note["merge_of_thread_id"] == fork["id"]
    assert workspace.store.get(fork["id"], "thread")["status"] == "merged"


def test_nvml_readings_fill_the_gpu_row():
    assert gpu_row(None) == {"reported": False, "basis": "no GPU reported by the host"}
    assert gpu_row({"gpu": {"status": "none_detected", "devices": []}})["reported"] is False
    listed = gpu_row({"gpu": {"status": "available", "devices": [{"id": "card0", "vendor": "NVIDIA", "utilization_percent": None, "memory_used_bytes": None, "memory_total_bytes": None}]}})
    assert listed["measured"] is False and "not measured" in listed["basis"]
    measured = gpu_row({"gpu": {"status": "available", "devices": [{"id": "card0", "vendor": "NVIDIA", "utilization_percent": 73, "memory_used_bytes": 4 * 2**30, "memory_total_bytes": 24 * 2**30}]}})
    assert measured == {"reported": True, "measured": True, "devices": 1, "busy": True, "utilization_percent": 73, "memory_used_bytes": 4 * 2**30, "memory_total_bytes": 24 * 2**30, "basis": "measured by nvidia-smi"}
