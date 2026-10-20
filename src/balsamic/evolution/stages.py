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


def _charter_of(store, note):
    """The charter of the note's latest adoption: the import's charter once the formulator wrote it, else the note's own link."""
    if _exists(store, note.get("import_id")):
        record = store.get(note["import_id"])
        if record.get("charter_id"):
            return store.get(record["charter_id"]) if _exists(store, record["charter_id"]) else None
    return store.get(note["charter_id"]) if _exists(store, note.get("charter_id")) else None


def _empty(section):
    section = section or {}
    return not ((section.get("text") or "").strip() or section.get("items") or section.get("latex"))


def definition(workspace, campaign):
    """The problem-definition gate: what still stands between this campaign and work on it (proposals, allocations, autopilot).

    A campaign with a problem note must have every section of the note written, the note adopted at its current revision,
    the charter confirmed and the tasks installed. A campaign that was never formulated (tasks from a problem adapter or
    a confirmed charter, no note) is defined by its charter. Returns {ready, step, missing} where step is the next_step
    dict (None when ready) and missing lists the titles of the unwritten sections."""
    from balsamic.notes.service import SECTIONS, TITLES, revision_of
    store = workspace.store
    tasks = store.list("task", campaign["id"])
    waiting = len(store.list("hypothesis", campaign["id"]))
    base = {"blocking": waiting > 0, "proposals": waiting, "missing": []}
    note = store.get(campaign["problem_note_id"], "problem_note") if _exists(store, campaign.get("problem_note_id")) else None
    if note is None and _exists(store, "note_" + campaign["id"]):
        note = store.get("note_" + campaign["id"], "problem_note")
    if note is None:
        if tasks:
            return {"ready": True, "step": None, "missing": []}
        return {"ready": False, "missing": [], "step": {**base, "kind": "note", "title": "Draft the problem note", "page": "#note",
                "text": "Ask the lead to write the problem note (/note). Adopting it drafts the charter that experiments run under."}}
    try:
        revision = revision_of(workspace, note["id"], note["current_revision"]) if note.get("current_revision") else None
    except KeyError:
        revision = None
    sections = (revision or {}).get("sections") or {}
    missing = [TITLES[name] for name in SECTIONS if _empty(sections.get(name))]
    base["missing"] = missing
    if missing:
        return {"ready": False, "missing": missing, "step": {**base, "kind": "sections", "title": "Complete the problem note", "page": "#note",
                "text": "Not written yet: " + ", ".join(missing) + ". Every section must be written before proposals, allocations or autopilot; "
                        "ask the lead to fill them (open questions reads \"none remaining\" when the definition is settled)."}}
    if note.get("status") == "drafting":
        again = note.get("adopted_revision") is not None
        return {"ready": False, "missing": [], "step": {**base, "kind": "adopt", "title": "Adopt the problem note" + (" again" if again else ""), "page": "#note",
                "text": ("The note changed since it was adopted; adopt the current revision so the charter follows it." if again else
                         "Read the note on the Problem note page and adopt it; the formulator then drafts the charter for you to confirm.")}}
    charter = _charter_of(store, note)
    if charter is None or charter.get("status") != "confirmed":
        return {"ready": False, "missing": [], "step": {**base, "kind": "confirm", "title": "Confirm the charter", "page": "#note/charter",
                "text": "No experiment can start until you confirm the charter. Review it on the Charter page and confirm it, or send it back with what to change."}}
    if not tasks:
        return {"ready": False, "missing": [], "step": {**base, "kind": "tasks", "title": "Finish the charter hand-over", "page": "#note/charter",
                "text": "The charter is confirmed but its tasks are not installed yet; open the Charter page to finish."}}
    return {"ready": True, "step": None, "missing": []}


def next_step(workspace, campaign):
    """The formulation step the researcher must take before work can start, or None once the definition gate is passed.
    Shown on every page until then, louder once proposals are waiting on it."""
    return definition(workspace, campaign)["step"]
