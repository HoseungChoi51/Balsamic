"""Persistent implementation workspaces, independent of short validation grants."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import atomic_json, now
from .development_runtime import IMAGE, LEGACY_MODEL, DockerWorkspace
from .models import LEAD, NOTICE


class WorkspaceCreate(Contract):
    hypothesis_id: str
    # The other proposals the same library serves: shown with the workspace and in what it delivers.
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=20)
    objective: str = Field(default="Implement this method from the saved specification and references.", min_length=1, max_length=50000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    request_key: str = Field(min_length=1, max_length=200)
    cpu_budget_seconds: float | None = Field(default=None, gt=0, le=86400)


class WorkspaceMessage(Contract):
    message: str = Field(min_length=1, max_length=50000)
    mode: Literal["steer", "follow_up"] = "steer"
    request_key: str = Field(min_length=1, max_length=200)
    question_id: str | None = None


class WorkspaceControl(Contract):
    action: Literal["pause", "resume", "stop"]
    request_key: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)


class SubmissionManifest(Contract):
    contract: Literal["ask_tell", "optimizer_v1"] = "optimizer_v1"
    entrypoint: str = "optimizer:create_optimizer"
    files: list[str] = Field(min_length=1, max_length=100)
    dependencies: dict[str, str] = Field(default_factory=dict, max_length=20)
    test_summary: str = Field(default="", max_length=10000)


class TestCounts(Contract):
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(default=0, ge=0)


class ReportTests(TestCounts):
    command: str = Field(default="", max_length=1000)


class MethodReport(Contract):
    method_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    hypothesis_id: str | None = None
    state: Literal["implemented", "partial", "not_implemented"]
    tests: TestCounts | None = None
    conformance: Literal["passed", "failed", "not_run"]
    note: str = Field(default="", max_length=1000)


class NextAction(Contract):
    owner: Literal["researcher", "lead", "validator"]
    action: str = Field(min_length=1, max_length=1000)


class DeliveryReport(Contract):
    """What the coding agent delivers, in its own judgement; its verdict has to agree with what it reports."""
    verdict: Literal["ready", "ready_with_limits", "not_ready"]
    summary: str = Field(min_length=1, max_length=2000)
    methods: list[MethodReport] = Field(min_length=1, max_length=30)
    tests: ReportTests
    limitations: list[str] = Field(default_factory=list, max_length=30)
    next_actions: list[NextAction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent(self):
        ids = [method.method_id for method in self.methods]
        if len(set(ids)) != len(ids):
            raise ValueError("methods: name each method_id once")
        if self.verdict == "ready":
            if any(method.state != "implemented" for method in self.methods):
                raise ValueError("verdict ready needs every method's state implemented; report ready_with_limits or not_ready")
            if any(method.conformance != "passed" for method in self.methods):
                raise ValueError("verdict ready needs every method's conformance passed; run tests/test_contract.py, or report ready_with_limits")
            if self.tests.failed:
                raise ValueError("verdict ready needs tests.failed 0; fix the failures, or report ready_with_limits or not_ready")
            if self.limitations:
                raise ValueError("verdict ready allows no limitations; report ready_with_limits with them")
        if self.verdict == "ready_with_limits" and not self.limitations:
            raise ValueError("verdict ready_with_limits needs the limitations listed")
        if self.verdict == "not_ready" and not self.next_actions:
            raise ValueError("verdict not_ready needs next_actions: what must happen, and who does it")
        return self


PHASES = ("orienting", "implementing", "testing", "fixing", "packaging", "blocked", "waiting")


def progress(payload):
    """The structured part of a checkpoint, field by field: a value the coding agent got wrong is left out, never the checkpoint."""
    found = {}
    if payload.get("phase") in PHASES:
        found["phase"] = payload["phase"]
    for key in ("done", "remaining"):
        if isinstance(payload.get(key), list):
            found[key] = [str(item)[:300] for item in payload[key][:20]]
    eta = payload.get("eta_minutes")
    if isinstance(eta, (int, float)) and not isinstance(eta, bool) and 0 <= eta <= 1440:
        found["eta_minutes"] = float(eta)
    try:
        found["tests"] = plain(TestCounts.model_validate(payload["tests"]).model_dump())
    except (KeyError, TypeError, ValueError):
        pass
    return found


def excerpt(text, limit=600):
    """A checkpoint's words in a notice: one paragraph, cut; the checkpoint itself keeps them whole."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def plain(value):
    """A contract's dump as the records keep it: without the schema version of every nested part."""
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items() if key != "schema_version"}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


BLOCKED_FAILS_SECONDS = 1800
LIVE = {"queued", "starting", "running", "resuming", "pausing", "stopping"}
SUBMISSION_STATES = {"submitted": "delivered", "validating": "validating", "validated": "validated", "needs_revision": "needs_revision"}


def outcome(record, submissions):
    """The workspace's latest result, from its records: its latest submission (delivered with the coding agent's verdict, then
    validating, validated or needs_revision), else stopped, else failed once the host has been unable to run it for 30 min;
    None while nothing has come of it yet."""
    mine = sorted((row for row in submissions if row["workspace_id"] == record["id"]), key=lambda row: row["created_at"])
    if mine:
        latest = mine[-1]
        state = SUBMISSION_STATES.get(latest["status"], latest["status"])
        return {"state": state, "verdict": (latest.get("report") or {}).get("verdict") or "unreported", "submission_id": latest["id"],
                "commit": latest["commit"], "at": latest.get("validated_at") or latest["created_at"]}
    if record.get("status") == "stopped":
        return {"state": "stopped", "at": record.get("control_requested_at") or record.get("updated_at") or record["created_at"]}
    since = record.get("blocked_since")
    if record.get("status") == "blocked" and since and (datetime.now(timezone.utc) - datetime.fromisoformat(since)).total_seconds() >= BLOCKED_FAILS_SECONDS:
        return {"state": "failed", "reason": record.get("error", ""), "at": since}
    return None


