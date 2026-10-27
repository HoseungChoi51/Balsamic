# 0006 The harness plan's decisions as implemented

| Date | Status | Where |
|---|---|---|
| 2026-10-22 to 23 | Accepted; D2 to be revisited by roadmap part T3; D5 open | Readiness Parts L–S in [lead-agent-readiness.md](../lead-agent-readiness.md) |

## Context

The agent harness update plan ([history/harness-update-plan.md](../history/harness-update-plan.md)) listed nine
decisions, D1–D9, for Hoseung to confirm. Phases 1–7 were built and checked live on 22 and 23 October, each at the
plan's recommended default, but the table still said "Open".

## Decision

| ID | Decided | Part |
|---|---|---|
| D1 | The page agents' operations leave the lead's enum, `fixed_mask.run` among them; the lead keeps its `implementation_workspace_*` tools | P |
| D2 | The specialist roles are kept, with briefs and output schemas. Merging them is decided by T3's eval comparison (roadmap decision 19) | R |
| D3 | Procedures are read with the gateway's `procedure_read`, files in Agent Skills format (option A; B not tried) | Q |
| D4 | The state block comes from `POST /api/internal/pi/turn_state`, called by the harness right before `prompt()` | M |
| D5 | Open: who an inbound MCP client acts as goes with Phase 8, which the roadmap does not plan | — |
| D6 | Live evals on the dev profile's default model, `llm_budget_usd` 0.30 per scenario, a $5 suite cap | L, S |
| D7 | `guidance_revision` is accepted and ignored, with a TODO to remove it in the next release | N |
| D8 | Only the Balsamic gateway extension; the per-role allowlist is empty until an extension passes the evals | O |
| D9 | Extension dialogs are questions above the chat (on the agent's page for page agents); the extension's timeout or 15 minutes; cancelled at once under autopilot | O |

## Consequences

- The plan moved to `docs/history/` once its decisions were marked (roadmap decision 21). Its Phase 9 (numeric claim
  checks) is roadmap part K2.
