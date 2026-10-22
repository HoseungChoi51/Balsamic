#!/usr/bin/env python3
"""Lead-agent evals: the failures of the readiness audits and rehearsals as scenarios that can be run again.

Each scenario starts a campaign in a workspace of its own run (create_app on a temporary directory, served on a uvicorn
thread), talks to it as the researcher does (commands through the bus), and grades what happened from the store.

  uv run python scripts/run_lead_evals.py --fake                         # plumbing only: the scripted harness, no model
  uv run python scripts/run_lead_evals.py --scenarios S3 --repeats 3     # the real harness on the dev profile's model
  uv run python scripts/run_lead_evals.py --model deepseek/deepseek-v4-flash:low --suite-cap 5
  uv run python scripts/run_lead_evals.py --source ../balsamic-a7e89b8 --record-baseline   # another checkout's code

Real runs call a model and cost money. See evals/lead/README.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "evals" / "lead"
QUADRATIC = {"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}
# Campaign set-ups a scenario starts from: the problem defined by its task (the gate open), or a campaign still being formulated.
PRESETS = {
    "quadratic": {"objective": "Find a better optimizer for this bounded continuous problem", "tasks": [QUADRATIC], "compute_budget_seconds": 600},
    "formulating": {"objective": "Design a grating deflector with higher first-order efficiency"},
}
ACTIVE = {"queued", "submitted", "running"}
TOOL_RESULT_BYTES = 256 * 1024
# A fake turn's waits are scaled down: the scripted harness answers at once and the plumbing is what is checked.
FAKE_TIME_SCALE = 0.02


def serialized_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_scenarios(directory, selected=None):
    scenarios = [json.loads(path.read_text()) for path in sorted(Path(directory).glob("*.json"))]
    if selected:
        wanted = [item.strip() for item in selected.split(",") if item.strip()]
        scenarios = [s for s in scenarios if any(s["id"] == w or s["id"].split("-", 1)[0] == w for w in wanted)]
    return scenarios


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def parse_model(text):
    """provider/model[:effort] as agent.activate's model."""
    if not text:
        return None
    provider, _, rest = text.partition("/")
    model, _, effort = rest.partition(":")
    if not provider or not model:
        raise SystemExit("--model is provider/model[:effort]")
    return {"provider": provider, "model": model, **({"effort": effort} if effort else {})}


def read_secrets(path):
    """KEY=value lines, as scripts/dev-stack passes them to the harness only."""
    values = {}
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value
    return values


def git_commit(directory):
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=directory, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class Turn:
    """What a scripted lead turn can do in --fake mode: call tools through the gateway, remember across turns, reply."""
    def __init__(self, agent, run, tools, store):
        self.agent_id, self.role, self.text = agent["id"], (agent.get("spec") or {}).get("role"), run["text"]
        self.memory = agent.setdefault("memory", {})
        self._tools, self.store = tools, store
        self.notice = "[Platform notice." in self.text

    def call(self, name, **arguments):
        return self._tools(name, arguments)

    def finish(self, report, summary="replied", disposition="complete"):
        """yield_work, then the reply; a refused yield_work leaves the turn without a checkpoint, as a model's would."""
        self.call("yield_work", disposition=disposition, summary=summary, report=report, evidence_ids=[])
        return report


