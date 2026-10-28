"""A mandate is what one researcher request allows (roadmap Phase 3): the classes of work, the proposals, coding workspaces and
runs it names, a compute and model-spend envelope, a deadline and a stop condition (contracts/mandates.py). Reads are not
commands and are always allowed; every command operation belongs to one class (CLASSES).

Four templates (decision 10): Answer reads and answers and starts nothing; Explore adds proposals, reviews, reuse of installed methods (L5), runs, validations
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

An agent proposes its request's mandate with mandate_propose (R2, agents/tools.py): Answer and Explore within the researcher's
thresholds are granted at once (propose()); Screen and Run the campaign become one inbox card, an approval.request of kind mandate,
and the researcher's choice records the mandate (approve()). A request with none has Explore, recorded at its first command that
starts work (register()).

The bus refuses an agent's work outside its request's mandate (R3, require()): a class the mandate does not allow, for a Screen
mandate a proposal it does not name, work past what is left of Explore's envelope, and once the mandate has ended (its deadline
passed, its envelope spent, or closed: decision 11) anything but answering, asking and recording what the work found; work already
running goes on. A request's own newest mandate governs it (governing()); a standing one serves requests with none of their own.
A request never narrows its own mandate, and has one Explore. The researcher's commands are never checked. When every run of a
mandate with the stop condition all_runs_terminal has ended, it closes and the agent working for its request is told once
(settle()); the researcher is told once when a mandate they granted ends.

Autopilot is a standing mandate (R4, src/balsamic/autopilot/settings.py): Run the campaign for the request the researcher's switch
opens in the autopilot thread, which every round carries. Its envelope is the compute cap, used by every allocation in the campaign
since the switch (campaign_baseline_seconds), as the cap always counted, and its deadline the report date. The bus checks autopilot's
commands (actor autopilot) as it checks the lead's; work that would take a mandate with an envelope of its own (no consent pays for
it) past what is left is refused, by the charge estimate (estimate()), never less than the seconds a run, a continuation, an
allocation or a batch's items state (the cap's own rule).

The researcher may also grant a request's mandate with the message that opens it (R7, the dial beside the chat's send button;
with_message()): Answer and Explore at once, Screen and Run the campaign as their go-ahead, recorded as a resolved decision of
theirs so that its compute part is a consent, which pays for that request's work only. A template the researcher chose is not
widened by an agent's own proposal, and a mandate the researcher closed (mandate.close) is not granted again automatically;
autopilot's mandate is closed by switching autopilot off, not with mandate.close. The campaign's default template, where the dial
starts, is a setting (default_template()); unset, it follows the campaign's autonomy (AUTONOMY)."""
from datetime import datetime, timedelta, timezone

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
    **dict.fromkeys(("implementation.commission", "implementation.attach", "implementation.revalidate",
                     "implementation.resolve_runtime", "implementation.reuse", "implementation.reference", "implementation.control",
                     "evaluator.commission", "evaluator.attach", "campaign.adopt_problem", "asset.reuse", "asset.import_reference_set"), "implement"),
    # Reuse (roadmap L5, decision 27): binding a proposal to an installed method and applying a strategy whose code is installed
    # take no coding time, so Explore allows them.
    **dict.fromkeys(("implementation.bind_builtin", "library.apply"), "reuse"),
    # A batch of interventions is checked by its items' classes (classes_of).
    # The resource planner's plan governs how runs are admitted, within the researcher's level (moved from configure by R3).
    **dict.fromkeys(("trial.create", "trial.continue", "trial.control", "draft.launch", "fixed_mask.run", "inference.run",
                     "runtime.profile", "hypothesis.allocate", "intervention.batch", "study.create", "study.activate",
                     "study.race.create", "study.race.control", "resources.plan"), "run"),
    **dict.fromkeys(("validation.run", "validation.execute", "validation.require", "trial.validate", "evaluator.equivalence",
                     "confirmation.schedule", "confirmation.validate", "reproduction.compare"), "validate"),
    # Stops, nominations, finalists, and what settles a result or a requirement.
    **dict.fromkeys(("hypothesis.status", "hypothesis.nominate", "study.nominate", "finalist.set", "study.race.decide",
                     "confirmation.release", "validation.waive", "validation.revoke_waiver", "decision.resolve",
                     "problem_note.adopt"), "decide"),
    # An agent closing an inbox issue records that its condition no longer holds (moved from configure by R3).
    **dict.fromkeys(("finding.record", "comparison.report", "bundle.export", "bundle.publish", "library.publish", "asset.snapshot",
                     "source.record", "source.ingest", "cost.reconcile", "problem_note.revise", "study.freeze_template", "issue.resolve"), "record"),
    **dict.fromkeys(("experiments.rules", "trial.hide", "journal.compact", "campaign.create", "campaign.update", "campaign.stage_pin",
                     "context.edit", "workers.set", "autopilot.set", "issue.reopen",
                     "problem_note.skip", "problem_note.unskip", "agent.activate", "agent.configure", "agent.control", "agent.rollback",
                     "thread.fork", "thread.rename", "thread.park", "thread.unpark", "thread.pin", "thread.merge_draft",
                     "thread.merge", "mandate.close"), "configure"),
    **dict.fromkeys(("approval.request", "trial.extension_request", "journal.compaction_request", "note.ask"), "ask"),
}
ALL_CLASSES = ("answer", "propose", "review", "reuse", "implement", "run", "validate", "decide", "record", "configure", "ask")
_ANSWER = ("answer", "ask")
_EXPLORE = (*_ANSWER, "propose", "review", "reuse", "run", "validate", "record")
_SCREEN = (*_EXPLORE, "implement", "decide")
TEMPLATES = {"answer": {"classes": _ANSWER, "go_ahead": False}, "explore": {"classes": _EXPLORE, "go_ahead": False},
             "screen": {"classes": _SCREEN, "go_ahead": True}, "run_campaign": {"classes": ALL_CLASSES, "go_ahead": True}}
