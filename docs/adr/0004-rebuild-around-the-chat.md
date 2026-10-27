# 0004 The rebuild around the chat, with autopilot as the one exception

| Date | Status | Commit |
|---|---|---|
| 2026-10-19 | Accepted | `52cbda4` (service layer), `daa8ff1` (M0 workspace shell and docs) |

## Context

The consolidated service had grown pages, managers and a compatibility API around a discovery workflow that the agents
had replaced. Fourteen documents described it; the researcher worked through forms while the agents worked in chat.

## Decision

Rebuild the workspace around the chat. `src/balsamic` is a service layer over the ported scientific core
(`src/optimization_framework`): threads, guidance revisions per thread, a command registry, the stage read model and the
v1 routes. The legacy manager, the discovery layer and the compatibility API are removed, and the frontend is rebuilt.
The lead works on request ([0002](0002-the-lead-acts-on-requests.md)); autopilot, switched on by the researcher with a
cap, is the one mode in which it runs rounds by itself.

## Consequences

- [ui-workspace.md](../ui-workspace.md) is the reference; the documents it superseded are in [history/](../history/README.md).
- The core never imports the service layer (`tests/balsamic/test_layering.py`).
- What the discovery layer held as evidence (enough tuning before a rejection, fidelity checks, locked results) went with
  it and survives mostly as prose; roadmap Phases 3 and 5 bring it back as code.
