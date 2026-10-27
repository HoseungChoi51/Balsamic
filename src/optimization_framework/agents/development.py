"""Persistent implementation workspaces, independent of short validation grants."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from optimization_framework.contracts.base import Contract, content_hash, field_names, lenient
from optimization_framework.contracts.commands import HOSTNAME
from optimization_framework.storage.sqlite import atomic_json, now
from .development_runtime import HARNESSES, IMAGE, LEGACY_MODEL, LIMITS, DockerWorkspace, ceilings, egress, harness, harness_refusal
from .development_ticket import TicketInput
from .models import LEAD, NOTICE


class WorkspaceLimits(Contract):
    """What the box's container may use, within the researcher's ceilings (development_runtime.ceilings)."""
    cpus: float = Field(default=LIMITS["cpus"], gt=0, le=128)
    memory_gb: float = Field(default=LIMITS["memory_gb"], gt=0, le=1024)
    gpus: int = Field(default=0, ge=0, le=16)


class WorkspaceCreate(Contract):
    hypothesis_id: str
    # The other proposals the same library serves: shown with the workspace and in what it delivers.
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=20)
    objective: str = Field(default="Implement this method from the saved specification and references.", min_length=1, max_length=50000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    request_key: str = Field(min_length=1, max_length=200)
    cpu_budget_seconds: float | None = Field(default=None, gt=0, le=86400)
    # The box's walls (H5): its wall-clock deadline from its first start (an agent's defaults to its go-ahead's wall time),
    # its limits, and the hosts beyond its model and the package index it may reach (an agent's must be approved with it).
    wall_seconds: float | None = Field(default=None, gt=0, le=604800)
    limits: WorkspaceLimits | None = None
    egress_hosts: list[str] = Field(default_factory=list, max_length=20)
    # Its coding harness (H2): only pi has an adapter; in its terminal UI unless this or the lab (GRATING_DEVELOPMENT_HARNESS_MODE)
    # says headless.
    harness: str = Field(default="pi", max_length=100)
    harness_mode: Literal["tui", "headless"] | None = None
    # The implementation lead's part of the work ticket (H4): acceptance tests the coding agent sees, protected ones it never does.
    ticket: TicketInput | None = None

    @model_validator(mode="after")
    def hostnames(self):
        import re
        bad = [host for host in self.egress_hosts if not re.fullmatch(HOSTNAME, host)]
        if bad:
            raise ValueError("egress_hosts: name each host by its lowercase DNS name, without scheme, port or path: " + ", ".join(bad))
        if self.harness not in HARNESSES:
            raise ValueError(harness_refusal(self.harness))
        return self


class WorkspaceMessage(Contract):
    message: str = Field(min_length=1, max_length=50000)
    mode: Literal["steer", "follow_up"] = "steer"
    request_key: str = Field(min_length=1, max_length=200)
    question_id: str | None = None


class WorkspaceControl(Contract):
    action: Literal["pause", "resume", "stop"]
    request_key: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    # resume: a new deadline, this long from now; past the deadline, going on is a new go-ahead and needs one.
    wall_seconds: float | None = Field(default=None, gt=0, le=604800)


class SubmissionManifest(Contract):
    contract: Literal["ask_tell", "optimizer_v1"] = "optimizer_v1"
    entrypoint: str = "optimizer:create_optimizer"
    files: list[str] = Field(min_length=1, max_length=100)
    dependencies: dict[str, str] = Field(default_factory=dict, max_length=20)
    test_summary: str = Field(default="", max_length=10000)


def submission_manifest(text, tracked):
    """A submission's manifest and the keys it ignored (decision 5).

    ``text`` is the committed manifest, None when the commit has none; ``tracked`` lists the commit's files under
    ``libraries/``. Unknown keys are dropped and reported, a near-miss is refused. With no manifest one is derived: every
    tracked file of the commit's single library, with the default contract and entry point.
    """
    if text is None:
        libraries = {}
        for path in tracked:
            parts = path.split("/")
            if len(parts) > 2 and parts[0] == "libraries":
                libraries.setdefault(parts[1], []).append(path)
        if len(libraries) != 1:
            raise ValueError("Commit an implementation-manifest.json: the commit has " + (
                f"{len(libraries)} libraries ({', '.join(sorted(libraries))})" if libraries else "no library under libraries/")
                + ", so its files cannot be derived")
        return SubmissionManifest(files=sorted(next(iter(libraries.values())))), []
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return SubmissionManifest.model_validate(raw), []
    known, ignored = lenient(raw, field_names(SubmissionManifest))
    return SubmissionManifest.model_validate(known), ignored


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


def past(at):
    """Whether a recorded time has come."""
    return bool(at) and datetime.fromisoformat(at) <= datetime.now(timezone.utc)


def after(seconds):
    """The time this many seconds from now, as records keep it."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


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
    for key in ("hypothesis_ids", "wall_seconds", "limits", "egress_hosts", "harness_mode", "ticket"):
        if not dump.get(key):
            dump.pop(key, None)
    if dump.get("harness") == "pi":   # the one harness: naming it changes nothing
        dump.pop("harness")
    return content_hash(dump)