LABELS = {"answer": "Answer", "explore": "Explore", "screen": "Screen", "run_campaign": "Run the campaign"}
# The three choices on a mandate's card.
OPTIONS = [{"id": "0", "label": "Approve", "description": "The requester starts the work at once, within this envelope and deadline."},
           {"id": "1", "label": "Approve as Explore only", "description": "Only work up to your go-ahead threshold in total, with no coding workspace."},
           {"id": "2", "label": "Decline", "description": "The requester is told and nothing starts."}]
# The classes of work that start something: a request's first such command records its default, Explore.
STARTING = {"propose", "review", "reuse", "implement", "run", "validate", "decide", "record"}
# What a request may still do once its mandate has ended (decision 11): answer, ask for more, and record what its work found.
AFTER_END = {"answer", "ask", "record"}
ENDED = {"expired", "exhausted", "closed"}
_UNFINISHED = {"queued", "running", "pausing", "paused", "stopping", "interrupted"}
# The original plan's three modes, as the default template a campaign's autonomy maps onto (R7).
AUTONOMY = {"manual": "answer", "guided": "explore", "delegated": "screen"}


def default_template(campaign):
    """The template the chat's mandate dial starts at: the researcher's setting (campaign.update), else the one the campaign's
    autonomy maps onto. A request with no mandate still has Explore (decision 10): the default only sets the dial."""
    return campaign.get("default_template") or AUTONOMY.get(campaign.get("autonomy") or "guided", "explore")


def delegates(campaign):
    """Whether the campaign's default template is a go-ahead (Screen or Run the campaign): what autonomy delegated meant."""
    return TEMPLATES[default_template(campaign)]["go_ahead"]


def classes_of(operation, payload=None):
    """The classes a command's work belongs to: its operation's, or for a batch, its items'."""
    if operation == "intervention.batch":
        return {CLASSES[item.get("operation")] for item in (payload or {}).get("items", []) if item.get("operation") in CLASSES}
    return {CLASSES[operation]}


def stated(operation, payload):
    """The worker seconds a command states it reserves, by the rule autopilot's cap guard had (R4): a run's, a continuation's or an
    allocation's wall_seconds (else worker_seconds), a batch's items' worker_seconds (else wall_seconds); 0 when it states none."""
    payload = payload if isinstance(payload, dict) else {}
    if operation in {"trial.create", "trial.continue", "hypothesis.allocate"}:
        return float(payload.get("wall_seconds") or payload.get("worker_seconds") or 0)
    if operation == "intervention.batch":
        return sum(float((item.get("payload") or {}).get("worker_seconds") or (item.get("payload") or {}).get("wall_seconds") or 0)
                   for item in payload.get("items") or [] if isinstance(item, dict))
    return 0.0


