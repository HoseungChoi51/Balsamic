# Balsamic agent harness update plan

| Item | Detail |
|---|---|
| Target | `kc-ml2/balsamic`, branch `workspace-rebuild` |
| Date | 2026-10-22 |
| How to work | Local Claude Code, one phase at a time (one phase = one branch = one PR) |

## Summary

| Phase | What | Problem it fixes | Size |
|---|---|---|---|
| 1 | Eval runner and baseline | Rehearsals and audits cannot be re-run (F8) | M |
| 2 | Per-turn state block, static manifest | Frozen instructions go stale; pins never reach the model (F1, F2, F7) | M |
| 3 | Server-side guidance revision pin | First command after a researcher answer is refused once (F3) | S |
| 4 | Pi extension host | Pi extensions cannot be used safely inside Balsamic; a turn without `yield_work` costs a whole extra turn (F9, F10) | M–L |
| 5 | Routing in code | Delegation rules live in prose; a status read costs three turns (F5) | S–M |
| 6 | Procedures split out, slimmer contract | Workflow procedures sit in the system prompt every turn (F6) | M–L |
| 7 | Specialist roles: briefs and output schemas | Specialist roles are names only (F4) | M |
| 8 (optional) | MCP at the edges only | — | L |
| 9 (optional) | Numeric claim checks | — | S–M |

---

## 0. Instructions for Claude Code (read first)

1. At the start of each phase, read §2 (principles), §3 (decisions) and that phase's section.
2. Read the phase's "Read first" files before planning (plan mode recommended). Line numbers refer to `a7e89b8`; find code by function name.
3. If a decision (D1–D9) the phase depends on is still open, ask Hoseung before implementing.
4. Write or update the tests first, then implement. A phase closes only when every "Done when" item holds.
5. Run live evals (real model calls, which cost money) only with Hoseung's explicit approval.
6. When closing a phase, add a new Part to `docs/lead-agent-readiness.md` in its existing format (What was wrong / What changed / Checked / Not done).
7. The core (`src/optimization_framework`) never imports the service layer (`src/balsamic`); see `tests/balsamic/test_layering.py`. For Balsamic-specific behavior, the service layer registers a hook on `workspace` and the core uses it when present. Existing examples: `workspace.lead_instructions`, `workspace.definition_gate`, `workspace.lead_operations`.
8. Pi's own documentation ships with the installed package: `agent-harness/node_modules/@earendil-works/pi-coding-agent/docs/` (run `npm ci --ignore-scripts` in `agent-harness` first). Prefer it, and the package's `.d.ts` files, over memory when using the SDK.

Test commands (from the README):

```bash
GRATING_LLM_DISABLED=true uv run pytest -q
(cd agent-harness && npm test)
(cd frontend && npx tsc -b && npx playwright test)   # only when the UI changes
```

---

## 1. Background

### 1.1 Current structure

The Python service owns campaign records, authority, the command bus and tool receipts. The Pi harness (`agent-harness/`, `@earendil-works/pi-coding-agent` 1.0.4) owns agent sessions and compaction.

- `agent-harness` embeds the Pi SDK (`createAgentSession`) in a Node HTTP service; it does not use Pi's RPC mode. Every agent is its own SDK session in that one process: the lead, the four page agents, the specialists and the grant-bound implementation roles.
- The coding workspace is the exception: a native Pi TUI in Docker, connected through Balsamic's own extension (`agent-harness/extensions/implementation.ts`) by command and event files.
- When the harness creates an agent's runtime, it fetches the instructions and tool list from the gateway (`POST /api/internal/pi/manifest`).
- Tool calls come back to Python through `POST /api/internal/pi/tool`, where they are schema-validated, authority-checked and receipted.
- The lead's instructions have three parts: the shared `INSTRUCTIONS` (about 2,000 words, used by every role), the `Role/Assignment` lines, and `lead_instructions` (about 900 words, partly dynamic).

Authority, the gate, budgets, the wake rules (`request_open`) and `yield_work`'s outstanding-work check are enforced in code. That part works well and stays as it is.

### 1.2 Findings

| ID | Problem | Evidence (`a7e89b8`) |
|---|---|---|
| F1 | Instructions are frozen per harness process. The harness fetches the manifest only when an agent has no runtime, then reuses that runtime for every later turn. So these are snapshots from the agent's first turn after a restart: the dynamic lines of `lead_instructions` (current gate state, library matches, autopilot), the experiment operator's rules, and the resource planner's level. The docs say the operator gets its rules every turn; the code does not do that. | `agent-harness/src/supervisor.ts` `pump()` L203–215 (`if (!agent.runtime)`); `src/balsamic/lead/instructions.py` L42–69; `src/optimization_framework/agents/tools.py` `manifest()` L423–445, `planner_instructions()` L199; `docs/pi-agent-harness.md` L182–183 |
| F2 | Thread pins never reach the model. `thread_pin` saves to the thread record only, and the context drawer presents pins as "what the lead sees", but no code path puts them into a turn. "Exclude" cannot remove anything from a Pi session either. | `src/balsamic/lead/tools.py` `thread_pin` L24–35; `src/balsamic/threads/context.py` |
| F3 | The model is asked to carry harness state. Three places disagree: `INSTRUCTIONS` says to send "the exact current guidance revision", the tool description says the revision is pinned, and the handler prefers the model's value. A value remembered from an earlier turn gets refused. This is the likely cause of the "first command after a researcher answer is refused once" pattern in readiness Parts E and G. | `tools.py` L100, L297, L882; `docs/lead-agent-readiness.md` Part E, Part G |
| F4 | Specialist roles are names only. The discussion roles get the lead's `INSTRUCTIONS`, one `Role:` line, whatever objective the delegator wrote, and the same 17 tools. The only structured output is `proposal_reviewer`'s `proposal_review`. `submit_output` is exposed only to grant agents, so other roles cannot use an output schema. | `tools.py` `names()` L373–400, `manifest()` L415–456; `agents/models.py` L16–20 |
| F5 | Routing depends on prose. The lead holds all 40 operations, including the page agents', while being told to hand that work over. For a status question it has no `experiment_progress` tool and is told to ask the operator, so one read costs three model turns. | `tools.py` `schema()` L402–413, `INSTRUCTIONS` L82–89; `docs/pi-agent-harness.md` L174 |
| F6 | Procedures for specific workflows sit in the system prompt every turn: report writing, journal clean-up, implementation-workspace supervision, runtime profiling, proposal fields, problem-note writing. | `tools.py` `INSTRUCTIONS` L46–152; `lead/instructions.py` |
| F7 | The fake harness differs from the real one. It fetches the manifest on every run, so tests cannot catch F1-type bugs. | `tests/fake_harness.py` `_play()` L119 |
| F8 | Evaluation relies on manual rehearsals. The audit and rehearsal results do not exist as a re-runnable suite. | `docs/lead-agent-readiness.md` Part E, G–K |
| F9 | Pi extensions cannot be used safely inside Balsamic. (a) Locked mode loads no extensions at all. (b) In dev mode every role gets the same profile extensions. (c) The harness never calls `session.bindExtensions()`, which in the SDK is what fires `session_start`, attaches a UI context and registers the error listener; Pi's interactive and RPC modes call it, the harness does not. So extensions that start anything on `session_start` (MCP connections, watchers, state rebuilt from the branch) never start, `ctx.ui` has nothing behind it, and extension errors are not reported. (d) Codemode, tool search and MCP are not loaded in SDK sessions unless added as extension factories. (e) Extension tools would bypass the gateway: no receipt, no authority check, no size cap. | `agent-harness/src/runtime.ts` L49–67 (locked loader `getExtensions` returns none at L55; no `bindExtensions` call); Pi `dist/core/agent-session.js` `bindExtensions` L2594–2617; Pi `dist/modes/rpc/rpc-mode.js` L230; Pi `docs/sdk.md` (codemode/MCP in SDK sessions) |
| F10 | A turn that ends without `yield_work` costs a whole extra controller turn. The controller notices only after the run ends and enqueues a `pi_continue_*` notice run; repeated silent turns become a researcher question. | `src/optimization_framework/agents/controller.py` `_receive` L853–868 |

