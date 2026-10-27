"""Decision freshness is a projection, never a renewal of execution authority."""
from copy import deepcopy


def public_decision(workspace, record):
    from .decision_presentation import present_decision
    campaign = workspace.store.get(record["campaign_id"], "campaign")
    current_guidance = workspace.memory.state(record["campaign_id"])["guidance_revision"]
    presentation = present_decision(record, None)
    source_guidance = record.get("guidance_revision")
    source_charter = record.get("charter_version")
    executable = ["0"] if record.get("trial_id") and record.get("incremental_solver_calls") is not None else []
    stale = bool(executable) and (source_charter != campaign["version"] or
        source_guidance is not None and source_guidance != current_guidance)
    pending = record.get("status") == "pending"
    freshness = {"state": "stale" if stale else "ready", "stale": stale,
        "can_accept": pending and not stale, "blocked_choice_ids": executable if stale else [],
        "can_refresh": pending and stale, "reason": "",
        "current_charter_version": campaign["version"], "proposal_charter_version": source_charter,
        "current_guidance_revision": current_guidance, "proposal_guidance_revision": source_guidance}
    if stale:
        freshness["reason"] = ("This request was made under an older charter or earlier researcher guidance. "
            "Ask the lead for a current one before approving it; defer or decline remains available.")
    if presentation["needs_clarification"]:
        blocked = [option["id"] for option in presentation["options"] if option["id"] not in {"defer", "reject"}]
        clarification = ("This is an internal question for the lead agent. Send it to the lead for review."
            if presentation["audience"] == "manager" else
            "The saved request does not define a clear proposal and distinct choices. Ask the lead to clarify them before deciding.")
        freshness.update(state="blocked", can_accept=False, can_refresh=pending,
            blocked_choice_ids=list(dict.fromkeys([*freshness["blocked_choice_ids"], *blocked])),
            reason=(freshness["reason"] + " " if freshness["reason"] else "") + clarification)
    return {**deepcopy(record), "freshness": freshness, "presentation": presentation}
