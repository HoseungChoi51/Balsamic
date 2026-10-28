#!/usr/bin/env python3
"""Lead-agent evals: the failures of the readiness audits and rehearsals as scenarios that can be run again.

Each scenario starts a campaign in a workspace of its own run (create_app on a temporary directory, served on a uvicorn
thread), talks to it as the researcher does (commands through the bus), and grades what happened from the store.

  uv run python scripts/run_lead_evals.py --fake                         # plumbing only: the scripted harness, no model
  uv run python scripts/run_lead_evals.py --scenarios S3 --repeats 3     # the real harness on the dev profile's model
  uv run python scripts/run_lead_evals.py --model deepseek/deepseek-v4-flash:low --suite-cap 5
  uv run python scripts/run_lead_evals.py --source ../balsamic-a7e89b8 --record-baseline   # another checkout's code
  uv run python scripts/run_lead_evals.py --preset deflector_2d --record-baseline          # the scenarios that support another problem

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
    # The traps (J1): a problem whose cheap fidelity has a spurious peak, and a 0/1 knapsack an exact algorithm solves.
    "fidelity_trap": {"objective": "Find the best design for this two-dimensional problem", "compute_budget_seconds": 600,
                      "tasks": [{"name": "Trap", "problem_id": "fidelity_trap", "configuration": {}, "fidelity": {"resolution": "coarse"}}]},
    "knapsack": {"objective": "Choose the items of most total value that fit the capacity", "compute_budget_seconds": 600,
                 "tasks": [{"name": "Knapsack", "problem_id": "knapsack_dp", "configuration": {}}]},
    # A second problem (J2): the 2D deflector at its installed example's configuration (MEENT, binary), and a declared problem
    # from another field, the flow reactor, made from its confirmed charter (no installed evaluator, so nothing runs).
    "deflector_2d": {"objective": "Find a better optimizer for this two-dimensional beam deflector", "compute_budget_seconds": 600,
                     "delegated_trial_seconds": 60, "example": "flrl_2d_deflector_1050nm_75deg"},
    "reactor": {"objective": "Find the conditions of highest isolated yield for this flow reaction", "compute_budget_seconds": 600,
                "validation_reserve_seconds": 0, "charter": "flow-reactor.json"},
    # Charter to results (G2): a small permutation charter whose declared problem no installed library provides yet, so the
    # methods are built in a coding workspace and Balsamic installs, adopts, binds and starts them.
    "baking_order": {"objective": "Find the order of bakes that is least late", "compute_budget_seconds": 7200,
                     "validation_reserve_seconds": 0, "charter": "baking-order.json"},
    # The set-up from the researcher's words (track P): the same campaigns before their charter, with their question only, so
    # the gate stays closed until a charter is confirmed and its tasks installed.
    "baking_words": {"objective": "Find the order of bakes that is least late", "compute_budget_seconds": 7200, "validation_reserve_seconds": 0},
    "reactor_words": {"objective": "Find the conditions of highest isolated yield for this flow reaction", "compute_budget_seconds": 600,
                      "validation_reserve_seconds": 0},
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
    number = lambda path: (int(re.match(r"S(\d+)", path.name).group(1)) if re.match(r"S\d+", path.name) else 10**6, path.name)
    scenarios = [json.loads(path.read_text()) for path in sorted(Path(directory).glob("*.json"), key=number)]
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
        self.campaign_id = agent.get("campaign_id")
        self.memory = agent.setdefault("memory", {})
        self._tools, self.store = tools, store
        self.notice = "[Platform notice." in self.text
        self.continuation = bool(run.get("continuation"))   # the Balsamic extension's one continuation of a turn without yield_work
        self.one_shot = False   # a session's turn; a one-shot role's call is a Call

    def call(self, name, **arguments):
        return self._tools(name, arguments)

    def external(self, tool, arguments, text):
        """An extension tool: blocked unless allowlisted for the role, receipted by the workspace otherwise."""
        return self._tools.external(tool, arguments, text)

    def dialog(self, method, title, **fields):
        return self._tools.dialog(method, title, **fields)

    def finish(self, report, summary="replied", disposition="complete"):
        """yield_work, then the reply; a refused yield_work leaves the turn without a checkpoint, as a model's would."""
        self.call("yield_work", disposition=disposition, summary=summary, report=report, evidence_ids=[])
        return report


class Call:
    """A one-shot role call in --fake mode (agents/calls.py): no tools, one reply. A script answers it by returning a dict (the
    role's result, sent as JSON) or text; .input is the context the backend assembled."""
    notice, continuation = False, False

    def __init__(self, body):
        self.role, self.text = body.get("label"), body.get("prompt") or ""
        self.one_shot, self.memory = True, {}
        try:
            self.input = json.loads(self.text)
        except ValueError:
            self.input = {}

    def call(self, name, **arguments):
        raise RuntimeError(f"A one-shot {self.role} has no tools ({name})")

    def finish(self, report, summary="replied", disposition="complete"):
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
        from fake_harness import STATUS, FakeHarness, http_gateway, serve
        from optimization_framework.agents import tiers
        # The scripted harness's model as the lab's tiers, as a researcher sets them on the Models page: a formulator's model
        # comes from them (problem_import/service.py), and without a dev profile there is none. A campaign's agents follow the
        # tiers only on a dev profile, so they are unchanged.
        defaults = tiers.defaults(dict(STATUS["defaults"]))
        tiers.save(self.workspace.store, tiers.TierSettings(tiers=defaults["tiers"], roles=defaults["roles"]))
        gateway = http_gateway(self.base, self.token)

        def play(agent, run, tools):
            script = self.fake_play or default_fake
            return script(Turn(agent, run, tools, self.workspace.store))
        harness = FakeHarness(gateway, script=play)

        def answer(call_id, body):
            from optimization_framework.agents.calls import ONE_SHOT_ROLES
            if body.get("label") not in ONE_SHOT_ROLES:
                return None
            reply = (self.fake_play or default_fake)(Call(body))
            return reply if isinstance(reply, str) else json.dumps(reply)
        harness.answer = answer

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

    def extensions(self, allowlist):
        """The extension allowlist the next sessions' manifests name (setup.extensions), or the default one."""
        self._env(GRATING_PI_EXTENSIONS=str((self.source / allowlist).resolve()) if allowlist else None)

    def development(self, enabled):
        """Coding workspaces on for a scenario that builds methods (setup.development), as the lab's own setting otherwise.
        The scripted harness has no coding agent, so a --fake run leaves them as they are."""
        key = "GRATING_DEVELOPMENT_ENABLED"
        self.saved_env.setdefault(key, os.environ.get(key))
        self._env(**{key: "true" if enabled and not self.fake else self.saved_env[key]})

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
        # What the researcher did, in order: each action with its kind, the round it belongs to (one return of the researcher
        # to the campaign) and its time since the start. A define step (track P) adds the set-up's own record.
        self.actions, self.round, self.setup = [], 0, None

    def act(self, kind, *, new_round=False):
        self.round += new_round
        self.actions.append({"kind": kind, "round": self.round, "s": round(time.monotonic() - self.started, 2)})

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

    def reply_messages(self):
        """The lead's messages since the researcher's last message: a notice turn after the answer may add one of its own
        ("no change to report"), and the answer is still the answer."""
        asked = max((m.get("created_at") or "" for m in self.store.list("message", self.campaign_id)
                     if m.get("role") == "user" and m.get("origin") == "researcher"), default="")
        replies = sorted(self.lead_replies(), key=lambda m: m.get("created_at") or "")
        return [m for m in replies if (m.get("created_at") or "") >= asked]

    def reply(self):
        """The lead's replies to the researcher's last message, together."""
        return "\n\n".join(m["content"] or "" for m in self.reply_messages())

    def unverified_numbers(self):
        """The numbers agents wrote that none of their evidence holds (K2): on their replies (the yield_work receipts) and on
        the findings they recorded."""
        found = [number for receipt in self.receipts() if receipt.get("tool") == "yield_work" and isinstance(receipt.get("result"), dict)
                 for number in receipt["result"].get("unverified_numbers") or []]
        return found + [number for note in self.store.list("manager_note", self.campaign_id) for number in note.get("unverified_numbers") or []]

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

    def format_value(self, value):
        """format() through the strings of a check's JSON argument."""
        if isinstance(value, dict):
            return {key: self.format_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.format_value(item) for item in value]
        return self.format(value)


