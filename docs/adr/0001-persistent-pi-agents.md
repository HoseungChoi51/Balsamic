# 0001 Persistent Pi agents replace the campaign manager

| Date | Status | Commit |
|---|---|---|
| 2026-09-29 | Accepted | `9a0cf2d` |

## Context

A Python campaign manager drove each campaign through fixed stages and called a model for each step. Every new kind of
work needed a new stage in code, the model saw only what a step handed it, and nothing carried a line of reasoning from
one step to the next.

## Decision

Each campaign gets a team of persistent Pi agents: a lead and specialists, each a Pi session that keeps its context and
acts through scoped tools on the campaign's records (the gateway). The manager is removed. A durable recovery path
restarts the agents with their sessions after the service restarts, and implementation work goes through the
implementation service.

## Consequences

- What the agents may do is set by their tools and the command bus, not by the stage they are in; the guarantees moved
  into those (see [invariants.md](../invariants.md)).
- A campaign's progress depends on the agents' judgement, so evals of that judgement became necessary
  (readiness Part L, roadmap Phase 2).
- The agent harness (`agent-harness/`) and its contract are a part of the system of their own
  ([pi-agent-harness.md](../pi-agent-harness.md)).
