"""A mandate is what one researcher request allows (roadmap Phase 3): the classes of work, the proposals, coding workspaces and
runs it names, a compute and model-spend envelope, a deadline and a stop condition (contracts/mandates.py). Reads are not
commands and are always allowed; every command operation belongs to one class (CLASSES).

Four templates (decision 10): Answer reads and answers and starts nothing; Explore adds proposals, reviews, runs, validations
and records up to the researcher's go-ahead threshold in total, with no coding workspace, and is the default when nothing else
is chosen; Screen adds implementation and decisions for the proposals, workspaces and runs a plan names, with their minutes
(today's compute go-ahead, B2); Run the campaign allows every class within its envelope and deadline. Answer and Explore may
start at once; Screen and Run the campaign are the researcher's go-ahead, a decision.

A compute consent (campaigns/compute_consent.py) is the compute part of the mandate that granted it: such a mandate's compute
envelope and use are the consent's, and charge() counts its compute there. A consent no mandate names, as every consent
recorded before mandates, reads as a Screen mandate with only a compute envelope: a view over the old record, never a rewrite.

A mandate's model spend (R5) is what the model calls made under its request cost: the lead's, its assistants', the page agents'
and the report stages' (agents/usage.py spent(), by the request root each call records), plus any dollars charged on it
directly; a standing mandate's is the campaign's since it was granted. When it reaches the envelope (model_usd), new agent
turns under that request hold, as the campaign's model cap holds every turn, with one inbox card to raise it (hold()).

This module records and reads mandates; the bus does not check them yet (R3)."""
from datetime import datetime, timezone

from optimization_framework.contracts.commands import PlannedRun
from optimization_framework.contracts.mandates import Mandate, MandateCompute, RequestRoot, StopCondition
from optimization_framework.storage.sqlite import identifier, now

from optimization_framework.agents import usage

from . import compute_consent

# Each command operation's class. A new operation without one fails tests/test_mandates.py.
CLASSES = {
    **dict.fromkeys(("literature.search", "resources.estimate", "bundle.inspect", "agent.message", "agent.ui_respond",
                     "agent.question_dismiss", "note.resolve"), "answer"),
    **dict.fromkeys(("hypothesis.create", "hypothesis.edit", "research.generate", "reproduction.draft", "draft.save"), "propose"),
    **dict.fromkeys(("hypothesis.review",), "review"),
    **dict.fromkeys(("implementation.commission", "implementation.attach", "implementation.revalidate", "implementation.bind_builtin",
                     "implementation.resolve_runtime", "implementation.reuse", "implementation.reference", "implementation.control",
                     "evaluator.commission", "evaluator.attach", "library.apply", "asset.reuse", "asset.import_reference_set"), "implement"),
    # A batch of interventions is checked by its items' classes (classes_of).
    **dict.fromkeys(("trial.create", "trial.continue", "trial.control", "draft.launch", "fixed_mask.run", "inference.run",
                     "runtime.profile", "hypothesis.allocate", "intervention.batch", "study.create", "study.activate",
                     "study.race.create", "study.race.control"), "run"),
    **dict.fromkeys(("validation.run", "validation.execute", "validation.require", "trial.validate", "evaluator.equivalence",
                     "confirmation.schedule", "confirmation.validate", "reproduction.compare"), "validate"),
    # Stops, nominations, finalists, and what settles a result or a requirement.
    **dict.fromkeys(("hypothesis.status", "hypothesis.nominate", "study.nominate", "finalist.set", "study.race.decide",
                     "confirmation.release", "validation.waive", "validation.revoke_waiver", "decision.resolve",
                     "problem_note.adopt"), "decide"),
    **dict.fromkeys(("finding.record", "comparison.report", "bundle.export", "bundle.publish", "library.publish", "asset.snapshot",
                     "source.record", "source.ingest", "cost.reconcile", "problem_note.revise", "study.freeze_template"), "record"),
    **dict.fromkeys(("experiments.rules", "trial.hide", "journal.compact", "campaign.create", "campaign.update", "campaign.stage_pin",
                     "context.edit", "workers.set", "autopilot.set", "resources.plan", "issue.resolve", "issue.reopen",
                     "problem_note.skip", "problem_note.unskip", "agent.activate", "agent.configure", "agent.control", "agent.rollback",
                     "thread.fork", "thread.rename", "thread.park", "thread.unpark", "thread.pin", "thread.merge_draft",
                     "thread.merge"), "configure"),
    **dict.fromkeys(("approval.request", "trial.extension_request", "journal.compaction_request", "note.ask"), "ask"),
}
ALL_CLASSES = ("answer", "propose", "review", "implement", "run", "validate", "decide", "record", "configure", "ask")
_ANSWER = ("answer", "ask")
_EXPLORE = (*_ANSWER, "propose", "review", "run", "validate", "record")
_SCREEN = (*_EXPLORE, "implement", "decide")
TEMPLATES = {"answer": {"classes": _ANSWER, "go_ahead": False}, "explore": {"classes": _EXPLORE, "go_ahead": False},
             "screen": {"classes": _SCREEN, "go_ahead": True}, "run_campaign": {"classes": ALL_CLASSES, "go_ahead": True}}
