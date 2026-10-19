"""autopilot.set: the researcher's switch, the compute cap and the report deadline; delegation follows it."""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract
from optimization_framework.storage.sqlite import now


class AutopilotInput(Contract):
    enabled: bool
    compute_cap_seconds: float | None = Field(default=None, gt=0, le=604800)
    report_by: str | None = Field(default=None, max_length=64, description="An ISO date or datetime; the last round asks for the report a day before it")
    rationale: str = Field(default="", max_length=2000)


def settings_of(campaign):
    return campaign.get("autopilot") or {"enabled": False}


def register(workspace):
    def set_autopilot(command, actor):
        if actor != "researcher":
            raise ValueError("Only the researcher turns autopilot on or off")
        values = AutopilotInput(**command.payload)
        with workspace.lock, workspace.store.transaction():
            campaign = workspace.store.get(command.campaign_id, "campaign")
            previous = settings_of(campaign)
            if values.enabled:
                if values.compute_cap_seconds is None:
                    raise ValueError("Autopilot needs a compute cap: how many worker seconds it may allocate")
                if not workspace.pi.owns(command.campaign_id):
                    raise ValueError("Start the agent team first: autopilot runs the lead")
                baseline = workspace.resources.assessment(command.campaign_id)["allocated_seconds"]
                settings = {"enabled": True, "compute_cap_seconds": values.compute_cap_seconds, "report_by": values.report_by,
                            "baseline_allocated_seconds": baseline, "enabled_at": now(), "command_id": command.id,
                            "rounds_completed": previous.get("rounds_completed", 0) if previous.get("enabled") else 0, "rationale": values.rationale,
                            "report_requested": False, "last_round_run_id": previous.get("last_round_run_id") if previous.get("enabled") else None}
                if campaign.get("autonomy") != "delegated":
                    campaign["autonomy_before_autopilot"] = campaign.get("autonomy")
                    campaign["autonomy"] = "delegated"
            else:
                settings = {**previous, "enabled": False, "disabled_at": now(), "disable_rationale": values.rationale}
                if campaign.get("autonomy_before_autopilot"):
                    campaign["autonomy"] = campaign.pop("autonomy_before_autopilot")
            campaign["autopilot"] = settings
            workspace.store.put("campaign", campaign, "campaign.autopilot_changed")
        return {"campaign_id": command.campaign_id, "autopilot": settings}

    workspace.commands.register("autopilot.set", set_autopilot, model=AutopilotInput)