# Steps -------------------------------------------------------------------------------------------------------
def step_say(ctx, text):
    text = ctx.format(text)
    receipt = ctx.stack.command(ctx.campaign_id, "agent.message", {"message": text, "thread_id": ctx.thread_id}, origin={"thread_id": ctx.thread_id})
    ctx.vars["last_run_id"] = "pi_run_" + receipt["id"]
    ctx.act("message", new_round=True)
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
        # A comparison report was written and nothing of the campaign's agents is queued or at work: the lead has replied with it.
        "compared": lambda: bool(_commands_of(ctx, "comparison.report")) and not any(r["status"] in ACTIVE for r in ctx.runs()),
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
    ctx.act("answer", new_round=True)
    return {"answered": question["id"], "run_id": "pi_run_" + receipt["id"]}


def step_approve_latest_decision(ctx, comment=""):
    pending = [d for d in ctx.store.list("decision", ctx.campaign_id) if d.get("status") == "pending"]
    if not pending:
        return {"approved": None, "note": "no pending decision"}
    decision = pending[-1]
    ctx.stack.command(ctx.campaign_id, "decision.resolve", {"decision_id": decision["id"], "choice": decision["options"][0]["id"],
                      "comment": comment or "Approved in the eval", "expected_resolution_revision": decision.get("resolution_revision", 0)})
    ctx.act("approve", new_round=True)
    return {"approved": decision["id"]}


def step_pin(ctx, record_id):
    record_id = ctx.format(record_id)
    ctx.stack.command(ctx.campaign_id, "thread.pin", {"thread_id": ctx.thread_id, "record_id": record_id}, origin={"thread_id": ctx.thread_id})
    return {"pinned": record_id}


# The set-up (track P): the researcher takes the problem through the definition gate --------------------------------
REPLY = "Use what you suggest: every number is in my first message."
REPLIES = 3   # the researcher's replies to a lead that has not finished the note, before the step gives up


def setup_imports(ctx):
    """The campaign's formulators: an import made by each adoption of its note, and one a request on its charter started."""
    store, note_id = ctx.store, "note_" + ctx.campaign_id
    found = {row["id"]: row for row in store.list("problem_import") if (row.get("notes") or "").startswith(f"Adopted from problem note {note_id} ")}
    try:
        note = store.get(note_id, "problem_note")
        charter = store.get(note["charter_id"], "problem_charter") if note.get("charter_id") else None
    except KeyError:
        charter = None
    if charter and charter.get("import_id") and charter["import_id"] not in found:
        try:
            found[charter["import_id"]] = store.get(charter["import_id"], "problem_import")
        except KeyError:
            pass
    return list(found.values())


def setup_busy(ctx):
    """Whether an agent of the campaign or one of its formulators is at work (a formulator's status is pulled first)."""
    if any(run["status"] in ACTIVE for run in ctx.runs()):
        return True
    imports = getattr(ctx.workspace, "problem_imports", None)
    for record in setup_imports(ctx):
        try:
            record = imports.sync(record["id"]) if imports is not None else record
        except (KeyError, ValueError):
            continue
        if record["status"] == "running":
            return True
    return False


def setup_charter_step(ctx, note, reply):
    """On the charter, what "Confirm and set the tasks" needs first, as the page asks it: the open questions answered (with
    their recommended option), the assumptions accepted; then the confirmation, which installs the tasks. A blocking finding the
    page does not settle stops the step."""
    from balsamic.evolution.stages import _charter_of
    record = _charter_of(ctx.store, note)
    if record is None:
        failed = [row for row in setup_imports(ctx) if row["status"] in {"failed", "stopped"}]
        raise RuntimeError("No charter to confirm" + (f": the formulator {failed[-1]['status']} ({failed[-1].get('error')})" if failed else ""))
    view = ctx.workspace.charters.view(record["id"])
    path = f"/api/v1/problem-charters/{record['id']}"
    open_questions = [q for q in view["charter"]["questions"] if q.get("answer") is None and not q.get("sent")]
    if open_questions:
        for question in open_questions:
            answer = (question.get("options") or [reply])[0]
            ctx.stack.http.post(path + "/answers", json={"expected_revision": ctx.workspace.charters.get(record["id"])["revision"],
                                "question_id": question["id"], "answer": answer}).raise_for_status()
            ctx.act("answer_charter")
        return ["answer_charter"] * len(open_questions)
    blocking = [row for row in view["findings"] if row["severity"] == "blocking" and row["code"] != "question.open" and not row.get("waived")]
    if any(row["code"] == "assumption.unaccepted" for row in blocking):
        ctx.stack.http.post(path + "/accept-assumptions", json={"expected_revision": view["revision"]}).raise_for_status()
        ctx.act("accept_assumptions")
        return ["accept_assumptions"]
    if blocking:
        raise RuntimeError("Blocking findings the page does not settle: " + "; ".join(row["message"] for row in blocking)[:1500])
    ctx.stack.http.post(path + "/confirm", json={"expected_revision": view["revision"]}).raise_for_status()
    ctx.stack.command(ctx.campaign_id, "campaign.update", {"charter": {"id": record["id"], "revision": view["revision"]},
                      "rationale": "Confirmed the charter adopted from the problem note"})
    ctx.act("confirm")
    return ["confirm"]


