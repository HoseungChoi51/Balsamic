"""Balsamic's additions to the command bus. Each feature module registers its own operations here."""
from optimization_framework.contracts.base import Contract
from optimization_framework.storage.sqlite import now
from pydantic import Field
from typing import Literal


class StagePinInput(Contract):
    """Pin the campaign's stage badge, or clear the pin so it follows the records again."""
    stage: Literal["formulate", "generate", "optimize", "report"] | None = None
    reason: str = Field(default="", max_length=2000)


def register(workspace):
    commands = workspace.commands
    # The Pi controller syncs with the harness when the harness notifies and on every maintenance tick (the legacy
    # campaign manager used to drive it): queued turns are submitted, finished ones received.
    previous_tick = workspace.on_manager_tick

    def sync_agents():
        if previous_tick:
            previous_tick()
        for campaign in workspace.store.list("campaign"):
            if workspace.pi.owns(campaign["id"]):
                workspace.pi.tick(campaign["id"])
    workspace.on_manager_tick = sync_agents

    def thread_revision(command):
        origin = command.origin
        thread_id = origin.thread_id if origin else None
        return workspace.memory.thread_revision(thread_id) if thread_id else 0

    commands.thread_revision = thread_revision

    def stage_pin(command, actor):
        if actor != "researcher":
            raise ValueError("Only the researcher pins the stage")
        values = StagePinInput(**command.payload)
        campaign = workspace.store.get(command.campaign_id, "campaign")
        campaign["stage_pin"] = values.stage
        campaign["stage_pin_reason"] = values.reason
        workspace.store.put("campaign", campaign, "campaign.stage_pinned")
        return {"campaign_id": campaign["id"], "stage_pin": values.stage}

    commands.register("campaign.stage_pin", stage_pin, model=StagePinInput)
    # The lead runs the workspace's operations on request; the page agents keep their own lists.
    workspace.lead_operations = {"hypothesis.allocate", "intervention.batch", "research.generate", "hypothesis.nominate", "thread.pin", "problem_note.revise", "library.apply"}
    from balsamic.threads.service import register as register_threads
    register_threads(workspace)
    from balsamic.evolution.generate import register as register_generate
    register_generate(workspace)
    from balsamic.notes.service import register as register_notes
    register_notes(workspace)
    from balsamic.evolution.interventions import register as register_interventions
    register_interventions(workspace)
    from balsamic.library.service import register as register_library
    register_library(workspace)
    from balsamic.autopilot.settings import register as register_autopilot
    from balsamic.autopilot.rounds import register as register_rounds
    register_autopilot(workspace)
    register_rounds(workspace)
    from balsamic.lead.tools import register as register_tools
    from balsamic.lead.instructions import lead_instructions
    if "thread_pin" not in __import__("optimization_framework.agents.tools", fromlist=["EXTRA_TOOLS"]).EXTRA_TOOLS:
        register_tools()   # process-wide; handlers act on the workspace of the tools that call them
    workspace.lead_instructions = lead_instructions(workspace)