def estimate(workspace, operation, payload):
    """A command's charge estimate, checked against its mandate's envelope: the worker seconds it may compute
    (compute_consent.estimate()), never less than what it states it reserves (stated()), so nothing autopilot's cap refused is
    allowed. None when it starts no compute; UNKNOWN when that cannot be told and it states nothing."""
    seconds, reserved = compute_consent.estimate(workspace, operation, payload), stated(operation, payload)
    if seconds is None or seconds == compute_consent.UNKNOWN:
        return reserved or seconds
    return max(seconds, reserved)


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
        if row.get("campaign_baseline_seconds") is not None:   # autopilot's cap (R4): every allocation in the campaign since the grant
            used["worker_seconds"] = max(0.0, workspace.allocated_seconds(row["campaign_id"]) - row["campaign_baseline_seconds"])
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
        status=_status(workspace, "closed" if consent.get("closed_at") else "active", compute, used, None, None, consent, current))


def of_consent(workspace, consent):
    """The mandate a consent is the compute part of: the recorded one that names it, else the consent read as a Screen mandate."""
    row = next((row for row in workspace.store.list("mandate", consent["campaign_id"]) if row.get("consent_id") == consent["id"]), None)
    return read(workspace, row) if row is not None else from_consent(workspace, consent)


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


def governing(workspace, campaign_id, root, found=None, hypothesis_ids=()):
    """The mandate an agent's work for this request is checked against (R3): the request's own newest, ended or not, else the newest
    standing mandate in force (one for no request) that covers the work: campaign-wide when it names no proposals (as a consent from
    before B2), else only work for the proposals it names (decision 4); None when neither, and the request has the default, Explore."""
    root = _root(root)
    found = [mandate for mandate in (mandates(workspace, campaign_id) if found is None else found) if mandate.status != "proposed"]
    own = [mandate for mandate in found if root and mandate.root and same_root(mandate.root.model_dump(), root)]
    if own:
        return own[-1]
    return next((mandate for mandate in reversed(found) if mandate.root is None and mandate.status == "active" and (not mandate.hypothesis_ids
                 or (hypothesis_ids and set(hypothesis_ids) <= set(mandate.hypothesis_ids)))), None)


def current(workspace, campaign_id, root):
    """The mandate in force for this request, its envelope spent or not: the one whose model spend holds its turns."""
    mandate = governing(workspace, campaign_id, root)
    return mandate if mandate is not None and mandate.status in {"active", "exhausted"} else None


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
          compute=None, model_usd=None, deadline_at=None, stop_when=None, consent_id=None, status="active", campaign_baseline=None,
          message_id=None):
    """Record a mandate for a request (root; None for a standing one). Answer and Explore take their template's envelope and may be
    granted automatically. Screen and Run the campaign are the researcher's go-ahead (granted_by, a decision of this campaign),
    with a compute envelope: the consent that is their compute part, or compute (worker_seconds, coding_workspaces). With
    campaign_baseline (the campaign's allocated worker seconds at the grant), its use is every allocation since (autopilot's, R4).
    message_id: the researcher's message it was granted with (R7)."""
    if campaign_baseline is not None and compute is None:
        raise ValueError("Only a mandate with a compute envelope of its own counts the campaign's allocations")
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
           "opened": [], "launched": [], "consent_id": consent_id, "created_at": now(),
           **({"campaign_baseline_seconds": float(campaign_baseline)} if campaign_baseline is not None else {}),
           **({"message_id": message_id} if message_id else {})}
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
    from .plan_runs import planned, run_of
    if consent and any(run_of(workspace.store, consent, run, seed, index) is None for index, seed, run in planned(consent)):
        return False   # a run its plan lists has not run yet
    launched = [*row.get("launched", []), *consent.get("launched", [])]
    trials = [_record(workspace, identity, "trial") for identity in launched]
    return bool(trials) and all(trial is not None and trial.get("status") not in _UNFINISHED for trial in trials)


def _needs(classes):
    """The narrowest template that allows these classes."""
    return next(name for name in TEMPLATES if set(classes) <= set(TEMPLATES[name]["classes"]))


def _ended(mandate):
    if mandate.status == "closed":
        return "it was closed"
    if mandate.status == "exhausted":
        return "its envelope is spent"
    return "its deadline passed" if mandate.deadline_at and compute_consent._clock(mandate.deadline_at) <= datetime.now(timezone.utc) \
        else "the go-ahead's time ran out"