def setup_act(ctx, step, reply, replied):
    """The researcher's next action on the gate's step, as the pages offer it; the kinds of what was done."""
    store, note_id = ctx.store, "note_" + ctx.campaign_id
    pending = [q for q in store.list("agent_question", ctx.campaign_id) if q["status"] == "pending" and not q["id"].startswith("pi_stalled_")]
    if pending:
        ctx.stack.command(ctx.campaign_id, "agent.message", {"message": reply, "question_id": pending[-1]["id"], "thread_id": ctx.thread_id},
                          origin={"thread_id": ctx.thread_id})
        ctx.act("answer")
        return ["answer"]
    note = store.get(note_id, "problem_note") if step["kind"] != "note" else None
    if step["kind"] == "sections":
        proposals = [row for row in store.list("note_skip", ctx.campaign_id) if row["note_id"] == note_id and row["status"] == "open"]
        if proposals:
            for row in proposals:
                ctx.stack.command(ctx.campaign_id, "problem_note.skip", {"skip_id": row["id"],
                                  "agree": [item["section"] for item in row["items"] if item["status"] == "proposed"]})
                ctx.act("agree_skips")
            return ["agree_skips"] * len(proposals)
    if step["kind"] in {"note", "sections"}:
        # The lead's turn ended without the note: the researcher answers what it asked in its reply.
        if replied >= REPLIES:
            raise RuntimeError(f"The lead did not finish the note after {REPLIES} replies: {step['title']}" + (" (" + ", ".join(step["missing"]) + ")" if step.get("missing") else ""))
        ctx.stack.command(ctx.campaign_id, "agent.message", {"message": reply, "thread_id": ctx.thread_id}, origin={"thread_id": ctx.thread_id})
        ctx.act("reply")
        return ["reply"]
    if step["kind"] == "adopt":
        ctx.stack.command(ctx.campaign_id, "problem_note.adopt", {"note_id": note_id, "revision": note["current_revision"]})
        ctx.act("adopt")
        return ["adopt"]
    if step["kind"] == "confirm":
        return setup_charter_step(ctx, note, reply)
    if step["kind"] == "tasks":
        from balsamic.evolution.stages import _charter_of
        record = _charter_of(store, note)
        ctx.stack.command(ctx.campaign_id, "campaign.update", {"charter": {"id": record["id"], "revision": record["confirmed_revision"]},
                          "rationale": "Finished the charter hand-over"})
        ctx.act("install")
        return ["install"]
    raise RuntimeError(f"No action for the step {step['kind']}: {step['title']}")


def step_define(ctx, spec=None):
    """The researcher takes the campaign through the problem-definition gate until it opens, as the pages let them (track P).

    Each time the campaign's agents and its formulators are idle, the gate's step decides the action: a question of the lead
    gets the scenario's reply, as does a lead whose note is unfinished (at most REPLIES times); proposed skips are agreed; Adopt
    adopts the current revision; on the charter, open questions get their recommended option, assumptions are accepted, and
    "Confirm and set the tasks" confirms the revision and installs its tasks (one action, as on the page). The step reads the
    gate, not the path, so it plays the quick path as it plays the full one."""
    spec = spec if isinstance(spec, dict) else {}
    reply = ctx.format(spec.get("reply", REPLY))
    deadline = time.monotonic() + spec.get("timeout_s", 1800)
    ctx.setup = {"defined": False, "defined_s": None}
    replied = quiet = 0
    step = None
    while time.monotonic() < deadline:
        quiet = 0 if setup_busy(ctx) else quiet + 1
        if quiet < 3:   # three idle polls in a row: a turn a command queued has had time to start
            time.sleep(ctx.poll)
            continue
        gate = ctx.workspace.definition_gate(ctx.store.get(ctx.campaign_id, "campaign"))
        if gate["ready"]:
            ctx.setup.update(defined=True, defined_s=round(time.monotonic() - ctx.started, 2))
            return {"define": "defined", "after_s": ctx.setup["defined_s"], "actions": [a["kind"] for a in ctx.actions]}
        step = gate["step"]
        ctx.round += 1
        done = setup_act(ctx, step, reply, replied)
        replied += done.count("reply")
        quiet = 0
    ctx.timed_out = True
    return {"define": "timed out", "waiting_for": (step or {}).get("title") or "the first idle moment", "actions": [a["kind"] for a in ctx.actions]}


def run_step(ctx, step):
    if step.get("live_only") and ctx.stack.fake:
        return {"skipped": {key: value for key, value in step.items() if key != "live_only"}, "why": "live only: the scripted harness has no coding agent"}
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
    if "define" in step:
        return step_define(ctx, step["define"])
    raise ValueError(f"Unknown step {step}")


# Checks: each returns (passed, detail) from the store --------------------------------------------------------
def _operations(value):
    return [value] if isinstance(value, str) else list(value)


def _count(ctx, arg):
    """Agents' accepted commands of the given operation(s), of one role's agents when arg names a role."""
    agents = ctx.agents()
    return sum(c["request"]["operation"] in _operations(arg["operation"]) and (not arg.get("role") or (agents.get(c["origin"]["agent_id"]) or {}).get("role") == arg["role"])
               for c in ctx.agent_commands())


def check_commands_exactly(ctx, arg):
    count = _count(ctx, arg)
    return count == arg["count"], f"{count} {arg['operation']}" + (f" by the {arg['role']}" if arg.get("role") else "")


def check_commands_at_least(ctx, arg):
    count = _count(ctx, arg)
    return count >= arg["count"], f"{count} {arg['operation']}" + (f" by the {arg['role']}" if arg.get("role") else "")


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
    found = [text for text in _expand(ctx, arg) if text.lower() in reply]
    return not found, f"found {found}" if found else "none"


def check_reply_links_page(ctx, arg):
    return arg in ctx.reply(), f"{arg} {'linked' if arg in ctx.reply() else 'not linked'}"


def check_reply_matches(ctx, arg):
    match = re.search(arg, ctx.reply())
    return bool(match), f"matched {match.group(0)!r}" if match else f"no match for {arg}"


def check_reply_numbers_verified(ctx, arg):
    """The reply's numbers each appear in what its request read (K2): no message of the reply has an unverified-numbers badge."""
    found = [number for m in ctx.reply_messages() for number in m.get("unverified_numbers") or []]
    return (not found) is bool(arg), f"unverified: {', '.join(found)}" if found else "every number of the reply is sourced"


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


def _external(ctx):
    return [r for r in ctx.receipts() if r.get("external")]


def check_external_receipts_at_least(ctx, arg):
    count = sum(r["tool"] == arg["tool"] for r in _external(ctx))
    return count >= arg["count"], f"{count} receipts of {arg['tool']}"


def check_no_external_receipts(ctx, arg):
    found = [r["tool"] for r in _external(ctx) if r["tool"] in arg]
    return not found, ", ".join(found) or "none"


def _outputs(ctx):
    return [(agent, agent.get("output")) for agent in ctx.agents().values() if agent.get("output") is not None]


