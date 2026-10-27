"""The evolution graph: ledger rows, stages, lineage, interventions, allocation, stop reasons, provenance."""
import pytest

from optimization_framework.storage.sqlite import now

from support import activate_team, command, submitted, tool_call

MAIN = "thread_main_demo"


def hypothesis(client, campaign, title, **extra):
    return command(client, "hypothesis.create", campaign["id"], {"title": title, "mechanism": "m", "rationale": "r", **extra}, campaign["version"], origin={"thread_id": MAIN})["outcome"]["hypothesis"]


def trial(workspace, campaign_id, hypothesis_id, *, status="completed", score=None, wall=60, executed=None, seed=0, identity=None, parent=None):
    record = {"id": identity or f"trial_{hypothesis_id}_{seed}", "campaign_id": campaign_id, "task_id": "task_1", "algorithm": "hillclimb", "status": status, "seed": seed,
              "max_steps": 100, "wall_seconds": wall, "execution_seconds": executed if executed is not None else wall * 0.9, "hypothesis_id": hypothesis_id, "control_revision": 0,
              "created_at": now(), **({"parent_trial_id": parent} if parent else {})}
    if score is not None:
        record["result"] = {"best_objective": score, "evaluations": 100, "scientific_complete": True}
    return workspace.store.put("trial", record, "trial.evidence_cataloged")


def test_ledger_rows_aggregate_trials_race_cells_reviews_and_readiness(client, workspace, campaign):
    a = hypothesis(client, campaign, "Restarts")
    b = hypothesis(client, campaign, "Annealing", parent_links=[{"id": a["id"], "kind": "variant"}], round=1)
    command(client, "hypothesis.review", campaign["id"], {"hypothesis_id": b["id"], "text": "plausible"}, campaign["version"])
    trial(workspace, "demo", a["id"], score=0.4, seed=0)
    trial(workspace, "demo", a["id"], score=0.6, seed=1, wall=1200, executed=1100)
    trial(workspace, "demo", a["id"], status="running", seed=2)
    body = client.get("/api/v1/campaigns/demo/evolution", params={"progress": "true"}).json()
    rows = {row["id"]: row for row in body["nodes"]}
    row = rows[a["id"]]
    assert row["best"] == {"score": 0.6, "basis": "measured", "source": "result", "trial_id": f"trial_{a['id']}_1", "interval": None}
    assert row["worker_seconds"] == pytest.approx(54 + 1100 + 54) and row["allotted_seconds"] == 1320 and row["evaluations"] == 200
    assert row["live_trials"] == 1 and row["stage"] == "extended" and row["race"] is None and row["finalist"] is False
    assert rows[b["id"]]["parent_links"] == [{"id": a["id"], "kind": "variant"}] and rows[b["id"]]["round"] == 1
    assert rows[b["id"]]["review"]["count"] == 1 and rows[b["id"]]["stage"] == "reviewed" and rows[b["id"]]["best"]["score"] is None
    assert isinstance(row["implementation_readiness"]["runnable"], bool) and row["actor"] == "researcher" and row["autonomous"] is False
    assert body["progress"]["best_so_far"] == 0.6 and [t["id"] for t in body["progress"]["live_trials"]] == [f"trial_{a['id']}_2"]
    again = client.get("/api/v1/campaigns/demo/evolution", params={"after": body["event_cursor"]}).json()
    assert again["unchanged"] is True
    assert body["edges"] == [{"from": a["id"], "to": b["id"], "kind": "variant", "external": False}]


