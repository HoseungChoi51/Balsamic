# Balsamic workspace: the chat-centred UI and its service

Status: milestone M0 (foundations) built on branch `workspace-rebuild`, 2026-10-19. This document is the reference for the
rebuilt service and frontend. It supersedes `workspace.md`, `cli-research.md`, the discovery documents, the model control
panel, decision reconsideration, proposal exploration and the consolidation plans, each of which now carries a banner
pointing here. The scientific core (problem adapters, optimizers, scheduler and workers, races, confirmation, admission,
the implementation service, assets and accounting), the Pi agent tools and the report writer are unchanged; their own
documents remain current.

## What changed and why

The previous workspace had sixteen views behind a hash router, one `/api/state` blob, a legacy Codex "campaign manager"
beside the Pi lead agent, and research modes that duplicated what a message to the lead does. The UI plan asks for a
chat-centred workspace: the lead agent is the control surface, its replies link to the page worth looking at, the
researcher formulates the problem with it, chats branch and merge, a strategy evolution graph shows how candidates were
generated, reviewed, killed, promoted, mutated and merged, a monitor pill waits in the top bar, and a strategy library
carries winners forward. Rather than bend the old shell into that shape, the service layer and the frontend were rebuilt
from an empty directory over the ported core.

Removed: the campaign manager (`research.start/control/retry`, research runs, decision refresh, context import, model
policy commands), the discovery controller and its records, the Codex CLI transport, `/api/state`, `/api/events`, every
compatibility route, and the `dqn_meent.workspace` grating-lab service. The Pi lead is the only chat backend.

Kept rules: viewing never acts; honest labels (measured vs forecast, unknown is not zero, stopped is not failed); a disabled
control says why; records are append-only; only the researcher grants limits, waivers, the worker ceiling, confirmations
and removals; there is no automatic paid fallback; the lead acts on requests (autopilot, in M3, is the explicit exception).

## Layout

```
src/optimization_framework/   the ported core: execution/ evaluation/ optimizers/ implementations/ assets/ analysis/
                              storage/ problem_charter/ problem_import/ reports/ contracts/ agents/ campaigns/ research/ llm/
src/balsamic/                 the service: app.py (create_app, main) · workspace.py · guidance.py · commands.py
                              threads/ (records, AG-UI stream) · evolution/stages.py · monitor/rows.py
                              telemetry/ (ui_event records, gate signals) · api/ (one module per concern)
agent-harness/                the Node Pi harness: supervisor.ts, runtime.ts, server.ts, sessions.ts (session tree)
frontend/                     the React workspace: src/shell, chat, router (pages.json), api, commands, telemetry, pages
tests/balsamic/               tests of the service layer
```

`optimization_framework` never imports `balsamic` (`tests/balsamic/test_layering.py`). `balsamic.app:main` is the
`optimization-lab` entry point with the same flags as before (`--directory --host --port --workers --frontend-directory`),
so `scripts/labctl` and `deploy/*.json` keep working.

## Pages and addresses

`frontend/src/router/pages.json` is the one catalog of pages. The frontend router and the lead's page links
(`optimization_framework/agents/pages.py`) both read it, so a page cannot exist on one side only.

| Rail page | Sub pages | Agent desk |
|---|---|---|
| `note` (Problem note) | charter, revisions | |
| `hypotheses` | rounds, implementations | discussion moderator; implementation lead on `implementations` |
| `experiments` | checks, rules, drafts; one run: `#experiments/<trial_id>` | experiment operator |
| `evolution` | frontier, lineage, curves, races | |
| `files` | assets, reports, notebook, sources | |
| `inbox` | | |
| `monitor` | resources, usage, races, agents, log, models, guidance, digest | resource planner on `resources` |
| `library` | | |
| `branches` | | |

Addresses are `#t/<thread>/<page>[/<sub>][/<id>]?sel=<id>&tab=`. A thread-less address (what the lead writes, e.g.
`#experiments/trial_x`) opens in the current thread. `#new` starts a campaign. Every old address still works: the
`aliases` block of `pages.json` maps `#overview`, `#decisions`, `#problem`, `#implementations`, `#comparison`, `#studies`,
`#validation`, `#assets`, `#notebook`, `#reports`, `#resources`, `#agents[/usage|/log|/models|/guidance]`, `#discussions`,
`#drafts`, `#models`, `#llm-usage`, `#memory` and `#problem-import` to their current pages, and `/reports/<id>` stays a
server-rendered page.