class WorkspaceValidate(Contract):
    submission_id: str
    spec: dict | None = None
    envelope_id: str | None = None
    compute_seconds: float = Field(gt=0, le=86400)
    request_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def one_specification(self):
        if (self.spec is None) == (self.envelope_id is None):
            raise ValueError("Provide exactly one frozen spec or validation envelope ID")
        return self


class WorkspaceEnvelope(Contract):
    spec: dict
    request_key: str = Field(min_length=1, max_length=200)


def request_hash(values):
    """The create request's identity; a request without other proposals hashes as it did before they could be named."""
    dump = values.model_dump()
    if not dump.get("hypothesis_ids"):
        dump.pop("hypothesis_ids", None)
    return content_hash(dump)


# Workspace events by the store event they put the workspace with: the pages that show a workspace refresh on them.
PUT_EVENTS = {"ready": "development.progress", "agent_start": "development.progress", "agent_settled": "development.progress",
              "message": "development.progress", "tool": "development.progress", "checkpoint": "development.checkpoint"}
# Events that are errors in their own right; a failed tool call is one when the event says so.
ERROR_EVENTS = {"bridge_error", "host_blocked", "budget_reached"}


class DevelopmentWorkspaces:
    def __init__(self, controller, driver=None):
        self.controller = controller
        self.workspace = controller.workspace
        self.store = controller.store
        self.directory = self.workspace.directory / "development"
        self.driver = driver or DockerWorkspace(self.directory)

    def enabled(self):
        return os.environ.get("GRATING_DEVELOPMENT_ENABLED", "false").lower() == "true"

    def installing(self):
        """Whether Balsamic installs delivered libraries by itself (GRATING_AUTO_INSTALL, on unless set to false)."""
        return os.environ.get("GRATING_AUTO_INSTALL", "true").lower() != "false"

    def install_delivered(self, campaign_id):
        """Install each workspace's latest delivered library that nobody installed or tried to (Installer.automatic), and try
        once more Balsamic's own install that waits for a confirmation its dry run, read again, does not need (Installer.reparsed)."""
        if not self.installing():
            return
        from optimization_framework.campaigns.method_catalog import latest_submissions
        from .development_runtime import ROOT
        from .library_install import Installer
        tried = {row.get("submission_id") for row in self.store.list("library_install", campaign_id)}
        for submission in latest_submissions(self.store, campaign_id):
            if submission["status"] not in {"submitted", "validated"}:
                continue
            installer = Installer(self.workspace, self, ROOT)
            if submission["id"] not in tried:
                installer.automatic(campaign_id, submission["workspace_id"], submission)
            else:
                installer.reparsed(campaign_id, submission)

    def get(self, campaign_id, identity):
        record = self.store.get(identity, "development_workspace")
        if record["campaign_id"] != campaign_id:
            raise ValueError("Implementation workspace belongs to another campaign")
        return record

    def workspace_events(self, record):
        return sorted((e for e in self.store.list("development_event", record["campaign_id"]) if e["workspace_id"] == record["id"]),
                      key=lambda e: e["seq"])

    def public(self, record, events=None):
        base = os.environ.get("GRATING_DEVELOPMENT_PUBLIC_URL", "").rstrip("/")
        runtime = record.get("runtime") or {}
        events = self.workspace_events(record) if events is None else events
        errors = [e["occurred_at"] for e in events if e["type"] in ERROR_EVENTS or (e["type"] == "tool" and e["payload"].get("error"))]
        return {**{k: v for k, v in record.items() if k not in {"runtime", "cpu_last", "event_files", "request_hash"}},
            "hypothesis_ids": record.get("hypothesis_ids") or [record["hypothesis_id"]],
            # Every checkpoint, not only the latest: what the coding agent said it had done, and when.
            "checkpoints": [{"at": e["occurred_at"], **e["payload"]} for e in events if e["type"] == "checkpoint"][-20:],
            "last_error_at": errors[-1] if errors else None,
            **self._result(record),
            "ide_url": base + f"/implementation-workspaces/{record['id']}/ide/?folder=/work/repo",
            "runtime": {"running": runtime.get("running", False), "paused": runtime.get("paused", False)},
            "terminal_command": f"docker exec --user 1000:1000 -it {self.driver.name(record)} tmux attach-session -t implementation",
            "validation_envelopes": [{k: v for k, v in e.items() if k != "spec"}
                for e in self.store.list("development_envelope", record["campaign_id"]) if e["workspace_id"] == record["id"]],
            "submissions": sorted(({k: v for k, v in s.items() if k != "package"} for s in self.store.list("development_submission", record["campaign_id"])
                                   if s["workspace_id"] == record["id"]), key=lambda s: s["created_at"]),
            "questions": [q for q in self.store.list("development_question", record["campaign_id"]) if q["workspace_id"] == record["id"] and q["status"] == "pending"],
            # The installs of what it delivered (Balsamic's own and the researcher's), newest last.
            "installs": sorted((i for i in self.store.list("library_install", record["campaign_id"]) if i.get("workspace_id") == record["id"]),
                               key=lambda i: i["requested_at"])}

    def _result(self, record):
        result = outcome(record, self.store.list("development_submission", record["campaign_id"]))
        return {"outcome": result, "finished_at": result["at"] if result and record.get("status") not in LIVE else None}

    def disabled(self):
        """Why workspaces are refused, and the two ways on: the commission the agents can make now, the switch the researcher can turn."""
        image = getattr(self.driver, "image", IMAGE)
        return ("Full implementation workspaces are disabled in the server configuration. Commission the implementation instead "
                "(implementation.commission, by the implementation lead): builders, test designers and reviewers build and validate it "
                "without a workspace. The researcher can turn workspaces on: build the image (docker build -t " + image + " "
                "deploy/implementation-workspace), then restart the lab with GRATING_DEVELOPMENT_ENABLED=true (scripts/stop, then "
                "GRATING_DEVELOPMENT_ENABLED=true scripts/start; development_enabled in a launcher file).")

    def view(self, campaign_id):
        events = {}
        for event in sorted(self.store.list("development_event", campaign_id), key=lambda e: e["seq"]):
            events.setdefault(event["workspace_id"], []).append(event)
        return {"enabled": self.enabled(), **({} if self.enabled() else {"disabled": self.disabled()}),
                "workspaces": [self.public(r, events.get(r["id"], [])) for r in self.store.list("development_workspace", campaign_id)]}

    def create(self, campaign_id, payload, *, actor="researcher", opener=None, root=None):
        """opener: the agent that opens it ({agent_id, role}), when an agent does; root: the researcher's request its turn
        works on (controller.request_root), which the workspace's notices continue."""
        if not self.enabled():
            raise ValueError(self.disabled())
        values = WorkspaceCreate.model_validate(payload)
        hypothesis = self.store.get(values.hypothesis_id, "hypothesis")
        if hypothesis["campaign_id"] != campaign_id or hypothesis["status"] in {"archived", "finalist"}:
            raise ValueError("Choose an active hypothesis in this campaign")
        served = [values.hypothesis_id]
        for other in values.hypothesis_ids:
            try:
                row = self.store.get(other, "hypothesis")
            except KeyError:
                raise ValueError(f"No proposal {other}") from None
            if row["campaign_id"] != campaign_id:
                raise ValueError(f"Proposal {other} belongs to another campaign")
            if other not in served:
                served.append(other)
        identity = "development_" + content_hash([campaign_id, values.hypothesis_id])[:24]
        with self.workspace.lock, self.store.transaction():
            try:
                saved = self.get(campaign_id, identity)
                if saved["request_key"] == values.request_key and saved["request_hash"] != request_hash(values):
                    raise ValueError("Workspace request key was reused with different content")
                return self.public(saved)
            except KeyError:
                pass
            from optimization_framework.campaigns import compute_consent
            consent = None
            if actor != "researcher":
                consent = compute_consent.require(self.workspace, campaign_id, "Opening a coding workspace", coding=1, hypothesis_ids=served)
            for evidence_id in values.evidence_ids:
                self.evidence(campaign_id, evidence_id)
            config = self.controller.configuration(campaign_id)
            if not config or not config["enabled"]:
                raise ValueError("Activate the campaign lead agent before creating an implementation workspace")
            # The coding agent runs on the campaign's own model, as its agents do.
            default = (config.get("models") or {}).get("default") or LEGACY_MODEL
            record = {"id": identity, "campaign_id": campaign_id, "hypothesis_id": values.hypothesis_id, "hypothesis_ids": served,
                "title": hypothesis["title"], "parent_agent_id": config["lead_id"], "created_at": now(),
                "opened_by": {"actor": actor, **(opener or {})}, "request_root": root,
                # The researcher's go-ahead it opened under, for the history: the approved plan, not a deadline.
                "consent": {"id": consent["id"], "decision_id": consent.get("decision_id"), "plan": (consent.get("plan") or "")[:2000]} if consent else None,
                "objective": values.objective, "evidence_ids": values.evidence_ids,
                "request_key": values.request_key, "request_hash": request_hash(values),
                "status": "queued", "desired_status": "running", "control_revision": 0,
                "guidance_revision": 0, "cpu_budget_seconds": values.cpu_budget_seconds,
                "model": {key: default.get(key) for key in ("provider", "model", "effort")},
                "usage": {"container_cpu_seconds": 0, "subscription_calls": 0, "input": 0, "output": 0,
                          "billing_mode": "subscription", "api_cost_usd": 0}, "event_files": [], "cursor": 0}
            self.store.put("development_workspace", record, "development.created")
            if actor != "researcher":
                compute_consent.charge(self.workspace, campaign_id, coding=1, what="a coding workspace", subjects=[identity], hypothesis_ids=served)
            self.message(campaign_id, identity, {"message": values.objective +
                "\nRead .campaign/assignment.md and .campaign/evidence.json first. Save checkpoints in .campaign/checkpoint.md. "
                "Use the normal Pi coding tools to implement, debug, and test. Submit a committed package with campaign_submit. "
                "Use campaign_checkpoint for progress, questions, and blockers. Continue authorized development until a concrete submission or genuine blocker.",
                "request_key": "initial-" + values.request_key, "mode": "follow_up"}, actor=actor)
            return self.public(self.get(campaign_id, identity))

    def evidence(self, campaign_id, identity):
        entry = self.store.get_entry(identity)
        data = entry["data"]
        if data.get("campaign_id") != campaign_id or entry["kind"] not in {
                "source", "source_excerpt", "hypothesis", "agent_artifact", "discovery_handoff", "discovery_artifact",
                "discovery_candidate", "implementation_reference", "reference_correction"}:
            raise ValueError("Evidence is not shareable implementation context in this campaign")
        if data.get("agent_id"):
            author = self.store.get(data["agent_id"], "agent_session")
            if author["role"] in {"implementation_test_designer", "implementation_validator"}:
                raise ValueError("Protected reviewer context cannot enter a builder workspace")
        return {"kind": entry["kind"], "data": data}

    def _command(self, record, values, actor):
        identity = "development_command_" + content_hash([record["id"], values["request_key"]])[:24]
        request_hash = content_hash([values, actor])
        try:
            old = self.store.get(identity, "development_command")
            # Commands saved before the role rename hashed actor "pi".
            legacy = content_hash([values, "pi"]) if actor == "lead" else request_hash
            if old["request_hash"] not in {request_hash, legacy}:
                raise ValueError("Command identity was reused with different content")
            return old
        except KeyError:
            pass
        return self.store.put("development_command", {"id": identity, "campaign_id": record["campaign_id"],
            "workspace_id": record["id"], "created_at": now(), "request_hash": request_hash,
            "actor": actor, "status": "queued", **values}, "development.command_queued")

    def message(self, campaign_id, identity, payload, *, actor="researcher"):
        values = WorkspaceMessage.model_validate(payload)
        with self.workspace.lock, self.store.transaction():
            record = self.get(campaign_id, identity)
            command = self._command(record, {"operation": "message", **values.model_dump()}, actor)
            if command.get("recorded"):
                return command
            if values.question_id:
                question = self.store.get(values.question_id, "development_question")
                if question["workspace_id"] != identity or question["status"] != "pending":
                    raise ValueError("Question is not pending in this workspace")
                question.update(status="answered", answer=values.message, answered_at=now())
                self.store.put("development_question", question)
            if actor == "researcher":
                record["guidance_revision"] += 1
                self.store.put("development_workspace", record)
                self.notify(record, command["id"], "The developer directed the implementation agent: " + values.message)
            command.update(recorded=True, guidance_revision=record["guidance_revision"])
            self.store.put("development_command", command)
            self.event(record, "input_" + command["id"], "instruction", {"text": values.message, "actor": actor, "command_id": command["id"], "status": "queued"})
            return command

    def control(self, campaign_id, identity, payload, *, actor="researcher"):
        values = WorkspaceControl.model_validate(payload)
        with self.workspace.lock, self.store.transaction():
            record = self.get(campaign_id, identity)
            command = self._command(record, {"operation": values.action, **values.model_dump()}, actor)
            if command.get("recorded"):
                return self.public(record)
            if record["control_revision"] != values.expected_revision:
                raise ValueError("Workspace control changed; refresh before continuing")
            if values.action == "resume" and record.get("cpu_budget_seconds") is not None and record["usage"]["container_cpu_seconds"] >= record["cpu_budget_seconds"]:
                raise ValueError("Development CPU allowance is exhausted; retain the checkpoint and explicitly extend the allowance")
            record.update(desired_status={"resume": "running", "pause": "paused", "stop": "stopped"}[values.action],
                control_revision=record["control_revision"] + 1, control_requested_at=now(),
                status="resuming" if values.action == "resume" else "pausing" if values.action == "pause" else "stopping")
            record.pop("error", None)
            command["recorded"] = True
            self.store.put("development_command", command)
            self.store.put("development_workspace", record, "development.control_requested")
            return self.public(record)

    def recipient(self, record, config):
        """Who a workspace's notices go to: the agent that opened it while it is a live agent of this campaign, else the lead."""
        opener = (record.get("opened_by") or {}).get("agent_id")
        try:
            agent = self.store.get(opener, "agent_session") if opener else None
        except KeyError:
            agent = None
        if agent and agent["campaign_id"] == record["campaign_id"] and agent["status"] not in {"stopped", "completed", "failed"}:
            return agent
        return self.store.get(config["lead_id"], "agent_session")

    def notify(self, record, key, text, read="its status"):
        """A platform notice of a change in the workspace, to whoever opened it, continuing the request it was opened for.
        read: the part of implementation_workspace_inspect that has the details."""
        config = self.controller.configuration(record["campaign_id"])
        if not config or not config["enabled"]:
            return
        agent, root = self.recipient(record, config), record.get("request_root")
        text = (NOTICE + f"Implementation workspace {record['id']} ({record['title']}): {text}\n"
                f"Read {read} in implementation_workspace_inspect. A development result is not protected validation.")
        identity = "pi_development_" + content_hash([record["id"], key])[:24]
        if agent["role"] == LEAD:
            self.controller.enqueue(agent, identity, text, root=root)
        else:
            # Another agent's turn names the request it continues in its origin, as the lead's does (controller.enqueue).
            self.controller.enqueue(agent, identity, text, origin={**root, "actor": "lab", "root": root} if root else None)

    def event(self, record, key, event_type, payload):
        identity = "development_event_" + content_hash([record["id"], key])[:24]
        try:
            return self.store.get(identity, "development_event")
        except KeyError:
            pass
        current = self.get(record["campaign_id"], record["id"])
        current["cursor"] += 1
        self.store.put("development_workspace", current)
        return self.store.put_immutable("development_event", {"id": identity, "campaign_id": record["campaign_id"],
            "workspace_id": record["id"], "seq": current["cursor"], "type": event_type, "occurred_at": now(), "payload": payload})

    def events(self, campaign_id, identity, after=0):
        record = self.get(campaign_id, identity)
        events = sorted((e for e in self.store.list("development_event", campaign_id)
                         if e["workspace_id"] == identity and e["seq"] > after), key=lambda e: e["seq"])
        events = events[:100] if after else events[-100:]
        commands = [c for c in self.store.list("development_command", campaign_id) if c["workspace_id"] == identity]
        return {"workspace": self.public(record), "events": events, "cursor": events[-1]["seq"] if events else after, "commands": commands[-100:]}

    def sync(self, campaign_id):
        try:
            self.install_delivered(campaign_id)
        except Exception as exc:   # an install never stops the workspaces' own sync
            import logging
            logging.getLogger(__name__).warning("Installing a delivered library failed: %s", exc)
        for saved in self.store.list("development_workspace", campaign_id):
            try:
                self._sync_one(saved)
            except Exception as exc:
                with self.workspace.lock, self.store.transaction():
                    record = self.get(campaign_id, saved["id"])
                    error = str(exc)[:2000]
                    changed = record.get("error") != error
                    record.setdefault("blocked_since", now())
                    record.update(error=error, status="blocked")
                    self.store.put("development_workspace", record, "development.blocked" if changed else None)
                    if changed:
                        self.event(record, f"host_blocked_{record['cursor']}", "host_blocked", {"error": error})
                        self.notify(record, "blocker_" + content_hash(error), error + " Saved work is retained; capability will be rechecked automatically.")

    def _sync_one(self, saved):
        cid, identity = saved["campaign_id"], saved["id"]
        root = self.driver.root(saved)
        record = self.get(cid, identity)
        if record["desired_status"] == "running" and self.enabled():
            if not (root / "prepared.json").exists():
                capability = self.driver.capability()
                if not capability["available"]:
                    raise ValueError(capability["reason"])
                evidence = [self.evidence(cid, ref) for ref in record["evidence_ids"]]
                hypothesis = self.store.get(record["hypothesis_id"], "hypothesis")
                brief = f"# {record['title']}\n\n{record['objective']}\n\n## Hypothesis\n\n" + json.dumps(hypothesis, indent=2) + "\n\n" + DEVELOPMENT_INSTRUCTIONS
                self.driver.prepare(record, brief, evidence)
                atomic_json(root / "prepared.json", {"workspace_id": identity})
            runtime = self.driver.start(record)
            with self.workspace.lock:
                record = self.get(cid, identity)
                recovered = bool(record.get("error"))
                record.update(runtime=runtime)
                record.pop("error", None)
                record.pop("blocked_since", None)
                if record["status"] in {"queued", "blocked", "resuming", "stopped"}:
                    record["status"] = "starting"
                self.store.put("development_workspace", record)
                if recovered:
                    self.event(record, f"host_recovered_{record['cursor']}", "host_recovered", {})
                    self.notify(record, "recovered_" + str(record["cursor"]), "Workspace capability recovered. Continue within existing authorization.")
        runtime = record.get("runtime") or self.driver.inspect(record)
        cpu = self.driver.cpu_seconds(runtime)
        with self.workspace.lock:
            record = self.get(cid, identity)
            if cpu is not None:
                old = record.get("cpu_last", 0)
                record["usage"]["container_cpu_seconds"] += cpu - old if cpu >= old else cpu
                record["cpu_last"] = cpu
                self.store.put("development_workspace", record)
        # Host-authored commands are mounted read-only in the container.
        for command in self.store.list("development_command", cid):
            if command["workspace_id"] != identity or command["status"] != "queued":
                continue
            target = root / "incoming/commands" / (command["created_at"].replace(":", "-") + "_" + command["id"] + ".json")
            if target.parent.exists() and not target.exists():
                atomic_json(target, command)
        self.receive(record)
        self.validation_feedback(record)
        record = self.get(cid, identity)
        budget = record.get("cpu_budget_seconds")
        used = record["usage"]["container_cpu_seconds"]
        if budget is not None and used >= budget and record["desired_status"] == "running":
            with self.workspace.lock:
                record.update(desired_status="paused", status="pausing", control_requested_at=now(),
                              error="Development CPU allowance reached. Workspace and session are saved.")
                self.store.put("development_workspace", record, "development.budget_reached")
                self.event(record, "budget_reached_" + str(budget), "budget_reached", {"used": used, "budget": budget})
                self.notify(record, "budget_" + str(budget), record["error"])
        elif budget is not None and used >= .8 * budget and not record.get("budget_checkpoint_requested"):
            self.message(cid, identity, {"message": "Development CPU allowance is approaching its limit. Save .campaign/checkpoint.md and use campaign_checkpoint with remaining work before starting more expensive commands.",
                "request_key": "budget-checkpoint-" + str(budget), "mode": "steer"}, actor="system")
            record = self.get(cid, identity)
            record["budget_checkpoint_requested"] = True
            self.store.put("development_workspace", record)
            self.event(record, "budget_warning_" + str(budget), "budget_warning", {"used": used, "budget": budget})
        if record["desired_status"] in {"paused", "stopped"}:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(record.get("control_requested_at", record["created_at"]))).total_seconds()
            if record.get("control_acknowledged") or elapsed >= 5 or (budget is not None and used >= budget):
                if record["desired_status"] == "paused":
                    self.driver.pause(record)
                else:
                    self.driver.stop(record)
                with self.workspace.lock:
                    current = self.get(cid, identity)
                    current["status"] = record["desired_status"]
                    current.pop("control_acknowledged", None)
                    self.store.put("development_workspace", current)

    def receive(self, record):
        root = self.driver.root(record)
        for path in sorted((root / "outgoing/events").glob("*.json"))[:200]:
            if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                event = json.loads(path.read_text())
                key = path.stem
                with self.workspace.lock, self.store.transaction():
                    current = self.get(record["campaign_id"], record["id"])
                    event_id = "development_event_" + content_hash([record["id"], key])[:24]
                    try:
                        self.store.get(event_id, "development_event")
                        continue
                    except KeyError:
                        pass
                    kind, payload = event["type"], event.get("payload", {})
                    # Submissions execute no candidate code on the host. Capture below,
                    # outside the transaction, before any scientific authority is granted.
                    if kind == "submission":
                        pass
                    else:
                        self._apply_event(current, key, kind, payload)
                        self.event(current, key, kind, payload)
                if kind == "submission":
                    self.capture_submission(record, key, payload)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                with self.workspace.lock, self.store.transaction():
                    self.event(record, path.stem, "bridge_error", {"error": str(exc)[:2000]})
                atomic_json(root / "incoming/results" / (path.stem + ".json"), {"error": str(exc)[:2000]})
            finally:
                # The canonical append-only record survives; archiving also bounds polling.
                archive = root / "outgoing/received"
                archive.mkdir(exist_ok=True)
                path.rename(archive / path.name)

    def _apply_event(self, record, key, kind, payload):
        cid = record["campaign_id"]
        if kind == "receipt":
            command = self.store.get(payload["command_id"], "development_command")
            if command["workspace_id"] != record["id"]:
                raise ValueError("Receipt belongs to another workspace")
            command.update(status=payload["status"], acknowledged_at=now())
            self.store.put("development_command", command)
            if command["operation"] in {"pause", "stop"}:
                record["control_acknowledged"] = True
        elif kind == "ready":
            record.update(status="idle", session_id=payload.get("session_id"), active_tools=payload.get("tools", []))
        elif kind == "agent_start":
            record["status"] = "running"
        elif kind == "agent_settled":
            record["status"] = "idle"
        elif kind == "checkpoint":
            before, phase = record.get("checkpoint") or {}, record.get("phase")
            record["checkpoint"] = payload
            record["activity"] = payload.get("summary", "")[:2000]
            found = progress(payload)
            record.update({key: found[key] for key in ("phase", "tests") if key in found})
            if "eta_minutes" in found:
                record["estimate"] = {"remaining_minutes": found["eta_minutes"], "given_at": now(), "source": "coding agent"}
            # Progress updates only the record and the timeline; a question or a new blocker is a notice.
            if payload.get("question"):
                question = self.store.put("development_question", {"id": "development_question_" + content_hash([record["id"], key])[:24],
                    "workspace_id": record["id"], "campaign_id": cid, "question": payload["question"], "status": "pending", "created_at": now()}, "development.question_created")
                self.notify(record, key, f"The coding agent asks ({question['id']}): {excerpt(payload['question'])} Answer with "
                            "implementation_workspace_message and that question_id.", "questions")
            elif (payload.get("blocker") and payload["blocker"] != before.get("blocker")) or (found.get("phase") == "blocked" and phase != "blocked"):
                self.notify(record, key, "The coding agent is blocked: " + excerpt(payload.get("blocker") or payload.get("summary")), "checkpoints")
        elif kind == "message" and payload.get("role") == "assistant":
            usage = payload.get("usage")
            if usage:
                record["usage"]["subscription_calls"] += 1
                for name in ("input", "output", "cacheRead", "cacheWrite"):
                    record["usage"][name] = record["usage"].get(name, 0) + usage.get(name, 0)
            record["activity"] = payload.get("text", "")[-2000:]
        at = now()
        if kind in {"ready", "agent_start"} and not record.get("started_at"):
            record["started_at"] = at
        record["last_activity_at"] = record["updated_at"] = at
        self.store.put("development_workspace", record, PUT_EVENTS.get(kind))

    def delivery_report(self, record, raw):
        """The submission's delivery report, checked; None from an extension that sends none."""
        if raw is None:
            return None
        report = plain(DeliveryReport.model_validate(raw).model_dump(mode="json"))
        for index, method in enumerate(report["methods"]):
            if method.get("hypothesis_id"):
                try:
                    row = self.store.get(method["hypothesis_id"], "hypothesis")
                except KeyError:
                    row = {}
                if row.get("campaign_id") != record["campaign_id"]:
                    raise ValueError(f"report.methods[{index}].hypothesis_id: {method['hypothesis_id']} is not a proposal of this campaign")
        return report

    def capture_submission(self, record, key, payload):
        report = self.delivery_report(record, payload.get("report"))
        package, manifest = self.driver.snapshot(record, payload["commit"], payload.get("manifest_path", "implementation-manifest.json"))
        with self.workspace.lock, self.store.transaction():
            identity = "development_submission_" + content_hash([record["id"], payload["commit"], package, manifest])[:24]
            submission = {"id": identity, "campaign_id": record["campaign_id"], "workspace_id": record["id"],
                "hypothesis_id": record["hypothesis_id"], "hypothesis_ids": record.get("hypothesis_ids") or [record["hypothesis_id"]],
                "commit": payload["commit"], "package": package, "manifest": manifest, "notes": payload.get("notes", ""),
                "report": report, "status": "submitted", "created_at": now()}
            try:
                saved = self.store.get(identity, "development_submission")
                if report and saved.get("report") != report:   # the same commit again: its latest report stands
                    saved["report"] = report
                    self.store.put("development_submission", saved, "development.submitted")
            except KeyError:
                saved = self.store.put("development_submission", submission, "development.submitted")
                verdict = f" The coding agent's verdict: {report['verdict'].replace('_', ' ')}; next: " + ("; ".join(
                    f"{a['owner']}: {a['action']}" for a in report["next_actions"]) or "nothing named") + "." if report else " It sent no delivery report."
                self.notify(record, identity, f"Commit {submission['commit']} submitted as {identity}.{verdict} Review its manifest and commission independent validation using implementation_workspace_validate under the compute go-ahead.", "submissions")
            self.event(record, key, "submission", {"submission_id": identity, "commit": payload["commit"]})
        atomic_json(self.driver.root(record) / "incoming/results" / (key + ".json"), {"submission_id": saved["id"], "status": saved["status"]})

    def validate(self, campaign_id, identity, payload, *, actor="researcher"):
        from optimization_framework.implementations.models import BoundOptimizerSpec, ImplementationSpec
        from .capabilities import implementation_execution
        values = WorkspaceValidate.model_validate(payload)
        record = self.get(campaign_id, identity)
        submission = self.store.get(values.submission_id, "development_submission")
        if submission["workspace_id"] != identity:
            raise ValueError("Submission belongs to another workspace")
        source = values.spec
        if values.envelope_id:
            envelope = self.store.get(values.envelope_id, "development_envelope")
            if envelope["workspace_id"] != identity or envelope["campaign_id"] != campaign_id:
                raise ValueError("Validation envelope belongs to another workspace")
            source = envelope["spec"]
        spec = (BoundOptimizerSpec if source.get("evaluator_version_id") else ImplementationSpec).model_validate(source)
        if spec.dependencies != submission["manifest"]["dependencies"]:
            raise ValueError("Validation dependencies must match the committed submission manifest")
        capability = implementation_execution()
        if not capability["available"]:
            raise ValueError("Protected validation is unavailable: " + capability["reason"])
        from optimization_framework.campaigns import compute_consent
        served = record.get("hypothesis_ids") or [record["hypothesis_id"]]   # a go-ahead covers the validation of what it opened
        if actor != "researcher":
            compute_consent.require(self.workspace, campaign_id, "Validating a submission", values.compute_seconds, hypothesis_ids=served)
        grant = self.workspace.implementations.reserve_commission(record["hypothesis_id"], spec,
            compute_seconds=values.compute_seconds, max_calls=12, api_budget_usd=0,
            idempotency_key="development-" + content_hash([identity, values.request_key])[:24],
            package=submission["package"], accounting_mode="execution_v1")
        if actor != "researcher":
            compute_consent.charge(self.workspace, campaign_id, values.compute_seconds, what="a validation of a coding workspace's submission",
                                   subjects=[identity], hypothesis_ids=served)
        # A validation of the same submission again: its result is news to the coding agent, like the first one's.
        submission.update(grant_id=grant["id"], status="validating", feedback_sent=False)
        self.store.put("development_submission", submission, "development.validation_requested")
        return {"submission_id": submission["id"], "grant_id": grant["id"]}

    def freeze_envelope(self, campaign_id, identity, payload):
        from optimization_framework.implementations.models import BoundOptimizerSpec, ImplementationSpec, digest
        values = WorkspaceEnvelope.model_validate(payload)
        record = self.get(campaign_id, identity)
        spec = (BoundOptimizerSpec if values.spec.get("evaluator_version_id") else ImplementationSpec).model_validate(values.spec)
        self.workspace.implementations.check_self_contained(spec.model_dump(mode="json"))
        if spec.problem_id != self.store.get(record["hypothesis_id"], "hypothesis").get("problem_id", spec.problem_id):
            raise ValueError("Validation envelope uses a different problem")
        serialized = spec.model_dump(mode="json")
        identity_hash = digest(serialized)
        envelope_id = "development_envelope_" + content_hash([identity, identity_hash])[:24]
        with self.workspace.lock, self.store.transaction():
            try:
                saved = self.store.get(envelope_id, "development_envelope")
            except KeyError:
                saved = self.store.put_immutable("development_envelope", {"id": envelope_id,
                    "workspace_id": identity, "campaign_id": campaign_id, "hypothesis_id": record["hypothesis_id"],
                    "created_at": now(), "request_key": values.request_key, "spec_digest": identity_hash,
                    "spec": serialized, "checks": {"behavior": len(spec.behavior_checks),
                        "mechanism": len(spec.mechanism_checks), "diagnostic": len(spec.diagnostic_checks)},
                    "problem_id": spec.problem_id, "n_cells": [spec.n_cells_min, spec.n_cells_max],
                    "dependencies": spec.dependencies}, "development.envelope_frozen")
                self.notify(record, envelope_id, f"Protected validation envelope {envelope_id} frozen with spec digest {identity_hash}. Use this ID with implementation_workspace_validate after an exact submission and explicit remaining allocation; do not reinsert the full specification into the lead agent's context.", "validation_envelopes")
            return {k: v for k, v in saved.items() if k != "spec"}

    def validation_feedback(self, record):
        for submission in self.store.list("development_submission", record["campaign_id"]):
            if submission["workspace_id"] != record["id"] or not submission.get("grant_id"):
                continue
            if (submission.get("validation_outcome") or {}).get("id") == submission["grant_id"]:
                continue   # this grant's result is recorded
            grant = self.store.get(submission["grant_id"], "implementation_grant")
            if grant["status"] not in {"completed", "failed", "blocked", "interrupted", "cancelled", "needs_reconciliation"}:
                continue
            # Only public findings and the grant identity go back; protected fixture
            # source and independent reviewer context remain in the service.
            feedback = {k: grant.get(k) for k in ("id", "status", "version_id", "error", "compute_seconds")}
            feedback["findings"] = []
            for attempt in grant.get("attempts", []):
                report = attempt.get("report") or {}
                feedback["findings"].extend({"check": check.get("name"), "detail": str(check.get("detail", ""))[:1000]}
                    for check in report.get("checks", []) if check.get("passed") is False)
                review = attempt.get("review") or {}
                feedback["findings"].extend({"review": str(item)[:1000]} for item in review.get("findings", []))
            # A result recorded before a repeated validation reset feedback_sent is corrected here without waking the agent again.
            if not submission.get("feedback_sent"):
                self.message(record["campaign_id"], record["id"], {"message": "Independent validation outcome for " + submission["commit"] + ":\n" + json.dumps(feedback)
                    + "\nInspect the recorded outcome. Preserve this revision. Repair failures in a new commit when authorized; a new validation run needs remaining allocation.",
                    "request_key": "validation-feedback-" + submission["id"] + "-" + grant["id"], "mode": "follow_up"}, actor="system")
            submission.update(status="validated" if grant["status"] == "completed" else "needs_revision", feedback_sent=True,
                              version_id=grant.get("version_id"), validation_outcome=feedback,
                              validated_at=grant.get("finished_at") or grant.get("updated_at") or now())
            self.store.put("development_submission", submission)