_UNFINISHED = {"queued", "running", "pausing", "paused", "stopping", "interrupted"}


def classes_of(operation, payload=None):
    """The classes a command's work belongs to: its operation's, or for a batch, its items'."""
    if operation == "intervention.batch":
        return {CLASSES[item.get("operation")] for item in (payload or {}).get("items", []) if item.get("operation") in CLASSES}
    return {CLASSES[operation]}


def envelope(workspace, campaign_id, template, compute=None):
    """A template's compute envelope: none for Answer, the go-ahead threshold in total for Explore (read now, so it follows the
    researcher's thresholds), the plan's own for Screen and Run the campaign."""
    if template == "answer":
        return MandateCompute(worker_seconds=0.0)
    if template == "explore":
        return MandateCompute(worker_seconds=compute_consent.thresholds(workspace, campaign_id)[1])
    return MandateCompute(**(compute or {"worker_seconds": 0.0}))


def same_root(first, second):
    """Whether two request roots name the same researcher request."""
    if not first or not second or first.get("thread_id") != second.get("thread_id"):
        return False
    if first.get("message_id") or second.get("message_id"):
        return first.get("message_id") == second.get("message_id")
    return first.get("run_id") == second.get("run_id")


def _root(root):
    """A request root as a mandate records it: its thread, message and run; None for none."""
    root = root.model_dump() if isinstance(root, RequestRoot) else root
    if not isinstance(root, dict) or not root.get("thread_id"):
        return None
    return {key: root.get(key) for key in ("thread_id", "message_id", "run_id")}


def _record(workspace, identity, kind):
    try:
        return workspace.store.get(identity, kind) if isinstance(identity, str) else None
    except KeyError:
        return None


def _status(workspace, stored, compute, used, model_usd, deadline_at, consent, current):
    if stored in {"proposed", "closed"}:
        return stored
    if (deadline_at and compute_consent._clock(deadline_at) <= current) or (consent is not None and not compute_consent._in_force(workspace, consent, current)):
        return "expired"
    spent = (compute["worker_seconds"] > 0 or compute["coding_workspaces"] > 0) and used["worker_seconds"] >= compute["worker_seconds"] \
        and used["coding_workspaces"] >= compute["coding_workspaces"]
    if spent or (model_usd is not None and used["model_usd"] >= model_usd):
        return "exhausted"
    return "active"


