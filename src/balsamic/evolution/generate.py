"""research.generate: the researcher asks for a round of strategies; the lead's turn produces them; placeholders stand in the chat until they land."""
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now


class GenerateInput(Contract):
    operation: Literal["diversify", "hybrid", "revise"] = "diversify"
    parent_ids: list[str] = Field(default_factory=list, max_length=12)
    count: int = Field(default=3, ge=1, le=8)
    note: str = Field(default="", max_length=8000)


PROMPTS = {
    "diversify": ("Propose {count} new strategies for this problem, each with a different mechanism from the others and from the recorded proposals. "
                  "Where the problem allows, take them from different families (exact, solver, constructive, local_search, learning, hybrid), "
                  "including an exact or problem-specific method when the instance sizes make one plausible; set each one's family, "
                  "and say why a family is left out."),
    "hybrid": "Propose {count} strategies that combine the mechanisms of {parents}; each names its parents in parent_ids.",
    "revise": "Revise {parents} in the light of its reviews and results: propose {count} revision(s), each naming it in parent_ids with a change_summary.",
}


def register(workspace):
    def generate(command, actor):
        values = GenerateInput(**command.payload)
        campaign_id = command.campaign_id
        for parent in values.parent_ids:
            if workspace.store.get(parent, "hypothesis")["campaign_id"] != campaign_id:
                raise ValueError("A parent belongs to another campaign")
        if values.operation != "diversify" and not values.parent_ids:
            raise ValueError("A hybrid or a revision names its parent hypotheses")
        if not workspace.pi.owns(campaign_id):
            raise ValueError("Start the agent team first: the lead generates strategies")
        origin = command.origin.model_dump() if command.origin else {}
        thread_id = origin.get("thread_id")
        batch = "ph_" + content_hash(command.id)[:12]
        placeholders = []
        for index in range(values.count):
            record = {"id": f"{batch}_{index + 1}", "campaign_id": campaign_id, "batch_id": batch, "thread_id": thread_id, "command_id": command.id,
                      "operation": values.operation, "status": "pending", "hypothesis_id": None, "created_at": now()}
            workspace.store.put("placeholder", record, "placeholder.created")
            placeholders.append(record["id"])
        parents = ", ".join(values.parent_ids) or "the recorded proposals"
        prompt = ("Research request (research.generate, batch " + batch + "): " + PROMPTS[values.operation].format(count=values.count, parents=parents)
                  + (" Researcher's note: " + values.note if values.note else "")
                  + " You own this request: propose the strategies yourself from the problem, the evidence and the library, or, for a wide search, ask the "
                  "discussion moderator (page_agent_message) to run a generation round with its specialists and report their proposals back to you. Either way, "
                  "record each strategy with hypothesis.create (mechanism, rationale, parent_ids where they apply, round = the next round number); the chat shows "
                  "a placeholder per expected strategy until each lands. When all are recorded, ask the moderator to review the batch, then yield_work with a short "
                  "summary that names each strategy.")
        from balsamic.threads.service import lead_agent, thread_of
        lead = lead_agent(workspace, campaign_id)
        workspace.pi._request(campaign_id, True)
        placement = {}
        if thread_id:
            thread = thread_of(workspace, thread_id)
            placement = {"thread_revision": thread.get("guidance_revision"), **({"leaf_entry_id": thread["agent_leaf"]} if thread.get("agent_leaf") else {"branch_from_entry_id": thread.get("fork_entry_id")})}
        run = workspace.pi.enqueue(lead, "pi_run_" + command.id, prompt, mode="steer", origin={**origin, "actor": origin.get("actor") or actor, "batch_id": batch}, **placement)
        workspace.store.put("message", {"id": "message_" + command.id, "campaign_id": campaign_id, "role": "user", "origin": "researcher" if actor == "researcher" else "autopilot",
                                        "content": f"/generate {values.count} {values.operation}" + (" of " + parents if values.parent_ids else "") + (": " + values.note if values.note else ""),
                                        "thread_id": thread_id, "refs": placeholders, "run_id": run["id"], "created_at": now()}, "message.created")
        return {"run_id": run["id"], "batch_id": batch, "placeholders": placeholders}

    def resolve_placeholders(record):
        """A hypothesis recorded by the generating run fills the next placeholder of its batch."""
        if record["request"]["operation"] != "hypothesis.create":
            return
        origin = record.get("origin") or {}
        run_id = origin.get("run_id")
        if not run_id:
            return
        try:
            run = workspace.store.get(run_id, "agent_run")
        except KeyError:
            return
        batch = (run.get("origin") or {}).get("batch_id")
        if not batch:
            return
        pending = [row for row in workspace.store.list("placeholder", record["campaign_id"]) if row["batch_id"] == batch and row["status"] == "pending"]
        if pending:
            slot = pending[0]
            slot.update(status="resolved", hypothesis_id=record["outcome"]["hypothesis_id"], resolved_at=now())
            workspace.store.put("placeholder", slot, "placeholder.resolved")

    workspace.commands.register("research.generate", generate, model=GenerateInput, delegable=True)
    workspace.commands.listeners.append(resolve_placeholders)