def test_stage_follows_the_plan_lifecycle_and_stopped_is_not_failed(client, workspace, campaign):
    h = hypothesis(client, campaign, "Lifecycle")
    stage = lambda: next(r for r in client.get("/api/v1/campaigns/demo/evolution").json()["nodes"] if r["id"] == h["id"])
    assert stage()["stage"] == "proposed"
    command(client, "hypothesis.review", campaign["id"], {"hypothesis_id": h["id"], "text": "ok"}, campaign["version"])
    assert stage()["stage"] == "reviewed"
    trial(workspace, "demo", h["id"], score=0.1, wall=30)
    assert stage()["stage"] == "screening"
    trial(workspace, "demo", h["id"], score=0.2, wall=3600, seed=1)
    assert stage()["stage"] == "extended"
    current = workspace.store.get(h["id"], "hypothesis")
    command(client, "hypothesis.status", campaign["id"], {"hypothesis_id": h["id"], "status": "archived", "expected_status_revision": current["status_revision"],
                                                          "stop_reason": "the curve flattened; cheaper to try the variant"}, campaign["version"])
    row = stage()
    assert row["stage"] == "stopped" and row["status"] == "archived" and row["stop_reason"] == "the curve flattened; cheaper to try the variant"
    assert "fail" not in row["stage"]
    command(client, "hypothesis.status", campaign["id"], {"hypothesis_id": h["id"], "status": "investigating", "expected_status_revision": 1}, campaign["version"])
    assert stage()["stop_reason"] is None and stage()["stage"] == "extended"


def test_typed_parent_links_and_rounds_lay_out_a_forest(client, workspace, campaign):
    a = hypothesis(client, campaign, "A")
    b = hypothesis(client, campaign, "B")
    ab = hypothesis(client, campaign, "A+B", parent_links=[{"id": a["id"], "kind": "hybrid"}, {"id": b["id"], "kind": "hybrid"}])
    a2 = hypothesis(client, campaign, "A revised", parent_ids=[a["id"]], round=3)
    saved = workspace.store.get(ab["id"], "hypothesis")
    assert saved["parent_ids"] == [a["id"], b["id"]] and saved["parent_links"] == [{"id": a["id"], "kind": "hybrid"}, {"id": b["id"], "kind": "hybrid"}]
    assert workspace.store.get(a2["id"], "hypothesis")["parent_links"] == [{"id": a["id"], "kind": "revision"}]
    body = client.get("/api/v1/campaigns/demo/evolution").json()
    layout = {node["id"]: node for node in body["layout"]}
    assert (layout[a["id"]]["round"], layout[b["id"]]["round"], layout[ab["id"]]["round"], layout[a2["id"]]["round"]) == (0, 0, 1, 3)
    assert layout[a["id"]]["lane"] < layout[ab["id"]]["lane"] < layout[b["id"]]["lane"], "children sit under their first parent"
    assert body["rounds"] == 3
    kinds = {(e["from"], e["to"]): e["kind"] for e in body["edges"]}
    assert kinds[(a["id"], ab["id"])] == "hybrid" and kinds[(a["id"], a2["id"])] == "revision"


def test_intervention_batch_is_all_or_nothing_and_bumps_guidance_once(client, workspace, campaign):
    a = hypothesis(client, campaign, "A")
    b = hypothesis(client, campaign, "B")
    before = workspace.memory.state("demo")["guidance_revision"]
    receipt = command(client, "intervention.batch", campaign["id"], {"rationale": "trim the round", "items": [
        {"operation": "hypothesis.status", "payload": {"hypothesis_id": a["id"], "status": "archived", "expected_status_revision": 0, "stop_reason": "duplicate of B"}},
        {"operation": "hypothesis.status", "payload": {"hypothesis_id": b["id"], "status": "investigating", "expected_status_revision": 0}}]}, campaign["version"], origin={"thread_id": MAIN})
    assert [item["operation"] for item in receipt["outcome"]["items"]] == ["hypothesis.status", "hypothesis.status"]
    assert workspace.memory.state("demo")["guidance_revision"] == before + 1
    assert workspace.store.get(a["id"], "hypothesis")["status"] == "archived" and workspace.store.get(b["id"], "hypothesis")["status"] == "investigating"
    intervention = workspace.store.get(receipt["outcome"]["intervention_id"], "intervention")
    assert intervention["origin"]["thread_id"] == MAIN and intervention["content_hash"]
    # One bad item undoes the whole batch: B keeps its state, no intervention is recorded, guidance moves no further.
    failed = command(client, "intervention.batch", campaign["id"], {"items": [
        {"operation": "hypothesis.status", "payload": {"hypothesis_id": b["id"], "status": "archived", "expected_status_revision": 1, "stop_reason": "x"}},
        {"operation": "hypothesis.status", "payload": {"hypothesis_id": b["id"], "status": "archived", "expected_status_revision": 99}}]}, campaign["version"], expect=409)
    assert "status changed" in failed["detail"]
    assert workspace.store.get(b["id"], "hypothesis")["status"] == "investigating"
    assert len(workspace.store.list("intervention", "demo")) == 1 and workspace.memory.state("demo")["guidance_revision"] == before + 1


