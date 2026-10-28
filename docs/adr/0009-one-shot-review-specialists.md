# 0009 Review specialists as one-shot calls; the specialists' merge (D2) left to the comparison

| Date | Status | Where |
|---|---|---|
| 2026-10-28 | Proposed: the default until the live comparison below, which Hoseung runs; D2 stays open until then | Roadmap part T3 ([readiness](../readiness/T3.md)), decision 19 |

## Context

T1 made the proposal reviewer one bounded call with an input the backend assembles, so a reviewer cannot read the other
verdicts first and every call records what it saw. Decision 19 puts the review specialists next and keeps sessions for
the roles that search or run analyses. Of the seven specialists, two only read: `methodology_specialist` and
`skeptical_domain_analyst`. The harness plan's D2 (merge the specialists into one analyst,
[0006](0006-harness-plan-decisions.md)) was left to T3's comparison.

## Decision

1. Both read-only specialists answer in one call by default. Their input is the reviewer's plus the machine's resources
   and budgets, with each cited trial read as its status, result and metrics, and no reviewer's verdict on any proposal.
   Their result is their role's schema, unchanged, saved as `submit_output` saves it.
2. `GRATING_ONE_SHOT_ROLES` (comma-separated; empty for none) picks the roles that answer in one call, without a code
   change. `analyst` in it makes one call, with the two briefs and schemas merged, answer for either name; the old names
   stay the roles' names (the harness plan's compatibility rule).
3. The literature specialist, the cross-domain explorer, the empirical assessor and the results analyst keep their
   sessions.
4. The comparison decides the default per role, and D2. No model is called in the cloud threads, so it has not run yet.
   On Centinels, S12, S14 and S16 with `--repeats 3` in three arms at T3's commit: `--one-shot-roles proposal_reviewer`
   (sessions), no flag (one-shot), and `--one-shot-roles proposal_reviewer,analyst` (D2). `summary.md`'s "Review roles"
   table gives the valid results, cost, seconds and input size per role. A role whose one-shot arm passes fewer scenarios
   or has fewer valid results than its session goes back to a session in the default; D2 is taken only if the analyst arm
   does as well as the one-shot arm at a lower cost.

## Consequences

- When the comparison has run, its results go in the readiness file, this record becomes Accepted (or a new record
  replaces it if the default changes), and D2 is marked decided in 0006's successor.
- A one-shot specialist cannot read on: what its input lacks, it can only say is missing.
