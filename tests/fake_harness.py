"""A scripted stand-in for the Pi agent harness, speaking its HTTP protocol, with a session tree.

For tests and for a local stack without a model: ``uv run python tests/fake_harness.py --port 8768`` beside
``GRATING_PI_URL=http://127.0.0.1:8768 optimization-lab ...``. Each run it receives plays a script: it calls a few tools
through the gateway (campaign_inspect, then yield_work with a reply that echoes the request), and reports the run completed
with the entry ids its session tree grew by. As on the real harness, the agent's manifest is fetched once, when its runtime
is made (``restart()`` forgets every runtime, as a harness restart does), and every turn asks the workspace for its state
block and puts it before the message. Threads work as on the real harness too: a run with ``branch_from_entry_id`` or
``leaf_entry_id`` positions the leaf first.

What the harness's Balsamic extension does is played too, so end-to-end tests can script it: ``tools.external(tool, args,
text)`` runs an extension tool (blocked unless the manifest allowlists it for the role, receipted through
``external_receipt`` otherwise), ``tools.dialog(method, title, ...)`` asks the researcher through ``ui_request`` and waits for
the answer, and a turn that ends without a saved yield_work is given one continuation in the same run (the script is played
again with ``run["continuation"]`` set and the reminder as its text).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

STATUS = {"configured": True, "mode": "dev", "provider": "openai-codex", "providers": {"openai-codex": {"auth": "oauth", "billing": "subscription"}},
          "defaults": {"provider": "openai-codex", "model": "gpt-6-astra", "effort": "medium"}, "login": None,
          "models": [{"provider": "openai-codex", "id": "gpt-6-astra", "name": "fake", "reasoning": True, "thinking_levels": ["off", "low", "medium", "high"], "context_window": 200000, "max_tokens": 32000, "cost": None}]}


class SessionTree:
    """Entries with parents and a leaf, like Pi's SessionManager, kept in memory."""
    def __init__(self):
        self.entries = {}
        self.order = []
        self.leaf = None

    def append(self, kind, text, role=None):
        identity = "e" + uuid.uuid4().hex[:8]
        self.entries[identity] = {"id": identity, "parent_id": self.leaf, "type": kind, "role": role, "preview": text[:160], "timestamp": time.time()}
        self.order.append(identity)
        self.leaf = identity
        return identity

    def branch(self, entry_id):
        if entry_id not in self.entries:
            raise ValueError("Unknown session entry")
        self.leaf = entry_id

    def path(self, leaf=None):
        out, current = [], leaf or self.leaf
        while current:
            out.insert(0, self.entries[current]); current = self.entries[current]["parent_id"]
        return out

    def tree(self):
        children = {}
        for entry in self.order:
            children.setdefault(self.entries[entry]["parent_id"], []).append(entry)
        def walk(parent):
            return [{**self.entries[e], "leaf": e == self.leaf, "children": walk(e)} for e in children.get(parent, [])]
        return walk(None)


REMINDER = "End the turn with yield_work: complete with the answer in report, or waiting if work you started is still running."


class Tools:
    """The tools a scripted turn calls: the gateway's, and an extension's through the Balsamic extension's rules."""
    def __init__(self, harness, agent, run):
        self.harness, self.agent, self.run = harness, agent, run
        self.yielded = False

    def __call__(self, name, arguments):
        live = self.harness.live[self.agent["id"]]
        live["steps"].append({"label": name, "done": False, "failed": False})
        result = self.harness.gateway("tool", {"agent_id": self.agent["id"], "run_id": self.run["id"], "call_id": name + "_" + uuid.uuid4().hex[:6], "name": name, "arguments": arguments})
        live["steps"][-1]["done"] = True
        self.harness._event(self.agent, "tool_execution_end", tool=name, summary=name)
        if name == "yield_work" and isinstance(result, dict) and result.get("saved") is True:
            self.yielded = True
        return result

    def external(self, tool, arguments, text):
        manifest = self.agent.get("manifest") or {}
        allowed = {name: entry["name"] for entry in manifest.get("extensions") or [] for name in entry.get("tools") or []}
        call_id = tool + "_" + uuid.uuid4().hex[:6]
        if tool not in allowed:
            self.harness._event(self.agent, "extension.tool_blocked", tool=tool, call_id=call_id)
            return {"blocked": True, "reason": f"{tool} is not allowed for the {self.agent['spec']['role'].replace('_', ' ')}"}
        receipt = self.harness.gateway("external_receipt", {"agent_id": self.agent["id"], "run_id": self.run["id"], "call_id": call_id, "tool": tool,
            "extension": allowed[tool], "arguments": arguments, "result_excerpt": text[:24 * 1024], "result_bytes": len(text.encode()), "is_error": False, "annotations": None})
        return {"content": text, **receipt}

    def dialog(self, method, title, *, timeout=None, poll=0.05, **fields):
        scope = {"agent_id": self.agent["id"], "run_id": self.run["id"]}
        state = self.harness.gateway("ui_request", {**scope, "request_id": uuid.uuid4().hex, "method": method, "title": title,
                                                   "timeout_ms": timeout * 1000 if timeout else None, **fields})
        deadline = time.time() + timeout if timeout else None
        while state.get("status") == "pending" and (deadline is None or time.time() < deadline):
            time.sleep(poll)
            state = self.harness.gateway("ui_request/" + state["question_id"], scope)
        if state.get("status") == "answered":
            return state.get("value")
        return False if method == "confirm" else None