### 1.3 Pi 1.0.4 behavior checked in the installed package

**Changing the system prompt invalidates the prompt cache for the whole session.**
- Pi records system-prompt changes in the transcript as section patches (system messages).
- The `openai-codex-responses`, `anthropic-messages` and `openai-completions` (including DeepSeek) providers default to `supportsMidConvoSystemMessages: false`. In that case the patches are folded into the leading system message (`node_modules/@earendil-works/pi-ai/dist/utils/transcript.js`, `resolveTranscript` and `collapseSystemMessages`).
- So any system-prompt change alters the start of the request and the cache is lost. Pi's extension docs say the same about tool-set changes on such providers.
- Conclusion: put dynamic state in the user turn, not the system prompt, and keep each role's tool set fixed during a session.

**Pi's native skills do not work in the current setup.**
- Pi lists skills in the system prompt only when a `read` or `bash` tool is active (`pi-coding-agent/dist/core/system-prompt.js`, `skillFileReadTool`).
- Balsamic turns built-in tools off in both modes (dev: `noTools: 'builtin'`; locked: gateway tools only).
- Conclusion: serve procedures through a gateway tool, or through an extension-provided `read` limited to the procedure folders (D3).

**Extensions and the SDK.**
- An extension runs inside the harness process with its full OS permissions and can see prompts, tool calls, credentials and session history.
- Extension hooks that matter here: `tool_call` (mutate or block a call), `tool_result` (compose, redact, truncate), `before_agent_start` (prompt sections), `context` (transform messages per request), `turn_end` and `agent_before_settle` (append entries and request one continuation), `cache_warming_decision`, `pi.registerVirtualModel` (route each request to a model), `pi.registerMcpServer`.
- `bindExtensions({uiContext, mode, onError, ...})` fires `session_start`. RPC mode passes a UI context that forwards `select`, `confirm`, `input` and `editor` as request/response dialogs and `notify`, `setStatus`, `setWidget`, `setTitle` as fire-and-forget messages (`docs/rpc-extension-ui.md`). `ExtensionMode` is `"tui" | "rpc" | "json" | "print"`.
- `DefaultResourceLoader` has `noExtensions` (turns off discovery; explicitly listed `additionalExtensionPaths` still load), `extensionFactories` (inline extensions), `noSkills`, `noPromptTemplates`, `noContextFiles`.
- Pi's example subagent extension spawns throwaway `pi --mode json -p --no-session` processes. They have no durable record, budget, wake rule, restart recovery or UI, so they do not replace Balsamic's controller.

---

## 2. Design principles

1. **Authority stays in code.** The gate, budgets, approvals, delegation scope and `yield_work`'s outstanding check stay enforced in code. None of it moves into prompts, procedure files or extensions.
2. **The system prompt is static per role.** For a given role it must be byte-identical regardless of campaign state; a test pins this.
3. **The harness builds changing state every turn.**
   - At the start of each turn, build a state block from the database, prepend it to the user turn, and save it on the run.
   - Never ask the model to remember or copy state.
4. **Delegate work; use tools for reads.** Hand a task to another agent only when it needs its own context or permissions.
5. **Extensions may change how an agent thinks; anything that acts goes through the gateway or reports to it.** Context management, prompt shaping and model routing can live in extensions. Anything that reads the outside world, writes, spawns agents or spends compute must be blocked, routed through a gateway tool, or receipted by the gateway.
6. **Prompt, role and extension changes are judged by evals.** A change merges only with no regression against the Phase 1 baseline.
7. **Stay compatible.** Saved sessions and records must keep working.
   - Do not delete role names.
   - When removing a tool argument, go through an "accept and ignore" transition.
8. **Leave protected areas alone.** Do not change the manifests of grant-holding implementation roles (builder, test designer, validator) or the `/api/internal/pi/implementation` routes. Grant roles get no extensions.

---

## 3. Decisions (Hoseung to confirm)

