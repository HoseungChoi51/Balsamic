"""Researcher approvals of what an agent asked for: extensions, limits, waivers, the worker ceiling, journal clean-ups, and
the platform's ask to raise a request's model-spend envelope.

An agent files a request as a decision (trial.extension_request, approval.request, journal.compaction_request); the
researcher resolves it in the inbox, and the change runs as the researcher's own command through the bus, with the
approval's guidance revision pinned. Nothing here starts work the researcher did not choose.
"""
from copy import deepcopy

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.commands import Command, DecisionResolveInput
from optimization_framework.storage.sqlite import identifier, now


def finish_decision(workspace, decision, choice, comment, outcome):
    decision.update(status="resolved", choice=choice, comment=comment, resolved_at=now(), outcome=outcome)
    workspace.store.put("decision", decision, "decision.resolved")
    label = next((o["label"] for o in decision["options"] if o["id"] == choice), choice)
    workspace.store.put("message", {"id": identifier("message"), "campaign_id": decision["campaign_id"], "role": "user",
        "origin": "lab_event", "content": f"Decision: {decision['title']}\nChoice: {label}\n{comment}", "created_at": now()}, "message.created")
    return decision


def _child(workspace, command, campaign, operation, payload):
    return Command(id="decision_action_" + content_hash(command.id)[:32], campaign_id=command.campaign_id,
        operation=operation, expected_revision=campaign["version"],
        expected_guidance_revision=workspace.memory.state(command.campaign_id)["guidance_revision"],
        expected_authority_hash=workspace.commands.authority_hash(campaign), payload=payload)


def resolve(workspace, command):
    values = DecisionResolveInput(**command.payload)
    decision = workspace.commands._target(command, "decision_id", "decision")
    if decision.get("resolution_revision", 0) != values.expected_resolution_revision:
        raise ValueError("Decision resolution changed; refresh before submitting another choice")
    if decision["status"] != "pending":
        raise ValueError("This decision has already been resolved or has a pending delivery")
    if values.choice not in {option["id"] for option in decision["options"]} and values.choice != "custom":
        raise ValueError("Select a listed option or provide a custom direction")
    from .decisions import public_decision
    view = public_decision(workspace, decision)
    if values.choice in view["freshness"]["blocked_choice_ids"]:
        raise ValueError(view["freshness"]["reason"])
    campaign = workspace.store.get(command.campaign_id, "campaign")
    effect = consent = None
    if values.choice == "0" and decision.get("trial_id") and decision.get("incremental_solver_calls") is not None:
        trial = workspace.store.get(decision["trial_id"], "trial")
        if trial["campaign_id"] != command.campaign_id:
            raise ValueError("The experiment belongs to another campaign")
        seconds = decision.get("estimated_seconds")
        if seconds is None:
            raise ValueError("No reliable runtime estimate exists; extend this trial with an explicit time budget")
        if decision["charter_version"] != campaign["version"]:
            raise ValueError("This request used an older charter; ask for a current one")
        child = _child(workspace, command, campaign, "trial.control",
            {"trial_id": trial["id"], "action": "extend", "expected_control_revision": trial["control_revision"],
             "max_steps": trial["max_steps"] + decision["incremental_solver_calls"],
             # An estimate gets a margin; a stated request is granted exactly as shown.
             "wall_seconds": trial["wall_seconds"] + (seconds if decision.get("requested_by") else max(5, seconds))})
        effect = {"child_command": child.model_dump(mode="json")}
    elif values.choice == "0" and (decision.get("approval_request") or {}).get("kind") == "compute":
        # The go-ahead itself: the requester starts the work, charged to this consent; Balsamic starts the runs it lists (plan_runs).
        from .compute_consent import grant
        from .proposals import approve
        consent = grant(workspace, decision, decision["approval_request"])
        approve(workspace, consent)
    elif values.choice == "0" and (decision.get("approval_request") or {}).get("kind") == "mandate_model":
        # A raise of one request's model-spend envelope (R5): its held turns go on at the next pass.
        from .mandates import raise_model
        request = decision["approval_request"]
        raise_model(workspace, request["mandate_id"], request["model_usd"], decision["id"])
    elif values.choice == "0" and decision.get("approval_request"):
        request = decision["approval_request"]
        reason = decision["rationale"] + (" Researcher: " + values.comment if values.comment else "")
        operation, payload = {
            "campaign_limits": lambda: ("campaign.update", {**request["limits"], "rationale": reason[:5000]}),
            "waiver": lambda: ("validation.waive", {"requirement_id": request["requirement_id"], "rationale": reason, "evidence_ids": request["evidence_ids"]}),
            "worker_ceiling": lambda: ("workers.set", {"workers": request["workers"], "gpu_workers": request.get("gpu_workers"), "rationale": reason[:5000]}),
        }[request["kind"]]()
        effect = {"child_command": _child(workspace, command, campaign, operation, payload).model_dump(mode="json")}
    elif values.choice == "0" and decision.get("journal_compaction"):
        child = _child(workspace, command, campaign, "journal.compact", {"trial_ids": decision["journal_compaction"]["trial_ids"]})
        effect = {"child_command": child.model_dump(mode="json")}
    memory = workspace.memory.state(command.campaign_id)
    memory["guidance_revision"] += 1
    workspace.store.put("manager_state", memory)
    if effect is not None:
        effect["approval"] = {"command_id": command.id, "guidance_revision": memory["guidance_revision"],
                              "authority_hash": workspace.commands.authority_hash(campaign)}
        effect["child_command"]["expected_guidance_revision"] = memory["guidance_revision"]
    decision.pop("delivery_error", None)
    decision.update(resolution_revision=values.expected_resolution_revision + 1, resolution_command_id=command.id)
    if effect is None:
        decision = finish_decision(workspace, decision, values.choice, values.comment, {"consent_id": consent["id"]} if consent else None)
    else:
        decision.update(status="executing", choice=values.choice, comment=values.comment)
        workspace.store.put("decision", decision, "decision.executing")
        effect.update(id="decision_" + command.id, campaign_id=command.campaign_id, kind="decision_resolution",
                      decision_id=decision["id"], resolution_command_id=command.id, status="pending", created_at=now())
        workspace.store.put("outbox", effect, "effect.queued")
    return {"decision_id": decision["id"], "decision": decision, **({"effect_id": effect["id"]} if effect is not None else {})}


def deliver_resolution(workspace, effect):
    with workspace.lock:
        decision = workspace.store.get(effect["decision_id"], "decision")
        if decision.get("resolution_command_id") != effect["resolution_command_id"] or decision["status"] == "resolved":
            return
    # The child command has its own stable receipt and original authority. A lost
    # acknowledgement reconciles that receipt before checking newer intent.
    outcome = workspace.commands.execute(effect["child_command"], actor="researcher")["outcome"]
    with workspace.lock, workspace.store.transaction():
        decision = workspace.store.get(effect["decision_id"], "decision")
        if decision["status"] != "resolved":
            finish_decision(workspace, decision, decision["choice"], decision["comment"], outcome)


def failed_resolution(workspace, effect, error):
    """A definitively rejected child needs a fresh researcher choice, not a retry loop."""
    with workspace.lock, workspace.store.transaction():
        decision = workspace.store.get(effect["decision_id"], "decision")
        if decision.get("resolution_command_id") == effect["resolution_command_id"] and decision["status"] == "executing":
            decision.update(status="pending", delivery_error=str(error))
            workspace.store.put("decision", decision, "decision.action_failed")
        effect.update(status="failed", error=str(error), finished_at=now())
        workspace.store.put("outbox", effect, "effect.failed")