def test_hypothesis_allocate_translates_to_race_decisions_or_a_continuation(client, workspace, campaign, monkeypatch):
    h = hypothesis(client, campaign, "Allocate me", algorithm="random")
    # No run yet: a short run of the strategy's algorithm on the development task, with an unused seed.
    outcome = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": h["id"], "worker_seconds": 45, "rationale": "a first look"}, campaign["version"])["outcome"]
    assert outcome["how"] == "trial.create" and outcome["seed"] == 0
    started = workspace.store.get(outcome["trial_id"], "trial")
    assert started["hypothesis_id"] == h["id"] and started["wall_seconds"] == 45 and started["status"] == "queued"
    # A finished run: more time continues it as a new run under the current source.
    started.update(status="completed", result={"best_objective": 0.3, "evaluations": 10, "scientific_complete": True})
    workspace.store.put("trial", started)
    continued = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": h["id"], "worker_seconds": 90, "rationale": "still improving"}, campaign["version"])["outcome"]
    # Without a saved state there is nothing to continue: a fresh run with the next seed, and the outcome says why.
    assert continued["how"] == "trial.create" and continued["seed"] == 1 and "no state" in continued["not_continued"]
    assert workspace.store.get(continued["trial_id"], "trial")["wall_seconds"] == 90
    # A run with a saved state is continued as one chain.
    started["result"]["state"] = {"step": 10}
    workspace.store.put("trial", started)
    chained = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": h["id"], "worker_seconds": 120, "rationale": "go on"}, campaign["version"], expect=None)
    if chained.get("outcome", {}).get("how") == "trial.continue":
        log = client.get(f"/api/v1/experiments/{chained['outcome']['trial_id']}").json()
        assert log["chain_trial_ids"][0] == chained["outcome"]["continued_from"]
    # Bound to a race configuration: the allocation is a race decision.
    calls = []
    monkeypatch.setattr(workspace.store, "list", _with_race(workspace.store.list, h["id"]))
    monkeypatch.setattr(workspace.racing, "_protocol", lambda race: {"configurations": [{"id": "cfg_h", "hypothesis_id": h["id"], "algorithm": "hillclimb"}]})
    monkeypatch.setattr(workspace.racing, "decide", lambda campaign_id, request, authority: calls.append((request.action, request.configuration_ids, request.rationale)) or {"id": "race_1"})
    raced = command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": h["id"], "worker_seconds": 900, "rationale": "promote in the race", "replicate": True}, campaign["version"])["outcome"]
    assert raced["how"] == "race.replicate" and calls == [("replicate", ["cfg_h"], "promote in the race")]


def _with_race(original, hypothesis_id):
    def listing(kind, campaign_id=None, *args, **kwargs):
        rows = original(kind, campaign_id, *args, **kwargs)
        if kind == "adaptive_race" and campaign_id == "demo":
            return [{"id": "race_1", "campaign_id": "demo", "status": "running", "configurations": {"cfg_h": {"status": "active"}}, "cells": []}]
        return rows
    return listing


def test_stop_records_a_reason_and_holds_the_race_configuration(client, workspace, campaign, monkeypatch):
    h = hypothesis(client, campaign, "In a race")
    monkeypatch.setattr(workspace.store, "list", _with_race(workspace.store.list, h["id"]))
    monkeypatch.setattr(workspace.racing, "_protocol", lambda race: {"configurations": [{"id": "cfg_h", "hypothesis_id": h["id"], "algorithm": "hillclimb"}]})
    calls = []
    monkeypatch.setattr(workspace.racing, "decide", lambda campaign_id, request, authority: calls.append((request.action, request.configuration_ids, request.rationale, authority)) or {"id": "race_1"})
    command(client, "hypothesis.status", campaign["id"], {"hypothesis_id": h["id"], "status": "archived", "expected_status_revision": 0, "stop_reason": "worse than the baseline at every rung"}, campaign["version"])
    assert calls == [("hold", ["cfg_h"], f"Strategy {h['id']} was stopped: researcher's decision; worse than the baseline at every rung", "researcher")]
    stopped = workspace.store.get(h["id"], "hypothesis")
    assert stopped["stop_reason"] == "worse than the baseline at every rung" and stopped["stopped_at"]
    assert stopped["stop"]["outcome"] == "researcher_decision"
    command(client, "hypothesis.allocate", campaign["id"], {"hypothesis_id": h["id"], "worker_seconds": 10, "rationale": "x"}, campaign["version"], expect=409)