def require(workspace, campaign_id, root, classes, *, what, hypothesis_ids=(), seconds=None):
    """Refuse (ValueError) an agent's work that its request's mandate does not allow (R3): a class outside it; for a Screen mandate,
    work for a proposal it does not name; once it has ended, anything but answering, asking and recording (decision 11); past what
    is left of an Answer or Explore envelope, unless a consent pays for the work, or of a go-ahead's envelope of its own (autopilot's).
    Returns the mandate, None for the default Explore."""
    classes = set(classes)
    if not classes:
        return None
    mandate = governing(workspace, campaign_id, root, hypothesis_ids=hypothesis_ids)
    template = mandate.template if mandate is not None else "explore"
    allowed = set(mandate.classes if mandate is not None else TEMPLATES["explore"]["classes"])
    if template != "answer":
        allowed.add("reuse")   # a mandate recorded before L5 named no reuse class; every template but Answer allows it
    named = (f"this request's {LABELS[template]} mandate ({mandate.id})" if mandate.root is not None else
             f"the standing {LABELS[template]} mandate ({mandate.id})") if mandate is not None else \
        "this request's default mandate, Explore,"   # it has none of its own
    if mandate is not None and mandate.status in ENDED:
        if classes - AFTER_END:
            raise ValueError(f"{what} is new work, and {named} has ended: {_ended(mandate)}. Work already running goes on; you may still answer, "
                             "ask and record what the work found. For more, propose a new mandate with mandate_propose, saying what was done "
                             "and what is left (screen goes to the researcher as one card).")
        return mandate
    if classes - allowed:
        need = _needs(classes)
        raise ValueError(f"{what} is {' and '.join(sorted(classes - allowed))} work, which {named} does not allow: {LABELS[template]} allows "
                         f"{', '.join(cls for cls in ALL_CLASSES if cls in allowed)}. To do it, propose the request's mandate with "
                         f"mandate_propose, template {need}" + (", which goes to the researcher as one card." if TEMPLATES[need]["go_ahead"] else "."))
    if template == "screen" and mandate.hypothesis_ids and (outside := [value for value in hypothesis_ids if value not in mandate.hypothesis_ids]):
        raise ValueError(f"{named[0].upper() + named[1:]} covers the work for {', '.join(mandate.hypothesis_ids)} only, and {what} is for {', '.join(outside)}. "
                         "Propose a mandate that names it with mandate_propose (template screen); it goes to the researcher as one card.")
    if template in {"answer", "explore"} and (mandate is None or not mandate.consent_id) and seconds and seconds != compute_consent.UNKNOWN:
        notice, _ = compute_consent.thresholds(workspace, campaign_id)
        if seconds > notice and any(compute_consent.covers(row, hypothesis_ids, _root(root)) for row in compute_consent.consents(workspace, campaign_id)):
            return mandate   # a consent pays for it, as register() charges it
        total = mandate.compute.worker_seconds if mandate is not None else envelope(workspace, campaign_id, template).worker_seconds
        left = max(0.0, total - (mandate.used.worker_seconds if mandate is not None else 0.0))
        if seconds > left + 1e-9:
            raise ValueError(f"{what} would compute for about {compute_consent._minutes(seconds)}, and {named} has "
                             f"{compute_consent._minutes(left)} of worker time left of {compute_consent._minutes(total)} in total. For more, propose "
                             "the request's mandate with mandate_propose, template screen; it goes to the researcher as one card.")
    if mandate is not None and TEMPLATES[template]["go_ahead"] and not mandate.consent_id and seconds and seconds != compute_consent.UNKNOWN:
        # An envelope of its own, which no consent pays for (autopilot's cap, R4): checked here, by what is left of it.
        total = mandate.compute.worker_seconds
        left = max(0.0, total - mandate.used.worker_seconds)
        if seconds > left + 1e-6:
            raise ValueError(f"{what} would reserve {seconds:g} s of worker time, and {named} has {left:g} s left of its compute cap of {total:g} s. "
                             "Start nothing beyond the cap; only the researcher raises it.")
    return mandate


def close(workspace, mandate_id, *, by, reason):
    """Close a mandate (by the researcher, or when its stop condition holds): new work under it is refused, work already running goes
    on. The consent that is its compute part closes with it, so it pays for nothing more and starts no planned run."""
    with workspace.lock:
        row = _record(workspace, mandate_id, "mandate")
        consent = _record(workspace, row.get("consent_id") if row else mandate_id, "compute_consent")
        if row is None and consent is None:
            raise ValueError(f"No mandate {mandate_id}")
        at = now()
        if consent is not None and not consent.get("closed_at"):
            consent.update(closed_at=at, closed_by=by)
            workspace.store.put("compute_consent", consent, "compute.consent_closed")
        if row is not None and row["status"] != "closed":
            row.update(status="closed", closed_at=at, closed_by=by, close_reason=reason)
            workspace.store.put("mandate", row, "mandate.closed")
    return read(workspace, row) if row is not None else from_consent(workspace, workspace.store.get(consent["id"], "compute_consent"))


AUTOPILOT_CLOSE = "it ends when you switch autopilot off (the Autopilot switch in the top bar)"


