"""Compute is the researcher's to start, at every step, under two thresholds they set per campaign (campaign.update; by default a
minute and five minutes of worker time). An agent's work up to the notice threshold starts freely. Work up to the go-ahead
threshold starts too, with a notice to the researcher that stays in the inbox until they acknowledge it, unless an approved plan
covers it. Anything longer, and any coding workspace, waits for the researcher's go-ahead, knowing what will run, why, how long
it takes and what they can do meanwhile.

The agent proposes a mandate (mandate_propose; approval.request kind mandate, which replaces kind compute for agents); the
researcher's approval records a compute consent for that plan's worker time (and the coding workspaces it opens) as the mandate's
compute part. The command bus refuses an agent's work-starting command that is not
covered (guard) and charges what it starts to the consent, or records the notice (listener); coding workspaces, their
validations and analysis scripts are checked where they start. The researcher's own commands are never checked, and autopilot's
go-ahead is the standing mandate its switch granted, with the cap the researcher set (mandates.py, R4). A request to do some work
is not a go-ahead for its compute.

A consent covers only the work its plan names (decision 4): a coding workspace for a proposal it names, a run or commission of
such a proposal, and work for no proposal (a runtime profile, a validation) asked in the same researcher request. A plan that
names no proposals, as every consent recorded before plans named them, covers any work in the campaign. A go-ahead the
researcher gives with a chat message (R7) is request-only: it covers the work of that request alone, with or without proposals
(Hoseung, 27 October 2026). A consent stays in force
while a coding workspace it opened runs, and for three times its wall time after the last one stops. The runs a plan lists
start by themselves once their proposals can run (plan_runs.py), each charged to the consent it ran under.

A consent is the compute part of a mandate (campaigns/mandates.py): one that no mandate names reads as a Screen mandate.
"""
from datetime import datetime, timedelta, timezone

from optimization_framework.storage.sqlite import identifier, now

NOTICE_SECONDS, GATE_SECONDS = 60.0, 300.0   # the defaults of a campaign's two thresholds
UNKNOWN = float("inf")
SAME = {"trial.create": 60, "trial.continue": 60, "validation.run": 120, "validation.execute": 120,
        "inference.run": 120, "evaluator.equivalence": 120}


# What a notice calls the work an operation starts.
WORDS = {"trial.create": "a run", "trial.continue": "a run's continuation", "draft.launch": "a run from a draft",
         "validation.run": "a validation", "validation.execute": "a validation", "inference.run": "an inference run",
         "evaluator.equivalence": "an evaluator equivalence check", "hypothesis.allocate": "an allocation", "intervention.batch": "a batch of work",
         "runtime.profile": "a runtime profile", "implementation.commission": "an implementation job", "evaluator.commission": "an evaluator job",
         "implementation.revalidate": "a revalidation", "study.race.create": "a race"}


def declare(operation, seconds, words):
    """An operation a problem pack registers that computes up to its payload's wall_seconds (default ``seconds``), and what
    a notice calls its work."""
    SAME[operation], WORDS[operation] = seconds, words


def thresholds(workspace, campaign_id):
    """The researcher's (notice, go-ahead) thresholds for this campaign, in worker seconds."""
    campaign = workspace.store.get(campaign_id, "campaign")
    notice, gate = campaign.get("compute_notice_seconds"), campaign.get("compute_gate_seconds")
    return (float(NOTICE_SECONDS if notice is None else notice), float(GATE_SECONDS if gate is None else gate))


def estimate(workspace, operation, payload):
    """The worker seconds an operation may compute, None when it starts no compute, UNKNOWN when it cannot be told."""
    if operation in SAME:
        return float(payload.get("wall_seconds", SAME[operation]))
    if operation == "draft.launch":
        draft = workspace.store.get(payload["draft_id"], "experiment_draft")
        return float((draft.get("request") or {}).get("wall_seconds", 60))
    if operation == "hypothesis.allocate":
        return float(payload.get("worker_seconds", UNKNOWN))
    if operation == "intervention.batch":
        parts = [estimate(workspace, item.get("operation"), item.get("payload") or {}) for item in payload.get("items", [])]
        return sum(part for part in parts if part is not None) if any(part is not None for part in parts) else None
    if operation == "runtime.profile":
        workers = max(1, int(getattr(workspace, "max_workers", 1) or 1))
        levels = sorted({1, workers, *(2 ** power for power in range(12) if 2 ** power < workers)})
        return float(payload.get("probe_seconds", 30)) * (sum(levels) + 1)   # each level's probes, and one on the GPU
    if operation in {"implementation.commission", "evaluator.commission"}:
        return float(payload.get("compute_seconds", UNKNOWN))
    if operation == "implementation.revalidate":
        return float(payload.get("compute_seconds", 120))
    if operation == "study.race.create":
        return float(payload.get("worker_seconds", 230400))
    if operation in {"confirmation.schedule", "confirmation.validate"}:
        return UNKNOWN
    return None


