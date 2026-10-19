"""Which stage a campaign is in, read from its records: formulate, generate, optimize, report. A researcher's pin overrides.

"Stopped" work never reads as failure here; the stage says what the lab is doing, not how well.
"""

STAGES = ("formulate", "generate", "optimize", "report")
RACE_ACTIVE = {"preflight", "running", "paused"}


def campaign_stage(workspace, campaign):
    store, campaign_id = workspace.store, campaign["id"]
    if campaign.get("stage_pin") in STAGES:
        return {"stage": campaign["stage_pin"], "pinned": True, "basis": campaign.get("stage_pin_reason") or "pinned by the researcher"}
    if any(job.get("status") in {"queued", "running", "awaiting_focus"} for job in store.list("report_writer_job", campaign_id)):
        return {"stage": "report", "pinned": False, "basis": "a report is being written"}
    if any(race.get("status") in RACE_ACTIVE for race in store.list("adaptive_race", campaign_id)):
        return {"stage": "optimize", "pinned": False, "basis": "a race is running"}
    if any(protocol.get("status") in {"scheduled", "running"} for protocol in store.list("confirmation_protocol", campaign_id)):
        return {"stage": "optimize", "pinned": False, "basis": "confirmation runs are scheduled"}
    tasks = store.list("task", campaign_id)
    note_adopted = bool(campaign.get("problem_note_id")) and (store.get(campaign["problem_note_id"], "problem_note").get("status") in {"adopted", "confirmed"}
                                                             if _exists(store, campaign.get("problem_note_id")) else False)
    if not tasks and not note_adopted and not store.list("hypothesis", campaign_id):
        return {"stage": "formulate", "pinned": False, "basis": "no problem definition has been adopted yet"}
    return {"stage": "generate", "pinned": False, "basis": "strategies are being proposed and screened"}


def _exists(store, identity):
    if not identity:
        return False
    try:
        store.get(identity)
        return True
    except KeyError:
        return False