def check_structured_outputs_valid(ctx, arg):
    """Every result an agent submitted matches its schema (the roles' schemas, agents/roles)."""
    import jsonschema
    bad = []
    for agent, output in _outputs(ctx):
        try:
            jsonschema.validate(output, agent.get("output_schema") or {})
        except jsonschema.ValidationError as exc:
            bad.append(f"{agent['role']}: {exc.message[:120]}")
    return not bad, "; ".join(bad) or f"{len(_outputs(ctx))} outputs valid"


def check_outputs_at_least(ctx, arg):
    count = sum(agent["role"] == arg["role"] for agent, _ in _outputs(ctx))
    return count >= arg["count"], f"{count} results from the {arg['role']}"


def check_verdicts_in(ctx, arg):
    """The proposal's reviews: at least one verdict, and every verdict among those given."""
    hypothesis = ctx.store.get(ctx.format(arg["hypothesis"]), "hypothesis")
    verdicts = [review["verdict"] for review in hypothesis.get("reviews") or [] if review.get("verdict")]
    return bool(verdicts) and set(verdicts) <= set(arg["verdicts"]), f"verdicts {verdicts}"


def check_synthesis_matches_tally(ctx, arg):
    """The moderator recorded a synthesis of the round, and no standing in it, nor a status it set, goes against the
    reviewers' verdicts (T2)."""
    syntheses = [row for row in ctx.store.list("agent_artifact", ctx.campaign_id) if row.get("kind") == "review_synthesis"]
    against = [f"{entry['hypothesis_id']} {entry['standing']}" for row in syntheses for entry in row["content"]["proposals"] if entry.get("against_tally")]
    against += [f"status {r['result']['against_tally']['status']}" for r in ctx.receipts() if isinstance(r.get("result"), dict) and r["result"].get("against_tally")]
    passed = bool(syntheses) and not against
    return passed, f"{len(syntheses)} syntheses; against the tally: {', '.join(against) or 'none'}"


def check_records_at_least(ctx, arg):
    count = len(ctx.store.list(arg["kind"], ctx.campaign_id))
    return count >= arg["count"], f"{count} {arg['kind']}"


def check_records_at_most(ctx, arg):
    count = len(ctx.store.list(arg["kind"], ctx.campaign_id))
    return count <= arg["count"], f"{count} {arg['kind']}"


def check_page_agents(ctx, arg):
    """The campaign's page_agents (T4): standing, or lead when the moderator and the operator are folded into the lead."""
    mode = (ctx.workspace.pi.configuration(ctx.campaign_id) or {}).get("page_agents") or "standing"
    return mode == arg, f"page_agents {mode}"


def check_all_of(ctx, arg):
    """A list of checks; passes when every one passes."""
    details = []
    for check in arg:
        (name, value), = check.items()
        passed, detail = CHECKS[name](ctx, value)
        if not passed:
            return False, f"{name}: {detail}"
        details.append(f"{name}: {detail}")
    return True, "; ".join(details)


def check_any_of(ctx, arg):
    """A list of checks; passes when one of them passes."""
    details = []
    for check in arg:
        (name, value), = check.items()
        passed, detail = CHECKS[name](ctx, value)
        if passed:
            return True, f"{name}: {detail}"
        details.append(f"{name}: {detail}")
    return False, "none passed (" + "; ".join(details) + ")"


def _expand(ctx, items):
    """Values a seed returned, named as {key} and joined with ", ", as one list."""
    return [part for item in ([items] if isinstance(items, str) else items) for part in ctx.format(item).split(", ") if part]


def check_no_reads_of(ctx, arg):
    """No tool call of the run names these records in its arguments or its result, except a refused call and a status-only view
    of a locked record (`protected_evidence`), which leak nothing; that view names a trial as status_<id>, not as itself."""
    ids = _expand(ctx, arg)
    intents = {i["id"].removeprefix("intent_"): i for i in ctx.store.list("agent_tool_intent", ctx.campaign_id)}
    found = []
    for receipt in ctx.receipts():
        result = receipt.get("result")
        if isinstance(result, dict) and (result.get("error") or result.get("protected_evidence")):
            continue
        text = json.dumps([(intents.get(receipt["id"]) or {}).get("arguments"), result], ensure_ascii=False, default=str)
        found += [f"{receipt['tool']} → {identity}" for identity in ids if re.search(rf"(?<!\w){re.escape(identity)}(?!\w)", text)]
    return not found, f"{len(found)} reads" + (f": {', '.join(found[:3])}" if found else f" of {len(ids)} records")


def _contains(value, subset):
    if isinstance(subset, dict):
        return isinstance(value, dict) and all(key in value and _contains(value[key], item) for key, item in subset.items())
    return value == subset


def check_commands_with(ctx, arg):
    """Agents' accepted commands of an operation whose payload contains `payload` (a subset, nested objects compared key by key)
    and, with `matches`, whose payload matches that regular expression. `count` is exact; without it, at least one."""
    payload, pattern = ctx.format_value(arg.get("payload") or {}), arg.get("matches")
    found = [c for c in ctx.agent_commands() if c["request"]["operation"] == arg["operation"] and _contains(c["request"].get("payload") or {}, payload)
             and (not pattern or re.search(pattern, json.dumps(c["request"].get("payload"), ensure_ascii=False)))]
    passed = len(found) == arg["count"] if "count" in arg else bool(found)
    return passed, f"{len(found)} {arg['operation']}" + (f" with {json.dumps(payload)}" if payload else "") + (f" matching {pattern}" if pattern else "")


def _commands_of(ctx, operation):
    """Accepted commands of an operation, whoever sent them (agents, the researcher or Balsamic), oldest first."""
    return sorted((c for c in ctx.store.list("work_command", ctx.campaign_id) if c["request"]["operation"] == operation and c.get("status") == "completed"),
                  key=lambda c: c.get("created_at") or "")


def check_trials_started_by(ctx, arg):
    """Every experiment of the campaign was started by this actor (`balsamic`: a planned run under the researcher's go-ahead),
    and at least `count` of them."""
    starters = {(c.get("outcome") or {}).get("trial_id"): c.get("actor") for c in _commands_of(ctx, "trial.create")}
    trials = [t for t in ctx.store.list("trial", ctx.campaign_id) if not t.get("hidden")]
    others = [f"{t['id']} by {starters.get(t['id'], 'no command')}" for t in trials if starters.get(t["id"]) != arg["actor"]]
    started = len(trials) - len(others)
    return not others and started >= arg["count"], f"{started} started by {arg['actor']}" + (f"; others: {', '.join(others[:3])}" if others else "")


def _after_activation(ctx):
    activated = _commands_of(ctx, "agent.activate")
    return activated[0] if activated else None