def proposals(workspace, operation, payload):
    """The proposals an operation's work is for: the payload's, a draft's, a continued run's, a race's or a batch's items'."""
    if operation == "intervention.batch":
        return list(dict.fromkeys(found for item in payload.get("items", [])
                                  for found in proposals(workspace, item.get("operation"), item.get("payload") or {})))
    found = [payload.get("hypothesis_id")]
    if operation == "draft.launch":
        found.append(((_record(workspace, payload.get("draft_id"), "experiment_draft") or {}).get("request") or {}).get("hypothesis_id"))
    if operation == "trial.continue":
        found.append((_record(workspace, payload.get("trial_id"), "trial") or {}).get("hypothesis_id"))
    if operation == "study.race.create":
        found += [item.get("hypothesis_id") for item in payload.get("configurations", []) if isinstance(item, dict)]
    return list(dict.fromkeys(value for value in found if isinstance(value, str)))


def request_root(workspace, origin):
    """The researcher's request an agent's command descends from: the lead turn's request root, the one an assistant or page
    agent was given with its assignment, or the researcher's own request on a page agent's page. None when it cannot be told."""
    origin = origin if isinstance(origin, dict) else origin.model_dump() if origin is not None else {}
    run = _record(workspace, origin.get("run_id"), "agent_run")
    if run is None:
        return None
    from optimization_framework.agents.models import LEAD
    agent = _record(workspace, run.get("agent_id"), "agent_session") or {}
    return workspace.pi.request_root(run) if agent.get("role") == LEAD else agent.get("assignment_origin") or agent.get("desk_root") or None


def _record(workspace, identity, kind):
    try:
        return workspace.store.get(identity, kind) if isinstance(identity, str) else None
    except KeyError:
        return None


def _clock(at):
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def _in_force(workspace, row, current):
    """Until its expiry, while a coding workspace it opened runs, and for 3 x its wall time after the last one stops; never once
    closed with its mandate (R3)."""
    if row.get("closed_at"):
        return False
    if _clock(row["expires_at"]) > current:
        return True
    opened = [found for found in (_record(workspace, identity, "development_workspace") for identity in row.get("workspace_ids") or []) if found]
    if any(found.get("desired_status") == "running" for found in opened):
        return True
    stopped = [_clock(found.get("control_requested_at") or found["created_at"]) for found in opened]
    return bool(stopped) and max(stopped) + timedelta(seconds=3 * row["wall_seconds"]) > current


def consents(workspace, campaign_id):
    """The researcher's compute consents still in force, oldest first."""
    current = datetime.now(timezone.utc)
    return sorted((row for row in workspace.store.list("compute_consent", campaign_id) if _in_force(workspace, row, current)),
                  key=lambda row: row["granted_at"])


def covers(row, hypothesis_ids=(), root=None):
    """Whether a consent's plan names this work: every proposal it is for, or for no proposal, the same researcher request. A
    request-only consent (the researcher's go-ahead given with a chat message, R7) covers work in its own request and nothing else,
    whether or not it names proposals."""
    if row.get("request_only"):
        from .mandates import same_root
        if not same_root(row.get("request_root"), root):
            return False
    named = row.get("hypothesis_ids")
    if not named:
        return True
    if hypothesis_ids:
        return set(hypothesis_ids) <= set(named)
    return root is not None and row.get("request_root") == root


def covering(workspace, campaign_id, seconds=0.0, *, coding=0, hypothesis_ids=(), root=None):
    """The first consent that names this work and has this much worker time (and these coding workspaces) left, or None."""
    return next((row for row in consents(workspace, campaign_id) if covers(row, hypothesis_ids, root)
                 and row["worker_seconds"] - row["used_seconds"] >= seconds
                 and row["coding_workspaces"] - row["used_workspaces"] >= coding), None)


