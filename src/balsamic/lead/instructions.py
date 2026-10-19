"""The lead's briefing about the researcher's workspace: pages and links, threads, the problem note, autopilot."""
from optimization_framework.agents.pages import pages


def lead_instructions(workspace):
    def text(agent):
        campaign = workspace.store.get(agent["campaign_id"], "campaign")
        lines = ["Workspace. The researcher reads your replies in a chat beside the pages. Keep replies short and link the page that shows the detail, "
                 "as a bare address (#experiments/<trial_id>, #hypotheses, #inbox, #evolution/frontier, #files/reports); the chat turns it into a link in the "
                 "researcher's current conversation. Bare record ids (hypothesis_…, trial_…, H01) become links too. The pages:"]
        lines += [f"- {address}: {title}" + (f" — {description}" if description else "") for address, title, description in pages() if description]
        lines.append("Proposals. The researcher asks you for strategies (research.generate, or in words); you own that request and record each "
                     "strategy with hypothesis.create. The discussion moderator reviews recorded proposals in rounds with its specialists and can run a "
                     "generation round when you ask it; it does not start rounds by itself.")
        lines.append("Threads. The researcher's conversation can branch: each thread is a branch of your session, and your turn runs in the thread that "
                     "asked. A message in one thread does not change what you were asked in another. Lab events (a command another thread ran) arrive as "
                     "one-line notes; thread_pin keeps a record in this thread's context, lab_events lists what happened elsewhere.")
        if campaign.get("formulating") or campaign.get("problem_note_id"):
            lines.append("Formulation. This campaign is being formulated. Write the problem note with problem_note_draft (objective, knobs, observables, "
                         "noise, constraints, confounders, open questions; LaTeX allowed), revise it as the researcher answers, and answer questions "
                         "about it as proposed edits (problem_note_propose), never a silent rewrite. The researcher adopts the note (Adopt on #note); "
                         "the formulator then writes the charter and the researcher confirms it. Start no experiments before that.")
        try:
            from balsamic.library.service import search
            matches = [row for row in search(workspace, campaign_id=campaign["id"], limit=5)["entries"] if row["match"]["score"] >= 3]
        except (KeyError, ValueError):
            matches = []
        if matches:
            lines.append("Library. Strategies that won earlier campaigns of this problem exist: " + "; ".join(
                f"{row['entry']['strategy'].get('title')} ({row['entry']['id']}, best {row['entry']['evidence'].get('best_score')}, {', '.join(row['match']['reasons'])})" for row in matches)
                + ". Mention them in your first reply and read them with library_search before proposing from scratch; apply one with library.apply when the researcher agrees.")
        if (campaign.get("autopilot") or {}).get("enabled"):
            lines.append("Autopilot is on with a compute cap: in an autopilot round you review the frontier, stop, promote, allocate or generate with a "
                         "stated rationale on every command, and end the round with yield_work(complete). Researcher messages still come first.")
        return "\n".join(lines)
    return text
