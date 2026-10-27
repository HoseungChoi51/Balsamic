# 0007 Compute is the researcher's: two thresholds

| Date | Status | Commit |
|---|---|---|
| 2026-10-26 and 27 | Accepted | `966b6b1`, `f6776da` |

## Context

After the researcher asked the lead only to check whether implementations were available, screening runs of about ten
minutes each started without their notice. One fixed minute then decided what an agent could start alone.

## Decision

- Nothing an agent starts that computes beyond the researcher's go-ahead threshold runs without their go-ahead. The agent
  asks with `approval.request` kind `compute` (what runs and why, how long until results, the worker time, any coding
  workspace); "Start now" records a consent that what the agent starts is charged against. The command bus refuses an
  agent's run, continuation, allocation, profile, validation, implementation job or race that no consent covers.
- Each campaign has two thresholds the researcher sets on Monitor → Resources: work up to the notice threshold (default
  1 min) starts freely; work up to the go-ahead threshold (default 5 min) starts and leaves a notice in the inbox until
  acknowledged, unless an approved plan covers it; anything longer, and any coding workspace, waits for the go-ahead.
- The researcher's own commands are never checked; autopilot runs within the cap set when it was switched on.

## Consequences

- INV-01 and INV-02 in [invariants.md](../invariants.md).
- Agents can ask for other thresholds only through an approval (`campaign_limits`).
- Roadmap decision 3 ([0008](0008-charter-to-results.md)) makes one go-ahead cover a whole request.