| ID | Question | Recommended default | Needed by | Status |
|---|---|---|---|---|
| D1 | Which page-agent-only operations to remove from the lead's enum | The table in Phase 5 | Phase 5 | Open |
| D2 | Specialist roles: keep them with briefs and schemas, or merge into one analyst role | Keep, with briefs and schemas; revisit merging after evals | Phase 7 | Open |
| D3 | How procedures are delivered | (A) Gateway tool `procedure_read` plus files in Agent Skills format. (B) Alternative once Phase 4 exists: an extension-provided `read` limited to the procedure folders, so Pi lists native skills. Default A; try B in dev mode | Phase 6 | Open |
| D4 | Where the state block is injected | The harness calls a gateway `turn_state` route right before `prompt()` | Phase 2 | Open |
| D5 | Who an inbound MCP client acts as | Read-only first; decide writes separately | Phase 8 | Open |
| D6 | Model and budget for live evals | A cheap model from the dev profile. For example, `llm_budget_usd` 0.30 per scenario and a $5 cap per suite run (for reference, the Part G service check cost $0.12 for three steps) | Phase 1 | Open |
| D7 | What to do with `campaign_command.guidance_revision` | Accept and ignore in this release; remove from the schema in the next | Phase 3 | Open |
| D8 | First curated extension set and per-role allowlist | Start with only the Balsamic gateway extension for every non-grant role. Add one third-party context-management extension after it passes the evals; then read-only web tools, receipted | Phase 4 | Open |
| D9 | How extension dialogs reach the researcher, and what happens when nobody answers | Show as a question above the chat (on the agent's page for page agents). Honour the extension's own timeout; otherwise cancel after 15 minutes. Under autopilot, cancel at once | Phase 4 | Open |

Why D4's default:
- If Python put the state into the run text at dispatch, a re-submit would carry different state and trip the harness's run-identity check (`requestHash`).
- A run that waited in the queue would also see stale state.

---

## 4. Phases

### Phase 1 — Eval runner and baseline

**Goal**
- Turn the audit and rehearsal failures in the readiness doc into re-runnable scenarios.
- Record a baseline on the current code (`a7e89b8`). Every later phase is judged against it.

**Read first**
- `docs/lead-agent-readiness.md` (Parts E, G–K)
- `scripts/qualify_agent_log_http.py` (pattern for running `create_app` in a temporary directory)
- `scripts/dev-stack` (environment for starting the real harness)
- `tests/balsamic/test_e2e_fake_harness.py`, `tests/fake_harness.py`, `tests/balsamic/support.py`

**Structure**

Tier A — contract tests (CI, no model)
- Add `tests/test_harness_contract.py`.
- This phase adds only a prompt-size ratchet: measure the word counts of the lead's instructions and a specialist's instructions, and fail if either grows more than 10% over its current value.
- Later phases add their contract tests here.

Tier B — live scenarios (opt-in, real model)
- Files:
  - `evals/lead/README.md`
  - `evals/lead/scenarios/*.json`
  - `evals/lead/seeds.py` (deterministic setup functions)
  - `scripts/run_lead_evals.py`
  - `pyproject.toml` has `testpaths = ["tests"]`, so pytest does not collect `evals/`.
- Runner design:
  - Start `create_app` in a temporary directory on a uvicorn thread, as `qualify_agent_log_http.py` does.
  - Start the real harness (`node agent-harness/dist/server.js`) as a subprocess.
  - Harness env: `GRATING_PI_TOKEN_FILE`, `GRATING_PI_DIRECTORY`, `GRATING_PI_PORT`, `GRATING_PI_WORKSPACE_URL`, `GRATING_PI_PROFILE=agent-harness/profiles/dev`, plus the keys in `~/.config/balsamic/secrets.env`.
  - Workspace env: `GRATING_PI_URL`, `GRATING_PI_TOKEN_FILE`, `GRATING_PI_PROFILE`, `GRATING_LLM_ENABLED=true`.
  - It runs independently of the user's dev stack.
- `--fake`: run the same runner against `tests/fake_harness.py` to check the plumbing only (safe for CI).
- `--model provider/model[:effort]`: passed as `agent.activate`'s `model`. Without it, the dev profile's default is used.
- Grading:
  - Prefer deterministic checks that read `app.state.workspace.store` directly.
  - Add an LLM rubric later.
- Output:
  - `runs/evals/<timestamp>/results.json`
  - `summary.md`
  - `transcripts/<scenario>.md` (messages, a summary of tool receipts, run inputs)
  - `runs/` is already in `.gitignore`.
- Repeats: `--repeats k`. Score the "does only what was asked" family as pass^k (k=3).
- Cost caps: each scenario's campaign gets an `llm_budget_usd` (D6); the runner stops when the suite cap is reached.

**Example scenario**

```json
{
  "id": "S3-narrow-request",
  "source": "lead-agent-readiness.md Part G",
  "setup": {"preset": "quadratic", "llm_budget_usd": 0.3},
  "steps": [
    {"say": "Create two hypotheses for this problem, each runnable with an installed method. Nothing else for now."},
    {"wait": "request_closed", "timeout_s": 600}
  ],
  "checks": [
    {"commands_exactly": {"operation": "hypothesis.create", "count": 2}},
    {"no_commands": ["trial.create", "draft.launch", "runtime.profile"]},
    {"max_lead_turns": 3}
  ],
  "repeats": 3
}
```

- Steps: `say`, `wait` (`idle` / `request_closed` / `seconds`), `approve_latest_decision`, `answer_latest_question`, `seed` (a function name in `seeds.py`), `pin`
- Checks: `commands_exactly`, `no_commands`, `max_lead_turns`, `no_model_calls`, `no_refusal_containing`, `max_tool_result_bytes`, `reply_contains_any`, `reply_links_page`, `no_researcher_question`, `request_closed`, `cost_usd_max`, `max_continue_turns` (count of `pi_continue_*` runs)

**Initial scenarios**

| ID | Scenario | Source | Expected |
|---|---|---|---|
| S1 | Start the team, send nothing for 120 s | Part G | 0 lead turns, 0 model calls |
| S2 | "What can you do for me, and what would you suggest as a first step?" | Part G | 1 turn, 0 commands, request closed |
| S3 | Create two hypotheses and nothing else | Part G | Exactly 2 `hypothesis.create`, 0 experiments or profiles |
| S4 | Create one hypothesis → researcher changes guidance with a page command (seeded) → ask for one more | Part E | 0 `guidance changed` refusals (expected to fail on the baseline) |
| S5 | Seed a large record and ask for a summary of it | Audit (a 55 MB result ended a session) | No tool result over 256 KiB; session stays healthy |
| S6 | Ask for strategies while the gate is closed | Gate rules | 0 proposals; reply names the missing sections and links `#note` |
| S7 | In the same session, open the gate (seeded, no harness restart), then ask for two strategies | F1 | Proposals recorded; reply does not say the gate is closed |
| S8 | Start two small runs, then ask "How are the experiments going?" | F5 | Reply has numbers. Record lead turns and operator calls (baseline: record only) |

**Baseline**
- Run S1–S8 once with k=3 on `a7e89b8`.
- Commit the summary to `evals/lead/baselines/a7e89b8.json`. Do not commit transcripts.
- Take the baseline from `a7e89b8` even if Phases 2 and 3 merge first, so the pre-fix state is on record.
- Record the number of `pi_continue_*` runs per scenario; Phase 4 is measured against it.

**Done when**
- `scripts/run_lead_evals.py --fake` passes in CI.
- A real-model baseline for S1–S8 is recorded and its `summary.md` shared.
- The README explains how to turn a new failure into a scenario.

---

### Phase 2 — Per-turn state block and static manifest (F1, F2, F7)

**Goal**
- Manifests become static per role.
- Each turn starts with fresh state prepended to the user turn.
- Thread pins actually reach the model.

**Read first**
- `agent-harness/src/supervisor.ts` (`pump`)
- `src/optimization_framework/agents/tools.py` (`manifest`, `planner_instructions`)
- `src/balsamic/lead/instructions.py`
- `src/balsamic/lead/tools.py` (`thread_pin`)
- `src/balsamic/api/internal_pi.py`
- `src/balsamic/commands.py` (where hooks are registered)
- `src/balsamic/threads/context.py`
- `tests/fake_harness.py`

**Implementation**

1. **State block builder**
   - Core: `src/optimization_framework/agents/turn_state.py` and `PiTools.turn_state(agent_id, run_id) -> {"text", "hash"}`. Covers the common items and the page agents' items.
   - Service layer: `src/balsamic/lead/state.py` covers the lead's items and is registered in `balsamic/commands.py` as `workspace.lead_state` (same pattern as `workspace.lead_instructions`).
   - Fixed item order, a 3,000-character cap, no wall-clock time.
   - Items:
     - Common: turn kind (request / notice), thread id and title, open researcher questions (up to 5, id plus one line)
     - Lead:
       - Gate (ready, next step, page, missing sections)
       - Autopilot (enabled / requested, cap, seconds remaining)
       - Top 3 library matches (move the logic from `lead_instructions` L58–66)
       - Up to 10 pins in this thread (id, kind, title, status, revision; one line each) and the excluded list ("records the researcher set aside")
       - Page agents with an open request
     - `experiment_operator`: the current experiment rules (the dynamic part of `manifest()` L423–445)
     - `resource_planner`: the current resource level and `max_workers` (the dynamic part of `planner_instructions`)
     - Specialists, import agents, grant agents: empty string
   - Example header: `[Workspace state at the start of this turn. Read-only; campaign_inspect has the full records.]`

2. **Gateway route** `POST /api/internal/pi/turn_state` (`internal_pi.py`, body `Context`)
   - Import agents get `{"text": ""}`.
   - Before returning, save `agent_run.turn_state = {"hash", "text", "at"}` (under `workspace.lock` and `store.transaction()`).

3. **Harness** (`supervisor.ts` `pump()`): after positioning the leaf, call `turn_state` right before `prompt()`.
   - The prompt becomes `[Assignment ${run.id}]\n${state}\n\n${run.text}`. With an empty state it is unchanged.
   - On 404, continue without state (older backends). Treat any other error like a manifest error: the run fails.
   - Keep computing `requestHash` from `run.text` only, so idempotency holds.
   - Leave the steering path unchanged.

4. **Make the instructions static**
   - In `lead_instructions`:
     - Remove the current gate state (L42–46), the conditional autopilot paragraphs (L54–57, L67–69) and the library block (L58–66).
     - Replace them with a static sentence: read the state block at the top of each turn to know the gate, autopilot and library matches.
     - Remove the `formulating` condition (L47) and always include the problem-note paragraph (Phase 6 moves it into a procedure).
     - Keep the `text(agent)` signature for existing callers, but stop reading the store.
   - In `manifest()`: move the experiment-rules block and the planner level into the state block. Keep each role's static sentences.

5. **Make the fake harness faithful** (`tests/fake_harness.py`)
   - Cache the manifest per agent, with `restart()` to clear it.
   - Call `turn_state` before each run and include it in the user entry's text.

6. **(Optional) Context drawer**
   - Add the size and text of the last `turn_state` to the layers in `threads/context.py`.
   - Change the "live" layer's description to "goes into the next turn's state block".
   - The UI change is in `frontend/src/chat/ContextDrawer.tsx`.

**Tests**

New `tests/test_turn_state.py`:
- `test_manifest_is_static_across_campaign_state`: the lead's, operator's and planner's manifest `instructions` and `tools` are byte-identical before and after each of these changes:
  - gate closed → open
  - autopilot off → on
  - a library entry added
  - an experiment-rules revision
  - a resource-level change
- `test_turn_state_reflects_changes_immediately`: each of those changes shows up in the next `turn_state`.
- `test_thread_pins_reach_the_next_turn_in_that_thread_only`
- `test_turn_state_is_saved_on_the_run_and_capped`

Existing tests to update (check `turn_state` instead of the manifest):
- `tests/balsamic/test_gate.py` L52, L71
- `tests/balsamic/test_library.py` L76
- `tests/test_experiment_rules.py` L42
- `tests/test_pi_agents.py` around L748 (planner level)
- `tests/balsamic/test_housekeeping.py` L158 checks static text and should pass unchanged.

Harness (`agent-harness/test/supervisor.test.mjs`):
- `turn_state` is called on every run; the manifest is fetched once per runtime.
- The prompt contains the state.
- A 404 is tolerated.
- Re-submitting the same run while the state differs does not raise an identity error.

End to end (`tests/balsamic/test_e2e_fake_harness.py`):
- Change the gate between two turns; the second turn's user entry carries the new state.
- The manifest is fetched only once.

Contract tests (`tests/test_harness_contract.py`): add "manifest is static per role".

**Docs**
- `docs/pi-agent-harness.md`: fix "What the lead agent is given" and the operator-rules sentence (L182–183).
- `docs/ui-workspace.md`: update the context drawer description.
- Add a new Part to the readiness doc.

**Done when**
- All tests pass.
- Live S7 passes (the open gate is seen without restarting the harness).
- Over a five-turn conversation, `cacheRead` tokens are no worse than the baseline (LLM usage page).

**Risks**
- The state block accumulates in the transcript every turn. The 3,000-character cap and the 10-pin limit contain it.
- Do not abbreviate to "same as last turn": each thread is a branch, so the previous turn differs per branch and this gets complicated.

---

### Phase 3 — Pin the guidance revision on the server (F3)

**Goal**
- The model never carries revision numbers.
- The "first command after a researcher answer is refused once" pattern from Parts E and G goes away.

**Read first**
- `campaign_command` in `tools.py` `_execute` (L860–886)
- `src/optimization_framework/campaigns/commands.py` (L231–237)
- `tests/balsamic/test_threads.py::test_lead_commands_pin_guidance_from_their_run`
- `tests/test_pi_agents.py::test_specialists_cannot_grant_authority_and_answers_invalidate_stale_commands`

**Implementation**

1. Set `expected_guidance_revision` to the larger of:
   - `run["guidance_revision"]`
   - the highest `guidance_revision` returned by this run's `campaign_inspect` receipts

   Ignore any `guidance_revision` the model sends (D7). Example receipt query:

   ```sql
   SELECT MAX(CAST(json_extract(data,'$.result.guidance_revision') AS INTEGER)) FROM records
   WHERE kind='agent_tool_receipt' AND json_extract(data,'$.run_id')=? AND json_extract(data,'$.tool')='campaign_inspect'
   ```

2. Schema: keep the `guidance_revision` property for now, with the description "Ignored. The revision is pinned from your turn and from any campaign_inspect you ran in it; omit it." Remove it in the next release (leave a TODO and note it in the readiness doc).
3. Delete "with the exact current guidance revision" from `INSTRUCTIONS` L100.
4. When a command is refused with `guidance changed`, make the tool result's `recovery` specific: "The researcher changed the campaign during your turn. Read campaign_inspect, check the change against what you were doing, and retry only if it still applies." Keep the bus message itself unchanged, since tests match on it.

**Tests**
- Update `test_lead_commands_pin_guidance_from_their_run` to check that a model-stated 99 is ignored and the run's value is used; rename it accordingly.
- Keep: a command sent after an answer without re-reading is still refused (`answers_invalidate_stale_commands`).
- New:
  - After `campaign_inspect` in the same run, the same command is accepted.
  - In a notice run, a command that states a revision read in an earlier run is accepted (Part E reproduction).
- Many existing tests pass `guidance_revision` (14 places in `tests/test_pi_agents.py`, among others). Because it is accepted and ignored, they should pass unchanged.

**Done when**
- Tests pass.
- Live S4 passes with k=3.

---

### Phase 4 — Pi extension host (F9, F10)

**Goal**
- Let Balsamic agents use Pi extensions without losing receipts, authority, budgets or visibility.
- Bind the extension lifecycle in the harness, load a curated per-role extension set in both modes, and add one Balsamic extension that every non-grant session loads first.
- Fix F10 inside the turn: a turn that would end without `yield_work` gets one in-turn continuation instead of a separate controller turn.

**Requires**: the Phase 1 baseline (with `pi_continue_*` counts), Phase 2 merged (both edit `supervisor.ts`), D8 and D9.

**Read first**
- `agent-harness/src/runtime.ts` (`createRuntime`, both resource loaders, the `createAgentSession` call)
- `agent-harness/src/supervisor.ts` (`pump`, `subscribe`, the `yield_work` `terminate` handling, `forget`, `close`)
- `agent-harness/extensions/implementation.ts` (the existing extension pattern: `defineTool`, `appendEntry`, `sendUserMessage`)
- In the installed Pi package (`agent-harness/node_modules/@earendil-works/pi-coding-agent/`):
  - `docs/extensions.md`, `docs/sdk.md`, `docs/rpc-extension-ui.md`, `docs/packages.md`, `docs/security.md`
  - `dist/modes/rpc/rpc-mode.js` around L215–260 (how RPC mode binds extensions and builds its UI context)
  - `dist/core/extensions/types.d.ts` (event, context and result types; `ExtensionMode`)
  - `examples/extensions/permission-gate.ts`, `truncated-tool.ts`, `tool-override.ts`, `custom-compaction.ts`, `subagent/`
- `src/optimization_framework/agents/controller.py` `_receive` L845–870 (the `pi_continue_*` path)
- `src/optimization_framework/agents/tools.py` (`names`, `manifest`, receipt identity in `call`)
- `src/balsamic/api/internal_pi.py`

**Implementation**

1. **Bind extensions** (`runtime.ts`)
   - After `createAgentSession`, call `await session.bindExtensions({ uiContext, mode: 'rpc', onError, shutdownHandler })`. Use `'rpc'` so extensions see `ctx.hasUI` true for dialogs and guard TUI-only behavior themselves; do not pass `commandContextActions` (Balsamic sends no `/` commands).
   - `onError` writes an `extension.error` event to the agent's journal (`supervisor.event`) with the extension path and event name.
   - Make sure `session_shutdown` handlers run on `forget()` and `close()`; check whether `dispose()` emits it and emit it explicitly if not.
   - A test extension whose `session_start` handler records a marker proves the binding.

2. **UI bridge** (`agent-harness/src/ui-bridge.ts`, plus Python)
   - Implement the extension UI context the way RPC mode does:
     - `select`, `confirm`, `input`, `editor`: POST to a new gateway route `/api/internal/pi/ui_request` and wait for the answer. Python stores an `agent_question` with `kind: "extension_dialog"`, the extension name, the options and the deadline. The researcher answers in the existing question area above the chat (or on the agent's page for page agents).
     - The answer goes back to the waiting extension, not into a new turn. Add a researcher command `agent.ui_respond {question_id, value | cancelled}` that records the answer without opening a request; the harness polls `GET /api/internal/pi/ui_request/{id}` (or long-polls) until it is answered, cancelled or past its deadline.
     - Timeouts follow D9: the extension's own `timeout` if given; otherwise cancel after the default; under autopilot cancel at once. A cancelled dialog resolves as `undefined` / `false`, as in RPC mode.
     - `notify` and `setStatus`: write to the agent's live entry (shown as its activity line) and to the event journal. `setWidget`, `setTitle` and terminal-only methods are no-ops, matching RPC mode's degradations.
   - Dismissing such a question (existing `agent.question_dismiss`) cancels the dialog.

3. **Curated extension set in both modes** (`runtime.ts`, Python manifest)
   - Locked mode: replace the custom resource loader with `DefaultResourceLoader` with discovery off (`noExtensions: true`, `noSkills: true`, `noPromptTemplates: true`, `noContextFiles: true`) and only the allowlisted extensions loaded through `additionalExtensionPaths` and `extensionFactories`. Keep the application instructions as the system prompt. Verify with a test that nothing from `~/.pi` or the working directory loads.
   - Dev mode: the profile's extensions keep loading for experimentation; the Balsamic extension (step 4) is always added first.
   - Per-role allowlist: the manifest returns `extensions: [...]` for the agent's role (a `ROLE_EXTENSIONS` table in `tools.py`, or a versioned JSON file in `agent-harness/extensions/`). Grant roles get an empty list and keep today's runtime exactly.
   - Put Balsamic's session extensions under `agent-harness/extensions/session/<name>/index.ts`, separate from `implementation.ts` (which runs in the container). Pin third-party extensions as exact versions in `agent-harness/package.json` and install with `npm ci --ignore-scripts`.
   - The allowlist is part of the manifest, so it is fixed for a runtime's life (static per role, §2.2). Prefer `codemode` or `deferred` exposure for rarely used extension tools so the declared tool list stays short.

4. **The Balsamic extension** (`agent-harness/src/gateway-extension.ts`, an inline factory created per session with a closure over the agent id, the active run id and the gateway client)
   - `tool_call`: gateway tools (the manifest's tool names) pass through. Any other tool must be on the role's allowlist of extension tools from the manifest; otherwise block it with a reason naming the role.
   - `tool_result`: for every non-gateway tool, POST a receipt to a new route `/api/internal/pi/external_receipt` with the agent id, run id, call id, tool name, extension name, bounded arguments, a bounded result summary, the result size and the tool's annotations. Python stores it as an immutable `agent_tool_receipt` with `external: true`, using the same identity scheme as gateway receipts (`pi_tool_` + hash of agent, run and call id), so it is idempotent and readable with `evidence_read` inside the campaign.
     - Truncate model-facing results above 256 KiB (the gateway's `TOOL_RESULT_BYTES`) and point the model at the saved record.
     - Web search and fetch results are evidence only through receipts; a page the agent wants to cite is captured with the existing `source_ingest`, so findings keep citing `source` records.
   - `agent_before_settle`: if the run has no saved `yield_work` (the supervisor already sees the saved result in the tool wrapper), request one continuation with a short custom message ("End the turn with yield_work: complete with the answer in report, or waiting if work you started is still running."). At most one per run; never for grant roles.
   - Keep the controller's `pi_continue_*` path as the fallback when the in-turn continuation also ends without `yield_work`; the stall count and the researcher question stay as they are.
   - `turn_end`: report the session's context usage (tokens used and window) to the event journal, so compaction can be tuned from the LLM usage data.

5. **Codemode, tool search and MCP**: not added in this phase. Phase 8 decides. When added, they go into `extensionFactories` (`createCodemodeExtension()`, `createToolSearchExtension()`, `createMcpExtension()`), and step 1's binding is what lets MCP connect.

6. **Trying a third-party extension** (the promotion path, written into `docs/pi-agent-harness.md`)
   1. Try it in the dev profile with `scripts/pi-dev`, then in a scratch campaign on `scripts/dev-stack up --real`.
   2. Read its code; list what it touches (files, network, processes, prompt, messages).
   3. If it acts, its tools must be allowlisted per role and receipted by the Balsamic extension; if it spawns processes or agents, do not promote it.
   4. Add or extend an eval scenario, run the suite, compare with the baseline (including `cacheRead`, since `context` transforms and prompt changes can cost the cache).
   5. Pin the version and add it to the allowlist.

**Tests**

Harness (new `agent-harness/test/extensions.test.mjs`):
- `bindExtensions` is called once per runtime and a test extension's `session_start` handler runs.
- Locked mode loads only allowlisted extensions; nothing from the profile, `~/.pi` or the working directory.
- Grant roles get no extensions.
- A non-allowlisted extension tool is blocked with a reason; an allowlisted one produces an `external_receipt` POST carrying the active run id; a large result is truncated.
- `agent_before_settle` requests one continuation when `yield_work` was not saved, none when it was, and never more than one per run.
- UI bridge: `confirm` creates a `ui_request`, an answer resolves it, a timeout resolves to the default, a dismissal cancels it.
- `onError` writes an `extension.error` event.

Python:
- `external_receipt`: immutable, idempotent on the same call id, refused for a foreign agent or a run that is not active, readable with `evidence_read` in the campaign only.
- `ui_request` creates an `extension_dialog` question; `agent.ui_respond` answers it without enqueueing a run or opening a request; `agent.question_dismiss` cancels it.
- The controller's `pi_continue_*` fallback still counts stalls when the in-turn continuation also fails.
- `tests/fake_harness.py`: add minimal support for `ui_request` and `external_receipt` so end-to-end tests can script them.

Contract tests: the manifest's `extensions` list is static per role; grant roles have none.

**Evals**
- Re-run S1–S8; no regression against the baseline.
- New S9: a test extension shipped with the suite offers one allowed read-only tool and one tool that is not allowed. The allowed call is receipted; the other is blocked.
- New S10: a seeded situation where turns tend to end without `yield_work` (for example, an open question answered in prose). `pi_continue_*` runs drop to about zero; extra model calls per turn stay at most one.

**Docs**
- `docs/pi-agent-harness.md`: a new "Extensions" section (binding, the UI bridge, the curated set and allowlist, the Balsamic extension, the promotion path).
- Readiness doc: a new Part.

**Done when**
- All tests pass in both modes.
- With only the Balsamic extension loaded, the eval suite shows no regression and `pi_continue_*` runs drop to about zero.
- Locked mode runs with the curated set.

**Risks**
- Extensions run with the harness's full OS permissions: review code, pin exact versions, install without scripts, keep the allowlist small.
- A dialog blocks the turn: D9 timeouts and cancel-at-once under autopilot.
- Extension tools change the declared tool list: changing an allowlist resets the prompt cache once for running sessions; prefer `codemode` or `deferred` exposure.
- A `context` transform that edits earlier messages on every request costs the cache each time; measure `cacheRead` before promoting one.

---

### Phase 5 — Routing in code (F5)

**Goal**
- Enforce "who does what" through the operation enum and the tools each agent is given.
- The lead does reads itself.

**Requires**: the Phase 1 baseline and D1. Independent of Phase 4; the two can be done in either order.

**Read first**
- `tools.py` (`ROLE_OPERATIONS`, `OPERATIONS`, `names`, `schema`, `INSTRUCTIONS` L82–89)
- `src/balsamic/commands.py` (`lead_operations`)
- `src/balsamic/autopilot/rounds.py` (`ROUND_PROMPT`)
- `src/balsamic/evolution/generate.py` (generation prompt)
- `src/balsamic/evolution/interventions.py` (operations a batch may carry, L24)

**D1 default**

| Operation | Owner | Note |
|---|---|---|
| `draft.save`, `draft.launch`, `trial.create`, `trial.continue`, `trial.extension_request`, `experiments.rules`, `trial.hide` | experiment_operator only | The lead asks through `page_agent_message` |
| `runtime.profile` | operator, resource_planner | Removed from the lead |
| `fixed_mask.run` | operator | Decide whether the lead keeps it for diagnostics |
| `implementation.*`, `evaluator.commission`, `evaluator.attach`, `evaluator.equivalence` | implementation_lead only | Decide whether the lead also loses the `implementation_workspace_*` tools |
| `resources.plan`, `resources.estimate` | resource_planner only | Already absent from the lead's enum |
| `trial.control` | Lead and operator | Keeps the lead's pause/stop safety control |
| `comparison.report` | Lead and operator | For analysis |
| `hypothesis.*`, `research.generate`, `hypothesis.allocate/nominate/edit`, `intervention.batch`, `library.apply`, `thread.pin`, `problem_note.revise`, `finding.record`, `validation.*`, `study.*`, `asset.snapshot`, `journal.compaction_request`, `approval.request` | Lead keeps | Autopilot and generation depend on these |

Notes:
- `hypothesis.allocate` creates experiments inside the service layer, so changing the lead's enum does not affect it.
- `intervention.batch` items are already limited to lead operations, so no extra guard is needed.

**Implementation**
1. Put the D1 result in a `LEAD_EXCLUDED_OPERATIONS` constant in `tools.py`.
   - Remove these from the lead's enum in `schema()`.
   - Refuse the same set in `_execute`, with a message naming the page agent and how to use `page_agent_message`.
   - The researcher's (UI) path is unaffected.
2. Give the lead `experiment_progress` (in `names()`). Change `INSTRUCTIONS` L87 from "Asked how the experiments are going, the lead asks the experiment operator" to "reads experiment_progress; asks the operator only when a decision about runs is needed".
3. Check that `ROUND_PROMPT`, the `generate.py` prompt and `INSTRUCTIONS` never tell the lead to run an excluded operation itself.

**Tests**
- The lead's enum contains no excluded operation.
- A direct call by the lead is refused with the guiding message.
- The lead has `experiment_progress`.
- `tests/balsamic/test_autopilot.py` and `tests/balsamic/test_evolution.py` pass.
- Update the lead-tools check around L59 of `tests/test_page_agents.py`.

**Evals**
- Re-run S3 and S8.
- New S11: "Run two short experiments" completes through the operator; record lead turns and cost.
- No regression against the baseline, and fewer lead turns on S8.

---

### Phase 6 — Split out procedures and slim the contract (F6)

**Goal**
- Move always-on workflow procedures into procedure files that are read only when needed.
- Cut the system prompt down to a short contract.

**Requires**: Phases 1–3 and D3. Phase 4 too if D3 picks option B.

**Read first**
- All of `INSTRUCTIONS` in `tools.py`
- `src/balsamic/lead/instructions.py`
- `agent-harness/node_modules/@earendil-works/pi-coding-agent/docs/skills.md` (format reference)
- `docs/problem-setup.md`, `docs/paper-mapping.md`
- `docs/lead-agent-readiness.md` Part F

**Implementation**

1. **Files**: `src/balsamic/procedures/<name>/SKILL.md`
   - Follow the Agent Skills format: frontmatter `name`, `description`, `metadata.roles`, plus `references/*.md` where needed.
   - The same files can later be used from Claude Code, the Pi CLI (`scripts/pi-dev`) and Claude Science.
2. **Loader and hook**
   - The service layer (`src/balsamic/procedures/__init__.py`) scans the directory at start-up and builds a per-role catalog (name — description), sorted by name.
   - It registers this as `workspace.procedures`; the core manifest uses it when present (layering rule).
3. **Delivery** (D3)
   - Option A, `procedure_read(name, file?)`:
     - Register it with `register_tool(..., roles=...)`.
     - Return the body (24 KB cap) and a list of bundled files.
     - Refuse procedures outside the agent's roles.
     - Receipts record which run read which procedure.
   - Option B (needs Phase 4): a session extension registers a `read` tool limited to the procedure folders of the agent's roles (check `examples/extensions/tool-override.ts`). Pi then lists the skills natively in the system prompt; the Balsamic extension receipts each read.
   - Running scripts is out of scope for this phase in either option.
4. **Add the catalog to the static contract** (option A): "Procedures available to you … Read the matching one with procedure_read before starting that workflow."
5. **Just-in-time hints**: when a workflow-starting tool runs and this run has not read the matching procedure (checked from receipts), add `"procedure": "<name>"` to its result.

   | Tool / operation | Procedure |
   |---|---|
   | `report_write` | `report-brief` |
   | `problem_note_draft` | `problem-formulation` |
   | `campaign_command` (`hypothesis.create`, `hypothesis.edit`) | `proposal-fields` |
   | `campaign_command` (`journal.compaction_request`) | `journal-cleanup` |
   | `campaign_command` (`finding.record`) | `recording-findings` |
   | `campaign_command` (`runtime.profile`) | `runtime-profiling` |
   | `implementation_workspace_create` | `implementation-supervision` |
   | `panel_render` | `panels` |

6. **Where things move**

   | Current location | Content | Moves to |
   |---|---|---|
   | `INSTRUCTIONS` L72–77 | Earlier campaigns' evidence, `finding.record` and publishing | `recording-findings` (one line stays in the contract) |
   | `INSTRUCTIONS` L78–81 | Journal clean-up | `journal-cleanup` |
   | `INSTRUCTIONS` L94–99 | Implementation workspaces | `implementation-supervision` |
   | `INSTRUCTIONS` L103–116 | Runtime profiles, flags, waivers, optimization allowance | `runtime-profiling` |
   | `INSTRUCTIONS` L120–124 | File tools, `analysis_run` | `analysis-scripts` |
   | `INSTRUCTIONS` L143–146 | Report writer | `report-brief` |
   | `lead_instructions` L15–25 | Proposal fields | `proposal-fields` |
   | `lead_instructions` L26–29 | Panels | `panels` |
   | `lead_instructions` L34–41, L47–53 | Gate details, writing the problem note | `problem-formulation` (two lines of gate rules stay in the contract) |
   | `lead_instructions` L8–11, page list | Duplicates `campaign_inspect.pages` | Only the linking rule stays in the contract |

   What stays in the contract:
   - role and authority
   - what requests and notices mean, and the narrow reading
   - the `yield_work` protocol
   - reply style and links
   - evidence-id discipline
   - approval and budget limits
   - delegation rules
   - the procedure catalog (option A)

   Target size: lead contract at most 900 words (about 2,900 now); shared core at most 350 words.

7. **Replace some rule lists with two or three short examples**:
   - A question gets an answer only.
   - In a notice turn with nothing new for the researcher, write no message and call `yield_work(waiting)`.
   - Read the request narrowly and say in one line what the broad reading would add.
8. **Domain procedures**: Claude Code drafts them from existing docs only, and Hoseung reviews the content. Do not invent physics.
   - `rcwa-convergence-check`: the Part F lesson (scores at the searched RCWA orders do not hold at higher orders)
   - `meent-problem-setup`: from `docs/problem-setup.md` and `docs/paper-mapping.md`

**Tests**
- The catalog is static per role (extend the Phase 2 contract test).
- Option A: `procedure_read` role scoping, size cap, receipts. Option B: the scoped `read` refuses paths outside the procedure folders, and reads are receipted.
- Hints appear at most once per run.
- Reset the word-count ratchet to the new baseline.
- Update tests that check moved sentences (keep the sentence in the contract or check it in the procedure instead):
  - `tests/test_pi_agents.py` L722 (`'campaign_inspect.pages'`, `'link the page instead'`)
  - `tests/test_page_agents.py` L44 (`"reviewer's own word"`)
  - `tests/balsamic/test_housekeeping.py` L158 (`"Proposal fields."`)

**Evals**
- No regression on the full suite against the baseline.
- The lead's instruction tokens drop by at least 50%.
- Record cost and turns per scenario.

---

### Phase 7 — Specialist roles: briefs and output schemas (F4)

**Goal**: make roles differ by brief, tool scope, output schema and independent context, not by name.

**Requires**: Phases 1 and 6, and D2.

**Read first**
- `src/optimization_framework/agents/models.py` (`ROLES`, `DISCUSSION_ROLES`)
- `tools.py` (`names`, `manifest`, `delegate`, `submit_output`, `proposal_review`)
- `src/optimization_framework/agents/discussions.py`
- `controller.py` (`create_agent`)
- `agent-harness/node_modules/@earendil-works/pi-coding-agent/examples/extensions/subagent/agents/*.md` (Pi's agent-definition format)

**Implementation**

1. Write the role briefs as files in Pi's agent-definition format: `src/optimization_framework/agents/roles/<role>.md` with frontmatter `name`, `description`, `tools`, `model` (optional tier hint) and the brief as the body (at most 200 words: purpose, what a good result looks like, what not to do). A loader in `src/optimization_framework/agents/roles.py` builds `ROLE_BRIEFS` and `ROLE_OUTPUT_SCHEMAS` (schemas in the same folder as `<role>.schema.json`). Editable files, portable to the Pi CLI.
2. Add a specialist contract, `SPECIALIST_CONTRACT` (at most 300 words):
   - who it reports to (the delegator, not the researcher)
   - `submit_output`, then `yield_work(complete)` with a one-line summary
   - cite record ids
   - start no new work
   - a tool-call budget

   Non-standing, non-grant roles get this instead of the shared `INSTRUCTIONS`.
3. Wire up output schemas:
   - `delegate()` sets the role's default `output_schema` (`create_agent` already supports it).
   - `names()` exposes `submit_output` whenever `output_schema` is set, not only for grant agents.
   - An agent with an `output_schema` cannot call `yield_work(complete)` before submitting its output.
4. Show structured outputs in the `discussions.py` view; the moderator reads and synthesizes them.
5. (Optional) Independence: a `proposal_reviewer` cannot read other reviewers' `proposal_review` of the same hypothesis revision until it has submitted its own (filter in `record()` / `evidence_search`).

**Draft schemas**
- `literature_specialist`: `claims[]: {claim, source_id, passage_ids[], support: direct|indirect|contradicts, relevance}`, `gaps[]`, `queries[]`
- `skeptical_domain_analyst`: `failure_modes[]: {mechanism, why_it_could_fail, falsifying_test, cost, severity: low|medium|high}`
- `methodology_specialist`: `fits[]: {algorithm, fits_representation, suggested_config, risks[]}`
- `cross_domain_explorer`: `analogies[]: {domain, mechanism, transfer_argument, source_id?}`
- `empirical_assessor`, `results_analyst`: `evidence[]: {claim, trial_ids[], metric, value, spread, comparable, caveat}`, `conclusion`, `confidence: low|medium|high`
- `proposal_reviewer`: keep the existing `proposal_review`.

**Compatibility**: do not delete role names. If D2 chooses merging, keep the old names loading as aliases.

**Tests**
- A specialist's manifest uses `SPECIALIST_CONTRACT` and its role file, and does not contain the lead's `INSTRUCTIONS`.
- Every role in `DISCUSSION_ROLES` has a role file and a valid schema.
- `submit_output` is exposed and validated against the schema.
- `complete` without an output is refused.
- The discussions view includes the outputs.
- Records with old role names still load.

**Evals**
- New S12: put a deliberately flawed proposal (an algorithm that isn't installed, a mechanism that contradicts the representation) into a review round. The skeptical analyst flags it and the verdict is revise or reject.
- 100% of structured outputs are valid.

---

### Phase 8 (optional) — MCP at the edges only

**Goal**: no MCP between internal agents; use it only at the system's outer edges.

**8a. Outbound (literature and similar)**
- For anything that becomes evidence, the Python gateway is the MCP client (official `mcp` Python SDK as an optional extra). It wraps the configured servers' tools as gateway tools, keeping receipts and the existing `source` / `source_capture` records.
- For read-only servers whose results are not cited directly, Pi-native MCP is an option once Phase 4 is in: add `createMcpExtension()` (and `createCodemodeExtension()` / `createToolSearchExtension()` for `codemode` or `deferred` exposure) to `extensionFactories`; the Balsamic extension receipts every call and enforces the role allowlist.

**8b. Inbound**: design and a read-only prototype of a Balsamic MCP server.
- Mount it on the FastAPI app over streamable HTTP, with token auth.
- Resources: campaigns, hypotheses, experiments, findings, reports.
- Read tools: `campaign_inspect`-style reads, `experiment_progress`.
- After D5, map write tools onto the command bus (`request_key`, receipts, authority hash).
- Extension candidates (check SDK support when implementing):
  - the Tasks extension from the 2026-07-28 spec for long-running work (experiments, reports)
  - the MCP Apps extension for panels

**Deliverables**
- `docs/mcp-server.md`
- The read-only prototype
- A check that Claude Code, connected with `claude mcp add`, can list hypotheses and read an experiment summary

---

### Phase 9 (optional) — Numeric claim checks

- Extract numbers from the text of `finding.record` and the report of `yield_work(complete)`.
- Check that each number appears in the cited evidence records or in this run's tool receipts (gateway and external).
- If not, mark it as `unverified_numbers` on the receipt. Do not refuse at first.
- Add an "unverified numbers" metric to the live evals.

---

## 5. Order and branches

```
Phase 1 (evals)     ─┐
Phase 2 (state)     ─┼─> Phase 4 (extension host) ─┐
Phase 3 (revision)  ─┘                             ├─> Phase 6 (procedures) ─> Phase 7 (roles) ─> Phases 8, 9 (optional)
                        Phase 5 (routing) ─────────┘
```

- Phases 2 and 3 are bug fixes and can run alongside Phase 1. Take the Phase 1 baseline on `a7e89b8` first.
- Phase 4 comes after Phase 2 because both change `supervisor.ts` and `runtime.ts`.
- Phases 4 and 5 are independent of each other. Phase 6 needs Phase 4 only if D3 picks option B.
- Branch names:
  - `harness/p1-evals`
  - `harness/p2-turn-state`
  - `harness/p3-revision-pin`
  - `harness/p4-extensions`
  - `harness/p5-routing`
  - `harness/p6-procedures`
  - `harness/p7-roles`
  - `harness/p8-mcp`
- Commit messages follow the existing `feat(gate): …` style: `feat(harness): …`, `fix(harness): …`, `test(evals): …`, `docs: …`

## 6. Out of scope

- Changing the Pi version or model providers
- Changing what the authority model means (budgets, approvals, the gate)
- Removing page agents or redesigning the agent hierarchy (apart from the Phase 5 enum cleanup)
- Replacing Balsamic's controller with Pi subagent extensions
- Redesigning the frontend (apart from the small context-drawer change in Phase 2 and showing extension dialogs in the existing question area in Phase 4)

## 7. References

- Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (2025-09-29)
- Anthropic, [Demystifying evals for AI agents](https://anthropic.com/engineering/demystifying-evals-for-ai-agents) (2026-01-09)
- Anthropic, [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- Anthropic, [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- Manus, [Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- Cemri et al., [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/html/2503.13657v3)
- Zheng et al., [Personas in system prompts do not improve performance](https://arxiv.org/abs/2311.10054v2)
- [MCP 2026-07-28 specification release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Docs in the installed Pi package: `agent-harness/node_modules/@earendil-works/pi-coding-agent/docs/{extensions,sdk,rpc-extension-ui,skills,mcp,codemode,packages,security}.md`

## Appendix A. Code locations (`a7e89b8`)

| File | Location | Phase |
|---|---|---|
| `agent-harness/src/supervisor.ts` | `pump()`: manifest fetch L203–215, leaf positioning L247, `prompt()` L252; `forget` L288, `close` L304 | 2, 4 |
| `agent-harness/src/runtime.ts` | Dev `DefaultResourceLoader` L49, locked loader L54–61 (`getExtensions` L55, `getSkills` L56), `createAgentSession` L63–67 | 2, 4, 6 |
| `agent-harness/extensions/implementation.ts` | Existing extension (container coding workspace) | 4 |
| `src/optimization_framework/agents/tools.py` | `INSTRUCTIONS` L46–152, `planner_instructions` L199, `TOOLS["campaign_command"]` L296–298, `names` L373, `schema` L402, `manifest` L415, `inspect` L643, `campaign_command` execution L860–886, `yield_work` L913 | 2–7 |
| `src/optimization_framework/agents/controller.py` | `enqueue` L396, `_sync` L633, `_receive` L745 (`pi_continue_*` L853–868), `_campaign_events` L933 | 2, 4 |
| `src/optimization_framework/agents/models.py` | `PAGE_AGENTS`, `DISCUSSION_ROLES`, `ROLES` L12–20 | 5, 7 |
| `src/optimization_framework/campaigns/commands.py` | Guidance and thread revision checks L231–237 | 3 |
| `src/balsamic/lead/instructions.py` | Whole file (dynamic parts L42–69) | 2, 6 |
| `src/balsamic/lead/tools.py` | `thread_pin` L24–35, tool registration | 2, 6 |
| `src/balsamic/api/internal_pi.py` | `manifest` route L70–75; new `turn_state`, `ui_request`, `external_receipt` routes go here | 2, 4 |
| `src/balsamic/commands.py` | Hook registration (`lead_operations` L90, `lead_instructions` L113) | 2, 5, 6 |
| `src/balsamic/evolution/interventions.py` | Operations a batch may carry, L24 | 5 |
| `src/balsamic/autopilot/rounds.py` | `ROUND_PROMPT` | 5 |
| `tests/fake_harness.py` | `_play()` manifest fetch L119 | 2, 4 |
| Pi package `dist/core/agent-session.js` | `bindExtensions` L2594–2617 | 4 |
| Pi package `dist/modes/rpc/rpc-mode.js` | RPC extension binding and UI context, L215–260 | 4 |
