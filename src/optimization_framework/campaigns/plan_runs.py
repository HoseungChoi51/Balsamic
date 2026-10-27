"""Approved runs start by themselves (roadmap B5). A compute go-ahead whose plan lists runs (each a task, a proposal, seeds, a wall
time) is the researcher's approval of exactly those runs. Once a planned run's proposal can run (bound to an installed method that
fits the task, its evaluator ready), Balsamic's system actor starts one trial per planned seed through the bus, under that consent
(decision 6): the command's origin names the consent and the request it was approved in, and its id derives from (consent, run,
seed), so a replay starts nothing. Never more than the plan: a run it does not list is never created, a seed already run since the
go-ahead (by anyone) is not run again, and when the consent's worker time is spent, launching stops and the lead is told. When
every planned run has ended, the lead is woken once to write the comparison.
"""
from optimization_framework.contracts.base import content_hash

# A run in one of these states has ended; paused and interrupted runs can still go on.
ENDED = {"completed", "stopped", "failed", "budget_exhausted"}


def command_id(consent_id, index, seed):
    return "balsamic_run_" + content_hash([consent_id, index, seed])[:24]


def current_task(store, task_id):
    """The task a planned run runs on: the planned one, or the task that superseded it (E4)."""
    seen = set()
    while task_id not in seen:
        seen.add(task_id)
        try:
            task = store.get(task_id, "task")
        except KeyError:
            return None
        if not task.get("superseded_by_task_id"):
            return task
        task_id = task["superseded_by_task_id"]
    return None


def lineage(store, task_id):
    """The planned task and every task that superseded it."""
    found, task = [task_id], None
    while (task := _get(store, found[-1], "task")) and task.get("superseded_by_task_id") and task["superseded_by_task_id"] not in found:
        found.append(task["superseded_by_task_id"])
    return found


def _get(store, identity, kind):
    try:
        return store.get(identity, kind)
    except KeyError:
        return None


def planned(consent):
    """[(run index, seed, run)] of a consent's plan: the runs that name a proposal, one entry per seed."""
    return [(index, seed, run) for index, run in enumerate(consent.get("runs") or []) if run.get("hypothesis_id")
            for seed in dict.fromkeys(run.get("seeds") or [])]


def matches(store, consent, run, seed, trial):
    return (trial.get("hypothesis_id") == run["hypothesis_id"] and trial.get("seed") == seed and not trial.get("hidden")
            and trial.get("task_id") in lineage(store, run["task_id"]) and trial.get("created_at", "") >= consent["granted_at"])


def run_of(store, consent, run, seed, index):
    """The trial that ran this planned seed since the go-ahead: Balsamic's, or one an agent or the researcher started. None."""
    receipt = _get(store, command_id(consent["id"], index, seed), "work_command")
    if receipt:
        return _get(store, receipt["outcome"].get("trial_id"), "trial")
    return next((trial for trial in store.list("trial", consent["campaign_id"]) if matches(store, consent, run, seed, trial)), None)


def check(workspace, command):
    """The bus guard for Balsamic's trial.create: the consent its origin names is in force, its plan lists this run (proposal, task
    or its successor, seed, at most the planned wall time and evaluations), the seed has not run since the go-ahead, and the
    consent has the worker time left. ValueError otherwise."""
    from .compute_consent import consents
    store, payload = workspace.store, command.payload
    consent_id = command.origin.consent_id if command.origin else None
    consent = next((row for row in consents(workspace, command.campaign_id) if row["id"] == consent_id), None)
    if consent is None:
        raise ValueError("Balsamic starts a run only under a compute go-ahead in force that its origin names (consent_id)")
    listed = [(index, run) for index, seed, run in planned(consent) if run["hypothesis_id"] == payload.get("hypothesis_id")
              and seed == payload.get("seed", 0) and payload.get("task_id") in lineage(store, run["task_id"])
              and float(payload.get("wall_seconds", 60)) <= float(run["wall_seconds"])
              and (run.get("max_evaluations") is None or payload.get("max_steps", 512) <= run["max_evaluations"])]
    if not listed:
        raise ValueError(f"The approved plan of {consent['id']} lists no such run; Balsamic starts only the runs a plan lists")
    if command.id not in {command_id(consent["id"], index, payload.get("seed", 0)) for index, _ in listed}:
        raise ValueError("A planned run's command id derives from its consent, run and seed")
    if any(run_of(store, consent, run, payload.get("seed", 0), index) for index, run in listed):
        raise ValueError("This planned run already ran since the go-ahead")
    if consent["worker_seconds"] - consent["used_seconds"] < float(payload.get("wall_seconds", 60)):
        raise ValueError(f"The worker time of {consent['id']} is spent")


