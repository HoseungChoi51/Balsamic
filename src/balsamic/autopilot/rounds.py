"""Autopilot rounds: while enabled, and no request is open, the lead gets a request turn in the autopilot thread to work the
frontier within the cap. A new round starts when the previous one's work has finished. The last round asks for the report.

Every round's run carries the request of autopilot's standing mandate (R4, settings.py), so the bus's mandate guard checks its
commands against the cap and the report date, and the state block states what is left; the prompt no longer does. Beside it, guard()
keeps autopilot's own checks: nothing while it is off, nothing under another mandate, and no card for another one."""
from datetime import datetime, timedelta, timezone

from optimization_framework.storage.sqlite import now

from balsamic.autopilot.settings import settings_of
from balsamic.threads.service import lead_agent

ROUND_PROMPT = ("Autopilot round {round}. Review the evolution graph (campaign_inspect with evolution; the frontier and the live runs). Stop "
                "strategies with a stop outcome and its evidence (hypothesis.status archived), promote finalists (hypothesis.nominate), allocate more "
                "time to the promising ones (hypothesis.allocate), and ask for new strategies (research.generate) when the frontier is thin; prefer "
                "intervention.batch for several at once. Every command states its rationale. Then call yield_work(complete) with one paragraph: what "
                "you did and why, and what the next round should look at.")
REPORT_PROMPT = ("Autopilot: the report is due by {report_by} (within a day) or the compute cap is reached. Do not start new runs. Write the report with report_write "
                 "from the finalists and the confirmed evidence, say what remains open, then yield_work(complete).")
RUN_WINDOW_SECONDS = 86400


def autopilot_thread_id(campaign_id):
    return f"thread_autopilot_{campaign_id}"


def ensure_thread(workspace, campaign_id):
    identity = autopilot_thread_id(campaign_id)
    try:
        return workspace.store.get(identity, "thread")
    except KeyError:
        record = {"id": identity, "campaign_id": campaign_id, "name": "autopilot", "title": "Autopilot", "parent_thread_id": None, "fork_message_id": None,
                  "fork_entry_id": None, "agent_leaf": None, "status": "active", "merged_into": None, "pinned_ids": [], "excluded_ids": [], "anchors": [], "summary": None,
                  "guidance_revision": 0, "last_seen_message_id": None, "system": True, "created_at": now(), "updated_at": now()}
        with workspace.lock:
            return workspace.store.put("thread", record, "thread.created")


def spent_since_baseline(workspace, campaign_id, settings):
    return max(0.0, workspace.resources.assessment(campaign_id)["allocated_seconds"] - float(settings.get("baseline_allocated_seconds") or 0))


def remaining(workspace, campaign_id, settings):
    return float(settings.get("compute_cap_seconds") or 0) - spent_since_baseline(workspace, campaign_id, settings)


def report_at(report_by):
    """The report date as a time (UTC when it names no zone); None when there is none or it cannot be read."""
    if not report_by:
        return None
    try:
        due = datetime.fromisoformat(str(report_by).replace("Z", "+00:00"))
    except ValueError:
        return None
    return due if due.tzinfo is not None else due.replace(tzinfo=timezone.utc)


def report_due(settings, clock=None):
    due = report_at(settings.get("report_by"))
    return due is not None and (clock or datetime.now(timezone.utc)) >= due - timedelta(days=1)


def round_state(workspace, campaign_id):
    """What the tick sees: whether a round may start, and why not otherwise. Read by the monitor too."""
    campaign = workspace.store.get(campaign_id, "campaign")
    settings = settings_of(campaign)
    if not settings.get("enabled"):
        return {"enabled": False, "reason": "autopilot is off", "can_start": False, "settings": settings}
    config = workspace.pi.configuration(campaign_id) or {}
    lead = lead_agent(workspace, campaign_id)
    state = {"enabled": True, "settings": settings, "spent_seconds": spent_since_baseline(workspace, campaign_id, settings),
             "remaining_seconds": remaining(workspace, campaign_id, settings), "rounds_completed": settings.get("rounds_completed", 0)}
    if not lead or config.get("status") != "running":
        return {**state, "can_start": False, "reason": "the agent team is not running"}
    if config.get("request_open"):
        return {**state, "can_start": False, "reason": "a request is open: researcher messages come first"}
    runs = workspace.store.list_agent_runs(lead["id"])
    if any(run["status"] in {"queued", "submitted", "running"} for run in runs):
        return {**state, "can_start": False, "reason": "the lead is in a turn"}
    live = [t for t in workspace.store.list("trial", campaign_id) if t.get("status") in {"queued", "running", "pausing", "stopping"}]
    if live:
        return {**state, "can_start": False, "reason": f"{len(live)} runs of the previous round are still going"}
    if settings.get("report_requested"):
        return {**state, "can_start": False, "reason": "the final round asked for the report"}
    from balsamic.evolution.stages import definition
    gate = definition(workspace, campaign)
    if not gate["ready"]:
        return {**state, "can_start": False, "reason": "the problem definition is incomplete: " + gate["step"]["title"].lower() + " (" + gate["step"]["page"] + ")"}
    from balsamic.evolution.stages import evaluator
    blocked = evaluator(workspace, campaign)
    if blocked:
        return {**state, "can_start": False, "reason": "the evaluator cannot start in this lab: " + blocked["error"]}
    if report_due(settings) or state["remaining_seconds"] <= 0:
        return {**state, "can_start": True, "final": True, "reason": "the cap or the report date is reached: the last round writes the report"}
    return {**state, "can_start": True, "final": False, "reason": "ready for the next round"}