def autopilots(workspace, mandate):
    """Whether this is autopilot's standing mandate while autopilot is on (R4): only switching autopilot off ends it, since its
    rounds would otherwise go on starting with all their work refused."""
    settings = (_record(workspace, mandate.campaign_id, "campaign") or {}).get("autopilot") or {}
    return bool(settings.get("enabled")) and settings.get("mandate_id") == mandate.id


def _closed_by(workspace, mandate):
    """Who closed a mandate: the researcher, stop_when, or None while it is not closed."""
    row = _record(workspace, mandate.id, "mandate") or _record(workspace, mandate.consent_id, "compute_consent") or {}
    return row.get("closed_by")


def _owner(workspace, mandate):
    """The agent working for a mandate's request: the page agent whose own request it is, else the lead. None with no team."""
    from optimization_framework.agents.models import PAGE_AGENTS
    config = workspace.pi.configuration(mandate.campaign_id)
    if not config or not config.get("enabled"):
        return None
    root = mandate.root.model_dump() if mandate.root else None
    page = next((agent for agent in workspace.store.list("agent_session", mandate.campaign_id) if agent.get("role") in PAGE_AGENTS
                 and root and same_root(agent.get("desk_root"), root)), None)
    return page or _record(workspace, config.get("lead_id"), "agent_session")


def settle(workspace, campaign_id):
    """Close each mandate whose stop condition holds (all_runs_terminal) and tell the agent working for its request once, under that
    request; tell the researcher once when a mandate they granted ends (expired or spent). Returns the ids of the mandates closed."""
    from optimization_framework.agents.models import NOTICE
    from optimization_framework.contracts.base import content_hash
    closed = []
    for mandate in mandates(workspace, campaign_id):
        row = _record(workspace, mandate.id, "mandate")
        if row is None:
            continue
        if mandate.status == "active" and stop_reached(workspace, mandate):
            mandate = close(workspace, mandate.id, by="stop_when", reason=mandate.stop_when.text)
            closed.append(mandate.id)
            launched = list(dict.fromkeys([*row.get("launched", []), *((_record(workspace, mandate.consent_id, "compute_consent") or {}).get("launched") or [])]))
            agent = _owner(workspace, mandate)
            if agent is not None:
                workspace.pi.enqueue(agent, "mandate_stop_" + content_hash(mandate.id)[:24], NOTICE +
                    f"Every run of this request's {LABELS[mandate.template]} mandate ({mandate.id}) has ended: {', '.join(launched)}. Its stop condition "
                    f"(\"{mandate.stop_when.text}\") holds, so it is closed and starts nothing more. Read the runs and report what they found "
                    "(comparison.report when they compare methods); you may answer, ask and record under it.",
                    root=mandate.root.model_dump(exclude={"schema_version"}) if mandate.root else None)
        elif mandate.status in {"expired", "exhausted"} and mandate.granted_by != "automatic" and not row.get("ended_notice_at"):
            # A quiet end is not news: the researcher is told when it stopped something, an agent's new work or a planned run.
            unstarted = _unstarted(workspace, mandate)
            refused = any(f"({mandate.id}) has ended" in (rejection.get("reason") or "") for rejection in workspace.store.list("command_rejection", campaign_id))
            if not unstarted and not refused:
                continue
            with workspace.lock:
                row["ended_notice_at"] = now()
                workspace.store.put("mandate", row, "mandate.ended")
            workspace.memory.issue(campaign_id, "mandate_ended", f"The {LABELS[mandate.template]} mandate you approved ({mandate.id}: "
                f"\"{(mandate.plan or '')[:120]}\") has ended: {_ended(mandate)}. The agents start no new work under it"
                + (f", and {len(unstarted)} of its approved runs did not start" if unstarted else "") + "; work already running goes on. "
                "Their next card asks you for more, if the request needs it.", affected=mandate.id)
            agent = _owner(workspace, mandate)
            if unstarted and mandate.status == "expired" and agent is not None:   # spent worker time already tells it (plan_runs)
                workspace.pi.enqueue(agent, "mandate_ended_" + content_hash(mandate.id)[:24], NOTICE +
                    f"This request's {LABELS[mandate.template]} mandate ({mandate.id}) has ended ({_ended(mandate)}) before {len(unstarted)} of its "
                    "approved runs started; Balsamic starts none of them now. Report what ran, and propose a new mandate with mandate_propose "
                    "if the request needs the rest.", root=mandate.root.model_dump(exclude={"schema_version"}) if mandate.root else None)
    return closed