class Stack:
    """The workspace on a uvicorn thread and a harness: the real one as a subprocess, or the scripted fake in this process."""
    def __init__(self, root, *, fake, source, profile, secrets_file, log):
        self.root, self.fake, self.source, self.profile, self.log = Path(root), fake, Path(source), profile, log
        self.secrets_file = secrets_file
        self.fake_play = None   # the current scenario's scripted turns (--fake)
        self.saved_env = {}

    def _env(self, **values):
        for key, value in values.items():
            self.saved_env.setdefault(key, os.environ.get(key))
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(24)
        self.token_file = self.root / "pi.token"
        self.token_file.write_text(token)
        self.token = token
        self.pi_port = free_port()
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(128)
        self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        # The workspace reads these per call; the harness gets its own environment.
        self._env(GRATING_PI_TOKEN_FILE=str(self.token_file), GRATING_PI_URL=f"http://127.0.0.1:{self.pi_port}",
                  GRATING_LLM_ENABLED="true", GRATING_LLM_DISABLED="false",
                  GRATING_PI_PROFILE=None if self.fake else str(self.profile),
                  GRATING_PI_PROVIDER="openai-codex" if self.fake else None)
        if str(self.source / "src") not in sys.path:
            sys.path.insert(0, str(self.source / "src"))
        import uvicorn
        from balsamic.app import create_app
        self.app = create_app(self.root / "workspace", start_workers=True)
        self.workspace = self.app.state.workspace
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        self.sock = sock
        deadline = time.monotonic() + 30
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The workspace did not start")
            time.sleep(.05)
        import httpx
        self.http = httpx.Client(base_url=self.base, timeout=60)
        self.harness = self._start_fake() if self.fake else self._start_real()
        return self

    def _start_fake(self):
        sys.path.insert(0, str(REPO / "tests"))
        from fake_harness import FakeHarness, http_gateway, serve
        gateway = http_gateway(self.base, self.token)

        def play(agent, run, tools):
            script = self.fake_play or default_fake
            return script(Turn(agent, run, tools, self.workspace.store))
        harness = FakeHarness(gateway, script=play)

        def notify(ids):
            self.http.post("/api/internal/pi/notify", json={"agent_ids": ids}, headers={"Authorization": "Bearer " + self.token})
        harness.notify = notify
        self.fake_server = serve(harness, self.pi_port, self.token)
        return harness

    def _start_real(self):
        server = self.source / "agent-harness" / "dist" / "server.js"
        if not server.exists():
            raise SystemExit(f"{server} is missing: run (cd agent-harness && npm ci --ignore-scripts && npm run build) in {self.source}")
        env = {**os.environ, **read_secrets(self.secrets_file), "GRATING_PI_TOKEN_FILE": str(self.token_file),
               "GRATING_PI_DIRECTORY": str(self.root / "pi"), "GRATING_PI_PORT": str(self.pi_port),
               "GRATING_PI_WORKSPACE_URL": self.base, "GRATING_PI_PROFILE": str(self.profile)}
        self.harness_log = (self.root / "harness.log").open("w")
        self.process = subprocess.Popen(["node", str(server)], env=env, stdout=self.harness_log, stderr=subprocess.STDOUT, start_new_session=True)
        import httpx
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{self.pi_port}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"The harness did not start; see {self.root / 'harness.log'}")
            time.sleep(.2)
        return self.process

    def __exit__(self, *exc):
        if self.fake:
            self.fake_server.shutdown()
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.harness_log.close()
        self.server.should_exit = True
        self.thread.join(timeout=20)
        self.sock.close()
        self.http.close()
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def command(self, campaign_id, operation, payload, *, origin=None, expect_ok=True):
        campaign = self.workspace.store.get(campaign_id, "campaign") if operation != "campaign.create" else {"version": 0}
        body = {"id": "eval_" + uuid.uuid4().hex, "campaign_id": campaign_id, "operation": operation,
                "expected_revision": campaign["version"], "payload": payload, **({"origin": origin} if origin else {})}
        response = self.http.post("/api/v1/commands", json=body)
        if expect_ok and response.status_code != 200:
            raise RuntimeError(f"{operation} was refused ({response.status_code}): {response.text[:500]}")
        return response.json()


def default_fake(turn):
    """The scripted harness's own turn: read the campaign, reply, end."""
    turn.call("campaign_inspect")
    return turn.finish(f"Fake lead: I read your request ({turn.text[:60]}) and did nothing else.")


