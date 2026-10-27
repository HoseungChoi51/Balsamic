"""The away digest: what happened while the researcher was away, written when an autopilot round completes after 30 minutes of absence."""
from datetime import datetime, timedelta, timezone

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

AWAY_MINUTES = 30


def last_seen(workspace, campaign_id):
    """The researcher's last sign of life: a UI event or a message of theirs."""
    stamps = [row.get("recorded_at") or row.get("at") for row in workspace.store.list("ui_event", campaign_id)]
    stamps += [m["created_at"] for m in workspace.store.list("message", campaign_id) if m.get("role") == "user" and m.get("origin") == "researcher"]
    return max((s for s in stamps if s), default=None)


def away_for(workspace, campaign_id, clock=None):
    seen = last_seen(workspace, campaign_id)
    if not seen:
        return None
    try:
        then = datetime.fromisoformat(seen.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (clock or datetime.now(timezone.utc)) - then


def compute(workspace, campaign_id, since_event):
    """What changed after an event id, as a digest; pure read."""
    store = workspace.store
    events = store.events(campaign_id, after=since_event, limit=5000)
    to_event = events[-1]["id"] if events else since_event
    commands = [c for c in store.list("work_command", campaign_id) if any(e["kind"] == "command.completed" and e["data"].get("record_id") == c["id"] for e in events)]
    stopped, promoted, started = [], [], []
    inner_ids = {item["command_id"] for c in commands if c["request"]["operation"] == "intervention.batch" for item in (c.get("outcome") or {}).get("items") or []}
    for c in commands:
        operation = c["request"]["operation"]
        if c["id"] in inner_ids:
            continue   # counted with its batch
        payload = c["request"].get("payload") or {}
        if operation == "hypothesis.status" and payload.get("status") == "archived":
            stopped.append({"hypothesis_id": payload.get("hypothesis_id"), "reason": payload.get("stop_reason"), **_stop(c), "by": (c.get("origin") or {}).get("actor") or c.get("actor")})
        if operation == "hypothesis.nominate" or (operation == "hypothesis.status" and payload.get("status") == "finalist"):
            promoted.append({"hypothesis_id": payload.get("hypothesis_id"), "by": (c.get("origin") or {}).get("actor") or c.get("actor")})
        if operation == "intervention.batch":
            for item in (c.get("outcome") or {}).get("items") or []:
                inner = store.get(item["command_id"], "work_command") if _exists(store, item["command_id"]) else None
                if inner and inner["request"]["operation"] == "hypothesis.status" and inner["request"]["payload"].get("status") == "archived":
                    stopped.append({"hypothesis_id": inner["request"]["payload"].get("hypothesis_id"), "reason": inner["request"]["payload"].get("stop_reason"), **_stop(inner), "by": "autopilot" if c.get("actor") == "autopilot" else c.get("actor")})
                if inner and inner["request"]["operation"] == "hypothesis.nominate":
                    promoted.append({"hypothesis_id": inner["request"]["payload"].get("hypothesis_id"), "by": c.get("actor")})
        if operation in {"trial.create", "draft.launch", "trial.continue", "hypothesis.allocate"}:
            started.append({"operation": operation, "trial_id": (c.get("outcome") or {}).get("trial_id"), "by": (c.get("origin") or {}).get("actor") or c.get("actor")})
    finished = [e["data"].get("record_id") for e in events if e["kind"] == "trial.evidence_cataloged"]
    decisions = [d for d in store.list("decision", campaign_id) if d.get("status") == "pending"]
    questions = [q for q in store.list("agent_question", campaign_id) if q.get("status") == "pending"]
    settings = (store.get(campaign_id, "campaign").get("autopilot") or {})
    rounds = sum(1 for e in events if e["kind"] == "campaign.autopilot_round_completed")
    return {"campaign_id": campaign_id, "from_event": since_event, "to_event": to_event, "rounds_completed": rounds, "autopilot_rounds_total": settings.get("rounds_completed", 0),
            "stopped": stopped, "promoted": promoted, "started": started, "finished_trial_ids": [t for t in finished if t],
            "decisions_waiting": [{"id": d["id"], "title": d.get("title")} for d in decisions], "questions_waiting": [{"id": q["id"], "question": q.get("question")} for q in questions],
            "commands": [{"id": c["id"], "operation": c["request"]["operation"], "by": (c.get("origin") or {}).get("actor") or c.get("actor")} for c in commands][-50:]}


def maybe_write_digest(workspace, campaign_id, *, clock=None):
    away = away_for(workspace, campaign_id, clock)
    if away is None or away < timedelta(minutes=AWAY_MINUTES):
        return None
    existing = [d for d in workspace.store.list("away_digest", campaign_id) if not d.get("seen_at")]
    since = existing[-1]["from_event"] if existing else _event_at(workspace, campaign_id, last_seen(workspace, campaign_id))
    digest = compute(workspace, campaign_id, since)
    if not digest["commands"] and not digest["finished_trial_ids"] and not digest["rounds_completed"]:
        return None
    record = {"id": "digest_" + content_hash([campaign_id, since, digest["to_event"]])[:20], **digest, "away_minutes": int(away.total_seconds() // 60), "written_at": now()}
    if existing and existing[-1]["to_event"] == record["to_event"]:
        return existing[-1]
    for old in existing:   # one open digest at a time; a newer one replaces it
        old["superseded_by"] = record["id"]; old["seen_at"] = now()
        workspace.store.put("away_digest", old)
    workspace.store.put("away_digest", record, "autopilot.digest_written")
    return record


def open_digest(workspace, campaign_id):
    rows = [d for d in workspace.store.list("away_digest", campaign_id) if not d.get("seen_at")]
    return rows[-1] if rows else None


def mark_seen(workspace, digest_id):
    with workspace.lock:
        record = workspace.store.get(digest_id, "away_digest")
        if not record.get("seen_at"):
            record["seen_at"] = now()
            workspace.store.put("away_digest", record, "autopilot.digest_seen")
        return record


def _event_at(workspace, campaign_id, stamp):
    if not stamp:
        return 0
    with workspace.store.connection() as db:
        row = db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE campaign_id=? AND created_at<=?", (campaign_id, stamp)).fetchone()
    return row[0]


def _exists(store, identity):
    try:
        store.get(identity); return True
    except KeyError:
        return False


def _stop(receipt):
    """The stop outcome a status command recorded, in words; a stop from before typed outcomes reads as unspecified."""
    from optimization_framework.campaigns.hypotheses import stop_of
    hypothesis = (receipt.get("outcome") or {}).get("hypothesis") or {"status": "archived"}
    stop = stop_of({**hypothesis, "status": "archived"})
    return {"outcome": stop["outcome"], "outcome_words": stop["words"]}