def read(workspace, row, current=None):
    """A recorded mandate, with its envelope and use filled in: a consent's when one is its compute part."""
    current = current or datetime.now(timezone.utc)
    consent = _record(workspace, row.get("consent_id"), "compute_consent")
    used = dict(row.get("used") or {})
    if consent is not None:
        compute = {"worker_seconds": consent["worker_seconds"], "coding_workspaces": consent.get("coding_workspaces", 0)}
        used.update(worker_seconds=consent["used_seconds"], coding_workspaces=consent["used_workspaces"])
        workspace_ids = list(dict.fromkeys([*row.get("workspace_ids", []), *consent.get("workspace_ids", [])]))
    else:
        compute = envelope(workspace, row["campaign_id"], row["template"], row.get("compute")).model_dump(exclude={"schema_version"})
        workspace_ids = list(dict.fromkeys([*row.get("workspace_ids", []), *row.get("opened", [])]))
    used = {"worker_seconds": 0.0, "coding_workspaces": 0, "model_usd": 0.0, **used}
    used["model_usd"] += model_spent(workspace, row)
    return Mandate(**{key: row.get(key) for key in ("id", "campaign_id", "root", "template", "classes", "plan", "hypothesis_ids", "runs",
        "model_usd", "deadline_at", "stop_when", "granted_by", "consent_id", "created_at")}, workspace_ids=workspace_ids, compute=compute,
        used=used, status=_status(workspace, row["status"], compute, used, row.get("model_usd"), row.get("deadline_at"), consent, current))


def model_spent(workspace, row):
    """API dollars of the model calls under a mandate's request; for a standing mandate, the campaign's since its grant."""
    root = row.get("root")
    return usage.spent(workspace.store, row["campaign_id"], root) if root else \
        usage.spent(workspace.store, row["campaign_id"], since=row.get("created_at"))


def model_left(mandate):
    """Dollars left in a mandate's model-spend envelope; None when it sets none."""
    return None if mandate.model_usd is None else max(0.0, mandate.model_usd - mandate.used.model_usd)


def from_consent(workspace, consent, current=None):
    """A compute consent no mandate names, read as a Screen mandate with only a compute envelope. Its root is the request it was
    asked in; one recorded before consents named requests is a standing mandate."""
    current = current or datetime.now(timezone.utc)
    compute = {"worker_seconds": consent["worker_seconds"], "coding_workspaces": consent.get("coding_workspaces", 0)}
    used = {"worker_seconds": consent["used_seconds"], "coding_workspaces": consent["used_workspaces"], "model_usd": 0.0}
    return Mandate(id=consent["id"], campaign_id=consent["campaign_id"], root=_root(consent.get("request_root")), template="screen",
        classes=list(TEMPLATES["screen"]["classes"]), plan=consent.get("plan"), hypothesis_ids=consent.get("hypothesis_ids") or [],
        workspace_ids=consent.get("workspace_ids") or [], runs=consent.get("runs") or [], compute=compute, used=used,
        granted_by=consent["decision_id"], consent_id=consent["id"], created_at=consent["granted_at"],
        status=_status(workspace, "active", compute, used, None, None, consent, current))


def mandates(workspace, campaign_id):
    """Every mandate of the campaign, recorded or read from a consent, oldest first."""
    current = datetime.now(timezone.utc)
    rows = workspace.store.list("mandate", campaign_id)
    owned = {row["consent_id"] for row in rows if row.get("consent_id")}
    found = [read(workspace, row, current) for row in rows]
    found += [from_consent(workspace, consent, current) for consent in workspace.store.list("compute_consent", campaign_id) if consent["id"] not in owned]
    return sorted(found, key=lambda mandate: mandate.created_at)


def serves(mandate, root):
    """Whether a mandate serves this request: its own, or every request for a standing mandate."""
    return mandate.root is None or same_root(mandate.root.model_dump(), _root(root))


def active(workspace, campaign_id, root):
    """The newest active mandate that serves this request, or None: then the request has the default, Explore (decision 10)."""
    return next((mandate for mandate in reversed(mandates(workspace, campaign_id)) if mandate.status == "active" and serves(mandate, root)), None)


def current(workspace, campaign_id, root):
    """The newest mandate in force for this request, its envelope spent or not: the one whose model spend holds its turns."""
    return next((mandate for mandate in reversed(mandates(workspace, campaign_id))
                 if mandate.status in {"active", "exhausted"} and serves(mandate, root)), None)


def model_spent_out(mandate):
    return mandate.model_usd is not None and mandate.used.model_usd >= mandate.model_usd - 1e-9


