# 0008 Charter to results: the evaluator from the library, no review gate on asked-for proposals, one go-ahead

| Date | Status | Commit |
|---|---|---|
| 2026-10-27 | Accepted; built by roadmap Phase 1 | `cc0e693` (the plan), `d707616` (the roadmap, decisions 1–3) |

## Context

After the charter, getting to ranked results took the researcher many steps: commissioning an evaluator, a concept
review before every run, and a separate approval for each workspace, evaluator and run
([history/charter-to-results-plan.md](../history/charter-to-results-plan.md)).

## Decision

1. **The evaluator comes from the library.** The coding agent writes the scoring function into the same library as the
   algorithms; Balsamic generates the boilerplate and tests from the charter, and once installed the task uses it like any
   installed problem. No separate evaluator commissioning on the default path.
2. **Concept review does not gate** runs of proposals the researcher asked for or approved. It happens on request and is
   shown when done; proposals agents create on their own still need it.
3. **One go-ahead per request** covers the coding workspace, the evaluator and the runs, with their minutes.
   Implementation compute counts against it. The go-ahead threshold ([0007](0007-compute-is-the-researchers.md)) still
   holds; work beyond what was approved asks again.

## Consequences

- After the charter the researcher confirms, asks and approves; everything else up to the comparison is Balsamic's
  (roadmap principle 2).
- Phase 1 of the [roadmap](../roadmap/README.md) builds it, in parts A–G.