def _minutes(seconds):
    return "an unknown time" if seconds == UNKNOWN else f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def _left(row):
    named = row.get("hypothesis_ids")
    return (f"{_minutes(row['worker_seconds'] - row['used_seconds'])} of worker time and {row['coding_workspaces'] - row['used_workspaces']} "
            f"coding workspaces for \"{row['plan'][:80]}\"" + (f" (for {', '.join(named)})" if named else ""))


def refusal(workspace, campaign_id, what, seconds=None, *, hypothesis_ids=(), root=None):
    gate = _minutes(thresholds(workspace, campaign_id)[1])
    from .mandates import same_root
    # Another request's request-only go-ahead (R7) is not this work's to use, so it is not offered.
    rows = [row for row in consents(workspace, campaign_id) if not row.get("request_only") or same_root(row.get("request_root"), root)]
    named = [row for row in rows if covers(row, hypothesis_ids, root)]
    work = f"work for {', '.join(hypothesis_ids)}" if hypothesis_ids else "this work"
    if named:
        state = "Approved and unused: " + "; ".join(map(_left, named)) + "."
    elif rows:
        state = (f"No approved plan covers {work}: each covers only the proposals it names, and work for no proposal only in "
                 "the request it was approved for. Approved and unused: " + "; ".join(map(_left, rows)) + ".")
    else:
        state = "No approved plan has time left."
    return (f"{what} would compute for {'about ' + _minutes(seconds) if seconds is not None else 'an unknown time'}, and the researcher "
            f"has not given the go-ahead for it. Nothing that computes for more than {gate} (the researcher's go-ahead threshold), and no "
            "coding workspace, starts without it, even when a request implies the work. Propose the request's mandate with mandate_propose, "
            "template screen: plan (what will run and why), wall_seconds (how long until results), worker_seconds, coding_workspaces, hypothesis_ids "
            "(the proposals it is for), meanwhile (what the researcher can do while it runs), and for experiments "
            "runs (each: task_id, hypothesis_id or algorithm, seeds, wall_seconds, max_evaluations, device), so the researcher reads "
            "their measured speed, outputs and disk use; start once they approve. " + state)


def require(workspace, campaign_id, what, seconds=0.0, *, coding=0, hypothesis_ids=(), root=None):
    """The consent that covers this work, or ValueError with the refusal; work up to the go-ahead threshold needs none."""
    if not coding and seconds is not None and seconds <= thresholds(workspace, campaign_id)[1]:
        return None
    consent = covering(workspace, campaign_id, seconds or 0.0, coding=coding, hypothesis_ids=hypothesis_ids, root=root)
    if consent is None:
        raise ValueError(refusal(workspace, campaign_id, what, seconds, hypothesis_ids=hypothesis_ids, root=root))
    return consent


def charge(workspace, campaign_id, seconds=0.0, *, coding=0, what="work", origin=None, subjects=(), hypothesis_ids=(), root=None,
           trial_ids=()):
    """Count started work against the consent that covers it, and record on it what it was spent on: the coding workspaces
    (subjects) and the runs (trial_ids). Work between the two thresholds that no consent covers is not charged: it starts with a
    notice to the researcher (a compute_notice, in the inbox until they acknowledge it)."""
    if not coding and seconds is None:
        return
    notice, gate = thresholds(workspace, campaign_id)
    if not coding and seconds <= notice:
        return
    with workspace.lock:
        consent = covering(workspace, campaign_id, seconds or 0.0, coding=coding, hypothesis_ids=hypothesis_ids, root=root)
        if consent is None and not coding and seconds <= gate:
            origin = origin or {}
            workspace.store.put("compute_notice", {"id": identifier("compute_notice"), "campaign_id": campaign_id, "what": what,
                "seconds": seconds, "agent_id": origin.get("agent_id"), "thread_id": origin.get("thread_id"), "subjects": list(subjects),
                "thresholds": {"notice_seconds": notice, "gate_seconds": gate}, "created_at": now()}, "compute.notice")
            return
        consent = consent or next((row for row in consents(workspace, campaign_id) if covers(row, hypothesis_ids, root)), None)
        if consent is not None:
            spend(workspace, consent, seconds, coding=coding, subjects=subjects, trial_ids=trial_ids)