def hold(workspace, campaign_id, root):
    """The mandate whose model envelope this request's turns wait on, or None. Its first hold asks the researcher, once per
    envelope, with one inbox card to raise it (raise_model on approval)."""
    mandate = current(workspace, campaign_id, root)
    if mandate is None or not model_spent_out(mandate):
        return None
    identity = f"mandate_model_{mandate.id}_{mandate.model_usd:g}".replace(".", "_")
    if _record(workspace, identity, "decision") is None:
        campaign = workspace.store.get(campaign_id, "campaign")
        step = mandate.model_usd or 1.0
        raised = round(mandate.model_usd + step, 2)
        title = f"Raise this request's model spending to ${raised:.2f}?"
        workspace.store.put("decision", {"id": identity, "campaign_id": campaign_id, "charter_version": campaign["version"],
            "guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"], "question": title, "title": title,
            "rationale": f"The agents' model calls for this request have cost ${mandate.used.model_usd:.2f} of the "
                         f"${mandate.model_usd:.2f} it was given, so its next turns wait.",
            "context": (mandate.plan or "")[:2000],
            "proposal": f"Raise the request's model-spend envelope from ${mandate.model_usd:.2f} to ${raised:.2f}. The campaign's own "
                        "LLM cap still applies.",
            "options": [{"id": "0", "label": f"Raise to ${raised:.2f}", "description": "The request's waiting turns go on."},
                        {"id": "1", "label": "Leave it as it is", "description": "The request's turns keep waiting; nothing else changes."}],
            "recommendation": "0", "approval_request": {"kind": "mandate_model", "mandate_id": mandate.id, "model_usd": raised},
            "requested_by": "platform", "audience": "researcher", "status": "pending", "created_at": now(),
            **({"request_root": mandate.root.model_dump(exclude={"schema_version"})} if mandate.root else {})}, "decision.created")
    return mandate


def raise_model(workspace, mandate_id, model_usd, decision_id):
    """The researcher's raise of a mandate's model-spend envelope, recorded with the decision that granted it."""
    with workspace.lock:
        row = _record(workspace, mandate_id, "mandate")
        if row is None:
            raise ValueError(f"No mandate {mandate_id}")
        if row.get("model_usd") is not None and model_usd < row["model_usd"]:
            raise ValueError("A raise does not lower the envelope")
        row["model_usd"] = model_usd
        row["raises"] = [*row.get("raises", []), {"model_usd": model_usd, "decision_id": decision_id, "at": now()}]
        workspace.store.put("mandate", row, "mandate.raised")
    return read(workspace, row)


