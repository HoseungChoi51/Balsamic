# 0002 The lead acts on the researcher's requests and starts nothing by itself

| Date | Status | Commit |
|---|---|---|
| 2026-10-13 | Accepted; autopilot is the exception ([0004](0004-rebuild-around-the-chat.md)) | `a2e2b3f` |

## Context

Starting the agent team queued a turn that told the lead to continue the campaign, its instructions said end-to-end
work was authorized, and every finished experiment woke it again. A new campaign's lead launched a runtime profile by
itself as soon as the team was started (readiness Part G).

## Decision

- Starting the team makes no model call; the lead's first turn is the researcher's first message.
- A campaign records whether a request is open. Outcomes wake the lead only while one is; a request closes when a turn
  ends with `yield_work(complete)`.
- The lead carries out the stage a request covers, reports, and stops. Turns the platform starts are notices, not
  requests.

## Consequences

- The first two rules are code (INV-04, INV-05 in [invariants.md](../invariants.md)); staying within the request once
  a turn has started is still prompt (INV-06), until roadmap Phase 3's mandates make it code.
- A campaign that should run on by itself needs an explicit exception: autopilot.