class Context:
    """One scenario run: its campaign, the steps taken, and the store to grade from."""
    def __init__(self, stack, scenario, campaign_id, scale):
        self.stack, self.scenario, self.campaign_id, self.scale = stack, scenario, campaign_id, scale
        self.store, self.workspace = stack.workspace.store, stack.workspace
        self.thread_id = "thread_main_" + campaign_id
        self.vars, self.timeline, self.timed_out = {"campaign_id": campaign_id}, [], False
        self.poll = 0.5 if scale >= 1 else 0.1
        self.started = time.monotonic()

    @property
    def lead_id(self):
        return (self.workspace.pi.configuration(self.campaign_id) or {}).get("lead_id")

    def runs(self):
        return self.store.list("agent_run", self.campaign_id)

    def lead_runs(self):
        return [r for r in self.runs() if r["agent_id"] == self.lead_id]

    def agents(self):
        return {a["id"]: a for a in self.store.list("agent_session", self.campaign_id)}

    def lead_replies(self):
        return [m for m in self.store.list("message", self.campaign_id)
                if m.get("role") == "assistant" and m.get("agent_id") == self.lead_id and m.get("origin") in {"lead", "autopilot"}]

    def reply(self):
        replies = self.lead_replies()
        return replies[-1]["content"] if replies else ""

    def agent_commands(self):
        return [c for c in self.store.list("work_command", self.campaign_id) if (c.get("origin") or {}).get("agent_id")]

    def receipts(self):
        return self.store.list("agent_tool_receipt", self.campaign_id)

    def usage(self):
        with self.store.connection() as db:
            row = db.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd),0), COALESCE(SUM(charged_usd),0), COALESCE(SUM(input),0), COALESCE(SUM(output),0), "
                             "COALESCE(SUM(cache_read),0), COALESCE(SUM(cache_write),0) FROM llm_usage WHERE campaign_id=?", (self.campaign_id,)).fetchone()
        return dict(zip(("model_calls", "cost_usd", "charged_usd", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"), row))

    def format(self, text):
        return text.format(**self.vars) if isinstance(text, str) else text


# Steps -------------------------------------------------------------------------------------------------------
def step_say(ctx, text):
    text = ctx.format(text)
    receipt = ctx.stack.command(ctx.campaign_id, "agent.message", {"message": text, "thread_id": ctx.thread_id}, origin={"thread_id": ctx.thread_id})
    ctx.vars["last_run_id"] = "pi_run_" + receipt["id"]
    return {"say": text, "run_id": ctx.vars["last_run_id"]}


def step_wait(ctx, what, timeout_s=600):
    config = lambda: ctx.workspace.pi.configuration(ctx.campaign_id) or {}
    if what == "seconds":
        time.sleep(timeout_s * ctx.scale)
        return {"waited_s": round(timeout_s * ctx.scale, 2)}
    conditions = {
        # The lead reported the request fulfilled and nothing of the campaign's agents is still queued or at work.
        "request_closed": lambda: not config().get("request_open") and not any(r["status"] in ACTIVE for r in ctx.runs()),
        "idle": lambda: not any(r["status"] in ACTIVE for r in ctx.runs()),
        "trials_settled": lambda: not any(t["status"] in {"queued", "running", "pausing"} for t in ctx.store.list("trial", ctx.campaign_id)),
    }
    if what not in conditions:
        raise ValueError(f"Unknown wait {what}")
    deadline = time.monotonic() + timeout_s
    settled = 0
    while time.monotonic() < deadline:
        settled = settled + 1 if conditions[what]() else 0
        if settled >= 3:   # three polls in a row: a notice queued right after a turn has had time to appear
            return {"wait": what, "after_s": round(time.monotonic() - ctx.started, 1)}
        time.sleep(ctx.poll)
    ctx.timed_out = True
    return {"wait": what, "timed_out": True}


def step_seed(ctx, name):
    seeds = load_module(EVALS / "seeds.py", "lead_eval_seeds")
    values = getattr(seeds, name)(ctx) or {}
    ctx.vars.update(values)
    return {"seed": name, **{key: str(value)[:200] for key, value in values.items()}}


def step_answer_latest_question(ctx, text):
    pending = [q for q in ctx.store.list("agent_question", ctx.campaign_id) if q["status"] == "pending"]
    if not pending:
        return {"answer": None, "note": "no pending question"}
    question = pending[-1]
    receipt = ctx.stack.command(ctx.campaign_id, "agent.message", {"message": ctx.format(text), "question_id": question["id"], "thread_id": ctx.thread_id},
                                origin={"thread_id": ctx.thread_id})
    return {"answered": question["id"], "run_id": "pi_run_" + receipt["id"]}


def step_approve_latest_decision(ctx, comment=""):
    pending = [d for d in ctx.store.list("decision", ctx.campaign_id) if d.get("status") == "pending"]
    if not pending:
        return {"approved": None, "note": "no pending decision"}
    decision = pending[-1]
    ctx.stack.command(ctx.campaign_id, "decision.resolve", {"decision_id": decision["id"], "choice": decision["options"][0]["id"],
                      "comment": comment or "Approved in the eval", "expected_resolution_revision": decision.get("resolution_revision", 0)})
    return {"approved": decision["id"]}


def step_pin(ctx, record_id):
    record_id = ctx.format(record_id)
    ctx.stack.command(ctx.campaign_id, "thread.pin", {"thread_id": ctx.thread_id, "record_id": record_id}, origin={"thread_id": ctx.thread_id})
    return {"pinned": record_id}


def run_step(ctx, step):
    if "say" in step:
        return step_say(ctx, step["say"])
    if "wait" in step:
        return step_wait(ctx, step["wait"], step.get("timeout_s", step.get("seconds", 600)))
    if "seed" in step:
        return step_seed(ctx, step["seed"])
    if "answer_latest_question" in step:
        return step_answer_latest_question(ctx, step["answer_latest_question"])
    if "approve_latest_decision" in step:
        return step_approve_latest_decision(ctx, step.get("approve_latest_decision") or "")
    if "pin" in step:
        return step_pin(ctx, step["pin"])
    raise ValueError(f"Unknown step {step}")


# Checks: each returns (passed, detail) from the store --------------------------------------------------------
def _operations(value):
    return [value] if isinstance(value, str) else list(value)


def check_commands_exactly(ctx, arg):
    count = sum(c["request"]["operation"] in _operations(arg["operation"]) for c in ctx.agent_commands())
    return count == arg["count"], f"{count} {arg['operation']}"


def check_commands_at_least(ctx, arg):
    count = sum(c["request"]["operation"] in _operations(arg["operation"]) for c in ctx.agent_commands())
    return count >= arg["count"], f"{count} {arg['operation']}"


def check_no_commands(ctx, arg):
    found = [c["request"]["operation"] for c in ctx.agent_commands() if c["request"]["operation"] in arg]
    return not found, ", ".join(found) or "none"


def check_max_commands(ctx, arg):
    count = len(ctx.agent_commands())
    return count <= arg, f"{count} agent commands"


def check_max_lead_turns(ctx, arg):
    count = len(ctx.lead_runs())
    return count <= arg, f"{count} lead turns"


def check_max_continue_turns(ctx, arg):
    count = sum(r["id"].startswith("pi_continue_") for r in ctx.runs())
    return count <= arg, f"{count} pi_continue turns"


def check_no_model_calls(ctx, arg):
    calls = ctx.usage()["model_calls"]
    return calls == 0, f"{calls} model calls"


def check_cost_usd_max(ctx, arg):
    cost = ctx.usage()["cost_usd"]
    return cost <= arg, f"${cost:.4f}"


def _refusals(ctx):
    """Every refused tool call of the campaign's agents (a refused command is also a command_rejection; counted once here)."""
    texts = [str((r.get("result") or {}).get("error") or "") for r in ctx.receipts() if isinstance(r.get("result"), dict)]
    return [text for text in texts if text]


def check_no_refusal_containing(ctx, arg):
    found = [text for text in _refusals(ctx) if arg.lower() in text.lower()]
    return not found, f"{len(found)} refusals" + (f": {found[0][:160]}" if found else "")


def check_max_tool_result_bytes(ctx, arg):
    largest = max([serialized_bytes(r.get("result")) for r in ctx.receipts()] or [0])
    return largest <= arg, f"largest tool result {largest} bytes"


def check_reply_contains_any(ctx, arg):
    reply = ctx.reply().lower()
    found = [text for text in arg if text.lower() in reply]
    return bool(found), f"found {found}" if found else f"none of {arg} in the reply ({len(reply)} characters)"


def check_reply_contains_none(ctx, arg):
    reply = ctx.reply().lower()
    found = [text for text in arg if text.lower() in reply]
    return not found, f"found {found}" if found else "none"


def check_reply_links_page(ctx, arg):
    return arg in ctx.reply(), f"{arg} {'linked' if arg in ctx.reply() else 'not linked'}"


def check_reply_matches(ctx, arg):
    match = re.search(arg, ctx.reply())
    return bool(match), f"matched {match.group(0)!r}" if match else f"no match for {arg}"


def check_no_researcher_question(ctx, arg):
    questions = [q for q in ctx.store.list("agent_question", ctx.campaign_id) if not q["id"].startswith("pi_stalled_")]
    return not questions, f"{len(questions)} questions"


def check_request_closed(ctx, arg):
    open_ = bool((ctx.workspace.pi.configuration(ctx.campaign_id) or {}).get("request_open"))
    return open_ is not bool(arg), "request open" if open_ else "request closed"


def check_no_failed_runs(ctx, arg):
    failed = [r["id"] for r in ctx.runs() if r["status"] == "failed"]
    return not failed, f"{len(failed)} failed runs" + (f": {failed[0]}" if failed else "")


def check_last_state_contains(ctx, arg):
    """The state block the lead's last turn was given (saved on its run) says this: what the platform told it, not what it said."""
    runs = [r for r in ctx.lead_runs() if r.get("turn_state")]
    text = runs[-1]["turn_state"]["text"] if runs else ""
    return arg in text, "found" if arg in text else ("no state block saved" if not runs else f"not in the last state block ({len(text)} characters)")


def check_records_at_least(ctx, arg):
    count = len(ctx.store.list(arg["kind"], ctx.campaign_id))
    return count >= arg["count"], f"{count} {arg['kind']}"


def check_records_at_most(ctx, arg):
    count = len(ctx.store.list(arg["kind"], ctx.campaign_id))
    return count <= arg["count"], f"{count} {arg['kind']}"


CHECKS = {name.removeprefix("check_"): value for name, value in globals().items() if name.startswith("check_")}


def metrics(ctx):
    agents = ctx.agents()
    runs = ctx.runs()
    page_turns = {}
    for run in runs:
        role = (agents.get(run["agent_id"]) or {}).get("role")
        if role and role != "lead":
            page_turns[role] = page_turns.get(role, 0) + 1
    operations = {}
    for command in ctx.agent_commands():
        operation = command["request"]["operation"]
        operations[operation] = operations.get(operation, 0) + 1
    return {"lead_turns": len(ctx.lead_runs()), "continue_turns": sum(r["id"].startswith("pi_continue_") for r in runs),
            "other_turns": page_turns, "failed_runs": sum(r["status"] == "failed" for r in runs), "agent_commands": operations,
            "refusals": len(_refusals(ctx)), "max_tool_result_bytes": max([serialized_bytes(r.get("result")) for r in ctx.receipts()] or [0]),
            **ctx.usage(), "seconds": round(time.monotonic() - ctx.started, 1)}


def transcript(ctx, result):
    """Messages, run inputs and a summary of tool receipts, for reading why a check failed."""
    agents = ctx.agents()
    lines = [f"# {ctx.scenario['id']} (repeat {result['repeat']})", "", f"- Campaign: `{ctx.campaign_id}`", f"- Status: **{result['status']}**",
             f"- Source: {ctx.scenario.get('source', '')}", "", "## Steps", ""]
    lines += [f"- `{json.dumps(item, ensure_ascii=False)[:400]}`" for item in ctx.timeline]
    lines += ["", "## Checks", ""]
    lines += [f"- {'PASS' if c['passed'] else 'FAIL'} `{c['name']}` {json.dumps(c['arg'], ensure_ascii=False)}: {c['detail']}" for c in result["checks"]]
    lines += ["", "## Metrics", "", "```json", json.dumps(result["metrics"], indent=2), "```", "", "## Runs", ""]
    for run in ctx.runs():
        role = (agents.get(run["agent_id"]) or {}).get("role", "?")
        lines += [f"### {role} · `{run['id']}` · {run['status']}", "", "```", run["input"][:1500], "```", ""]
        state = (run.get("turn_state") or {}).get("text")
        if state:
            lines += ["State block:", "", "```", state, "```", ""]
        if run.get("error"):
            lines += [f"Error: {run['error'][:500]}", ""]
    lines += ["## Messages", ""]
    for message in ctx.store.list("message", ctx.campaign_id):
        who = message.get("agent_role") or message.get("origin") or message.get("role")
        lines += [f"**{message.get('role')} · {who}** ({message.get('created_at')})", "", message.get("content", "")[:4000], ""]
    lines += ["## Tool receipts", ""]
    intents = {i["id"].removeprefix("intent_"): i for i in ctx.store.list("agent_tool_intent", ctx.campaign_id)}
    for receipt in ctx.receipts():
        role = (agents.get(receipt["agent_id"]) or {}).get("role", "?")
        args = (intents.get(receipt["id"]) or {}).get("arguments")
        error = (receipt.get("result") or {}).get("error") if isinstance(receipt.get("result"), dict) else None
        lines.append(f"- {role} `{receipt['tool']}` {json.dumps(args, ensure_ascii=False)[:240] if args else ''}"
                     f" → {serialized_bytes(receipt.get('result'))} bytes" + (f" **refused**: {str(error)[:240]}" if error else ""))
    return "\n".join(lines) + "\n"


def run_scenario(stack, scenario, repeat, *, model, scale, fakes):
    setup = scenario.get("setup", {})
    campaign_id = f"eval_{scenario['id'].split('-', 1)[0].lower()}_r{repeat}_{uuid.uuid4().hex[:6]}"
    preset = dict(PRESETS[setup.get("preset", "quadratic")])
    stack.command(campaign_id, "campaign.create", {"name": f"Eval {scenario['id']} #{repeat}", **preset, "llm_budget_usd": setup.get("llm_budget_usd", 0.3)})
    ctx = Context(stack, scenario, campaign_id, scale)
    stack.fake_play = fakes.get(scenario["id"]) if fakes is not None else None
    result = {"repeat": repeat, "campaign_id": campaign_id, "checks": [], "error": None}
    try:
        for name in setup.get("seeds", []):
            ctx.timeline.append(step_seed(ctx, name))
        stack.command(campaign_id, "agent.activate", {**({"model": model} if model else {})})
        for step in scenario["steps"]:
            ctx.timeline.append(run_step(ctx, step))
    except Exception as exc:   # a broken step is a failed run, not a crashed suite
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
    for check in scenario["checks"]:
        (name, arg), = check.items()
        try:
            passed, detail = CHECKS[name](ctx, arg)
        except Exception as exc:
            passed, detail = False, f"check failed to run: {type(exc).__name__}: {exc}"
        result["checks"].append({"name": name, "arg": arg, "passed": bool(passed), "detail": detail})
    result["metrics"] = metrics(ctx)
    result["timed_out"] = ctx.timed_out
    result["passed"] = not result["error"] and all(c["passed"] for c in result["checks"])
    result["status"] = "pass" if result["passed"] else "xfail" if scenario.get("known_failure") else "fail"
    stop(stack, ctx)
    return result, ctx


def stop(stack, ctx):
    """Stop the scenario's team and its runs, so nothing of it spends while the next one runs."""
    try:
        config = stack.workspace.pi.configuration(ctx.campaign_id)
        if config and config.get("enabled") and config["status"] == "running":
            stack.command(ctx.campaign_id, "agent.control", {"action": "stop", "expected_control_revision": config["control_revision"]}, expect_ok=False)
        for trial in stack.workspace.store.list("trial", ctx.campaign_id):
            if trial["status"] in {"queued", "running"}:
                stack.command(ctx.campaign_id, "trial.control", {"trial_id": trial["id"], "action": "stop",
                              "expected_control_revision": trial.get("control_revision", 0)}, expect_ok=False)
    except Exception:
        pass


def summarize(scenario, repeats):
    passes = sum(r["passed"] for r in repeats)
    scoring = scenario.get("scoring", "all")
    passed = passes == len(repeats) if scoring == "all" else passes > 0
    keys = ("lead_turns", "continue_turns", "model_calls", "cost_usd", "cache_read_tokens", "input_tokens", "seconds")
    mean = {key: round(statistics.fmean(r["metrics"][key] for r in repeats), 4) for key in keys} if repeats else {}
    status = "pass" if passed else "xfail" if scenario.get("known_failure") else "fail"
    return {"id": scenario["id"], "source": scenario.get("source"), "scoring": scoring, "known_failure": scenario.get("known_failure"),
            "passes": passes, "repeats": len(repeats), "passed": passed, "status": status, "metrics_mean": mean, "runs": repeats}


def summary_markdown(results, baseline=None):
    lines = [f"# Lead evals · {results['mode']} · {results['commit']}", "",
             f"- Started {results['started_at']}, {results['seconds']} s; model {results['model'] or 'profile default'}",
             f"- Model use: ${results['cost_usd']:.4f} (suite cap ${results['suite_cap']:.2f})", ""]
    header = "| Scenario | Status | Passes | Lead turns | pi_continue | Model calls | Cost | cacheRead |"
    rule = "|---|---|---|---|---|---|---|---|"
    if baseline:
        header += " Baseline |"; rule += "---|"
    lines += [header, rule]
    for row in results["scenarios"]:
        m = row["metrics_mean"]
        line = (f"| {row['id']} | {row['status']} | {row['passes']}/{row['repeats']} ({row['scoring']}) | {m.get('lead_turns', 0):g} | "
                f"{m.get('continue_turns', 0):g} | {m.get('model_calls', 0):g} | ${m.get('cost_usd', 0):.4f} | {m.get('cache_read_tokens', 0):g} |")
        if baseline:
            old = baseline.get("scenarios", {}).get(row["id"])
            line += (" — |" if not old else f" {old['passes']}/{old['repeats']}{' **regressed**' if old['passed'] and not row['passed'] else ''} |")
        lines.append(line)
    skipped = results.get("skipped") or []
    if skipped:
        lines += ["", "Skipped at the suite cap: " + ", ".join(skipped)]
    failed = [(row, run, check) for row in results["scenarios"] for run in row["runs"] for check in run["checks"] if not check["passed"]]
    errors = [(row, run) for row in results["scenarios"] for run in row["runs"] if run["error"]]
    if failed or errors:
        lines += ["", "## Failed checks", ""]
        lines += [f"- {row['id']} #{run['repeat']}: `{check['name']}` — {check['detail']}" for row, run, check in failed]
        lines += [f"- {row['id']} #{run['repeat']}: error — {run['error'][:300]}" for row, run in errors]
    known = [row for row in results["scenarios"] if row["known_failure"]]
    if known:
        lines += ["", "## Known failures", ""] + [f"- {row['id']}: {row['known_failure']}" for row in known]
    return "\n".join(lines) + "\n"


def baseline_record(results):
    return {"commit": results["commit"], "mode": results["mode"], "model": results["model"], "recorded_at": results["started_at"],
            "scenarios": {row["id"]: {key: row[key] for key in ("passes", "repeats", "passed", "status", "metrics_mean")} for row in results["scenarios"]}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fake", action="store_true", help="the scripted harness (tests/fake_harness.py): plumbing only, no model calls")
    parser.add_argument("--model", help="provider/model[:effort] for agent.activate; default: the dev profile's")
    parser.add_argument("--scenarios", help="comma-separated ids or prefixes (S3, S4-guidance-...)")
    parser.add_argument("--repeats", type=int, help="runs per scenario (default: the scenario's own)")
    parser.add_argument("--suite-cap", type=float, default=5.0, help="stop starting scenarios once the suite's model use reaches this many dollars")
    parser.add_argument("--out", type=Path, help="output directory (default runs/evals/<timestamp>)")
    parser.add_argument("--source", type=Path, default=REPO, help="checkout whose workspace and harness are run (default: this one)")
    parser.add_argument("--profile", type=Path, help="Pi dev profile (default <source>/agent-harness/profiles/dev)")
    parser.add_argument("--secrets", default=os.environ.get("BALSAMIC_SECRETS", str(Path.home() / ".config/balsamic/secrets.env")))
    parser.add_argument("--time-scale", type=float, help=f"factor on 'seconds' waits (default 1, or {FAKE_TIME_SCALE} with --fake)")
    parser.add_argument("--record-baseline", nargs="?", const="", help="also write the summary to evals/lead/baselines/<commit>.json (or the path given)")
    parser.add_argument("--compare", type=Path, help="a baseline file to compare with in summary.md")
    args = parser.parse_args(argv)
    scenarios = load_scenarios(EVALS / "scenarios", args.scenarios)
    if not scenarios:
        raise SystemExit("No scenario matches")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or REPO / "runs" / "evals" / (stamp + ("-fake" if args.fake else ""))
    (out / "transcripts").mkdir(parents=True, exist_ok=True)
    model = parse_model(args.model)
    scale = args.time_scale if args.time_scale is not None else FAKE_TIME_SCALE if args.fake else 1.0
    fakes = load_module(EVALS / "fakes.py", "lead_eval_fakes").FAKES if args.fake else None
    source = args.source.resolve()
    results = {"mode": "fake" if args.fake else "real", "commit": git_commit(source), "source": str(source), "model": args.model,
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "suite_cap": args.suite_cap, "scenarios": [], "skipped": []}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="lead-evals-") as root, \
            Stack(root, fake=args.fake, source=source, profile=args.profile or source / "agent-harness" / "profiles" / "dev",
                  secrets_file=args.secrets, log=print) as stack:
        spent = 0.0
        for scenario in scenarios:
            repeats = []
            for repeat in range(1, (args.repeats or scenario.get("repeats", 1)) + 1):
                if spent >= args.suite_cap:
                    results["skipped"].append(f"{scenario['id']} #{repeat}")
                    continue
                result, ctx = run_scenario(stack, scenario, repeat, model=model, scale=scale, fakes=fakes)
                spent += result["metrics"]["cost_usd"]
                (out / "transcripts" / f"{scenario['id']}-r{repeat}.md").write_text(transcript(ctx, result))
                print(f"{scenario['id']} #{repeat}: {result['status']}" + (f" ({result['error']})" if result["error"] else ""), flush=True)
                repeats.append(result)
            if repeats:
                results["scenarios"].append(summarize(scenario, repeats))
        if not args.fake:
            # Kept beside the results: the harness log says why a turn failed on the provider's side.
            log = Path(root) / "harness.log"
            if log.exists():
                (out / "harness.log").write_text(log.read_text()[-200000:])
    results["seconds"] = round(time.monotonic() - started, 1)
    results["cost_usd"] = round(sum(run["metrics"]["cost_usd"] for row in results["scenarios"] for run in row["runs"]), 6)
    baseline = json.loads(args.compare.read_text()) if args.compare else None
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out / "summary.md").write_text(summary_markdown(results, baseline))
    if args.record_baseline is not None:
        path = Path(args.record_baseline) if args.record_baseline else EVALS / "baselines" / f"{results['commit']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(baseline_record(results), indent=2) + "\n")
        print(f"baseline: {path}")
    print(f"results: {out / 'summary.md'}")
    failed = [row["id"] for row in results["scenarios"] if row["status"] == "fail"]
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