def tick(workspace):
    """Called from the workspace's maintenance thread; starts at most one round per campaign per pass."""
    for campaign in workspace.store.list("campaign"):
        settings = settings_of(campaign)
        if not settings.get("enabled"):
            continue
        try:
            count_finished_rounds(workspace, campaign["id"])
            state = round_state(workspace, campaign["id"])
            if state.get("can_start"):
                start_round(workspace, campaign["id"], final=state.get("final", False))
        except (KeyError, ValueError) as exc:
            workspace.memory.issue(campaign["id"], "autopilot_round", str(exc), affected=campaign["id"])


def count_finished_rounds(workspace, campaign_id):
    """A round is complete when its run ended; the settings carry the count and the digest is written then."""
    with workspace.lock, workspace.store.transaction():
        campaign = workspace.store.get(campaign_id, "campaign")
        settings = settings_of(campaign)
        last = settings.get("last_round_run_id")
        if not last:
            return
        run = workspace.store.get(last, "agent_run")
        if run["status"] in {"completed", "failed", "interrupted", "stopped"} and not settings.get("last_round_counted"):
            settings["rounds_completed"] = settings.get("rounds_completed", 0) + 1
            settings["last_round_counted"] = True
            settings["last_round_finished_at"] = now()
            campaign["autopilot"] = settings
            workspace.store.put("campaign", campaign, "campaign.autopilot_round_completed")
            from balsamic.monitor.digest import maybe_write_digest
            maybe_write_digest(workspace, campaign_id)


def start_round(workspace, campaign_id, *, final=False):
    campaign = workspace.store.get(campaign_id, "campaign")
    settings = settings_of(campaign)
    thread = ensure_thread(workspace, campaign_id)
    lead = lead_agent(workspace, campaign_id)
    number = settings.get("rounds_completed", 0) + 1
    prompt = REPORT_PROMPT.format(report_by=settings.get("report_by") or "the cap") if final else ROUND_PROMPT.format(round=number)
    identity = f"pi_autopilot_{campaign_id}_{number}"
    with workspace.lock, workspace.store.transaction():
        if not settings.get("mandate_id"):   # switched on before autopilot was a mandate (R4): granted now, on the terms set then
            from balsamic.autopilot.settings import grant_mandate
            settings.update(grant_mandate(workspace, campaign_id, settings, settings.get("command_id") or identity))
        workspace.pi._request(campaign_id, True)
        message = {"id": "message_" + identity, "campaign_id": campaign_id, "role": "user", "origin": "autopilot", "thread_id": thread["id"],
                   "content": f"Round {number}" + (" (final: the report)" if final else "") + f": review the frontier within {remaining(workspace, campaign_id, settings):.0f} s of the cap.", "created_at": now()}
        workspace.store.put("message", message, "message.created")
        # A turn of autopilot's request: its mandate's root (the switch) with this run, so that governing() finds the mandate.
        root = {**settings["mandate_root"], "run_id": identity}
        run = workspace.pi.enqueue(lead, identity, prompt, mode="follow_up", origin={"thread_id": thread["id"], "message_id": message["id"], "actor": "autopilot", "root": root},
                                   **({"leaf_entry_id": thread["agent_leaf"]} if thread.get("agent_leaf") else {}), thread_revision=thread.get("guidance_revision"), autopilot=True)
        settings.update(last_round_run_id=run["id"], last_round_counted=False, last_round_started_at=now(), report_requested=bool(final))
        campaign["autopilot"] = settings
        workspace.store.put("campaign", campaign, "campaign.autopilot_round")
    return run


def guard(workspace):
    """Autopilot's own checks, beside the bus's mandate guard that holds it to its standing mandate (R4): its commands are refused
    while it is off, and under any mandate but the one its switch granted; no agent files a mandate card for its request, whose
    terms (the cap and the report date) are the researcher's, set with autopilot.set."""
    from optimization_framework.campaigns import mandates
    from optimization_framework.campaigns.compute_consent import request_root

    def check(command, actor, campaign):
        if actor not in {"autopilot", "manager"}:
            return
        settings = settings_of(campaign)
        if actor == "autopilot" and not settings.get("enabled"):
            raise ValueError("Autopilot is off; this turn's commands are refused")
        if not settings.get("enabled") or not settings.get("mandate_root"):
            return
        asked = request_root(workspace, command.origin)
        if command.operation == "approval.request" and (command.payload or {}).get("kind") == "mandate" and mandates.same_root(asked, settings["mandate_root"]):
            raise ValueError(f"Autopilot's request works under the standing mandate its switch granted ({settings['mandate_id']}): its compute "
                             "cap and report date are the researcher's to change, so no other mandate is proposed for it. Say what more it "
                             "needs in the round's summary.")
        if actor == "autopilot":
            found = mandates.governing(workspace, command.campaign_id, asked)
            if found is None or found.id != settings["mandate_id"]:
                raise ValueError(f"Autopilot works only under the standing mandate its switch granted ({settings['mandate_id']}); this "
                                 "turn is under " + (f"another ({found.id})" if found else "none") + ". Say what more it needs in the "
                                 "round's summary; the researcher sets autopilot's cap and report date.")
    return check


def register(workspace):
    workspace.commands.guards.insert(0, guard(workspace))   # first, as the cap guard it replaces came first for autopilot's commands
    previous = workspace.on_manager_tick

    def on_tick():
        if previous:
            previous()
        tick(workspace)
    workspace.on_manager_tick = on_tick
