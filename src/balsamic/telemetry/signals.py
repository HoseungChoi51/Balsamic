"""The plan's gate table, computed from ui_event records: what the next milestone should keep, drop or add."""
from collections import Counter
from statistics import median


def _sessions(rows):
    return {row.get("session") or row["at"][:13] for row in rows} or {None}


def gate(workspace, campaign_id, milestone):
    rows = workspace.store.list("ui_event", campaign_id)
    kinds = Counter(row["kind"] for row in rows)
    sessions = len(_sessions(rows))
    per_session = lambda kind: round(kinds[kind] / sessions, 2)
    turns = [row for row in rows if row["kind"] == "page.open" and row.get("thread_id")]
    outside_main = sum(1 for row in turns if not str(row["thread_id"]).startswith("thread_main_"))
    interventions = [row for row in rows if row["kind"] == "intervention.send"]
    by_kind = Counter(str(row["data"].get("kind")) for row in interventions)
    overrides = sum(1 for row in interventions if row["data"].get("override"))
    gaps = [float(row["data"]["seconds_since_round_end"]) for row in rows
            if row["kind"] == "round.next_action" and isinstance(row["data"].get("seconds_since_round_end"), (int, float))]
    asks = [row for row in rows if row["kind"] == "note.ask"]
    signals = {
        "events": len(rows), "sessions": sessions,
        "branching": {"forks_per_session": per_session("thread.fork"), "switches_per_session": per_session("thread.switch"),
                      "merges_per_session": per_session("thread.merge"), "parks_per_session": per_session("thread.park"),
                      "share_of_page_opens_outside_main": round(outside_main / len(turns), 3) if turns else None,
                      "question": "Keep branching?"},
        "context": {"drawer_opens": kinds["context.open"], "pins": kinds["context.pin"], "exclusions": kinds["context.exclude"],
                    "forgot_reports": kinds["context.forgot_report"], "question": "Context before features?"},
        "interventions": {"total": len(interventions), "by_kind": dict(by_kind), "overrides": overrides,
                          "override_rate": round(overrides / len(interventions), 3) if interventions else None, "question": "Which controls stay?"},
        "rounds": {"median_seconds_to_next_action": median(gaps) if gaps else None, "samples": len(gaps), "question": "Is a canvas needed?"},
        "monitor": {"opens": kinds["monitor.open"], "alerts_acted_on": kinds["monitor.alert_acted"], "question": "Which rows?"},
        "note": {"asks_by_tier": dict(Counter(str(row["data"].get("tier")) for row in asks)),
                 "escalations": sum(1 for row in asks if row["data"].get("escalated")), "question": "Router tuning"},
        "chips": {"opened": kinds["chip.open"], "traces_opened": kinds["trace.open"], "visuals_opened": kinds["visual.open"], "digests_seen": kinds["digest.seen"]},
    }
    focus = {"M1": ["branching", "context", "note"], "M2": ["interventions", "rounds"], "M3": ["monitor", "interventions"], "M4": ["chips", "branching"]}[milestone]
    return {"milestone": milestone, "campaign_id": campaign_id, "focus": focus, "signals": signals}