def _unstarted(workspace, mandate):
    """The runs a mandate's plan lists (through its consent) that never ran."""
    from .plan_runs import planned, run_of
    consent = _record(workspace, mandate.consent_id, "compute_consent")
    return [(index, seed) for index, seed, run in planned(consent or {}) if run_of(workspace.store, consent, run, seed, index) is None]



def describe(workspace, mandate):
    """A mandate in one line: its template, what is left of its envelope, and its deadline."""
    from .compute_consent import _minutes
    compute, used = mandate.compute, mandate.used
    left = [f"{_minutes(max(0.0, compute.worker_seconds - used.worker_seconds))} of worker time"]
    if compute.coding_workspaces:
        left.append(f"{compute.coding_workspaces - used.coding_workspaces} coding workspace{'s' if compute.coding_workspaces - used.coding_workspaces != 1 else ''}")
    if mandate.model_usd is not None:
        left.append(f"${max(0.0, mandate.model_usd - used.model_usd):.2f} of model spend")
    return (f"{LABELS[mandate.template]} ({mandate.status}), left: " + ", ".join(left)
            + (f"; deadline {mandate.deadline_at[:16].replace('T', ' ')} UTC" if mandate.deadline_at else "; no deadline")
            + (f"; for {', '.join(mandate.hypothesis_ids)}" if mandate.hypothesis_ids else ""))


