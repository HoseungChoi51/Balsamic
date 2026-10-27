"""Compute is the researcher's to start, at every step, under two thresholds they set per campaign (campaign.update; by default a
minute and five minutes of worker time). An agent's work up to the notice threshold starts freely. Work up to the go-ahead
threshold starts too, with a notice to the researcher that stays in the inbox until they acknowledge it, unless an approved plan
covers it. Anything longer, and any coding workspace, waits for the researcher's go-ahead, knowing what will run, why, how long
it takes and what they can do meanwhile.

The agent asks with approval.request (kind compute); the researcher's approval records a compute consent for that plan's
worker time (and the coding workspaces it opens). The command bus refuses an agent's work-starting command that is not
covered (guard) and charges what it starts to the consent, or records the notice (listener); coding workspaces, their
validations and analysis scripts are checked where they start. The researcher's own commands are never checked, and autopilot's
compute cap, which the researcher set when switching it on, is autopilot's go-ahead. A request to do some work is not a go-ahead
for its compute.
"""
from datetime import datetime, timedelta, timezone

from optimization_framework.storage.sqlite import identifier, now

NOTICE_SECONDS, GATE_SECONDS = 60.0, 300.0   # the defaults of a campaign's two thresholds
UNKNOWN = float("inf")
SAME = {"trial.create": 60, "trial.continue": 60, "fixed_mask.run": 60, "validation.run": 120, "validation.execute": 120,
        "inference.run": 120, "evaluator.equivalence": 120}


# What a notice calls the work an operation starts.
WORDS = {"trial.create": "a run", "trial.continue": "a run's continuation", "fixed_mask.run": "a fixed-mask run", "draft.launch": "a run from a draft",
         "validation.run": "a validation", "validation.execute": "a validation", "inference.run": "an inference run",
         "evaluator.equivalence": "an evaluator equivalence check", "hypothesis.allocate": "an allocation", "intervention.batch": "a batch of work",
         "runtime.profile": "a runtime profile", "implementation.commission": "an implementation job", "evaluator.commission": "an evaluator job",
         "implementation.revalidate": "a revalidation", "study.race.create": "a race"}


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


def _clock(at):
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def consents(workspace, campaign_id):
    """The researcher's compute consents still in force, oldest first."""
    current = datetime.now(timezone.utc)
    return sorted((row for row in workspace.store.list("compute_consent", campaign_id) if _clock(row["expires_at"]) > current),
                  key=lambda row: row["granted_at"])


def covering(workspace, campaign_id, seconds=0.0, *, coding=0):
    """The first consent with this much worker time (and these coding workspaces) left, or None."""
    return next((row for row in consents(workspace, campaign_id) if row["worker_seconds"] - row["used_seconds"] >= seconds
                 and row["coding_workspaces"] - row["used_workspaces"] >= coding), None)


def _minutes(seconds):
    return "an unknown time" if seconds == UNKNOWN else f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def refusal(workspace, campaign_id, what, seconds=None):
    gate = _minutes(thresholds(workspace, campaign_id)[1])
    left = [f"{_minutes(row['worker_seconds'] - row['used_seconds'])} of worker time and {row['coding_workspaces'] - row['used_workspaces']} "
            f"coding workspaces for \"{row['plan'][:80]}\"" for row in consents(workspace, campaign_id)]
    return (f"{what} would compute for {'about ' + _minutes(seconds) if seconds is not None else 'an unknown time'}, and the researcher "
            f"has not given the go-ahead for it. Nothing that computes for more than {gate} (the researcher's go-ahead threshold), and no "
            "coding workspace, starts without it, even when a request implies the work. File approval.request with kind compute: plan "
            "(what will run and why), wall_seconds (how long until results), worker_seconds, coding_workspaces, meanwhile (what the researcher can do while it runs), and for experiments "
            "runs (each: task_id, hypothesis_id or algorithm, seeds, wall_seconds, max_evaluations, device), so the researcher reads "
            "their measured speed, outputs and disk use; start once they approve. " + ("Approved and unused: " + "; ".join(left) + "." if left else "No approved plan has time left."))


def require(workspace, campaign_id, what, seconds=0.0, *, coding=0):
    """The consent that covers this work, or ValueError with the refusal; work up to the go-ahead threshold needs none."""
    if not coding and seconds is not None and seconds <= thresholds(workspace, campaign_id)[1]:
        return None
    consent = covering(workspace, campaign_id, seconds or 0.0, coding=coding)
    if consent is None:
        raise ValueError(refusal(workspace, campaign_id, what, seconds))
    return consent


def charge(workspace, campaign_id, seconds=0.0, *, coding=0, what="work", origin=None, subjects=()):
    """Count started work against the consent that covers it. Work between the two thresholds that no consent covers is not
    charged: it starts with a notice to the researcher (a compute_notice, in the inbox until they acknowledge it)."""
    if not coding and seconds is None:
        return
    notice, gate = thresholds(workspace, campaign_id)
    if not coding and seconds <= notice:
        return
    with workspace.lock:
        consent = covering(workspace, campaign_id, seconds or 0.0, coding=coding)
        if consent is None and not coding and seconds <= gate:
            origin = origin or {}
            workspace.store.put("compute_notice", {"id": identifier("compute_notice"), "campaign_id": campaign_id, "what": what,
                "seconds": seconds, "agent_id": origin.get("agent_id"), "thread_id": origin.get("thread_id"), "subjects": list(subjects),
                "thresholds": {"notice_seconds": notice, "gate_seconds": gate}, "created_at": now()}, "compute.notice")
            return
        consent = consent or next(iter(consents(workspace, campaign_id)), None)
        if consent is not None:
            consent.update(used_seconds=consent["used_seconds"] + (seconds or 0.0), used_workspaces=consent["used_workspaces"] + coding)
            workspace.store.put("compute_consent", consent, "compute.consent_used")


def _subjects(outcome):
    """The records a started command names, for the notice's links."""
    outcome = outcome if isinstance(outcome, dict) else {}
    found = [outcome[key] for key in ("trial_id", "draft_id", "validation_id", "profile_id", "grant_id") if isinstance(outcome.get(key), str)]
    return found + [value for value in outcome.get("trial_ids") or [] if isinstance(value, str)]


def grant(workspace, decision, request):
    """Record the researcher's approval of a compute plan; returns the consent."""
    granted = datetime.now(timezone.utc)
    return workspace.store.put("compute_consent", {"id": identifier("compute_consent"), "campaign_id": decision["campaign_id"],
        "decision_id": decision["id"], "plan": request["plan"], "worker_seconds": request["worker_seconds"],
        "wall_seconds": request["wall_seconds"], "coding_workspaces": request.get("coding_workspaces", 0), "used_seconds": 0.0,
        "used_workspaces": 0, "granted_at": now(),
        "expires_at": (granted + timedelta(seconds=max(3600, 3 * request["wall_seconds"]))).isoformat()}, "compute.consent_granted")


def register(bus):
    """Check and charge every agent's work-starting command on the bus."""
    workspace = bus.workspace

    def guard(command, actor, campaign):
        if actor != "manager":
            return
        seconds = estimate(workspace, command.operation, command.payload)
        if seconds is not None:
            require(workspace, command.campaign_id, command.operation, seconds)

    def listener(record):
        if record.get("actor") == "manager" and record.get("status") == "completed":
            request = record["request"]
            charge(workspace, request["campaign_id"], estimate(workspace, request["operation"], request["payload"]),
                   what=WORDS.get(request["operation"], request["operation"]), origin=record.get("origin"), subjects=_subjects(record.get("outcome")))

    bus.guards.append(guard)
    bus.listeners.append(listener)