def started_by_balsamic(workspace, campaign_id, payload):
    """A run Balsamic started for a plan that an agent's trial.create would repeat (same proposal, task, seed): its trial, or None."""
    store = workspace.store
    from .compute_consent import consents
    for consent in consents(workspace, campaign_id):
        for index, seed, run in planned(consent):
            if (run["hypothesis_id"] == payload.get("hypothesis_id") and seed == payload.get("seed", 0)
                    and payload.get("task_id") in lineage(store, run["task_id"])):
                receipt = _get(store, command_id(consent["id"], index, seed), "work_command")
                trial = _get(store, (receipt or {}).get("outcome", {}).get("trial_id"), "trial")
                if trial and not trial.get("hidden"):
                    return trial
    return None


def charge(workspace, record):
    """Count a run Balsamic started against the consent its origin names, and list it there."""
    origin, request = record.get("origin") or {}, record["request"]
    trial_id = (record.get("outcome") or {}).get("trial_id")
    with workspace.lock:
        consent = _get(workspace.store, origin.get("consent_id"), "compute_consent")
        if consent is None:
            return
        consent.update(used_seconds=consent["used_seconds"] + float(request["payload"].get("wall_seconds", 60)),
                       launched=list(dict.fromkeys([*consent.get("launched", []), *([trial_id] if trial_id else [])])))
        workspace.store.put("compute_consent", consent, "compute.consent_used")


def runnable(workspace, hypothesis, task):
    """None when a planned run of this proposal can start on this task, else why not."""
    if hypothesis is None:
        return "No such proposal"
    if hypothesis.get("status") == "archived":
        return "The proposal is stopped"
    if task is None or task.get("archived"):
        return "Its task is no longer current"
    view = workspace.evaluators.task_view(task)
    if not view.get("problem"):
        return "Its task has no problem definition yet"
    implementation = workspace.implementations.readiness(hypothesis, view)
    if not implementation.get("runnable"):
        return implementation.get("reason") or "Its method cannot run yet"
    if implementation.get("default_method"):
        return "No method has been chosen or bound for it yet"
    from .proposals import readiness
    if not (review := readiness(workspace.store, hypothesis))["eligible"]:
        return review["reason"]
    try:
        evaluator = workspace.evaluators.readiness(view, wait=False)
    except (KeyError, ValueError) as exc:
        return str(exc)
    if not evaluator.get("runnable"):
        return evaluator.get("reason") or "Its evaluator is not ready"
    return None