def deadline(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat() if minutes else None


def propose(workspace, campaign_id, template, root, *, plan=None, hypothesis_ids=(), runs=(), worker_seconds=None, coding_workspaces=0,
            model_usd=None, deadline_minutes=None, stop_when=None):
    """An Answer or Explore mandate an agent proposes, granted at once when it fits the template: none of the researcher's compute for
    Answer, up to their go-ahead threshold in total and no coding workspace for Explore. Larger work is a card (kind mandate).
    (mandate, granted): a request never narrows its own mandate, so one in force that already allows the template's classes is
    returned ungranted; and a request has one Explore, so a second is refused (R3)."""
    if template not in {"answer", "explore"}:
        raise ValueError(f"A {LABELS.get(template, template)} mandate is the researcher's go-ahead: it is proposed as a card")
    from .compute_consent import _minutes
    allowed = envelope(workspace, campaign_id, template).worker_seconds
    if coding_workspaces or (worker_seconds or 0) > allowed:
        raise ValueError(f"{LABELS[template]} covers up to {_minutes(allowed)} of worker time in total and no coding workspace. "
                         "Propose screen (or run_campaign) for more; it goes to the researcher as one card.")
    found = mandates(workspace, campaign_id)
    held = governing(workspace, campaign_id, root, found)
    if held is not None and held.status == "active" and set(TEMPLATES[template]["classes"]) <= set(held.classes):
        return held, False
    # The researcher's own choice for this request stands (R7): a template they chose with their message is not widened, and a
    # mandate they closed is not granted again, by an agent's proposal; a card asks them.
    row = (_record(workspace, held.id, "mandate") or {}) if held is not None and held.root is not None else {}
    if held is not None and held.status == "closed" and _closed_by(workspace, held) == "researcher":
        raise ValueError(f"The researcher closed this request's {LABELS[held.template]} mandate ({held.id}): nothing new starts under it, and it is "
                         "not granted again automatically. Answer, and record what the work found; for more, propose screen, which goes to them as one card.")
    if row.get("message_id") and held.status == "active":
        raise ValueError(f"The researcher chose {LABELS[held.template]} for this request with their message, so it is not widened automatically: "
                         "work within it, and say in your reply what more would need. For more, propose screen, which goes to them as one card.")
    used = next((mandate for mandate in reversed(found) if template == "explore" and mandate.template == "explore" and mandate.root
                 and same_root(mandate.root.model_dump(), _root(root))), None)
    if used is not None:
        raise ValueError(f"This request has had its Explore ({used.id}, {used.status}); a request has one. Propose screen for more work; "
                         "it goes to the researcher as one card.")
    return grant(workspace, campaign_id, template, root=root, plan=plan, hypothesis_ids=hypothesis_ids, runs=runs, model_usd=model_usd,
                 deadline_at=deadline(deadline_minutes), stop_when=stop_when), True


def approve(workspace, decision, explore_only=False):
    """The researcher's choice on a mandate card: the mandate as proposed, its compute part a consent for its plan (so the bus's
    compute guard lets its work start), or Explore only. Returns the outcome the decision records."""
    from .compute_consent import grant as consent_for
    from .proposals import approve as approve_proposals
    request, campaign_id = decision["approval_request"], decision["campaign_id"]
    common = {"root": decision.get("request_root"), "granted_by": decision["id"], "plan": request["plan"], "message_id": decision.get("message_id"),
              "model_usd": request.get("model_usd"), "deadline_at": deadline(request.get("deadline_minutes")), "stop_when": request.get("stop_when")}
    if explore_only:
        mandate = grant(workspace, campaign_id, "explore", hypothesis_ids=request.get("hypothesis_ids") or [], runs=request.get("runs") or [], **common)
        return {"mandate_id": mandate.id, "template": "explore"}
    consent = consent_for(workspace, decision, request)
    approve_proposals(workspace, consent)
    mandate = grant(workspace, campaign_id, request["template"], consent_id=consent["id"], **common)
    return {"mandate_id": mandate.id, "template": mandate.template, "consent_id": consent["id"]}


def with_message(workspace, campaign_id, values, root, *, plan, message_id):
    """The mandate the researcher grants with the message that opens a request (R7): Answer and Explore at once; Screen and Run the
    campaign are their go-ahead, recorded as a resolved decision of theirs for this request and approved as a card would be
    (approve()), so its compute part is a consent and the bus's compute guard lets the work start. That consent is request-only
    (compute_consent.covers()): it pays for this request's work and never another's. Returns the mandate."""
    from optimization_framework.contracts.commands import ApprovalRequestInput
    from optimization_framework.contracts.mandates import MessageMandate
    values = values if isinstance(values, MessageMandate) else MessageMandate(**values)
    root = _root(root)
    if root is None:
        raise ValueError("A mandate is granted with a message in a thread: name the thread")
    plan = plan[:5000]
    if not TEMPLATES[values.template]["go_ahead"]:
        return grant(workspace, campaign_id, values.template, root=root, plan=plan, message_id=message_id)
    for identity in values.hypothesis_ids:
        if (_record(workspace, identity, "hypothesis") or {}).get("campaign_id") != campaign_id:
            raise ValueError(f"{identity} is not a proposal of this campaign")
    wall = min(604800.0, values.deadline_minutes * 60 if values.deadline_minutes else values.worker_seconds)
    request = ApprovalRequestInput(kind="mandate", template=values.template, rationale="Granted by the researcher with their message in the chat",
        plan=plan, worker_seconds=values.worker_seconds, wall_seconds=wall, coding_workspaces=values.coding_workspaces,
        hypothesis_ids=values.hypothesis_ids, model_usd=values.model_usd, deadline_minutes=values.deadline_minutes).model_dump(mode="json", exclude={"schema_version"})
    campaign = workspace.store.get(campaign_id, "campaign")
    title = f"{LABELS[values.template]} mandate granted with your message"
    decision = {"id": "decision_" + message_id, "campaign_id": campaign_id, "charter_version": campaign["version"],
        "guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"], "question": title, "title": title,
        "rationale": "You granted this request's mandate with your message in the chat.", "context": plan[:2000], "proposal": plan,
        "options": OPTIONS[:1], "recommendation": "0", "approval_request": request, "requested_by": "researcher", "audience": "researcher",
        "status": "resolved", "choice": "0", "comment": "", "request_root": root, "message_id": message_id, "created_at": now(), "resolved_at": now(),
        # The go-ahead pays for this request's work only, never another request's, whether or not it names proposals (Hoseung).
        "request_only": True}
    workspace.store.put("decision", decision, "decision.created")
    decision["outcome"] = approve(workspace, decision)
    workspace.store.put("decision", decision, "decision.resolved")
    return read(workspace, workspace.store.get(decision["outcome"]["mandate_id"], "mandate"))


def view(workspace, mandate):
    """A mandate as the chat shows it above the conversation (R7): its template, what is left of its envelope, its deadline, who
    granted it (the researcher with their message or on a card, or automatically) and whether the researcher can still close it."""
    row = _record(workspace, mandate.id, "mandate") or {}
    compute, used = mandate.compute, mandate.used
    decision = _record(workspace, mandate.granted_by, "decision") or {}
    granted = "message" if row.get("message_id") else "automatic" if mandate.granted_by == "automatic" else \
        "autopilot" if decision.get("autopilot") is not None else "card"
    on = autopilots(workspace, mandate)   # autopilot's while it is on: closed by its switch, not here
    return {"id": mandate.id, "template": mandate.template, "label": LABELS[mandate.template], "status": mandate.status,
            "standing": mandate.root is None, "plan": mandate.plan, "hypothesis_ids": mandate.hypothesis_ids, "deadline_at": mandate.deadline_at,
            "granted": granted, "envelope": {"worker_seconds": compute.worker_seconds, "coding_workspaces": compute.coding_workspaces, "model_usd": mandate.model_usd},
            "left": {"worker_seconds": max(0.0, compute.worker_seconds - used.worker_seconds),
                     "coding_workspaces": max(0, compute.coding_workspaces - used.coding_workspaces), "model_usd": model_left(mandate)},
            "summary": describe(workspace, mandate), "closable": mandate.status in {"active", "exhausted"} and not on,
            **({"close_hint": "Autopilot's mandate: " + AUTOPILOT_CLOSE} if on else {}), "closed_by": _closed_by(workspace, mandate),
            "created_at": mandate.created_at}


