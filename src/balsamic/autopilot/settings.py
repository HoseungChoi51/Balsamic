"""autopilot.set: the researcher's switch, the compute cap and the report deadline; delegation follows it.

Switching it on grants autopilot's standing mandate (roadmap R4): Run the campaign, for the request the switch opens in the
autopilot thread, with the cap as its worker seconds (used by every allocation in the campaign since the switch, as the cap always
counted) and the report date as its deadline. The switch is recorded as a decision the researcher resolved: the go-ahead the
mandate names, whose id stands for the request's message in its root. A change of the cap or the date while on closes that mandate
and grants one on the new terms for the same request, so a round at work goes on under them; switching off closes it."""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now


class AutopilotInput(Contract):
    enabled: bool
    compute_cap_seconds: float | None = Field(default=None, gt=0, le=604800)
    report_by: str | None = Field(default=None, max_length=64, description="An ISO date or datetime; the last round asks for the report a day before it")
    rationale: str = Field(default="", max_length=2000)


def settings_of(campaign):
    return campaign.get("autopilot") or {"enabled": False}


def grant_mandate(workspace, campaign_id, settings, command_id, root=None):
    """Record the researcher's switch (command_id) as a resolved decision and grant autopilot's standing mandate under it, for root
    (the request a change while on continues) or a new request in the autopilot thread. Returns the settings' mandate_id and
    mandate_root."""
    from optimization_framework.campaigns import mandates
    from optimization_framework.campaigns.compute_consent import _minutes
    from balsamic.autopilot.rounds import ensure_thread, report_at
    campaign = workspace.store.get(campaign_id, "campaign")
    cap, due = float(settings["compute_cap_seconds"]), report_at(settings.get("report_by"))
    terms = f"a compute cap of {_minutes(cap)}" + (f", the report by {due.isoformat()[:16].replace('T', ' ')} UTC" if due else "")
    identity = "decision_autopilot_" + content_hash([campaign_id, command_id])[:24]
    workspace.store.put("decision", {"id": identity, "campaign_id": campaign_id, "charter_version": campaign["version"],
        "title": "Autopilot on: " + terms, "question": "Autopilot on: " + terms, "rationale": settings.get("rationale") or "",
        "options": [{"id": "0", "label": "On", "description": "Rounds on the frontier within the cap, until the report date."}],
        "status": "resolved", "choice": "0", "comment": "", "requested_by": "researcher", "audience": "researcher", "command_id": command_id,
        "autopilot": {"compute_cap_seconds": cap, "report_by": settings.get("report_by")}, "created_at": now(), "resolved_at": now()},
        "decision.resolved")
    root = root or {"thread_id": ensure_thread(workspace, campaign_id)["id"], "message_id": identity, "run_id": None}
    mandate = mandates.grant(workspace, campaign_id, "run_campaign", root=root, granted_by=identity, compute={"worker_seconds": cap},
        plan="Autopilot: rounds on the frontier (stop, promote, allocate, generate) within " + terms,
        deadline_at=due.isoformat() if due else None, campaign_baseline=settings.get("baseline_allocated_seconds") or 0.0)
    return {"mandate_id": mandate.id, "mandate_root": root}


def register(workspace):
    def set_autopilot(command, actor):
        if actor != "researcher":
            raise ValueError("Only the researcher turns autopilot on or off")
        values = AutopilotInput(**command.payload)
        from optimization_framework.campaigns import mandates
        with workspace.lock, workspace.store.transaction():
            campaign = workspace.store.get(command.campaign_id, "campaign")
            previous = settings_of(campaign)
            if values.enabled:
                if values.compute_cap_seconds is None:
                    raise ValueError("Autopilot needs a compute cap: how many worker seconds it may allocate")
                if not workspace.pi.owns(command.campaign_id):
                    raise ValueError("Start the agent team first: autopilot runs the lead")
                from balsamic.evolution.gate import check
                check(workspace, command.campaign_id, "Autopilot")
                baseline = workspace.resources.assessment(command.campaign_id)["allocated_seconds"]
                settings = {"enabled": True, "compute_cap_seconds": values.compute_cap_seconds, "report_by": values.report_by, "requested": None,
                            "baseline_allocated_seconds": baseline, "enabled_at": now(), "command_id": command.id,
                            "rounds_completed": previous.get("rounds_completed", 0) if previous.get("enabled") else 0, "rationale": values.rationale,
                            "report_requested": False, "last_round_run_id": previous.get("last_round_run_id") if previous.get("enabled") else None}
                if campaign.get("autonomy") != "delegated":
                    campaign["autonomy_before_autopilot"] = campaign.get("autonomy")
                    campaign["autonomy"] = "delegated"
                # A change while on: the same request goes on, under a mandate on the new terms.
                if previous.get("enabled") and previous.get("mandate_id"):
                    mandates.close(workspace, previous["mandate_id"], by="researcher", reason="Autopilot's cap or report date changed")
                settings.update(grant_mandate(workspace, command.campaign_id, settings, command.id,
                                              root=previous.get("mandate_root") if previous.get("enabled") else None))
            else:
                settings = {**previous, "enabled": False, "disabled_at": now(), "disable_rationale": values.rationale}
                if campaign.get("autonomy_before_autopilot"):
                    campaign["autonomy"] = campaign.pop("autonomy_before_autopilot")
                if previous.get("mandate_id"):
                    mandates.close(workspace, previous["mandate_id"], by="researcher", reason="Autopilot switched off"
                                   + (": " + values.rationale if values.rationale else ""))
            campaign["autopilot"] = settings
            workspace.store.put("campaign", campaign, "campaign.autopilot_changed")
        return {"campaign_id": command.campaign_id, "autopilot": settings}

    workspace.commands.register("autopilot.set", set_autopilot, model=AutopilotInput)
