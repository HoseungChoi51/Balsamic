"""The baking order replayed offline (roadmap G1): the whole path from a charter to ranked results, with the scripted harness
standing in for the model. A permutation charter of 8 bakes (durations and due dates; minimize total tardiness) is confirmed
and a campaign made from it; the researcher asks for four methods, and the lead's turn records 4 proposals and one compute
plan (the coding workspace and 4 proposals x 2 seeds), which the researcher approves.

Steps 4 and 5 (a fake coding agent fills the generated scaffold, a fake uv installs it) and the assertions on adoption, the 8
automatic starts and the single comparison wake are added as F3, F4, E4 and E5 merge, never against a stand-in for them."""
import itertools
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from balsamic.app import create_app  # noqa: E402
from fake_harness import FakeHarness, serve  # noqa: E402
from optimization_framework.problem_charter import charter as C  # noqa: E402
from support import command  # noqa: E402

MAIN = "thread_main_bakery"
DURATIONS = [30, 45, 20, 60, 35, 25, 50, 40]       # minutes
DUE = [210, 130, 200, 110, 190, 100, 40, 120]      # minutes from the oven's start; earliest due date is 415 late, the best order 290
METHODS = [("Earliest due date", "Sort the bakes by due time: the classic rule for lateness, one pass"),
           ("Adjacent swap search", "From the earliest-due-date order, swap neighbours while the tardiness falls"),
           ("Random restarts", "Swap search from random orders, keeping the best"),
           ("Exact enumeration", "All 8! = 40,320 orders: the optimum, as the reference")]
SEEDS = [0, 1]
RUN_SECONDS = 60


def bakery():
    """Choose the order of 8 bakes in one oven: a declared problem whose decision variable is an order."""
    return {
        "title": "Baking order",
        "summary": "Order {n_bakes:.0f} bakes in one oven to minimize their total tardiness.",
        "text": "One oven takes {n_bakes:.0f} bakes, one after another. Each bake has a duration and a due time; a bake that ends after "
                "its due time is late by the difference. Choose the order that minimizes the total lateness.",
        "quantities": {"n_bakes": {"description": "Bakes to schedule", "kind": "integer", "value": 8, "units": "1", "citation": 1}},
        "tables": {"durations": {"description": "Duration of each bake, by its index", "x_units": "1", "y_units": "min",
                                 "points": [[i, d] for i, d in enumerate(DURATIONS)], "citation": 1},
                   "due_dates": {"description": "Due time of each bake, by its index, from the oven's start", "x_units": "1", "y_units": "min",
                                 "points": [[i, d] for i, d in enumerate(DUE)], "citation": 1}},
        "variables": [{"name": "bake_order", "description": "The order the bakes go into the oven", "representation": "permutation",
                       "shape": ["n_bakes"], "meaning": "Each entry is the index of a bake in the tables"}],
        "constraints": [],
        "objective": {"name": "total_tardiness", "direction": "minimize", "units": "min",
                      "definition": "The sum over bakes of max(0, end time - due time)"},
        "metrics": [],
        "evaluator": {"kind": "declared", "problem_id": "baking_order", "deterministic": True, "configuration": {"n_bakes": "n_bakes"},
                      "fidelity": {}, "notes": "Run the bakes in the given order from time 0; sum each bake's lateness past its due time."},
        "instances": [{"name": "Eight bakes", "split": "development"}],
        "citations": [{"id": 1, "source": "documents/bakery.md.txt", "location": "the order sheet"}],
    }


def tardiness(order):
    clock, late = 0, 0
    for bake in order:
        clock += DURATIONS[bake]
        late += max(0, clock - DUE[bake])
    return late


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    return create_app(tmp_path / "workspace", start_workers=False)