# Workspace events by the store event they put the workspace with: the pages that show a workspace refresh on them.
PUT_EVENTS = {"ready": "development.progress", "agent_start": "development.progress", "agent_settled": "development.progress",
              "message": "development.progress", "tool": "development.progress", "checkpoint": "development.checkpoint",
              "harness_error": "development.progress"}
# Events that are errors in their own right; a failed tool call is one when the event says so.
ERROR_EVENTS = {"bridge_error", "host_blocked", "budget_reached", "deadline_reached", "harness_error"}


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
        return {**{k: v for k, v in record.items() if k not in {"runtime", "cpu_last", "wall_last", "event_files", "request_hash"}},
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
            # Each with its diff's headline; the files changed are in the review of the latest (events()).
            "submissions": sorted(({**{k: v for k, v in s.items() if k not in {"package", "diff"}},
                                    **({"diff": {k: v for k, v in s["diff"].items() if k != "files"}} if s.get("diff") else {})}
                                   for s in self.store.list("development_submission", record["campaign_id"])
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

    def create(self, campaign_id, payload, *, actor="researcher", opener=None, root=None, asked=None):
        """opener: the agent that opens it ({agent_id, role}), when an agent does; root: the researcher's request its turn
        works on (controller.request_root), which the workspace's notices continue; asked: the request whose mandate the
        agent works under (compute_consent.request_root), which must allow it (R3)."""
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
            from optimization_framework.campaigns import compute_consent, mandates
            consent = mandate = None
            # The request the agent works for: its mandate must allow the workspace, and a request-only go-ahead (R7) covers it there.
            request = asked if asked is not None else root
            if actor != "researcher":
                consent = compute_consent.require(self.workspace, campaign_id, "Opening a coding workspace", coding=1, hypothesis_ids=served, root=request)
                mandate = mandates.require(self.workspace, campaign_id, request, {"implement"}, what="Opening a coding workspace", hypothesis_ids=served)
            for evidence_id in values.evidence_ids:
                self.evidence(campaign_id, evidence_id)
            config = self.controller.configuration(campaign_id)
            if not config or not config["enabled"]:
                raise ValueError("Activate the campaign lead agent before creating an implementation workspace")
            # The coding agent runs on the campaign's own model, as its agents do.
            default = (config.get("models") or {}).get("default") or LEGACY_MODEL
            model = {key: default.get(key) for key in ("provider", "model", "effort")}
            walls = self.walls(values, consent, model)
            setting = harness({"name": values.harness, "mode": values.harness_mode or os.environ.get("GRATING_DEVELOPMENT_HARNESS_MODE") or "tui"})
            record = {"id": identity, "campaign_id": campaign_id, "hypothesis_id": values.hypothesis_id, "hypothesis_ids": served,
                "title": hypothesis["title"], "parent_agent_id": config["lead_id"], "created_at": now(),
                "opened_by": {"actor": actor, **(opener or {})}, "request_root": root,
                # The researcher's go-ahead it opened under, for the history: the approved plan, not a deadline.
                "consent": {"id": consent["id"], "decision_id": consent.get("decision_id"), "plan": (consent.get("plan") or "")[:2000]} if consent else None,
                "objective": values.objective, "evidence_ids": values.evidence_ids,
                "request_key": values.request_key, "request_hash": request_hash(values),
                "status": "queued", "desired_status": "running", "control_revision": 0,
                "guidance_revision": 0, "cpu_budget_seconds": values.cpu_budget_seconds, "model": model, **walls, "harness": setting,
                "usage": {"container_cpu_seconds": 0, "wall_seconds": 0, "subscription_calls": 0, "input": 0, "output": 0,
                          "billing_mode": "subscription", "api_cost_usd": 0}, "event_files": [], "cursor": 0}
            # The work ticket (H4), checked as a commission's specification is when an agent writes it; its protected tests stay here.
            ticket = self.ticket(record, values.ticket, consent=consent, mandate=mandate)
            if actor != "researcher":
                self.workspace.implementations.check_self_contained(ticket)
            record["ticket_id"] = ticket["id"]
            self.store.put("development_workspace", record, "development.created")
            self.store.put_immutable("development_ticket", ticket, "development.ticket_written")
            from .library_validation import protect   # where validation outside the box (H6) reads them
            for test in values.ticket.protected_tests if values.ticket else ():
                protect(self.store, record, test.name, test.content)
            if actor != "researcher":
                compute_consent.charge(self.workspace, campaign_id, coding=1, what="a coding workspace", subjects=[identity], hypothesis_ids=served,
                                       root=request)
            self.message(campaign_id, identity, {"message": values.objective +
                "\nYour work ticket is TASK.md and the house rules are in AGENTS.md: read them, .campaign/assignment.md and "
                ".campaign/evidence.json first. Continue until you submit, or a genuine blocker stops you.",
                "request_key": "initial-" + values.request_key, "mode": "follow_up"}, actor=actor)
            return self.public(self.get(campaign_id, identity))

    def walls(self, values, consent, model):
        """The box's walls (H5) from its request, checked: limits within the researcher's ceilings; for an agent, a deadline and
        hosts within the go-ahead it opens under (its wall time, its approved hosts). Refused before anything is recorded."""
        limits = (values.limits or WorkspaceLimits()).model_dump(exclude={"schema_version"})
        if values.limits is None:   # today's default, lowered to the researcher's ceilings
            limits.update(cpus=min(limits["cpus"], ceilings()["cpus"]), memory_gb=min(limits["memory_gb"], ceilings()["memory_gb"]))
        over = [f"{key} {limits[key]:g} (ceiling {ceiling:g})" for key, ceiling in ceilings().items() if limits[key] > ceiling]
        if over:
            raise ValueError("The workspace's limits are above the researcher's ceilings: " + ", ".join(over) + ". Ask for less, or ask "
                             "the researcher to raise the ceilings (development_max_cpus, development_max_memory_gb, development_max_gpus)")
        wall, hosts = values.wall_seconds, list(values.egress_hosts)
        if consent is not None:
            hosts = hosts or list(consent.get("egress_hosts") or [])   # none named: the hosts its go-ahead approved (H4's ticket carries them)
            wall = wall or consent["wall_seconds"]
            if wall > consent["wall_seconds"]:
                raise ValueError(f"The workspace's deadline ({wall:.0f} s) is past the go-ahead's wall time ({consent['wall_seconds']:.0f} s)")
            unapproved = sorted(set(values.egress_hosts) - set(consent.get("egress_hosts") or []))
            if unapproved:
                raise ValueError("The go-ahead did not approve these hosts for the workspace: " + ", ".join(unapproved) + ". Name them in "
                                 "egress_hosts of the request's mandate (mandate_propose, template screen), so the researcher approves them with it")
        return {"limits": limits, "wall_seconds": wall, "deadline_at": None, "egress": egress(model, hosts)}

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
            if values.action == "resume":
                if values.wall_seconds is None and past(record.get("deadline_at")):
                    raise ValueError("The workspace's deadline has passed. Going on is a new go-ahead: resume with wall_seconds, the time it may run from now")
                if values.wall_seconds is not None:
                    record.update(wall_seconds=values.wall_seconds, deadline_at=after(values.wall_seconds), deadline_reached=None)
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
        public = self.public(record)
        return {"workspace": public, "events": events, "cursor": events[-1]["seq"] if events else after, "commands": commands[-100:],
                "ticket": self.ticket_summary(record), "review": self.review(record, public["submissions"])}

    def ticket_summary(self, record):
        """The ticket as the implementation lead reviews against it: what it asks for, without the texts it holds."""
        ticket = self.ticket_of(record)
        return {"id": ticket["id"], "proposals": [{key: row[key] for key in ("hypothesis_id", "title", "method_key")} for row in ticket["proposals"]],
                "library": (ticket.get("library") or {}).get("path"), "test_command": ticket.get("test_command"),
                "acceptance_tests": [{key: row[key] for key in ("path", "source")} for row in ticket["acceptance_tests"]],
                "protected_tests": ticket["protected_tests"], "budget": ticket.get("budget"), "deadline": ticket.get("deadline")}

    def diff(self, record, submission):
        """A submission's diff summary against the base its ticket wrote (development_ticket.diff_summary): the commit's library,
        read from the workspace's Git store as the install reads it (the submitted package's files where the store cannot be
        read), against the generated library and the implementation lead's tests."""
        from optimization_framework.campaigns.method_catalog import library_of
        from .development_ticket import diff_summary, sha256
        try:
            ticket, library = self.ticket_of(record), record.get("library") or {}
            name = library_of(submission) or library.get("name")
            prefix = f"libraries/{name}/" if name else ""
            delivered, source = None, "commit"
            if name:
                from .development_runtime import ROOT
                from .library_install import Installer
                try:
                    delivered = Installer(self.workspace, self, ROOT).files(record, submission, name)
                except (ValueError, OSError):
                    delivered = None
            if delivered is None:
                source = "package"
                delivered = {row["path"]: str(row["content"]).encode() for row in (submission.get("package") or {}).get("files", [])
                             if row["path"].startswith(prefix)}
            hashes = (library.get("files") or {}) if library.get("name") == name else {}
            base = {}
            if hashes:   # the generated library, made again from its charter revision: kept where it has the recorded bytes
                generated = self.generated_library(record)[0] or {}
                for path, content in (generated.get("files") or {}).items():
                    if hashes.get(prefix + path) == sha256(content):
                        base[prefix + path] = content
            base |= {row["path"]: row["content"].encode() for row in ticket["acceptance_tests"]
                     if row.get("content") is not None and row["path"].startswith(prefix)}
            return {"library": name, "source": source, **diff_summary(base, delivered, hashes=hashes, ticket=ticket)}
        except Exception as exc:   # a review that cannot be made never stops a delivery
            return {"error": f"The diff could not be made: {exc}"[:500]}

    def review(self, record, submissions):
        """What the implementation lead reviews of the latest delivery: the coding agent's verdict, the diff against the ticket's
        base, and the host's validation outside the box (H6 records it on the install, as host_validation and refused_methods;
        None until an install has)."""
        if not submissions:
            return None
        latest = self.store.get(submissions[-1]["id"], "development_submission")
        installs = sorted((row for row in self.store.list("library_install", record["campaign_id"]) if row.get("submission_id") == latest["id"]),
                          key=lambda row: row["requested_at"])
        install = installs[-1] if installs else {}
        return {"submission_id": latest["id"], "commit": latest["commit"], "verdict": (latest.get("report") or {}).get("verdict"),
                "diff": latest.get("diff") or self.diff(record, latest),
                "install": {key: install.get(key) for key in ("id", "status", "methods_added", "error")} if install else None,
                "host_validation": install.get("host_validation"), "refused_methods": install.get("refused_methods"),
                "protected_tests": self.ticket_of(record)["protected_tests"]}

    def sync(self, campaign_id):
        try:
            self.install_delivered(campaign_id)
        except Exception as exc:   # an install never stops the workspaces' own sync
            import logging
            logging.getLogger(__name__).warning("Installing a delivered library failed: %s", exc)
        try:
            from optimization_framework.campaigns.plan_runs import launch_ready
            launch_ready(self.workspace, campaign_id)
        except Exception as exc:   # nor does starting the approved runs
            import logging
            logging.getLogger(__name__).warning("Starting the approved runs failed: %s", exc)
        try:
            from optimization_framework.campaigns.mandates import settle
            settle(self.workspace, campaign_id)
        except Exception as exc:   # nor does closing the mandates whose stop condition holds
            import logging
            logging.getLogger(__name__).warning("Settling the mandates failed: %s", exc)
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
                library, charter, why = generated = self.generated_library(record)
                # The ticket's four files (H4) go in beside the library; nothing protected is among them.
                from .development_ticket import files
                ticket = files(self.ticket_of(record, generated))
                if library:
                    hashes = self.driver.prepare(record, self.brief(record), evidence, library=library, ticket=ticket)
                    library = {key: value for key, value in library.items() if key != "files"} | {"files": hashes}
                    with self.workspace.lock:
                        self.store.put("development_workspace", {**self.get(cid, identity), "library": library})
                else:
                    self.driver.prepare(record, self.brief(record), evidence, ticket=ticket)
                atomic_json(root / "prepared.json", {"workspace_id": identity, **({"library": library} if library else {})})
            runtime = self.driver.start(record)
            with self.workspace.lock:
                record = self.get(cid, identity)
                recovered = bool(record.get("error"))
                record.update(runtime=runtime)
                record.pop("error", None)
                record.pop("blocked_since", None)
                if record["status"] in {"queued", "blocked", "resuming", "stopped"}:
                    record["status"] = "starting"
                if record.get("wall_seconds") and not record.get("deadline_at"):   # the deadline runs from the box's first start
                    record["deadline_at"] = after(record["wall_seconds"])
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
            self.charge_wall(record)
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
        if past(record.get("deadline_at")) and record["desired_status"] == "running":
            record = self.reach_deadline(record)
        elif budget is not None and used >= budget and record["desired_status"] == "running":
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
            if record.get("control_acknowledged") or elapsed >= 5 or (budget is not None and used >= budget) or record.get("deadline_reached"):
                if record["desired_status"] == "paused":
                    self.driver.pause(record)
                else:
                    self.driver.stop(record)
                with self.workspace.lock:
                    current = self.get(cid, identity)
                    current["status"] = record["desired_status"]
                    current.pop("control_acknowledged", None)
                    self.store.put("development_workspace", current)

    def charge_wall(self, record):
        """Count the wall time the box has been running since the last sync, on the workspace and on the go-ahead it opened
        under: the consent that is its request's mandate's compute part (campaigns/mandates.py). A paused, stopped or blocked box
        is not charged."""
        at = datetime.now(timezone.utc)
        running = record["desired_status"] == "running" and record["status"] not in {"queued", "blocked"}
        last = record.get("wall_last")
        if running and last:
            spent = max(0.0, (at - datetime.fromisoformat(last)).total_seconds())
            record["usage"]["wall_seconds"] = record["usage"].get("wall_seconds", 0) + spent
            consent_id = (record.get("consent") or {}).get("id")
            if consent_id and spent:
                consent = self.store.get(consent_id, "compute_consent")
                consent["used_wall_seconds"] = consent.get("used_wall_seconds", 0) + spent
                self.store.put("compute_consent", consent)
        record["wall_last"] = at.isoformat() if running else None
        self.store.put("development_workspace", record)

    def reach_deadline(self, record):
        """At its deadline the box is paused, not removed: its session and worktree are kept, the coding agent's last state is
        recorded, and whoever opened it and the researcher are told once. Going on is a new go-ahead (control resume)."""
        with self.workspace.lock:
            record = self.get(record["campaign_id"], record["id"])
            last = {"phase": record.get("phase"), "activity": (record.get("activity") or "")[:2000],
                    "checkpoint": excerpt((record.get("checkpoint") or {}).get("summary")), "tests": record.get("tests")}
            record.update(desired_status="paused", status="pausing", control_requested_at=now(), deadline_reached=last,
                          error=f"The workspace reached its deadline ({record['deadline_at'][:16].replace('T', ' ')} UTC) and is paused. "
                                "Its session and work are saved; going on is a new go-ahead.")
            self.store.put("development_workspace", record, "development.deadline_reached")
            self.event(record, "deadline_reached_" + record["deadline_at"], "deadline_reached",
                       {"deadline_at": record["deadline_at"], "wall_seconds": record.get("wall_seconds"), **last})
            self.notify(record, "deadline_" + record["deadline_at"], record["error"])
            return record

    def generated_library(self, record):
        """(library, charter, why not) a workspace starts from: the campaign's charter revision generated as a Balsamic library
        ({name, package, charter_id, revision, fixed, files}, roadmap F4), and the charter document. The library is None,
        with the reason, when the charter cannot give one (it names no evaluator, say); all three are None for a campaign
        made without a charter."""
        from optimization_framework.problem_charter.charter import parse
        from optimization_framework.problem_charter.scaffold import package_name, scaffold
        reference = self.store.get(record["campaign_id"], "campaign").get("charter")
        if not reference:
            return None, None, None
        charter = self.workspace.charters.revision(reference["id"], reference["revision"])["charter"]
        try:
            files = scaffold(charter, reference["revision"], charter_id=reference["id"], balsamic=True)
        except ValueError as exc:
            return None, charter, str(exc)
        problem_id = charter["evaluator"]["problem_id"]
        package = package_name(parse(charter))
        name = problem_id if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}", problem_id) else package.replace("_", "-")
        return {"name": name, "package": package, "charter_id": reference["id"], "revision": reference["revision"],
                "fixed": [f"libraries/{name}/charter.json", f"libraries/{name}/{package}/data.py"], "files": files}, charter, None

    def ticket(self, record, given=None, *, consent=None, mandate=None, generated=None):
        """The work ticket of a workspace record (H4, agents/development_ticket.py): the proposals it serves with their METHODS
        keys, the campaign's charter revision and the library generated from it (``generated``: generated_library()'s result
        when it is at hand), the implementation lead's tests (``given``), the budget of the go-ahead and mandate it opens under,
        and the walls on its record (H5)."""
        from .development_ticket import build, problem_of
        served = []
        for hypothesis_id in record.get("hypothesis_ids") or [record["hypothesis_id"]]:
            try:
                served.append(self.store.get(hypothesis_id, "hypothesis"))
            except KeyError:
                continue
        library, charter, why = generated or self.generated_library(record)
        reference = self.store.get(record["campaign_id"], "campaign").get("charter")
        return build(record, served, method_keys(served), library=library, problem=problem_of(charter, reference) if charter else None,
                     why=why, given=given, consent=consent, mandate=mandate)

    def ticket_of(self, record, generated=None):
        """The ticket the workspace opened with; one built from its record for a workspace opened before tickets."""
        try:
            return self.store.get(record["ticket_id"], "development_ticket")
        except KeyError:
            return self.ticket(record, generated=generated)

    def brief(self, record):
        """`.campaign/assignment.md`: DEVELOPMENT_INSTRUCTIONS, what the house rules (AGENTS.md) do not say about this Pi session.
        The work itself is the ticket's (TASK.md)."""
        return f"# {record['title']}\n\n" + DEVELOPMENT_INSTRUCTIONS

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

    def capture_submission(self, record, key, payload, *, snapshot=None, source=None):
        """The exact commit as a submission: its manifest and files as `snapshot` reads them (the box's Git unless given), and
        its delivery report. source: who delivered it when the coding agent did not ("own_session": the researcher, from their
        own coding agent, agents/own_session.py); only the coding agent waits for a result file. Returns that result."""
        report = self.delivery_report(record, payload.get("report"))
        package, manifest, ignored = (snapshot or self.driver.snapshot)(record, payload["commit"], payload.get("manifest_path", "implementation-manifest.json"))
        submission = {"campaign_id": record["campaign_id"], "workspace_id": record["id"],
            "hypothesis_id": record["hypothesis_id"], "hypothesis_ids": record.get("hypothesis_ids") or [record["hypothesis_id"]],
            "commit": payload["commit"], "package": package, "manifest": manifest, "notes": payload.get("notes", ""),
            "report": report, "status": "submitted", "created_at": now(), **({"source": source} if source else {})}
        diff = self.diff(record, submission)   # read from the store the commit is in (the source's), outside the transaction
        with self.workspace.lock, self.store.transaction():
            identity = "development_submission_" + content_hash([record["id"], payload["commit"], package, manifest])[:24]
            submission = {"id": identity, **submission, "diff": diff}
            try:
                saved = self.store.get(identity, "development_submission")
                if report and saved.get("report") != report:   # the same commit again: its latest report stands
                    saved["report"] = report
                    self.store.put("development_submission", saved, "development.submitted")
            except KeyError:
                saved = self.store.put("development_submission", submission, "development.submitted")
                verdict = f" {'The researcher' if source else 'The coding agent'}'s verdict: {report['verdict'].replace('_', ' ')}; next: " + ("; ".join(
                    f"{a['owner']}: {a['action']}" for a in report["next_actions"]) or "nothing named") + "." if report else " It sent no delivery report."
                what = f"The researcher delivered commit {submission['commit']} from their own coding session" if source else f"Commit {submission['commit']} submitted"
                self.notify(record, identity, f"{what} as {identity}.{verdict} {changed(diff)} Review it against its ticket (review in "
                            "implementation_workspace_inspect).", "submissions")
            self.event(record, key, "submission", {"submission_id": identity, "commit": payload["commit"], **({"source": source} if source else {})})
        result = {"submission_id": saved["id"], "status": saved["status"], **({"ignored_fields": ignored} if ignored else {})}
        if not source:
            atomic_json(self.driver.root(record) / "incoming/results" / (key + ".json"), result)
        return result

    def validate(self, campaign_id, identity, payload, *, actor="researcher", asked=None):
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
        from optimization_framework.campaigns import compute_consent, mandates
        served = record.get("hypothesis_ids") or [record["hypothesis_id"]]   # a go-ahead covers the validation of what it opened
        # Checked against the request the agent works for (asked), else the one the workspace was opened for.
        request = asked if asked is not None else record.get("request_root")
        if actor != "researcher":
            compute_consent.require(self.workspace, campaign_id, "Validating a submission", values.compute_seconds, hypothesis_ids=served, root=request)
            mandates.require(self.workspace, campaign_id, request, {"validate"}, what="Validating a submission", hypothesis_ids=served,
                             seconds=values.compute_seconds)
        grant = self.workspace.implementations.reserve_commission(record["hypothesis_id"], spec,
            compute_seconds=values.compute_seconds, max_calls=12, api_budget_usd=0,
            idempotency_key="development-" + content_hash([identity, values.request_key])[:24],
            package=submission["package"], accounting_mode="execution_v1")
        if actor != "researcher":
            compute_consent.charge(self.workspace, campaign_id, values.compute_seconds, what="a validation of a coding workspace's submission",
                                   subjects=[identity], hypothesis_ids=served, root=request)
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


def changed(diff):
    """A delivery's diff summary as a line of a notice."""
    if not diff or diff.get("error"):
        return (diff or {}).get("error") or ""
    touched = list(dict.fromkeys(diff["generated_files_touched"] + diff["acceptance_tests_touched"]))
    return (f"It changes {diff['files_changed']} files of {diff['library'] or 'its package'} (+{diff['lines_added']} −{diff['lines_removed']} lines)"
            + (f"; generated files and acceptance tests it touched: {', '.join(touched)}." if touched else "."))


def method_keys(proposals):
    """{proposal id: a method id for it}: its title as an identifier (a method id's pattern), unique among the proposals."""
    keys, used = {}, set()
    for proposal in proposals:
        base = re.sub(r"[^a-z0-9]+", "_", str(proposal.get("short_title") or proposal.get("title") or proposal["id"]).lower()).strip("_")
        base = (base if base[:1].isalpha() else "method_" + base).rstrip("_")[:56] or "method"
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        keys[proposal["id"]] = key
        used.add(key)
    return keys


DEVELOPMENT_INSTRUCTIONS = """## Development workflow

Your work ticket is TASK.md: the proposals, the acceptance tests, the budget, the deadline and
the network. AGENTS.md holds the house rules: what to build, how to run the tests, how to
submit and what not to touch. Read both first.

This is a complete Pi coding workspace: read, edit, write, bash, Git, tests and skills;
`python -m pip install --user ...` installs packages. The host campaign database, private
files, protected validation fixtures and Docker socket are outside it.

The developer can steer this session, and their direction wins; the campaign lead agent
answers your questions. Reread files the developer changed before editing them. Keep decisions
and continuation notes in `.campaign/checkpoint.md`: it survives compaction and reconnects.

At each `campaign_checkpoint`, give your phase, what is done and what remains, the latest
test counts and the minutes left until you submit; use it for questions and blockers too.
Use a new commit for each repair. Whether a method performs well is for the campaign's
experiments, not the implementation. At its deadline the workspace pauses with your session
saved.
"""