def check_researcher_actions(ctx, arg):
    """The researcher's actions after the team started (their messages, decisions, answers), with the decisions and questions
    still waiting for them counted too: what the flow needed of them, exactly `arg`."""
    activated = _after_activation(ctx)
    since = (activated or {}).get("created_at") or ""
    sent = [c["request"]["operation"] for c in ctx.store.list("work_command", ctx.campaign_id)
            if c.get("actor") == "researcher" and (c.get("created_at") or "") >= since and c["id"] != (activated or {}).get("id")]
    waiting = [d["id"] for d in ctx.store.list("decision", ctx.campaign_id) if d.get("status") == "pending"]
    waiting += [q["id"] for q in ctx.store.list("agent_question", ctx.campaign_id) if q["status"] == "pending" and not q["id"].startswith("pi_stalled_")]
    count = len(sent) + len(waiting)
    return count == arg, f"{count} researcher actions: {', '.join(sent) or 'none'}" + (f"; waiting: {', '.join(waiting)}" if waiting else "")


def _numbers(value):
    """How a reply would write a score: 290, 290.0, 290.00, 1,290."""
    return {f"{value:g}", f"{value:.1f}", f"{value:.2f}", f"{value:,.0f}"} | ({f"{value:.0f}"} if float(value).is_integer() else set())


def check_reply_ranks_by_report(ctx, arg):
    """The lead's reply gives the last comparison report's method means in the report's rank order (best first, under the
    objective's direction): each ranked mean appears, and each after the one ranked above it."""
    reports = [c for c in _commands_of(ctx, "comparison.report") if c.get("outcome")]
    if not reports:
        return False, "no comparison report"
    groups = [g for g in reports[-1]["outcome"].get("groups", []) if any(s.get("rank") for s in g.get("method_summaries", []))]
    if not groups:
        return False, "the report ranks no method"
    group = max(groups, key=lambda g: len(g["method_summaries"]))
    ranked = sorted((s for s in group["method_summaries"] if s.get("rank")), key=lambda s: s["rank"])
    reply, cursor, found = ctx.reply(), 0, []
    for summary in ranked:
        hits = [m.start() for text in _numbers(summary["mean"]) for m in re.finditer(rf"(?<![\d.,]){re.escape(text)}(?![\d]|[.,]\d)", reply)]
        later = [position for position in hits if position >= cursor]
        if not later:
            where = "not in the reply" if not hits else "before a method ranked above it"
            return False, f"{summary['method_id']} (rank {summary['rank']}, mean {summary['mean']:g}) {where}; ranked so far: {found}"
        cursor = min(later)
        found.append(f"{summary['method_id']} {summary['mean']:g}")
    return True, f"{group.get('direction')}: " + ", ".join(found)


def check_live_only(ctx, arg):
    """A check of what only a live run produces (a coding agent's library, its runs, their comparison): graded live,
    reported as not graded on the scripted harness."""
    (name, value), = arg.items()
    if ctx.stack.fake:
        return True, f"{name}: not graded on the scripted harness (no coding agent)"
    return CHECKS[name](ctx, value)


def check_definition_ready(ctx, arg):
    """The problem-definition gate is open (true) or still closed (false) at the end."""
    gate = ctx.workspace.definition_gate(ctx.store.get(ctx.campaign_id, "campaign"))
    return gate["ready"] is bool(arg), "the gate is open" if gate["ready"] else f"the gate is closed: {(gate.get('step') or {}).get('title')}"


def _matches(value, subset):
    """subset is in value: a dict's keys recursively, a list's items in order, anything else equal."""
    if isinstance(subset, dict):
        return isinstance(value, dict) and all(key in value and _matches(value[key], item) for key, item in subset.items())
    if isinstance(subset, list):
        return isinstance(value, list) and len(value) >= len(subset) and all(_matches(item, part) for item, part in zip(value, subset))
    return value == subset


def confirmed_charter(ctx):
    """(reference, the charter revision record) the campaign's tasks were installed from, or (None, None)."""
    reference = ctx.store.get(ctx.campaign_id, "campaign").get("charter")
    if not reference:
        return None, None
    return reference, ctx.workspace.charters.revision(reference["id"], reference["revision"])


def check_charter_matches(ctx, arg):
    """The charter the campaign was confirmed from holds `subset` (a JSON subset: keys recursively, list items in order), and
    each of `values` is the value of one of its quantities, whatever the quantity is called."""
    reference, revision = confirmed_charter(ctx)
    if not reference:
        return False, "the campaign has no confirmed charter"
    charter = revision["charter"]
    wrong = [key for key, item in (arg.get("subset") or {}).items() if not (key in charter and _matches(charter[key], item))]
    values = [quantity.get("value") for quantity in charter.get("quantities", {}).values()]
    wrong += [f"no quantity of value {value}" for value in arg.get("values") or [] if value not in values]
    return not wrong, f"{reference['id']} r{reference['revision']}" + (": " + "; ".join(wrong) if wrong else " matches")


def check_charter_writer(ctx, arg):
    """Who saved the revision the campaign was confirmed from: lead, formulator or researcher."""
    reference, revision = confirmed_charter(ctx)
    by = revision["by"] if revision else None
    return by == arg, f"saved by {by}" if by else "the campaign has no confirmed charter"


def check_setup_actions_at_most(ctx, arg):
    """The researcher's actions from their first message to the gate opening, at most this many."""
    setup = setup_metrics(ctx) or {}
    count = setup.get("researcher_actions")
    return count is not None and count <= arg, f"{count} researcher actions: " + (", ".join(f"{kind} {n}" for kind, n in (setup.get("actions") or {}).items()) or "none")


CHECKS = {name.removeprefix("check_"): value for name, value in globals().items() if name.startswith("check_")}


