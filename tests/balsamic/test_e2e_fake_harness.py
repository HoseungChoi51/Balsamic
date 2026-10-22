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


def test_each_turn_carries_the_state_at_its_start_and_the_manifest_is_fetched_once(client, workspace, campaign, stack):
    calls, gateway = [], stack.gateway
    stack.gateway = lambda operation, body: (calls.append(operation), gateway(operation, body))[1]
    version = lambda: workspace.store.get("demo", "campaign")["version"]
    command(client, "agent.activate", "demo", {}, version())
    def turn(text):
        receipt = command(client, "agent.message", "demo", {"message": text, "thread_id": MAIN}, version(), origin={"thread_id": MAIN})
        return settle(workspace, "demo", "pi_run_" + receipt["id"])
    lead_id = workspace.pi.configuration("demo")["lead_id"]
    first = turn("Hello")
    prompt = stack.agents[lead_id]["runs"][first["id"]]["prompt"]
    assert prompt.startswith(f"[Assignment {first['id']}]\n[Workspace state") and "Gate: open" in prompt and prompt.endswith("\n\nHello")
    # The researcher starts a problem note between the two turns: the gate closes, and the next turn is told so, by the same runtime.
    command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"objective": {"text": "Minimise the quadratic"}}}, version())
    second = turn("Propose two strategies.")
    prompt = stack.agents[lead_id]["runs"][second["id"]]["prompt"]
    assert "Gate: closed" in prompt and "Not written yet: Knobs" in prompt and "Gate: open" not in prompt
    assert workspace.store.get(second["id"], "agent_run")["turn_state"]["text"] in prompt
    entries = stack.session(lead_id, "entries", {})["entries"]
    assert [e["preview"][:len(f"[Assignment {second['id']}]")] for e in entries if e["role"] == "user"][-1] == f"[Assignment {second['id']}]"
    assert calls.count("manifest") == 1 and calls.count("turn_state") == 2
    # A harness restart makes a new runtime, which fetches the manifest again.
    stack.restart()
    turn("Again.")
    assert calls.count("manifest") == 2


def test_extension_calls_are_receipted_dialogs_answered_without_a_turn_and_a_silent_turn_continues_once(client, workspace, campaign, stack, tmp_path, monkeypatch):
    import json
    import threading
    folder = tmp_path / "extensions"
    (folder / "session" / "web").mkdir(parents=True)
    (folder / "session" / "web" / "index.ts").write_text("export default function () {}\n")
    (folder / "allowlist.json").write_text(json.dumps({"extensions": {"web": {"path": "session/web/index.ts", "tools": {"web_read": {}}}}, "roles": {"lead": ["web"]}}))
    monkeypatch.setenv("GRATING_PI_EXTENSIONS", str(folder / "allowlist.json"))
    seen = {}
    def script(agent, run, tools):
        if run.get("continuation"):
            tools("yield_work", {"disposition": "complete", "summary": "Answered", "report": "The paper reports 0.93.", "evidence_ids": []})
            return ""
        seen["read"] = tools.external("web_read", {"url": "https://example.org/paper"}, "The paper reports an efficiency of 0.93.")
        seen["shell"] = tools.external("shell_exec", {"command": "ls"}, "files")
        seen["choice"] = tools.dialog("select", "Which source should I trust?", options=["arXiv", "Crossref"])
        return "The paper reports 0.93."   # in prose, without yield_work
    stack.script = script
    version = lambda: workspace.store.get("demo", "campaign")["version"]
    command(client, "agent.activate", "demo", {}, version())
    def answer():   # the researcher answers the dialog above the chat while the turn waits for it
        for _ in range(200):
            pending = [q for q in workspace.store.list("agent_question", "demo") if q.get("kind") == "extension_dialog" and q["status"] == "pending"]
            if pending:
                command(client, "agent.ui_respond", "demo", {"question_id": pending[0]["id"], "value": "Crossref"}, version())
                return
            time.sleep(0.05)
    responder = threading.Thread(target=answer); responder.start()
    receipt = command(client, "agent.message", "demo", {"message": "What does the paper report?", "thread_id": MAIN}, version(), origin={"thread_id": MAIN})
    run = settle(workspace, "demo", "pi_run_" + receipt["id"])
    responder.join(timeout=10)
    assert run["status"] == "completed" and seen["choice"] == "Crossref"
    # The allowlisted call is receipted with the run; the other was blocked and left nothing.
    external = [r for r in workspace.store.list("agent_tool_receipt", "demo") if r.get("external")]
    assert [(r["tool"], r["run_id"], r["extension"]) for r in external] == [("web_read", run["id"], "web")] and seen["read"]["receipt_id"] == external[0]["id"]
    assert seen["shell"]["blocked"] is True
    # The answer went back to the waiting extension: no run was queued for it, and only the one turn ran.
    lead_runs = workspace.store.list_agent_runs(workspace.pi.configuration("demo")["lead_id"])
    assert [r["id"] for r in lead_runs] == [run["id"]], "no notice turn: the silent turn was continued in the same run"
    assert run["disposition"]["disposition"] == "complete" and workspace.pi.configuration("demo")["request_open"] is False
    reply = workspace.store.get("message_" + run["id"], "message")
    assert reply["content"] == "The paper reports 0.93."
