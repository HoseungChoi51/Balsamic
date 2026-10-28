# 0010 The moderator's and the operator's sessions: kept or folded into the lead, by a comparison

| Date | Status | Where |
|---|---|---|
| 2026-10-28 | Proposed: both settings exist, `standing` stays the default; the comparison below, which Hoseung runs, decides each page agent | Roadmap part T4 ([readiness](../readiness/T4.md)) |

## Context

Since the harness plan's Phase 5 four page agents keep Pi sessions for the whole campaign, and the lead cannot run their
pages' operations: it asks with `page_agent_message`, and the reply comes back as a notice. Each hand-off is another turn
and another set of prose boundaries. In the session behind `docs/suggestions.md` R2 the lead made 81 `page_agent_message`
calls, 27 of its turns were exactly inspect, `page_agent_message`, `yield_work`, and the operator's median request was 404k
tokens. S11 (experiments go through the operator) passes, so the routing works; whether each hop is worth its cost was
never measured. Folding moves context into the lead, whose context is already the heaviest (suggestions R3).

## Decision

1. A per-campaign switch, `page_agents: standing | lead`, for the discussion moderator and the experiment operator. It is set
   when the team starts (`agent.activate`'s `page_agents`, else `GRATING_PAGE_AGENTS`, else `standing`) and changed in the
   dev profile with `agent.configure` while no request is open. No default changes.
2. Under `lead`, the lead gets their operations and tools, reads their page instructions as procedures (`review-rounds`,
   `running-experiments`) when the work starts, answers the researcher on their pages, and records the synthesis of a round
   it ran with reviewers before it ends the request, as the moderator does.
3. The implementation lead (its work changes with Phase 4) and the resource planner (it starts nothing) are out of scope and
   keep their sessions in both settings.
4. The comparison decides, per page agent, whether it keeps its session or is folded. On Centinels, at T4's commit, the whole
   suite and the J2 presets in both arms (`--page-agents standing`, `--page-agents lead`), 3 repeats where the suite allows.
   `summary.md`'s "Page agents" table gives per scenario the lead's hand-offs, the moderator's and the operator's turns, the
   lead's turns, the lead's largest context, J3's researcher actions and seconds to the report, the seconds and the cost.
   A page agent is folded only if the `lead` arm passes as many scenarios, with fewer turns or a lower cost, and the lead's
   largest context stays within its model's window with room to spare (the review scenarios S12, S14 and S16 for the
   moderator; S8, S11 and the J2 presets for the operator).

## Consequences

- When the comparison has run, its results go in the readiness file and this record becomes Accepted with its result per
  page agent.
- A fold (removing the session, the page's routing, open requests, the switch itself) is a new part of Phase 7, added to the
  roadmap when Hoseung accepts this record. Until then both settings are kept and tested.
- Under `lead`, J3's partnership rows count a request made on Hypotheses or Experiments (it is the lead's); under
  `standing` such a request is the page agent's own and is not a row. Compare the rows of requests made in the chat.