def _time(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def go_ahead_to_results(ctx):
    """Seconds from the researcher's go-ahead (their first decision after the team started) to the lead's first reply after the
    first comparison report written since; None while either is missing."""
    since = (_after_activation(ctx) or {}).get("created_at") or ""
    go = next((c for c in _commands_of(ctx, "decision.resolve") if c.get("actor") == "researcher" and (c.get("created_at") or "") >= since), None)
    report = next((c for c in _commands_of(ctx, "comparison.report") if go and c["created_at"] >= go["created_at"]), None)
    reply = min((m["created_at"] for m in ctx.lead_replies() if report and (m.get("created_at") or "") >= report["created_at"]), default=None)
    return round((_time(reply) - _time(go["created_at"])).total_seconds(), 1) if reply else None


def review_roles(ctx):
    """T3's comparison, per review role delegated: one call or a session, how many answered with a valid result, their cost,
    the seconds from delegation to the end of their run, and the size of what they read (tokens; and bytes for a call)."""
    from optimization_framework.agents.calls import ONE_SHOT_ROLES
    calls = {row["agent_id"]: row for row in ctx.store.list("agent_call", ctx.campaign_id)}
    runs = {}
    for run in ctx.runs():
        runs.setdefault(run["agent_id"], []).append(run)
    roles = {}
    for agent in ctx.agents().values():
        if agent["role"] not in ONE_SHOT_ROLES:
            continue
        row = roles.setdefault(agent["role"], {"modes": [], "agents": 0, "valid": 0, "cost_usd": 0.0, "seconds": 0.0, "input_tokens": 0, "prompt_bytes": 0})
        mode = agent.get("answers_as", "one_shot") if agent.get("one_shot") else "session"
        row["modes"] = sorted({*row["modes"], mode})
        row["agents"] += 1
        own = [run for run in runs.get(agent["id"], []) if not run["id"].startswith("pi_child_result_")]
        done = [run for run in own if run["status"] == "completed"]
        row["valid"] += bool(done) and (agent["role"] == "proposal_reviewer" or agent.get("output") is not None)
        usage = agent.get("usage") or {}
        row["cost_usd"] = round(row["cost_usd"] + (usage.get("cost_usd") or 0.0), 6)
        row["input_tokens"] += usage.get("input") or 0
        finished = max((run.get("finished_at") or "" for run in own), default="")
        if finished and agent.get("created_at"):
            row["seconds"] = round(row["seconds"] + (_time(finished) - _time(agent["created_at"])).total_seconds(), 1)
        call = calls.get(agent["id"])
        if call and call.get("input") is not None:
            row["prompt_bytes"] += len(((call.get("instructions") or "") + json.dumps(call["input"], ensure_ascii=False)).encode())
    return roles


def page_agents(ctx):
    """T4's comparison: the campaign's page_agents, the lead's hand-offs to page agents (page_agent_message), the turns of the
    two foldable page agents, the largest context one lead model call read (input and cache-read tokens), and J3's partnership
    numbers over the scenario's requests (the researcher's actions, the seconds from each request to its report)."""
    from optimization_framework.agents.models import FOLDABLE
    from balsamic.monitor.partnership import requests
    agents = ctx.agents()
    rows = requests(ctx.workspace, ctx.campaign_id)
    timed = [row["seconds_to_report"] for row in rows if row["seconds_to_report"] is not None]
    with ctx.store.connection() as db:
        peak = db.execute("SELECT COALESCE(MAX(input + cache_read), 0) FROM llm_usage WHERE campaign_id=? AND agent_id=?",
                          (ctx.campaign_id, ctx.lead_id or "")).fetchone()[0]
    return {"mode": (ctx.workspace.pi.configuration(ctx.campaign_id) or {}).get("page_agents") or "standing",
            "hand_offs": sum(r.get("tool") == "page_agent_message" and r.get("agent_id") == ctx.lead_id for r in ctx.receipts()),
            "page_agent_turns": sum((agents.get(r["agent_id"]) or {}).get("role") in FOLDABLE for r in ctx.runs()),
            "lead_peak_context_tokens": peak, "requests": len(rows),
            "researcher_actions": sum(row["researcher_actions"]["total"] for row in rows),
            "seconds_to_report": round(statistics.fmean(timed), 1) if timed else 0.0}


def setup_metrics(ctx):
    """Track P's measure of the set-up, for a scenario with a define step: the researcher's actions by kind and their rounds
    (returns to the campaign), from their first message until the gate opened; lead turns; the formulators' turns, model calls
    and cost, from their imports (not in llm_usage); and the seconds from the first message to the gate opening."""
    if ctx.setup is None:
        return None
    end = ctx.setup["defined_s"]
    actions = [action for action in ctx.actions if end is None or action["s"] <= end]
    kinds = {}
    for action in actions:
        kinds[action["kind"]] = kinds.get(action["kind"], 0) + 1
    imports = setup_imports(ctx)
    usage = [row.get("usage") or {} for row in imports]
    first = next((action["s"] for action in actions if action["kind"] == "message"), None)
    return {"defined": ctx.setup["defined"], "researcher_actions": len(actions), "actions": kinds, "rounds": len({action["round"] for action in actions}),
            "lead_turns": len(ctx.lead_runs()), "formulator_turns": sum(len(row.get("runs") or []) for row in imports),
            "formulator_model_calls": sum(item.get("calls", 0) for item in usage),
            "formulator_cost_usd": round(sum(item.get("cost_usd", 0.0) for item in usage), 6),
            "words_to_charter_s": round(end - first, 1) if end is not None and first is not None else None}


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
            "unverified_numbers": len(ctx.unverified_numbers()),
            "refusals": len(_refusals(ctx)), "max_tool_result_bytes": max([serialized_bytes(r.get("result")) for r in ctx.receipts()] or [0]),
            **ctx.usage(), "seconds": round(time.monotonic() - ctx.started, 1), "go_ahead_to_results_s": go_ahead_to_results(ctx),
            "review_roles": review_roles(ctx), "page_agents": page_agents(ctx), "setup": setup_metrics(ctx)}