The shell: a top bar (campaign switcher, stage badge, search and autopilot placeholders that say when they arrive, the
monitor pill, Expand), the rail, the conversation with the lead on the left and the stage panel with the current page on
the right. Expand hides the chat; the choice is kept per browser.

## Reads

Every page read is scoped: it takes `?after=<event cursor>` and answers `{unchanged: true, event_cursor}` when the campaign
has no newer event. One SSE stream, `GET /api/v1/events?campaign_id=`, carries frames of
`{id, kind, record_id, campaign_id, status, revision}`; the frontend refetches the pages that show those kinds.

| Route | Returns |
|---|---|
| `GET /api/v1/workspace` | workspace id, worker ceiling, dev mode, provider, resource level |
| `GET /api/v1/campaigns` | rows with `stage` (formulate, generate, optimize, report; researcher pin overrides), autopilot, main thread |
| `GET /api/v1/campaigns/{id}/summary` | campaign, tasks, charter, budget, stage, counts, studies, trials (the CLI's state) |
| `GET /api/v1/campaigns/{id}/threads` | threads with message counts, the lead, the active run |
| `GET /api/v1/threads/{id}` · `/messages?after&before&limit` · `/stream` | the thread, its messages and open questions, the lead's turn as AG-UI events |
| `GET /api/v1/campaigns/{id}/experiments` · `/api/v1/experiments/{trial}[/metrics|/logs|/artifacts/{name}|/problem]` | runs by kind (short, long, checks), drafts, rules; one run |
| `GET /api/v1/campaigns/{id}/hypotheses` | proposals with readiness, aliases (H01…), review rounds |
| `GET /api/v1/campaigns/{id}/inbox` | decisions with freshness, issues, questions |
| `GET /api/v1/campaigns/{id}/monitor` | rows (problem, budget, compute, agents, needs you) and the pill |
| `GET /api/v1/campaigns/{id}/files` | assets, findings, reports and report jobs, sources, agent artifacts |
| `GET /api/v1/campaigns/{id}/agents[/live|/models|/records/{rid}]`, `/discussions`, `/guidance`, `/models`, `/charters`, `/export`, `/analysis`, `/comparison`, `/validations`, `/studies` | as before, under `/api/v1` |
| `GET /api/v1/resources`, `PUT /api/v1/resources/level`, `/api/v1/llm-usage`, `/api/v1/model-tiers`, `/api/v1/problems`, `/api/v1/assets*`, `/api/v1/bundles*`, `/api/v1/races/{id}`, `/api/v1/confirmations/{id}`, `/api/v1/problem-charters*`, `/api/v1/problem-imports*`, `/api/reports*`, `/api/campaigns/{id}/agent-log*`, `/api/campaigns/{id}/implementation-workspaces*` | unchanged |
| `GET /api/v1/command-catalog` | every operation's payload schema and whether the lead may run it |
| `POST /api/v1/ui-events`, `GET /api/v1/ui-events`, `GET /api/v1/ui-events/gate?campaign_id&milestone` | telemetry (below) |

## Writes: the command bus

Every write is `POST /api/v1/commands` with a `Command` (`contracts/commands.py`): a client-made `ui_<uuid>` id, the
campaign, the operation, `expected_revision` (the campaign version; 0 creates a campaign), optional
`expected_guidance_revision`, `expected_authority_hash` and, new, `expected_thread_revision` and `origin`
(`{thread_id, message_id, actor, agent_id, run_id, rationale}`). The receipt (`work_command`) carries the origin, so every
page can show who ran a command and from which conversation. The browser journals its commands in `localStorage`
(`balsamic.commands`) and retries a lost reply under the same id.

The service layer adds operations with `CommandService.register(operation, handler, model=, delegable=)`; an operation
must be declared in the `Operation` literal. M0 adds `campaign.stage_pin`; the thread, note, intervention, autopilot and
library operations are declared and arrive with their milestones.

Guidance: `manager_state.guidance_revision` stays the campaign-wide counter bumped by researcher graph and page commands.
Each thread has its own `guidance_revision` (bumped by a message in that thread, M1); a command pinned to a thread revision
is refused with "The researcher wrote in this conversation since this command was prepared" when that thread moved on, and
a message in another thread does not stale it.

A campaign may now be created without tasks or a charter: it starts in its formulation stage (`formulating: true`, no
study yet), the lead drafts the problem note with the researcher (M1), and the confirmed charter sets the tasks through
`campaign.update`. `CampaignInput` also carries `autopilot` settings, off by default.

## Threads on the lead's session tree

A thread is a branch of the lead's single Pi session. The harness (`agent-harness/src/sessions.ts`) exposes the tree:
`GET /v1/agents/{id}/tree`, `/entries?after&leaf`, `/context?leaf` (what the model would see from a leaf, with sizes),
`POST /v1/agents/{id}/leaf {entry_id, summary?}` (idle agents only) and `GET /v1/agents/{id}/export?leaf`. A run submitted
with `thread_id`, `leaf_entry_id` or `branch_from_entry_id` (and an optional `summary`) has its leaf positioned before the
prompt, and its result reports `entry_ids {parent, last}`. Steering reaches the turn in progress only from its own thread;
another thread's message waits as its own run. `tests/sessions.test.mjs` runs this against the pinned SDK 1.0.4.

M0 records one `thread` per campaign (`thread_main_<campaign>`); messages carry `thread_id` (absent means main) and a
`desk` when written to a page agent. The Python client (`agents/client.py`) has the matching calls. Fork, park, merge,
summaries, the context drawer and placeholders arrive with M1.

## Telemetry and gates

`ui_event` records hold the kind, time, campaign, thread, page, a session tag and a few scalars: which controls are used,
never what was written. The frontend batches them (`frontend/src/telemetry/events.ts`). `GET /api/v1/ui-events/gate`
computes the plan's gate table per milestone: forks, switches, merges and parks per session and the share of page opens
outside `main` (keep branching?); context-drawer opens, pins, exclusions and forgot reports (context before features?);
interventions per kind and the override rate (which controls stay?); the median time from a round's end to the next action
(canvas needed?); monitor opens and alerts acted on (which rows?); note asks by tier and escalations (router tuning).

## Running it

```bash
uv sync --extra dev --extra meent
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
uv run optimization-implementations --directory runs/dev/library --port 8767      # the implementation service
GRATING_PI_TOKEN_FILE=... GRATING_PI_DIRECTORY=runs/dev/pi GRATING_PI_WORKSPACE_URL=http://127.0.0.1:8765 \
  GRATING_PI_PROFILE=agent-harness/profiles/dev npm --prefix agent-harness start   # the Pi harness
GRATING_PI_URL=http://127.0.0.1:8768 uv run optimization-lab --directory runs/dev/workspace --port 8765 --workers 2
(cd frontend && npm run dev)                                                      # http://127.0.0.1:5173 during development
```

`scripts/labctl` starts the same services from a launcher configuration. Tests: `GRATING_LLM_DISABLED=true uv run pytest -q`,
`(cd agent-harness && npm test)`, `(cd frontend && npx tsc -b && npx playwright test)`.

## Milestones

| Milestone | State | Contents |
|---|---|---|
| M0 Foundations | built | service layer, scoped reads, SSE with kinds, command origin and thread pin, pages.json, session-tree routes, shell with chat on `main`, Inbox, Files, Monitor, Experiments, Hypotheses, New campaign, telemetry, legacy address redirects |
| M1 Formulation and branchable chat | next | thread fork, edit-and-resend, switch, park, merge; branch map; context chip and drawer; placeholders; slash commands; problem note with annotations and Adopt |
| M2 Evolution graph v1 | planned | ledger rows, lineage, stages, provenance, frontier interventions, hypothesis card, experiment log |
| M3 Merge, monitor, autopilot | planned | merge note, monitor rows and digest, autopilot rounds within a cap, iteration progress |
| M4 Reuse and polish | planned | strategy library, search, keyboard navigation, export |

The page placeholders for later milestones say which milestone brings them; nothing pretends to exist.
