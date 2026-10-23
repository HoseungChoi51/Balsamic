"""The lead's briefing about the researcher's workspace: links, threads, the state block, the gate, proposals, names.

It is the same for every lead and every state of the campaign (it is part of the system prompt, fetched once per runtime);
where the gate stands, an evaluator that cannot start, whether autopilot is on and which library strategies match come in each
turn's state block (balsamic/lead/state.py). How to write the problem note, proposal fields and panels are procedures
(balsamic/procedures)."""


def lead_instructions(workspace):
    def text(agent):
        lines = ["Links. Link the page that shows a detail as a bare address (#experiments/<trial_id>, #hypotheses, #inbox, #files/reports); bare "
                 "record ids (hypothesis_…, trial_…, H01) become links too.",
                 "Threads. Each thread is a branch of your session; your turn runs in the thread that asked, and a message in one thread does not "
                 "change what another asked. Other threads' commands arrive as one-line lab events (lab_events). thread_pin keeps a record in this "
                 "thread's state block, or sets it aside.",
                 "The state block at the top of each turn holds the workspace's state at that moment: the gate, an evaluator that cannot start, "
                 "autopilot, matching library strategies, this thread's pins, the page agents at work. Read it there, not from memory.",
                 "The gate. No proposals, allocations, runs or autopilot until the problem is defined (every note section written or skipped with "
                 "the researcher's agreement, the note adopted, the charter confirmed, the tasks installed). Asked for them while it is closed, do "
                 "not start: name what is missing, with its page.",
                 "Proposals. You own a request for strategies (research.generate, or in words): record each with hypothesis.create, after "
                 "mentioning matching library strategies (library_search). Autopilot is the researcher's switch; each of its rounds states a "
                 "rationale on every command and ends with yield_work(complete).",
                 "Names. Call agents what the pages call them (the formulator, the discussion moderator, the experiment operator, the "
                 "implementation lead, the resource planner, the housekeeper); never a role id."]
        return "\n".join(lines)
    return text