def spend(workspace, consent, seconds=0.0, *, coding=0, subjects=(), trial_ids=()):
    """Count work against this consent, with the coding workspaces (subjects) and the runs it paid for. The caller holds the lock."""
    consent.update(used_seconds=consent["used_seconds"] + (seconds or 0.0), used_workspaces=consent["used_workspaces"] + coding)
    if coding:
        consent["workspace_ids"] = list(dict.fromkeys([*consent.get("workspace_ids", []), *subjects]))
    if trial_ids:
        consent["launched"] = list(dict.fromkeys([*consent.get("launched", []), *trial_ids]))
    return workspace.store.put("compute_consent", consent, "compute.consent_used")


def _subjects(outcome):
    """The records a started command names, for the notice's links."""
    outcome = outcome if isinstance(outcome, dict) else {}
    found = [outcome[key] for key in ("trial_id", "draft_id", "validation_id", "profile_id", "grant_id", "workspace_id") if isinstance(outcome.get(key), str)]
    return found + [value for value in outcome.get("trial_ids") or [] if isinstance(value, str)]


def _trials(outcome):
    """The runs a started command launched."""
    outcome = outcome if isinstance(outcome, dict) else {}
    return [value for value in [outcome.get("trial_id"), *(outcome.get("trial_ids") or [])] if isinstance(value, str)]


def grant(workspace, decision, request):
    """Record the researcher's approval of a compute plan, with what it names: the proposals (those it lists and those its runs
    are for) and the researcher's request it was asked in. Returns the consent."""
    granted = datetime.now(timezone.utc)
    named = [*(request.get("hypothesis_ids") or []), *(run.get("hypothesis_id") for run in request.get("runs") or [])]
    return workspace.store.put("compute_consent", {"id": identifier("compute_consent"), "campaign_id": decision["campaign_id"],
        "decision_id": decision["id"], "plan": request["plan"], "worker_seconds": request["worker_seconds"],
        "wall_seconds": request["wall_seconds"], "coding_workspaces": request.get("coding_workspaces", 0), "used_seconds": 0.0,
        "egress_hosts": list(request.get("egress_hosts") or []), "used_wall_seconds": 0.0,
        "used_workspaces": 0, "hypothesis_ids": list(dict.fromkeys(value for value in named if value)), "runs": list(request.get("runs") or []),
        "request_root": decision.get("request_root"), "workspace_ids": [], "launched": [], "granted_at": now(),
        "expires_at": (granted + timedelta(seconds=max(3600, 3 * request["wall_seconds"]))).isoformat(),
        # Given with the researcher's chat message (R7): it pays for the work of that request only (covers()).
        **({"request_only": True} if decision.get("request_only") else {})}, "compute.consent_granted")


def register(bus):
    """Check and charge every agent's work-starting command on the bus, against the consent that names its proposals."""
    workspace = bus.workspace

    def guard(command, actor, campaign):
        if actor == "balsamic" and command.operation == "trial.create":
            from .plan_runs import check
            return check(workspace, command)
        if actor in {"manager", "autopilot"} and command.operation == "trial.create":
            from .plan_runs import started_by_balsamic
            if (trial := started_by_balsamic(workspace, command.campaign_id, command.payload)) is not None:
                raise ValueError(f"Balsamic already started this approved run ({trial['id']}, seed {trial.get('seed', 0)}); "
                                 "use another seed to run the proposal again")
        if actor != "manager":
            return
        seconds = estimate(workspace, command.operation, command.payload)
        if seconds is not None:
            require(workspace, command.campaign_id, command.operation, seconds,
                    hypothesis_ids=proposals(workspace, command.operation, command.payload), root=request_root(workspace, command.origin))

    def listener(record):
        if record.get("actor") == "balsamic" and record["request"]["operation"] == "trial.create":
            from .plan_runs import charge as charge_planned
            return charge_planned(workspace, record)
        if record.get("actor") == "manager" and record.get("status") == "completed":
            request = record["request"]
            charge(workspace, request["campaign_id"], estimate(workspace, request["operation"], request["payload"]),
                   what=WORDS.get(request["operation"], request["operation"]), origin=record.get("origin"), subjects=_subjects(record.get("outcome")),
                   hypothesis_ids=proposals(workspace, request["operation"], request["payload"]),
                   root=request_root(workspace, record.get("origin")), trial_ids=_trials(record.get("outcome")))

    bus.guards.append(guard)
    bus.listeners.append(listener)