class FakeHarness:
    def __init__(self, gateway, *, script=None):
        self.gateway = gateway          # gateway(operation, body) -> dict, like the real harness's callbacks
        self.script = script or self.default_script
        self.answer = None              # answer(call_id, body) -> text, or None for the default single-call answer
        self.agents = {}
        self.lock = threading.Lock()
        self.live = {}

    def default_script(self, agent, run, tools):
        """What a turn does: read the campaign, then reply through yield_work. Override for richer behaviour."""
        tools("campaign_inspect", {})
        reply = f"Fake lead: I read your request ({run['text'][:60]}) and did nothing else; ask for something specific."
        tools("yield_work", {"disposition": "complete", "report": reply, "summary": "replied", "evidence_ids": []})
        return reply

    def status(self):
        return STATUS

    def _agent(self, agent_id, spec=None):
        with self.lock:
            agent = self.agents.setdefault(agent_id, {"id": agent_id, "spec": spec, "runs": {}, "events": [], "seq": 0, "tree": SessionTree(), "control": None,
                                                      "manifest": None})
            if spec:
                agent["spec"] = spec
            return agent

    def view(self, agent_id, after=0):
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        events = [e for e in agent["events"] if e["seq"] > after]
        return {"id": agent_id, "session_id": "fake_" + agent_id, "session_file": None, "runs": agent["runs"], "events": events, "cursor": events[-1]["seq"] if events else after}

    def submit(self, agent_id, body):
        agent = self._agent(agent_id, body.get("spec"))
        run_id = body["run_id"]
        if run_id in agent["runs"]:
            return agent["runs"][run_id]
        run = {"id": run_id, "text": body["text"], "mode": body.get("mode", "follow_up"), "status": "queued", "result": None, "error": None,
               "thread_id": body.get("thread_id"), "leaf_entry_id": body.get("leaf_entry_id"), "branch_from_entry_id": body.get("branch_from_entry_id")}
        agent["runs"][run_id] = run
        threading.Thread(target=self._play, args=(agent, run), daemon=True).start()
        return run

    def _event(self, agent, kind, **data):
        agent["seq"] += 1
        agent["events"].append({"seq": agent["seq"], "type": kind, "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data})

    def _play(self, agent, run):
        time.sleep(0.05)
        tree = agent["tree"]
        run["status"] = "running"
        self.live[agent["id"]] = {"id": agent["id"], "run_id": run["id"], "phase": "thinking", "steps": [], "thinking": "", "text": "", "started_at": time.time(), "finished_at": None}
        try:
            if run["branch_from_entry_id"]:
                tree.branch(run["branch_from_entry_id"])
            elif run["leaf_entry_id"] and run["leaf_entry_id"] != tree.leaf:
                tree.branch(run["leaf_entry_id"])
            parent = tree.leaf
            if agent.get("manifest") is None:
                agent["manifest"] = self.gateway("manifest", {"agent_id": agent["id"], "run_id": run["id"]})
            state = self._turn_state(agent, run)
            run["prompt"] = f"[Assignment {run['id']}]\n" + (state + "\n\n" if state else "") + run["text"]
            tree.append("message", run["prompt"], role="user")
            tools = Tools(self, agent, run)
            reply = self.script(agent, run, tools)
            # As the harness: a manifest that says nothing of it hosts the extension (the grant roles that did not were retired in H8).
            host = (agent.get("manifest") or {}).get("extension_host", True)
            if not tools.yielded and host:
                # The Balsamic extension's agent_before_settle: one continuation in the same run.
                self._event(agent, "turn.continued", run_id=run["id"], summary="The run was ending without yield_work")
                tree.append("custom", REMINDER, role="custom")
                more = self.script(agent, {**run, "text": REMINDER, "continuation": True}, tools)
                reply = "\n\n".join(part for part in (reply, more) if part)
            last = tree.append("message", reply, role="assistant")
            self._event(agent, "assistant.message", text=reply, usage={"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0, "totalTokens": 15, "cost_usd": 0},
                        stop_reason="stop", provider="openai-codex", model="gpt-6-astra", billing="subscription")
            run.update(status="completed", result={"text": reply, "entry_ids": {"parent": parent, "last": last}})
        except Exception as exc:   # the harness reports a failed turn; the workspace says so
            run.update(status="failed", error=str(exc)[:500])
        finally:
            self.live[agent["id"]]["finished_at"] = time.time()
            self._event(agent, "run." + run["status"], run_id=run["id"])
            notify = getattr(self, "notify", None)
            if notify:
                try:
                    notify([agent["id"]])
                except Exception:
                    pass

    def _turn_state(self, agent, run):
        """The workspace's state block for this turn; empty from a workspace without the route."""
        try:
            return (self.gateway("turn_state", {"agent_id": agent["id"], "run_id": run["id"]}) or {}).get("text") or ""
        except HTTPError as exc:
            if exc.code == 404:
                return ""
            raise

    def restart(self):
        """What a harness restart does to the runtimes: each agent's next turn fetches its manifest again."""
        with self.lock:
            for agent in self.agents.values():
                agent["manifest"] = None

    def control(self, agent_id, action):
        agent = self._agent(agent_id)
        agent["control"] = None if action == "resume" else action
        return {"status": agent["control"] or "idle"}

    def session(self, agent_id, view, params):
        agent = self.agents.get(agent_id)
        if not agent:
            return None
        tree = agent["tree"]
        if view == "tree":
            return {"session_id": "fake_" + agent_id, "session_file": None, "leaf_id": tree.leaf, "entries": len(tree.order), "tree": tree.tree()}
        if view == "entries":
            return {"leaf_id": params.get("leaf") or tree.leaf, "entries": tree.path(params.get("leaf"))}
        if view == "context":
            path = tree.path(params.get("leaf"))
            return {"leaf_id": params.get("leaf") or tree.leaf, "entries": len(path), "bytes": sum(len(json.dumps(e)) for e in path), "messages": len(path), "summaries": 0, "compactions": 0, "items": path}
        raise ValueError("Unknown session view")

    def set_leaf(self, agent_id, entry_id):
        agent = self._agent(agent_id)
        previous = agent["tree"].leaf
        agent["tree"].branch(entry_id)
        return {"previous_leaf_id": previous, "leaf_id": entry_id, "summary_entry_id": None}

    def complete(self, call_id, body):
        if self.answer is not None:
            # A scripted one-shot call (agents/calls.py): the script answers from the call's label (the role) and prompt.
            text = self.answer(call_id, body)
            if text is not None:
                return {"text": text, "usage": {"input": 5, "output": 5, "cost_usd": 0}, "stop_reason": "stop", "provider": "openai-codex",
                        "model": body.get("model"), "billing": "subscription", "thinking_level": body.get("effort")}
        return {"text": "Fake answer: " + str(body.get("prompt", ""))[:80], "usage": {"input": 5, "output": 5, "cost_usd": 0}, "stop_reason": "stop",
                "provider": "openai-codex", "model": body.get("model"), "billing": "subscription", "thinking_level": body.get("effort")}

    def forget(self, agent_id):
        return {"removed": self.agents.pop(agent_id, None) is not None}


def http_gateway(backend, token):
    def gateway(operation, body):
        request = Request(f"{backend}/api/internal/pi/{operation}", method="POST", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        with urlopen(request, timeout=120) as response:
            return json.load(response)
    return gateway


def serve(harness, port, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def _route(self):
            path, _, query = self.path.partition("?")
            params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
            if path == "/health":
                return self._send({"status": "ok", "service": "grating-pi", "harness": "fake"})
            if self.headers.get("Authorization") != "Bearer " + token:
                return self._send({"detail": "Authentication required"}, 401)
            parts = path.strip("/").split("/")
            if parts == ["v1", "status"]:
                return self._send(harness.status())
            if parts == ["v1", "live"]:
                ids = params.get("ids", "").split(",")
                return self._send({i: harness.live[i] for i in ids if i in harness.live})
            if len(parts) == 3 and parts[:2] == ["v1", "complete"]:
                return self._send(harness.complete(parts[2], self._body()))
            if len(parts) >= 3 and parts[:2] == ["v1", "agents"]:
                agent_id = parts[2]
                sub = parts[3] if len(parts) > 3 else None
                if sub is None and self.command == "GET":
                    value = harness.view(agent_id, int(params.get("after", 0))); return self._send(value, 200 if value else 404)
                if sub is None and self.command == "DELETE":
                    return self._send(harness.forget(agent_id))
                if sub == "runs":
                    return self._send(harness.submit(agent_id, self._body()))
                if sub == "control":
                    return self._send(harness.control(agent_id, self._body().get("action")))
                if sub == "leaf":
                    return self._send(harness.set_leaf(agent_id, self._body().get("entry_id")))
                if sub in {"tree", "entries", "context"}:
                    value = harness.session(agent_id, sub, params); return self._send(value, 200 if value else 404)
            return self._send({"detail": "not found"}, 404)

        def do_GET(self):
            try: self._route()
            except Exception as exc: self._send({"detail": str(exc)}, 400)
        do_POST = do_DELETE = do_GET

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("GRATING_PI_PORT", 8768)))
    parser.add_argument("--workspace-url", default=os.environ.get("GRATING_PI_WORKSPACE_URL", "http://127.0.0.1:8765"))
    args = parser.parse_args(argv)
    token = Path(os.environ["GRATING_PI_TOKEN_FILE"]).read_text().strip()
    harness = FakeHarness(http_gateway(args.workspace_url, token))
    def notify(ids):
        request = Request(f"{args.workspace_url}/api/internal/pi/notify", method="POST", data=json.dumps({"agent_ids": ids}).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        urlopen(request, timeout=10).read()
    harness.notify = notify
    server = serve(harness, args.port, token)
    print(f"fake harness on http://127.0.0.1:{args.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
