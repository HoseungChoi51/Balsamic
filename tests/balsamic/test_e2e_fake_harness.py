"""End to end against the scripted harness: a message becomes a turn, the turn's tools reach the workspace's callback routes,
the reply lands in the thread with its session entries, and a fork continues from the right leaf."""
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fake_harness import FakeHarness, serve  # noqa: E402
from support import command  # noqa: E402

MAIN = "thread_main_demo"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def stack(tmp_path, monkeypatch, client, workspace, campaign):
    token = "f" * 40
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
    harness.notify = workspace.pi.notify   # as the real harness does: a notice says which agents to inspect
    server = serve(harness, port, token)
    yield harness
    server.shutdown()


def settle(workspace, campaign_id, run_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        workspace.on_manager_tick()   # what the maintenance thread does: the controller syncs with the harness
        for thread in list(workspace.pi.threads.values()):
            thread.join(timeout=2)
        run = workspace.store.get(run_id, "agent_run")
        if run["status"] in {"completed", "failed"}:
            return run
        time.sleep(0.1)
    raise AssertionError("the turn did not settle: " + workspace.store.get(run_id, "agent_run")["status"])


def test_a_message_becomes_a_turn_whose_reply_lands_in_its_thread_with_its_entries(client, workspace, campaign, stack):
    command(client, "agent.activate", "demo", {}, campaign["version"])
    receipt = command(client, "agent.message", "demo", {"message": "What should we try first?", "thread_id": MAIN}, campaign["version"], origin={"thread_id": MAIN})
    run = settle(workspace, "demo", "pi_run_" + receipt["id"])
    assert run["status"] == "completed", run.get("error")
    reply = workspace.store.get("message_" + run["id"], "message")
    assert reply["origin"] == "lead" and reply["thread_id"] == MAIN and "Fake lead" in reply["content"]
    assert reply["entry_id"] == run["result"]["entry_ids"]["last"]
    thread = workspace.store.get(MAIN, "thread")
    assert thread["agent_leaf"] == reply["entry_id"]
    # The turn's tool calls reached the workspace through the authenticated callback route and were receipted.
    receipts = [r for r in workspace.store.list("agent_tool_receipt", "demo") if r["run_id"] == run["id"]]
    assert {r["tool"] for r in receipts} == {"campaign_inspect", "yield_work"}
    assert workspace.pi.configuration("demo")["request_open"] is False, "yield_work(complete) closed the request"
    # A fork continues from the reply's entry: the harness branched there before the next prompt.
    fork = command(client, "thread.fork", "demo", {"thread_id": MAIN, "message_id": "message_" + receipt["id"]}, campaign["version"])["outcome"]["thread"]
    assert fork["fork_entry_id"] == reply["entry_id"]
    second = command(client, "agent.message", "demo", {"message": "On this branch, try annealing.", "thread_id": fork["id"]}, campaign["version"], origin={"thread_id": fork["id"]})
    run2 = settle(workspace, "demo", "pi_run_" + second["id"])
    assert run2["result"]["entry_ids"]["parent"] == reply["entry_id"]
    lead_id = workspace.pi.configuration("demo")["lead_id"]
    tree = stack.session(lead_id, "tree", {})
    assert tree["leaf_id"] == run2["result"]["entry_ids"]["last"]
    branch = client.get(f"/api/v1/threads/{fork['id']}/messages").json()
    assert [m["role"] for m in branch["messages"]] == ["user", "assistant"] and branch["inherited"][0]["count"] == 2
    context = client.get(f"/api/v1/threads/{fork['id']}/context").json()
    assert context["layers"]["branch"]["measured"] is True and context["layers"]["branch"]["entries_since_fork"] == 4