def grant(workspace, campaign_id, template, *, root=None, granted_by="automatic", plan=None, hypothesis_ids=(), workspace_ids=(), runs=(),
          compute=None, model_usd=None, deadline_at=None, stop_when=None, consent_id=None, status="active"):
    """Record a mandate for a request (root; None for a standing one). Answer and Explore take their template's envelope and may be
    granted automatically. Screen and Run the campaign are the researcher's go-ahead (granted_by, a decision of this campaign),
    with a compute envelope: the consent that is their compute part, or compute (worker_seconds, coding_workspaces)."""
    if template not in TEMPLATES:
        raise ValueError("Unknown mandate template: " + str(template) + ". Choose one of " + ", ".join(TEMPLATES))
    if status not in {"proposed", "active"}:
        raise ValueError("A mandate is recorded proposed or active")
    if TEMPLATES[template]["go_ahead"]:
        decision = _record(workspace, granted_by, "decision")
        if decision is None or decision["campaign_id"] != campaign_id:
            raise ValueError(f"A {template} mandate is the researcher's go-ahead: name the decision that granted it")
        if consent_id is None and compute is None:
            raise ValueError(f"A {template} mandate has a compute envelope: its consent or its worker seconds")
    elif compute is not None or consent_id is not None:
        raise ValueError(f"The {template} template sets its own compute envelope")
    elif granted_by != "automatic" and _record(workspace, granted_by, "decision") is None:
        raise ValueError("A mandate is granted automatically or by a decision of the campaign")
    consent = _record(workspace, consent_id, "compute_consent")
    if consent_id is not None and (consent is None or consent["campaign_id"] != campaign_id):
        raise ValueError("The consent is not one of this campaign's")
    for identity, kind in [*((value, "hypothesis") for value in hypothesis_ids), *((value, "development_workspace") for value in workspace_ids)]:
        found = _record(workspace, identity, kind)
        if found is None or found.get("campaign_id") != campaign_id:
            raise ValueError(f"{identity} is not a {kind.replace('_', ' ')} of this campaign")
    row = {"id": identifier("mandate"), "campaign_id": campaign_id, "root": _root(root), "template": template,
           "classes": list(TEMPLATES[template]["classes"]),
           "plan": plan or (consent or {}).get("plan"),
           "hypothesis_ids": list(dict.fromkeys([*hypothesis_ids, *((consent or {}).get("hypothesis_ids") or [])])),
           "workspace_ids": list(dict.fromkeys(workspace_ids)),
           "runs": [run.model_dump(mode="json") if isinstance(run, PlannedRun) else PlannedRun(**run).model_dump(mode="json") for run in runs]
                   or list((consent or {}).get("runs") or []),
           "compute": MandateCompute(**compute).model_dump(exclude={"schema_version"}) if compute is not None and consent is None else None,
           "model_usd": model_usd, "deadline_at": deadline_at,
           "stop_when": (stop_when if isinstance(stop_when, StopCondition) else StopCondition(**stop_when)).model_dump(exclude={"schema_version"}) if stop_when else None,
           "status": status, "granted_by": granted_by, "used": {"worker_seconds": 0.0, "coding_workspaces": 0, "model_usd": 0.0},
           "opened": [], "launched": [], "consent_id": consent_id, "created_at": now()}
    read(workspace, row)   # a row that does not read as a mandate is never recorded
    workspace.store.put("mandate", row, "mandate.proposed" if status == "proposed" else "mandate.granted")
    return read(workspace, row)


def charge(workspace, mandate_id, seconds=0.0, *, coding=0, model_usd=0.0, subjects=(), trial_ids=()):
    """Count started work against a mandate. Its compute goes to the consent that is its compute part, with that consent's
    accounting (compute_consent.spend); otherwise to the mandate itself, with the coding workspaces (subjects) and the runs."""
    with workspace.lock:
        row = _record(workspace, mandate_id, "mandate")
        consent = _record(workspace, row.get("consent_id") if row else mandate_id, "compute_consent")
        if row is None and consent is None:
            raise ValueError(f"No mandate {mandate_id}")
        if row is None and model_usd:
            raise ValueError("A consent recorded before mandates has no model-spend envelope")
        if consent is not None and (seconds or coding or trial_ids):
            compute_consent.spend(workspace, consent, seconds, coding=coding, subjects=subjects, trial_ids=trial_ids)
        if row is not None:
            used = dict(row["used"])
            used["model_usd"] += model_usd or 0.0
            if consent is None:
                used.update(worker_seconds=used["worker_seconds"] + (seconds or 0.0), coding_workspaces=used["coding_workspaces"] + coding)
                if coding:
                    row["opened"] = list(dict.fromkeys([*row.get("opened", []), *subjects]))
                row["launched"] = list(dict.fromkeys([*row.get("launched", []), *trial_ids]))
            row["used"] = used
            workspace.store.put("mandate", row, "mandate.charged")
    return read(workspace, row) if row is not None else from_consent(workspace, workspace.store.get(consent["id"], "compute_consent"))


def stop_reached(workspace, mandate):
    """Whether a mandate's machine stop condition holds: all_runs_terminal, once every run it launched has finished."""
    if mandate.stop_when is None or mandate.stop_when.machine != "all_runs_terminal":
        return False
    row = _record(workspace, mandate.id, "mandate") or {}
    consent = _record(workspace, mandate.consent_id, "compute_consent") or {}
    launched = [*row.get("launched", []), *consent.get("launched", [])]
    trials = [_record(workspace, identity, "trial") for identity in launched]
    return bool(trials) and all(trial is not None and trial.get("status") not in _UNFINISHED for trial in trials)