@pytest.fixture
def workspace(app):
    return app.state.workspace


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def stack(tmp_path, monkeypatch, client, workspace):
    """The scripted harness on a port, calling the workspace's callback routes as the real one does."""
    token = "b" * 40
    token_file = tmp_path / "pi.token"
    token_file.write_text(token)
    port = free_port()
    monkeypatch.setenv("GRATING_PI_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("GRATING_PI_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setenv("GRATING_LLM_ENABLED", "true")

    def gateway(operation, body):
        response = client.post(f"/api/internal/pi/{operation}", json=body, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200, response.text
        return response.json()
    harness = FakeHarness(gateway)
    harness.notify = workspace.pi.notify
    server = serve(harness, port, token)
    yield harness
    server.shutdown()


def settle(workspace, run_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        workspace.on_manager_tick()
        for thread in list(workspace.pi.threads.values()):
            thread.join(timeout=2)
        run = workspace.store.get(run_id, "agent_run")
        if run["status"] in {"completed", "failed"}:
            return run
        time.sleep(0.1)
    raise AssertionError("the turn did not settle: " + workspace.store.get(run_id, "agent_run")["status"])


def lead_turn(workspace, campaign_id):
    """The lead's answer to the researcher's request: 4 proposals and one compute plan naming them, through campaign_command."""
    def script(agent, run, tools):
        tools("campaign_inspect", {})
        [task] = workspace.current_tasks(campaign_id)
        proposals = []
        for index, (title, mechanism) in enumerate(METHODS):
            receipt = tools("campaign_command", {"operation": "hypothesis.create", "request_key": f"proposal_{index}", "payload": {
                "title": title, "mechanism": mechanism, "rationale": "The researcher asked for it", "algorithm": "custom",
                "algorithm_config": {"design_note": mechanism}}})
            proposals.append(receipt["outcome"]["hypothesis_id"])
        runs = [{"task_id": task["id"], "hypothesis_id": h, "seeds": SEEDS, "wall_seconds": RUN_SECONDS} for h in proposals]
        tools("campaign_command", {"operation": "approval.request", "request_key": "plan", "payload": {
            "kind": "compute", "plan": "Implement the four methods in one coding workspace, then run each on 2 seeds",
            "rationale": "Compare the four orders at matched cost", "wall_seconds": 1800,
            "worker_seconds": 900 + len(runs) * len(SEEDS) * RUN_SECONDS, "coding_workspaces": 1, "hypothesis_ids": proposals,
            "meanwhile": "Read the charter's tables", "runs": runs}})
        reply = "I recorded four proposals and asked for one go-ahead covering the coding workspace and the 8 runs."
        tools("yield_work", {"disposition": "complete", "report": reply, "summary": "proposed and asked", "evidence_ids": []})
        return reply
    return script


def test_the_baking_order_goes_from_a_charter_to_one_approved_plan(client, workspace, stack):
    # 1. The permutation charter, confirmed by the researcher, and a campaign made from it.
    rows = C.findings(bakery())
    assert not [row for row in rows if row["severity"] == "blocking"], rows
    assert tardiness(sorted(range(8), key=lambda b: DUE[b])) > min(
        tardiness(order) for order in itertools.permutations(range(8))), "earliest due date is not optimal here"
    record = workspace.charters.create(bakery(), source={"kind": "test", "id": "bakery", "name": "Bakery"})
    response = client.post(f"/api/v1/problem-charters/{record['id']}/confirm", json={"expected_revision": record["revision"]})
    assert response.status_code == 200, response.text
    confirmed = response.json()
    receipt = command(client, "campaign.create", "bakery", {"name": "Baking order", "research_question": "Which order of bakes is least late?",
        "charter": confirmed["charter"], "compute_budget_seconds": 7200, "validation_reserve_seconds": 0, "llm_budget_usd": 1}, 0)
    campaign = receipt["outcome"]["campaign"]
    cid = campaign["id"]
    [task] = workspace.current_tasks(cid)
    schema = task["evaluator_manifest"]["candidate_schema"]
    assert (schema["representation"], schema["dimensions"]) == ("permutation", 8)
    assert task["evaluator_manifest"]["primary_objective"]["direction"] == "minimize"
    assert workspace.charters.get(record["id"])["campaign_ids"] == [cid]

    # 2. The lead starts; the researcher's one message gets a turn that records the 4 proposals and the plan.
    version = lambda: workspace.store.get(cid, "campaign")["version"]
    command(client, "agent.activate", cid, {}, version())
    stack.script = lead_turn(workspace, cid)
    ask = command(client, "agent.message", cid, {"message": "Compare four ways to order the bakes: earliest due date, an adjacent swap "
        "search, random restarts and exact enumeration. Two seeds each.", "thread_id": MAIN}, version(), origin={"thread_id": MAIN})
    run = settle(workspace, "pi_run_" + ask["id"])
    assert run["status"] == "completed", run.get("error")
    proposals = sorted(workspace.store.list("hypothesis", cid), key=lambda h: h["created_at"])
    assert [h["title"] for h in proposals] == [title for title, _ in METHODS]
    assert all(h["requested_by"]["message_id"] == "message_" + ask["id"] for h in proposals), "asked for by the researcher"

    # 3. One compute plan, the workspace and 4 x 2 runs, approved by the researcher's one decision.
    [decision] = [d for d in workspace.store.list("decision", cid) if d.get("status") == "pending"]
    assert [o["label"] for o in decision["options"]] == ["Start now", "Not now"]
    command(client, "decision.resolve", cid, {"decision_id": decision["id"], "choice": "0", "comment": "", "expected_resolution_revision": 0},
            version())
    [consent] = workspace.store.list("compute_consent", cid)
    assert sorted(consent["hypothesis_ids"]) == sorted(h["id"] for h in proposals)
    planned = [(r["hypothesis_id"], seed) for r in consent["runs"] for seed in r["seeds"]]
    assert len(planned) == 8 and len(set(planned)) == 8
    assert consent["request_root"]["message_id"] == "message_" + ask["id"]
    assert workspace.store.list("trial", cid) == [], "nothing runs before the methods exist"

    # The researcher acted three times: the charter's confirmation, one message and one decision.
    researcher = [r["request"]["operation"] for r in workspace.store.list("work_command", cid) if r.get("actor") == "researcher"]
    assert [op for op in researcher if op not in {"campaign.create", "agent.activate"}] == ["agent.message", "decision.resolve"]
    assert len(workspace.charters.get(record["id"])["confirmed"]) == 1