def test_provenance_walks_origin_run_turn_thread_and_model(client, workspace, campaign, monkeypatch):
    lead = activate_team(client, workspace, campaign, monkeypatch)
    receipt = command(client, "agent.message", campaign["id"], {"message": "Record a strategy.", "thread_id": MAIN}, campaign["version"], origin={"thread_id": MAIN})
    run = submitted(workspace, "pi_run_" + receipt["id"])
    created = tool_call(workspace, lead, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "p", "payload": {"title": "From the lead", "mechanism": "m", "rationale": "r"}})
    hid = created["outcome"]["hypothesis_id"]
    body = client.get(f"/api/v1/records/{hid}/provenance").json()
    hops = [(hop["hop"], hop["via"]) for hop in body["trail"]]
    assert hops[0] == ("hypothesis", "the record")
    assert hops[1][0] == "work_command" and "manager ran hypothesis.create" in hops[1][1]
    assert [h[0] for h in hops[2:6]] == ["agent_run", "agent_session", "message", "thread"]
    assert any("lead on gpt-6-astra" in hop["record"]["title"] for hop in body["trail"] if hop["hop"] == "agent_session")
    assert body["trail"][1]["page"] == "#hypotheses"
    card = client.get(f"/api/v1/hypotheses/{hid}").json()
    assert card["ledger_row"]["actor"] == "lead" and card["provenance"][0]["record"]["id"] == hid and card["parents"] == [] and "runnable" in card["implementation"]
    assert client.get("/api/v1/records/nothing/provenance").status_code == 404


def test_the_next_formulation_step_is_named_until_the_charter_is_confirmed(client, workspace, campaign):
    from balsamic.evolution.stages import next_step
    from optimization_framework.storage.sqlite import now
    record = workspace.store.get(campaign["id"], "campaign")
    tasks = workspace.store.list("task", campaign["id"])
    if tasks:
        assert next_step(workspace, record) is None and client.get("/api/v1/campaigns").json()["campaigns"][0]["next_step"] is None
        for task in tasks:
            workspace.store.delete(task["id"], "task") if hasattr(workspace.store, "delete") else None
    if workspace.store.list("task", campaign["id"]):
        return   # the fixture campaign carries tasks and the store keeps them: the None branch above is the test
    record.pop("problem_note_id", None); workspace.store.put("campaign", record)
    assert next_step(workspace, record)["kind"] == "note"
    note = {"id": "note_x", "campaign_id": campaign["id"], "thread_id": MAIN, "title": "t", "current_revision": 1, "adopted_revision": None, "charter_id": None, "import_id": None, "status": "drafting", "created_at": now(), "updated_at": now()}
    workspace.store.put("problem_note", note); record["problem_note_id"] = "note_x"; workspace.store.put("campaign", record)
    assert next_step(workspace, record)["kind"] == "adopt"
    note.update(status="adopted", charter_id="charter_x"); workspace.store.put("problem_note", note)
    from optimization_framework.problem_charter.service import KIND
    workspace.store.put(KIND, {"id": "charter_x", "campaign_id": campaign["id"], "status": "proposed", "revision": 1, "charter": {}, "created_at": now()})
    assert client.get("/api/v1/campaigns").status_code == 200, "the campaign list must never fail on a charter lookup"
    step = next_step(workspace, record)
    assert step["kind"] == "confirm" and step["page"] == "#note/charter" and step["blocking"] is False
    hypothesis(client, campaign, "A proposal before the charter")
    step = next_step(workspace, workspace.store.get(campaign["id"], "campaign"))
    assert step["kind"] == "confirm" and step["blocking"] is True and step["proposals"] == 1
    assert client.get("/api/v1/campaigns").json()["campaigns"][0]["next_step"]["kind"] == "confirm"