def transcript(ctx, result):
    """Messages, run inputs and a summary of tool receipts, for reading why a check failed."""
    agents = ctx.agents()
    lines = [f"# {ctx.scenario['id']} (repeat {result['repeat']})", "", f"- Campaign: `{ctx.campaign_id}`", f"- Status: **{result['status']}**",
             f"- Preset: {result['preset']} ({', '.join(result['problems']) or 'no task'})",
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


def supported_presets(scenario):
    """The presets a scenario may run on: its own `presets`, or only the one its set-up names."""
    return scenario.get("presets") or [scenario.get("setup", {}).get("preset", "quadratic")]


def campaign_preset(stack, name):
    """campaign.create's fields for a preset: an installed example's instances become the tasks, and a charter file is created
    and confirmed (as the researcher does on the Problem page) so the campaign is made from it."""
    preset = dict(PRESETS[name])
    example_id = preset.pop("example", None)
    if example_id:
        examples = {row["id"]: row for row in stack.http.get("/api/v1/problem-examples").raise_for_status().json()["examples"]}
        if example_id not in examples:
            raise RuntimeError(f"Preset {name} needs the installed example {example_id}, which is not installed")
        preset["tasks"] = [{key: instance[key] for key in ("name", "problem_id", "configuration", "fidelity") if key in instance}
                           for instance in examples[example_id]["instances"]]
    charter_file = preset.pop("charter", None)
    if charter_file:
        charters = stack.workspace.charters
        record = charters.create(json.loads((EVALS / "charters" / charter_file).read_text()), source={"kind": "lead_eval", "preset": name})
        preset["charter"] = charters.confirm(record["id"])["charter"]
    return preset


def run_scenario(stack, scenario, repeat, *, model, scale, fakes, preset=None):
    setup = scenario.get("setup", {})
    campaign_id = f"eval_{scenario['id'].split('-', 1)[0].lower()}_r{repeat}_{uuid.uuid4().hex[:6]}"
    preset = preset or setup.get("preset", "quadratic")
    stack.command(campaign_id, "campaign.create", {"name": f"Eval {scenario['id']} #{repeat}", **campaign_preset(stack, preset),
                                                   "llm_budget_usd": setup.get("llm_budget_usd", 0.3)})
    ctx = Context(stack, scenario, campaign_id, scale)
    stack.fake_play = fakes.get(scenario["id"]) if fakes is not None else None
    problems = [task["problem"]["definition_id"] for task in stack.workspace.current_tasks(campaign_id)]
    result = {"repeat": repeat, "campaign_id": campaign_id, "preset": preset, "problems": problems, "checks": [], "error": None}
    try:
        for name in setup.get("seeds", []):
            ctx.timeline.append(step_seed(ctx, name))
        stack.extensions(setup.get("extensions"))
        stack.development(setup.get("development", False))
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
    keys = ("lead_turns", "continue_turns", "model_calls", "cost_usd", "cache_read_tokens", "input_tokens", "seconds", "unverified_numbers")
    mean = {key: round(statistics.fmean(r["metrics"].get(key, 0) for r in repeats), 4) for key in keys} if repeats else {}
    timed = [r["metrics"]["go_ahead_to_results_s"] for r in repeats if r["metrics"].get("go_ahead_to_results_s") is not None]
    if timed:
        mean["go_ahead_to_results_s"] = round(statistics.fmean(timed), 1)
    roles = {}
    for r in repeats:   # T3's comparison: the review roles' totals over the repeats
        for role, row in (r["metrics"].get("review_roles") or {}).items():
            total = roles.setdefault(role, {"modes": []})
            total["modes"] = sorted({*total["modes"], *row["modes"]})
            for key, value in row.items():
                if key != "modes":
                    total[key] = round(total.get(key, 0) + value, 6)
    if roles:
        mean["review_roles"] = roles
    folded = [r["metrics"]["page_agents"] for r in repeats if r["metrics"].get("page_agents")]
    if folded:   # T4's comparison, the mean over repeats
        mean["page_agents"] = {"mode": folded[0]["mode"], **{key: round(statistics.fmean(row[key] for row in folded), 1)
                                                            for key in ("hand_offs", "page_agent_turns", "lead_peak_context_tokens",
                                                                        "requests", "researcher_actions", "seconds_to_report")}}
    setups = [r["metrics"]["setup"] for r in repeats if r["metrics"].get("setup")]
    if setups:   # track P's measure of the set-up, the mean over repeats; words_to_charter_s over the runs that got there
        mean["setup"] = {"defined": f"{sum(row['defined'] for row in setups)}/{len(setups)}",
                         **{key: round(statistics.fmean(row[key] for row in setups), 4) for key in
                            ("researcher_actions", "rounds", "lead_turns", "formulator_turns", "formulator_model_calls", "formulator_cost_usd")},
                         "actions": {kind: round(statistics.fmean((row["actions"] or {}).get(kind, 0) for row in setups), 2)
                                     for kind in dict.fromkeys(kind for row in setups for kind in row["actions"] or {})}}
        timed_setup = [row["words_to_charter_s"] for row in setups if row["words_to_charter_s"] is not None]
        mean["setup"]["words_to_charter_s"] = round(statistics.fmean(timed_setup), 1) if timed_setup else None
    status = "pass" if passed else "xfail" if scenario.get("known_failure") else "fail"
    return {"id": scenario["id"], "source": scenario.get("source"), "scoring": scoring, "known_failure": scenario.get("known_failure"),
            "passes": passes, "repeats": len(repeats), "passed": passed, "status": status, "metrics_mean": mean, "runs": repeats}


def baseline_label(baseline):
    """A baseline's column heading: its commit, model and preset (an older baseline names no model: the profile's default)."""
    model = baseline.get("model_id") or baseline.get("model") or "profile default"
    return " · ".join([baseline.get("commit", "?"), model] + ([baseline["preset"]] if baseline.get("preset") else []))


def summary_markdown(results, baselines=None):
    if isinstance(baselines, dict):
        baselines = [baselines]
    baselines = baselines or []
    lines = [f"# Lead evals · {results['mode']} · {results['commit']}", "",
             f"- Started {results['started_at']}, {results['seconds']} s; model {results.get('model_id') or results['model'] or 'profile default'}",
             f"- Preset: {results.get('preset') or 'each scenario on its own'}",
             f"- Model use: ${results['cost_usd']:.4f} (suite cap ${results['suite_cap']:.2f})",
             f"- Unverified numbers: {results.get('unverified_numbers', 0)} in the suite (numbers in replies and findings that none of "
             "their evidence holds; per scenario, the mean over repeats)", ""]
    header = "| Scenario | Status | Passes | Lead turns | pi_continue | Model calls | Cost | cacheRead | Unverified numbers |"
    rule = "|---|---|---|---|---|---|---|---|---|"
    for baseline in baselines:
        header += f" {baseline_label(baseline)} |"; rule += "---|"
    lines += [header, rule]
    for row in results["scenarios"]:
        m = row["metrics_mean"]
        line = (f"| {row['id']} | {row['status']} | {row['passes']}/{row['repeats']} ({row['scoring']}) | {m.get('lead_turns', 0):g} | "
                f"{m.get('continue_turns', 0):g} | {m.get('model_calls', 0):g} | ${m.get('cost_usd', 0):.4f} | {m.get('cache_read_tokens', 0):g} | "
                f"{m.get('unverified_numbers', 0):g} |")
        for baseline in baselines:
            old = baseline.get("scenarios", {}).get(row["id"])
            line += (" — |" if not old else f" {old['passes']}/{old['repeats']}{' **regressed**' if old['passed'] and not row['passed'] else ''} |")
        lines.append(line)
    timed = [row for row in results["scenarios"] if row["metrics_mean"].get("go_ahead_to_results_s") is not None]
    if timed:
        lines += ["", "## Go-ahead to ranked results", ""] + [
            f"- {row['id']}: {row['metrics_mean']['go_ahead_to_results_s'] / 60:.1f} min ({row['metrics_mean']['go_ahead_to_results_s']:g} s, "
            f"mean of {sum(run['metrics'].get('go_ahead_to_results_s') is not None for run in row['runs'])} runs)" for row in timed]
    defined = [row for row in results["scenarios"] if row["metrics_mean"].get("setup")]
    if defined:
        lines += ["", "## Words to a confirmed charter", "",
                  "| Scenario | Defined | Researcher actions | Rounds | Lead turns | Formulator turns | Model calls: agents + formulator | Cost: agents + formulator | Minutes |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for row in defined:
            m, s = row["metrics_mean"], row["metrics_mean"]["setup"]
            kinds = ", ".join(f"{kind} {count:g}" for kind, count in s["actions"].items())
            minutes = f"{s['words_to_charter_s'] / 60:.1f}" if s.get("words_to_charter_s") is not None else "—"
            lines.append(f"| {row['id']} | {s['defined']} | {s['researcher_actions']:g} ({kinds}) | {s['rounds']:g} | {s['lead_turns']:g} | "
                         f"{s['formulator_turns']:g} | {m.get('model_calls', 0):g} + {s['formulator_model_calls']:g} | "
                         f"${m.get('cost_usd', 0):.4f} + ${s['formulator_cost_usd']:.4f} | {minutes} |")
    reviewed = [row for row in results["scenarios"] if row["metrics_mean"].get("review_roles")]
    if reviewed:
        lines += ["", f"## Review roles (one-shot roles: {results.get('one_shot_roles') or 'the default'})", "",
                  "| Scenario | Role | Mode | Valid results | Cost | Seconds | Input tokens | Call prompt bytes |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {row['id']} | {role} | {', '.join(item['modes'])} | {item['valid']:g}/{item['agents']:g} | ${item['cost_usd']:.4f} | "
                  f"{item['seconds']:g} | {item['input_tokens']:g} | {item['prompt_bytes']:g} |"
                  for row in reviewed for role, item in sorted(row["metrics_mean"]["review_roles"].items())]
    paged = [row for row in results["scenarios"] if row["metrics_mean"].get("page_agents")]
    if paged:
        lines += ["", f"## Page agents (page_agents: {results.get('page_agents') or 'standing'})", "",
                  "| Scenario | Hand-offs | Moderator and operator turns | Lead turns | Lead's largest context (tokens) | Researcher actions | "
                  "Seconds to report | Seconds | Cost |", "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {row['id']} | {m['page_agents']['hand_offs']:g} | {m['page_agents']['page_agent_turns']:g} | {m.get('lead_turns', 0):g} | "
                  f"{m['page_agents']['lead_peak_context_tokens']:g} | {m['page_agents']['researcher_actions']:g} | "
                  f"{m['page_agents']['seconds_to_report']:g} | {m.get('seconds', 0):g} | ${m.get('cost_usd', 0):.4f} |"
                  for row in paged for m in [row["metrics_mean"]]]
    unsupported = results.get("unsupported") or []
    if unsupported:
        lines += ["", f"## Not run on {results['preset']}", ""] + [f"- {row['id']}: {row['reason']}" for row in unsupported]
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


def profile_model(profile):
    """The dev profile's default provider/model, which a run without --model uses."""
    try:
        settings = json.loads((Path(profile) / "settings.json").read_text())
    except (OSError, ValueError):
        return None
    if settings.get("defaultProvider") and settings.get("defaultModel"):
        return f"{settings['defaultProvider']}/{settings['defaultModel']}"
    return None


def baseline_path(results):
    """baselines/<commit>-<provider>-<model>[-<preset>].json: a baseline names what it measured, so two models' or two
    presets' runs of one commit sit side by side. A run of the scripted harness is <commit>-fake."""
    model = "fake" if results["mode"] == "fake" else (results.get("model_id") or "unknown-model")
    parts = [results["commit"], model] + ([results["preset"]] if results.get("preset") else [])
    return EVALS / "baselines" / (re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(parts)) + ".json")


def baseline_record(results):
    return {"commit": results["commit"], "mode": results["mode"], "model": results["model"], "model_id": results.get("model_id"),
            "preset": results.get("preset"), "recorded_at": results["started_at"], "unverified_numbers": results.get("unverified_numbers", 0),
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
    parser.add_argument("--preset", choices=sorted(PRESETS), help="run every selected scenario on this preset; scenarios that do not list it are not run")
    parser.add_argument("--record-baseline", nargs="?", const="",
                        help="also write the summary to evals/lead/baselines/<commit>-<provider>-<model>[-<preset>].json (or the path given)")
    parser.add_argument("--one-shot-roles", help="GRATING_ONE_SHOT_ROLES for this run: the roles that answer in one call (T3's arms: "
                        "'proposal_reviewer' for sessions, the default for one-shot specialists, 'proposal_reviewer,analyst' for one merged analyst)")
    parser.add_argument("--page-agents", choices=["standing", "lead"], help="GRATING_PAGE_AGENTS for this run (T4's two arms): "
                        "standing keeps the moderator's and the operator's sessions; lead folds their work into the lead")
    parser.add_argument("--compare", type=Path, nargs="+", help="baseline files to compare with in summary.md, a column each")
    args = parser.parse_args(argv)
    scenarios = load_scenarios(EVALS / "scenarios", args.scenarios)
    if not scenarios:
        raise SystemExit("No scenario matches")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = args.out or REPO / "runs" / "evals" / (stamp + ("-fake" if args.fake else ""))
    (out / "transcripts").mkdir(parents=True, exist_ok=True)
    model = parse_model(args.model)
    if args.one_shot_roles is not None:
        os.environ["GRATING_ONE_SHOT_ROLES"] = args.one_shot_roles
    if args.page_agents is not None:
        os.environ["GRATING_PAGE_AGENTS"] = args.page_agents
    scale = args.time_scale if args.time_scale is not None else FAKE_TIME_SCALE if args.fake else 1.0
    fakes = load_module(EVALS / "fakes.py", "lead_eval_fakes").FAKES if args.fake else None
    source = args.source.resolve()
    profile = args.profile or source / "agent-harness" / "profiles" / "dev"
    results = {"mode": "fake" if args.fake else "real", "commit": git_commit(source), "source": str(source), "model": args.model,
               "model_id": None if args.fake else args.model or profile_model(profile), "preset": args.preset,
               "one_shot_roles": os.environ.get("GRATING_ONE_SHOT_ROLES"), "page_agents": os.environ.get("GRATING_PAGE_AGENTS") or "standing",
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "suite_cap": args.suite_cap, "scenarios": [], "skipped": [], "unsupported": []}
    if args.preset:
        for scenario in [s for s in scenarios if args.preset not in supported_presets(s)]:
            reason = f"supports {', '.join(supported_presets(scenario))}, not {args.preset}"
            results["unsupported"].append({"id": scenario["id"], "reason": reason})
            print(f"{scenario['id']}: not run ({reason})", flush=True)
        scenarios = [s for s in scenarios if args.preset in supported_presets(s)]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="lead-evals-") as root, \
            Stack(root, fake=args.fake, source=source, profile=profile,
                  secrets_file=args.secrets, log=print) as stack:
        spent = 0.0
        for scenario in scenarios:
            repeats = []
            for repeat in range(1, (args.repeats or scenario.get("repeats", 1)) + 1):
                if spent >= args.suite_cap:
                    results["skipped"].append(f"{scenario['id']} #{repeat}")
                    continue
                result, ctx = run_scenario(stack, scenario, repeat, model=model, scale=scale, fakes=fakes, preset=args.preset)
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
    results["unverified_numbers"] = sum(run["metrics"].get("unverified_numbers", 0) for row in results["scenarios"] for run in row["runs"])
    baselines = [json.loads(path.read_text()) for path in args.compare or []]
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out / "summary.md").write_text(summary_markdown(results, baselines))
    if args.record_baseline is not None:
        path = Path(args.record_baseline) if args.record_baseline else baseline_path(results)
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