def register(bus):
    """The bus checks an agent's command, autopilot's too (R4), against its request's mandate (guard, require(), with the charge
    estimate()), and Balsamic's planned runs against the mandate whose consent they run under. A request's first command that starts
    work, from an agent, records the request's default,
    Explore, when no mandate serves it; work an Answer or Explore mandate covers is charged to it, unless a consent pays for it
    (compute_consent.charge); every run started under a mandate is listed on it, for its stop condition."""
    from . import compute_consent as consents
    from optimization_framework.contracts.mandates import MandateCloseInput
    workspace = bus.workspace

    def close_command(command, actor):
        """The researcher closes a mandate from the chat (R7): new work under it is refused, work already running goes on."""
        if actor != "researcher":
            raise ValueError("Only the researcher closes a mandate")
        values = MandateCloseInput(**command.payload)
        mandate = next((found for found in mandates(workspace, command.campaign_id) if found.id == values.mandate_id), None)
        if mandate is None:
            raise ValueError(f"No mandate {values.mandate_id} in this campaign")
        if autopilots(workspace, mandate):
            raise ValueError(f"{mandate.id} is autopilot's standing mandate: {AUTOPILOT_CLOSE}. Closing it alone would leave autopilot on "
                             "with every round's work refused.")
        closed = close(workspace, mandate.id, by="researcher", reason=values.reason)
        return {"mandate_id": closed.id, "template": closed.template, "status": closed.status}

    def guard(command, actor, campaign):
        if actor == "balsamic" and command.operation == "trial.create":
            identity = (command.origin.mandate_id or command.origin.consent_id) if command.origin else None
            mandate = next((found for found in mandates(workspace, command.campaign_id) if identity in {found.id, found.consent_id}), None)
            if mandate is not None and mandate.status != "active":
                raise ValueError(f"The {LABELS[mandate.template]} mandate {mandate.id} that this planned run is approved under has ended "
                                 f"({_ended(mandate)}); Balsamic starts nothing more under it")
            return
        if actor not in {"manager", "autopilot"} or command.operation not in CLASSES:
            return
        require(workspace, command.campaign_id, consents.request_root(workspace, command.origin), classes_of(command.operation, command.payload),
                what=command.operation, hypothesis_ids=consents.proposals(workspace, command.operation, command.payload),
                seconds=estimate(workspace, command.operation, command.payload))

    def listener(record):
        if record.get("actor") != "manager" or record.get("status") != "completed":
            return
        request = record["request"]
        operation, payload, campaign_id = request["operation"], request["payload"], request["campaign_id"]
        if operation not in CLASSES or not classes_of(operation, payload) & STARTING:
            return
        asked = consents.request_root(workspace, record.get("origin"))
        root = _root(asked)
        if root is None:
            return
        with workspace.lock:
            found = governing(workspace, campaign_id, root)
            if found is None:
                found = grant(workspace, campaign_id, "explore", root=root)
            if found.status != "active":
                return
            trials = consents._trials(record.get("outcome"))
            row = _record(workspace, found.id, "mandate")
            if trials and row is not None and set(trials) - set(row.get("launched", [])):
                row["launched"] = list(dict.fromkeys([*row.get("launched", []), *trials]))
                workspace.store.put("mandate", row, "mandate.launched")
            seconds = estimate(workspace, operation, payload)
            if found.consent_id or found.template not in {"answer", "explore"} or not seconds or seconds == consents.UNKNOWN:
                return
            notice, gate = consents.thresholds(workspace, campaign_id)
            hypothesis_ids = consents.proposals(workspace, operation, payload)
            if seconds > notice and any(consents.covers(row, hypothesis_ids, asked) for row in consents.consents(workspace, campaign_id)):
                return   # a consent pays for it
            charge(workspace, found.id, seconds, trial_ids=trials)

    bus.register("mandate.close", close_command, model=MandateCloseInput)
    bus.guards.append(guard)
    # Before the consent's own listener, so that a consent's use is read before it charges.
    bus.listeners.insert(0, listener)