def launch_ready(workspace, campaign_id):
    """Start every approved planned run that can run now and has not run since its go-ahead; tell the lead when a consent's
    worker time stops the launching, and once when all of a consent's planned runs have ended. {launched, waiting}."""
    from optimization_framework.contracts.commands import Command, CommandOrigin
    from .compute_consent import consents
    store = workspace.store
    from .mandates import of_consent
    launched, waiting = [], []
    for consent in consents(workspace, campaign_id):
        if not planned(consent):
            continue
        mandate = of_consent(workspace, consent)
        if mandate.status != "active":
            continue   # its deadline passed or it was closed: Balsamic starts nothing more under it (R3)
        for index, seed, run in planned(consent):
            if run_of(store, consent, run, seed, index):
                continue
            hypothesis = _get(store, run["hypothesis_id"], "hypothesis")
            task = current_task(store, run["task_id"])
            if (reason := runnable(workspace, hypothesis, task)) is not None:
                waiting.append({"consent_id": consent["id"], "hypothesis_id": run["hypothesis_id"], "seed": seed, "reason": reason})
                continue
            consent = store.get(consent["id"], "compute_consent")
            if consent["worker_seconds"] - consent["used_seconds"] < float(run["wall_seconds"]):
                _spent(workspace, consent)
                break
            root = consent.get("request_root") or {}
            payload = {"task_id": task["id"], "hypothesis_id": run["hypothesis_id"], "seed": seed, "wall_seconds": run["wall_seconds"],
                       "question": f"An approved planned run: {consent['plan']}"[:10000]}
            if hypothesis.get("implementation_version_id"):
                payload["algorithm"] = "package"
            else:
                payload.update(algorithm=hypothesis["algorithm"], algorithm_config=hypothesis.get("algorithm_config") or {})
            if run.get("max_evaluations"):
                payload["max_steps"] = run["max_evaluations"]
            if run.get("device"):
                payload["device"] = run["device"]
            campaign = store.get(campaign_id, "campaign")
            command = Command(id=command_id(consent["id"], index, seed), campaign_id=campaign_id, operation="trial.create",
                expected_revision=campaign["version"], payload=payload,
                origin=CommandOrigin(actor="balsamic", consent_id=consent["id"], mandate_id=mandate.id if mandate.id != consent["id"] else None,
                                     thread_id=root.get("thread_id"),
                                     message_id=root.get("message_id"),
                                     rationale=f"Run {index + 1} of the plan approved in {consent['decision_id']}, seed {seed}"))
            try:
                receipt = workspace.commands.execute(command, actor="balsamic")
            except ValueError as exc:
                waiting.append({"consent_id": consent["id"], "hypothesis_id": run["hypothesis_id"], "seed": seed, "reason": str(exc)[:300]})
                continue
            launched.append({"consent_id": consent["id"], "hypothesis_id": run["hypothesis_id"], "task_id": task["id"], "seed": seed,
                             "trial_id": receipt["outcome"].get("trial_id"), "command_id": receipt["id"]})
    for consent in store.list("compute_consent", campaign_id):
        _finished(workspace, consent)
    return {"launched": launched, "waiting": waiting}


def _lead(workspace, campaign_id):
    config = workspace.pi.configuration(campaign_id)
    if not config or not config.get("enabled"):
        return None
    return _get(workspace.store, config.get("lead_id"), "agent_session")


def _tell(workspace, consent, key, text):
    from optimization_framework.agents.models import NOTICE
    lead = _lead(workspace, consent["campaign_id"])
    if lead is not None:
        workspace.pi.enqueue(lead, "plan_runs_" + content_hash([consent["id"], key])[:24], NOTICE + text, root=consent.get("request_root"))


def _spent(workspace, consent):
    """Once per consent: its worker time stopped the launching."""
    if consent.get("launch_stopped_at"):
        return
    from optimization_framework.storage.sqlite import now
    consent["launch_stopped_at"] = now()
    workspace.store.put("compute_consent", consent, "compute.consent_spent")
    total = len(planned(consent))
    started = sum(1 for index, seed, run in planned(consent) if run_of(workspace.store, consent, run, seed, index))
    _tell(workspace, consent, "spent", f"The go-ahead {consent['decision_id']} (\"{consent['plan'][:120]}\") has no worker time left: "
          f"Balsamic started {started} of its {total} approved runs and stopped there. Ask the researcher for a new go-ahead "
          "(a mandate, mandate_propose) for the rest.")


def _finished(workspace, consent):
    """Once per consent that Balsamic started runs for (in force or not): every planned run has a run that ended. A mandate with a
    stop condition tells its request itself when it closes (mandates.settle)."""
    store = workspace.store
    from .mandates import of_consent
    stop = of_consent(workspace, consent).stop_when
    if consent.get("finished_notice_at") or (stop is not None and stop.machine) or not any(_get(store, command_id(consent["id"], index, seed), "work_command")
                                                    for index, seed, _ in planned(consent)):
        return
    runs = [run_of(store, consent, run, seed, index) for index, seed, run in planned(consent)]
    if not runs or not all(trial and trial["status"] in ENDED for trial in runs):
        return
    from optimization_framework.storage.sqlite import now
    consent["finished_notice_at"] = now()
    store.put("compute_consent", consent, "compute.consent_finished")
    _tell(workspace, consent, "finished", f"All {len(runs)} approved runs of the go-ahead {consent['decision_id']} "
          f"(\"{consent['plan'][:120]}\") finished: {', '.join(trial['id'] for trial in runs)}. Write the comparison (comparison.report).")
