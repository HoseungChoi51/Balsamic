"""The lead's part of the state block (optimization_framework/agents/turn_state.py): where the problem-definition gate stands,
an evaluator that cannot start, autopilot, the library strategies that match, what this thread pins or sets aside, and the page
agents at work. Read from the records at the start of each turn; the lead's instructions only say that it is there."""
from optimization_framework.agents.models import PAGE_AGENTS
from optimization_framework.agents.turn_state import one_line

PINS = 10
LIBRARY = 3
NAMES = {"discussion_moderator": "the discussion moderator", "experiment_operator": "the experiment operator",
         "implementation_lead": "the implementation lead", "resource_planner": "the resource planner"}


def gate_line(workspace, campaign):
    gate = workspace.definition_gate(campaign) if getattr(workspace, "definition_gate", None) else None
    if gate is None:
        return []
    if gate["ready"]:
        return ["Gate: open; the problem is defined."]
    step = gate["step"]
    return [f"Gate: closed. Next: {step['title'].lower()} ({step['page']})." + (" Not written yet: " + ", ".join(step["missing"]) + "." if step.get("missing") else "")
            + (" Skipped with the researcher's agreement: " + ", ".join(step["skipped"]) + "." if step.get("skipped") else "")
            + (" Your skip proposal waits for the researcher: " + ", ".join(step["proposed_skips"]) + "." if step.get("proposed_skips") else "")]


def evaluator_line(workspace, campaign):
    from balsamic.evolution.stages import evaluator
    blocked = evaluator(workspace, campaign, wait=True)
    if not blocked:
        return []
    return [f"Evaluator: cannot start in this lab, checked before any run. {blocked['text']} Runs, runtime profiles and screening on it "
            "are refused until it starts, so do not queue them. Tell the researcher this error as it stands and the fix it names, never "
            "another cause you guess at; campaign_inspect's tasks[].evaluator_readiness says when it starts."]


def autopilot_line(workspace, campaign):
    settings = campaign.get("autopilot") or {}
    if settings.get("enabled"):
        from balsamic.autopilot.rounds import remaining
        return [f"Autopilot: on, cap {settings.get('compute_cap_seconds'):.0f} worker seconds, {remaining(workspace, campaign['id'], settings):.0f} left; "
                f"{settings.get('rounds_completed', 0)} rounds completed."]
    requested = settings.get("requested")
    if requested:
        return [f"Autopilot: chosen at setup (cap {requested.get('compute_cap_seconds')} s) and waiting for the gate; only the researcher switches it on."]
    return ["Autopilot: off."]


def library_line(workspace, campaign):
    try:
        from balsamic.library.service import search
        matches = [row for row in search(workspace, campaign_id=campaign["id"], limit=5)["entries"] if row["match"]["score"] >= 3][:LIBRARY]
    except (KeyError, ValueError):
        matches = []
    if not matches:
        return []
    return ["Library (strategies that won earlier campaigns of this problem): " + "; ".join(
        f"{row['entry']['strategy'].get('title')} ({row['entry']['id']}, best {row['entry']['evidence'].get('best_score')}, {', '.join(row['match']['reasons'])})"
        for row in matches) + "."]


def pin_lines(workspace, run):
    thread_id = ((run or {}).get("origin") or {}).get("thread_id")
    try:
        thread = workspace.store.get(thread_id, "thread") if thread_id else None
    except KeyError:
        thread = None
    if thread is None:
        return []
    lines = []
    pinned = (thread.get("pinned_ids") or [])[-PINS:]
    if pinned:
        lines.append(f"Pinned in this thread ({len(pinned)}):")
        for record_id in pinned:
            try:
                entry = workspace.store.get_entry(record_id)
            except KeyError:
                lines.append(f"- {record_id}: missing")
                continue
            data = entry["data"]
            title = data.get("title") or data.get("name") or data.get("question") or ""
            revision = data.get("revision") if data.get("revision") is not None else data.get("version")
            lines.append(f"- {record_id} · {entry['kind']} · {one_line(title, 80)}" + (f" · {data['status']}" if data.get("status") else "")
                         + (f" · revision {revision}" if revision is not None else ""))
    excluded = thread.get("excluded_ids") or []
    if excluded:
        lines.append("Records the researcher set aside in this thread (leave them out unless asked): " + ", ".join(excluded[-PINS:]))
    return lines


def page_agent_line(workspace, campaign):
    at_work = [a for a in workspace.store.list("agent_session", campaign["id"]) if a["role"] in PAGE_AGENTS and a.get("request_open")]
    if not at_work:
        return []
    return ["Page agents with an open request: " + "; ".join(
        NAMES.get(a["role"], a["role"]) + " (asked by " + ("the researcher" if a.get("requested_by") == "researcher" else
                                                         "the platform" if a.get("requested_by") == "platform" else "you") + ")" for a in at_work) + "."]


def lead_state(workspace):
    def lines(agent, run):
        campaign = workspace.store.get(agent["campaign_id"], "campaign")
        return [*gate_line(workspace, campaign), *evaluator_line(workspace, campaign), *autopilot_line(workspace, campaign),
                *library_line(workspace, campaign), *pin_lines(workspace, run), *page_agent_line(workspace, campaign)]
    return lines
