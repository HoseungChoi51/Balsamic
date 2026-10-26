"""Summary cards for threads: the branch map reads them; a parked branch is remembered by one.

With model calls allowed and a lead to bill, two sentences come from the lead's model through the harness's single
call; otherwise the card says what happened from the records alone and is labelled ``activity_only``.
"""

from optimization_framework.storage.sqlite import now

TURNS = 12


def activity_text(messages, *, agents=False):
    turns = [m for m in messages if m.get("origin") != "lab_event"]
    if agents:
        last = (turns[-1].get("content") or "").strip().split("\n")[0][:160] if turns else ""
        return f"{len(turns)} message{'s' if len(turns) != 1 else ''} between the agents." + (f" Last: {last}" if last else "")
    you = sum(1 for m in turns if m.get("role") == "user")
    lead = len(turns) - you
    last = next((m for m in reversed(turns) if m.get("role") == "assistant"), None)
    tail = (last.get("content") or "").strip().split("\n")[0][:160] if last else ""
    return f"{you} message{'s' if you != 1 else ''} from you, {lead} from the lead." + (f" Last from the lead: {tail}" if tail else "")


def summarize(workspace, thread, messages, *, reason, model=True):
    from balsamic.threads.service import activity_strip
    strip = activity_strip(workspace, thread, messages)
    card = {"text": activity_text(messages, agents=thread.get("kind") == "agents"), "strip": strip[-40:], "as_of_message_id": messages[-1]["id"] if messages else None,
            "written_by": "activity_only", "stale": False, "edited": False, "reason": reason, "written_at": now()}
    if not model or not messages:
        return card
    from balsamic import housekeeping
    transcript = "\n".join(f"{'Researcher' if m.get('role') == 'user' else 'Lead'}: {(m.get('content') or '')[:1200]}" for m in messages[-TURNS:] if m.get("origin") != "lab_event")
    reply = housekeeping.complete(workspace, "summary_" + thread["id"],
        "Summarize a research conversation branch in two plain sentences: what was asked, and what was concluded or left open. No praise, no advice.",
        transcript, max_tokens=200, label="branch summary", timeout=120)
    if reply:
        card.update(text=reply["text"][:600], written_by="model", model=reply["model"], cost_usd=reply.get("cost_usd"))
    return card
    config = workspace.pi.configuration(thread["campaign_id"]) or {}
    default = (config.get("models") or {}).get("default")
    if not default:
        return card
    transcript = "\n".join(f"{'Researcher' if m.get('role') == 'user' else 'Lead'}: {(m.get('content') or '')[:1200]}" for m in messages[-TURNS:] if m.get("origin") != "lab_event")
    try:
        reply = workspace.pi.client.complete("summary_" + thread["id"], {
            "provider": default.get("provider"), "model": default.get("model"), "effort": "low", "max_tokens": 200, "label": "branch summary",
            "system": "Summarize a research conversation branch in two plain sentences: what was asked, and what was concluded or left open. No praise, no advice.",
            "prompt": transcript}, timeout=120)
        text = (reply or {}).get("text", "").strip()
        if text:
            card.update(text=text[:600], written_by="model", model=default.get("model"), cost_usd=((reply or {}).get("usage") or {}).get("cost_usd"))
    except (ValueError, OSError):
        pass   # the activity card stands; it says so
    return card