DEVELOPMENT_INSTRUCTIONS = """## Development workflow

This is a complete Pi coding workspace. Use read, edit, write, bash, Git, tests,
dependency installation, skills, and project instructions. You can install Python
packages with `python -m pip install --user ...`. Code runs in this workspace's
container. `/references/flrl` contains the author's reference code when available;
`/references/paper.txt` and `/references/paper.pdf` contain the supplied paper.
The host campaign database, private files, protected validation fixtures, and
Docker socket are outside this environment. Public network access is available;
new connections to host, TailNet, and private network services are blocked.

The developer and the campaign lead agent can steer this same session. Explicit
developer direction takes precedence over conflicting lead-agent guidance. Reread files changed by
the developer before editing them. Save decisions and continuation instructions
in `.campaign/checkpoint.md`; use `campaign_checkpoint` for progress or questions.
Compaction and reconnects preserve this file, evidence, repository, and session.

Implement the method as a library under `libraries/<name>/`, the way
`libraries/grating-mask-search` and docs/optimizer-plugins.md do: a module per method
following the optimizer_v1 package contract (`create_optimizer(context)`, then
initialize, propose, observe, checkpoint as bytes, restore, inspect), with no Balsamic
imports; your own tests showing it does what the specification says; `plugin.py`
listing the methods for the `optimization_framework.optimizers` entry point in its
`pyproject.toml`; and a README naming the specification. An `export_artifacts` item's
`kind` is one Balsamic's catalog holds: `solution` for a best design,
`learner_diagnostics` for a search log. Copy `tests/test_contract.py`
from the example and name your methods in it: it runs Balsamic's contract checks
(valid candidates, seeded replay, checkpoint continuation, export kinds) and needs Balsamic itself
(`python -m pip install --user -e .`), else it runs on the host.

Commit the library and an `implementation-manifest.json` holding exactly `contract`
(optimizer_v1), `entrypoint` (module:factory), `files` (the library's
repository-relative paths), exact `dependencies`, and a `test_summary`, and nothing else.
Submit the full commit hash with `campaign_submit` and your delivery report: your verdict
(ready only when every method is implemented, its conformance check passed, no test fails
and nothing is limited; ready_with_limits with the limitations; not_ready with what must
happen next), each method's id, proposal, state, tests and conformance, the totals of your
test run with its command, and the next actions with who does each. The researcher reads this
report as the outcome of your work. Balsamic installs the library in the lab when you deliver
it (unless you report it not ready), so installing is nobody's next action. Raise the
library's version with each new delivery: the running lab loads its new code only when the
version changes.

At each `campaign_checkpoint`, give your phase, what is done and what remains, the latest
test counts and your estimate of the minutes left until you submit: the researcher follows
your work by these. Balsamic installs the library once you deliver it with its tests
passing (`uv run pytest libraries/<name>`); a proposal then runs by naming its method.
Use a new commit for each repair. Whether the method performs well is for the
campaign's experiments and the researcher, not something the implementation proves.

This session has no programming wall-clock deadline. Container CPU usage is
measured separately; an optional development CPU allowance is shown in the
campaign. Existing experiment and protected validation allocations still apply.
"""
