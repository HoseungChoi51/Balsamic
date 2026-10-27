# Phase 3 — A mandate for every request

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §08 A ("a mandate for every request: turns prose into code"), §06, §09 (Part S's open decision) |
| Decisions it needs | 10, 11, 12 |
| Start after | B2 (Phase 1): a consent that names what it covers is the first piece of a mandate. The Phase 2 baseline, to judge the change |
| Status | Not started |

## Why

The stance on autonomy moved four times in a month (graded delegation, autonomous iteration, "acts on requests",
per-action compute consent) and settled on two compute thresholds: graded delegation again, in a narrower form. What a
request allows beyond compute still rests on the prompt: "That the lead stays within a request once a turn has started
rests on its instructions and on the model following them" (`docs/pi-agent-harness.md` L102–103). With no typed shape for
a request, each new rule is attached to one command after an incident.

A **mandate** is the typed shape: for one request, the classes of work allowed, the proposals and runs it names, a compute
and model-spend envelope, a deadline and a stop condition. Small mandates start at once; larger ones are one inbox card.
The command bus refuses what is outside the active mandate. Compute consent (B2) becomes a mandate's compute part,
autopilot becomes a standing mandate, and the two thresholds become the default template. Agents stay free to plan and
propose; what they start is checked.

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| R1 | The mandate record and its templates | Nothing records what a request allows except its compute | B2, decision 10 | M | 1 |
| R2 | `mandate_propose`: the lead's first act on a request | The lead decides a request's scope in prose; only compute is asked for | R1 | M | 2 |
| R3 | The bus refuses work outside the active mandate | Staying within a request rests on the prompt | R1, R2, decisions 11, 12 | M | 3 |
| R4 | Autopilot is a standing mandate | Autopilot is a special case with its own guard | R3 | S–M | 4 |
| R5 | The model-spend envelope | Model spend is capped only per campaign, and usage cannot be told per request | R1 | S–M | 2 |
| R6 | From prose to code: who is woken, and the instructions | Part S's open decision; prompt lines that the mandate now enforces | R3 | S | 4 |
| R7 | The mandate dial in the chat | Graded delegation is an on/off switch plus two settings | R1, R2 | M | 3 |

---

## Parts

### R1 — The mandate record and its templates

**Depends on:** B2, decision 10. **Size:** M.

**Read first:** `campaigns/compute_consent.py` (all of it; `grant()` L138, `register()` L148), `campaigns/approvals.py`
`resolve()` L30–95, `contracts/commands.py` (`ApprovalRequestInput` L271–300, `CommandOrigin` L21–28), `agents/controller.py`
`request_root()` L397, `campaigns/commands.py` (`describe()` L125, the guard loop L252), `src/balsamic/evolution/gate.py`.

**Today**
- A compute consent records a plan's worker and wall seconds and its coding workspaces; after B2 it also names the
  proposals and runs it covers.
- Under autopilot, the campaign's autopilot settings hold a compute cap and a report date.
- Everything else a request allows is a line of the lead's instructions (`agents/tools.py` L58–60: "Stages … are
  separate: start one only when a request covers it").

**Change**
1. `contracts/mandates.py` `Mandate`: `id`, `campaign_id`, `root` (`thread_id`, `message_id`: the request it serves, as
   `request_root()` gives it), `template`, `classes`, `hypothesis_ids`, `workspace_ids`, `runs` (`PlannedRun`, as B2),
   `compute` (`worker_seconds`, `coding_workspaces`), `model_usd`, `deadline_at`, `stop_when` (text, plus an optional
   machine condition, first `all_runs_terminal`), `status` (`proposed`, `active`, `exhausted`, `expired`, `closed`),
   `granted_by` (`automatic`, or a decision id), `used` (worker seconds, workspaces, model dollars), `created_at`.
2. `campaigns/mandates.py`:
   - `CLASSES`: each registered operation belongs to one class: `answer`, `propose`, `review`, `implement`, `run`,
     `validate`, `decide` (stops, nominations, finalists), `record` (findings, comparisons, reports), `configure`
     (experiment rules, hiding runs, journal requests), `ask` (approval requests). Reads are not commands and are always
     allowed.
   - `TEMPLATES` (decision 10): **Answer** = {answer, ask}, no compute; **Explore** = Answer + {propose, review, run,
     validate, record} up to the go-ahead threshold in total, no coding workspace; **Screen** = Explore + {implement,
     decide} for the proposals, workspaces and runs it names, with their minutes; **Run the campaign** = every class within
     its envelope. Explore's envelope is taken from the campaign's thresholds (`compute_consent.thresholds()`).
   - `active(workspace, campaign_id, root)`, `grant(...)`, `charge(...)`. `charge()` reuses the consent's accounting; a
     consent is the compute part of the mandate that granted it.
3. Every compute consent already recorded reads as a Screen mandate with only a compute envelope: a view over the old
   record, never a rewrite.

**Tests**
- Every operation that `commands.describe()` lists has a class (a new operation without one fails the test).
- A consent recorded before this part reads as a mandate with its plan, seconds and workspaces.
- Explore's envelope follows the campaign's thresholds when the researcher changes them.

**Done when** the tests pass.

### R2 — `mandate_propose`: the lead's first act on a request

**Depends on:** R1. **Size:** M.

**Read first:** `agents/tools.py` (`PiTools.names()` L446, the tool table `TOOLS` from L341, `INSTRUCTIONS` L56–62,
`LEAD_CONTRACT` L79), `agents/turn_state.py` (`compute_rule()` L53, `build()` L111), `campaigns/approvals.py`,
`frontend/src/inbox/InboxPage.tsx`, `frontend/tests/compute-thresholds.spec.ts`.

**Today** the lead decides what a request covers and says so in prose. It asks for compute (`approval.request` kind
`compute`) only when the work passes the go-ahead threshold.

**Change**
1. A tool for the lead and the page agents, `mandate_propose`: `template`, `plan` (text the researcher reads),
   `hypothesis_ids`, `runs`, `worker_seconds`, `coding_workspaces`, `model_usd`, `deadline_minutes`, `stop_when`.
   - An Answer or Explore mandate within the researcher's thresholds is granted at once (`granted_by: automatic`); the
     reply says so in one line.
   - Anything larger becomes one inbox card: an `approval.request` of a new kind `mandate`, which replaces kind `compute`
     for agents (old `compute` requests stay readable). The card says what will run, why, the envelope and the deadline,
     with three choices: approve, approve as Explore only, decline.
2. A researcher's request with no mandate gets Explore by default at its first work-starting command, so a turn that only
   answers needs no call.
3. The state block gains one line: the active mandate (template, what is left, deadline), or "none: Explore by default".
4. A page agent asked by the researcher on its page proposes its own with the same tool (decision 12).

**Tests**
- An Explore mandate under the threshold is granted at once and named in the reply's receipt.
- A Screen mandate becomes one card; approving it records the mandate with the decision; "Explore only" records Explore.
- The state block shows the mandate and what is left.

**Done when** the tests pass, and Playwright `inbox-actions.spec.ts` covers the mandate card.

### R3 — The bus refuses work outside the active mandate

**Depends on:** R1, R2, decisions 11 and 12. **Size:** M.

**Read first:** `campaigns/commands.py` (`_execute()` L205–207, the guard loop L252), `campaigns/compute_consent.py`
`register()` L148–166, `src/balsamic/evolution/gate.py` (the guard pattern), `agents/controller.py` (`request_root()` L397,
`enqueue(..., root=...)` L405; page agents' runs take `root=agent.get("assignment_origin")`), `campaigns/plan_runs.py` (B5).

**Today** the compute guard checks only compute. Nothing checks that a command is the kind of work its request allowed,
or that it is for a proposal the request named.

**Change**
1. A guard beside the compute guard. For actor `manager`: find the command's run (`origin.run_id`), its request root, and
   that root's active mandate (or the default Explore). Refuse when:
   - the operation's class is not in the mandate;
   - a Screen mandate does not name the command's proposal or workspace;
   - the deadline has passed or the envelope is spent (decision 11).
   The refusal names what the mandate allows and how to ask for more (`mandate_propose`).
2. Compute is charged to the mandate. B5's `balsamic` launches act under the mandate their origin names (`consent_id`
   becomes `mandate_id`; old consents keep working through R1's view).
3. A page agent's run started by the lead carries the lead's root (check `page_agent_message` passes it), so it works under
   the lead's mandate; one the researcher started on its page works under its own (decision 12).
4. The researcher's own commands are never checked, as today.
5. `stop_when: all_runs_terminal`: when every run charged to the mandate has a terminal status, the mandate closes and the
   lead gets one notice under the root. This generalizes B5's single wake.

**Tests**
- A Screen mandate for H01–H04 refuses a `trial.create` for H05, with the text; it allows H02's.
- After the deadline, a new run is refused and the running ones continue.
- A page agent asked by the lead is checked against the lead's mandate.
- The researcher's commands pass with no mandate.
- The invariant "the lead stays within a request" (I1) becomes `code`, pinned by these tests.

**Done when** the tests pass, and the fake-harness scenarios S1–S12 still pass.

### R4 — Autopilot is a standing mandate

**Depends on:** R3. **Size:** S–M.

**Read first:** `src/balsamic/autopilot/rounds.py` (`ROUND_PROMPT` L10, `cap_guard()` L146–162, `register()` L165),
`src/balsamic/autopilot/settings.py`, the section "Autopilot: the exception to 'acts on requests'" at the end of
`docs/lead-agent-readiness.md`.

**Today** autopilot is "the one explicit exception": its own guard (`cap_guard`), its own settings, and a prompt that
restates the cap.

**Change**
1. `autopilot.set` (researcher only, as now) grants a standing Run-the-campaign mandate rooted in the autopilot thread: the
   compute cap as its worker seconds, the report date as its deadline. Switching autopilot off closes it.
2. Each round's run carries that root, and the mandate guard replaces `cap_guard`, which is removed. Its reservation rule
   (`wall_seconds` or `worker_seconds` of `trial.create`, `trial.continue`, `hypothesis.allocate`, and the items of
   `intervention.batch`) moves into the mandate's charge estimate, so nothing that is refused today is allowed.
3. `ROUND_PROMPT` loses the limits the state block now states.

**Tests**
- Today's autopilot cap tests pass through the mandate guard.
- Autopilot off closes the mandate; a round's command after that is refused.
- The badge, the actor `autopilot` and the away digest are unchanged.

**Done when** the tests pass.

### R5 — The model-spend envelope

**Depends on:** R1. **Size:** S–M.

**Read first:** `agents/usage.py` (`SCHEMA` L10–19, `record()` L47, `charged()` L78), `agents/controller.py`
(`model_allowance()` L319, `_within_llm_budget()` L942), `reports/pipeline.py` `afford()` L63.

**Today** model spend is capped per campaign (`llm_budget_usd`). The `llm_usage` table has no run id, so spend cannot be
told per request.

**Change**
1. `llm_usage` gains `run_id` (nullable for old rows) and `root_message_id`; `record()` fills them from the event's run.
2. A mandate's model spend is the sum over the runs under its root: the lead, page agents, specialists and report stages.
   When it reaches `model_usd`, new turns under that root hold, as `_within_llm_budget()` holds the campaign's, with one
   inbox card to raise it. The campaign cap still applies.
3. The state block's mandate line shows the dollars left.

**Tests**
- Usage rows carry their run and root; a mandate's spend sums its runs and nothing else.
- Turns under a spent envelope hold; the campaign cap still holds without a mandate.

**Done when** the tests pass.

### R6 — From prose to code: who is woken, and the instructions

**Depends on:** R3. **Size:** S.

**Read first:** `docs/pi-agent-harness.md` L85–103, `agents/tools.py` (`INSTRUCTIONS` L56–62; `GRANT_INSTRUCTIONS` L90
keeps an older copy of the same lines for the grant roles, which H8 retires), the "Not done" list of readiness Part S (its
first item), `tests/test_harness_contract.py`.

**Today** Part S left a decision open: the outcomes of runs the researcher started wake the lead, so its request stays
open and it writes "no change to report" twice.

**Change**
1. Outcomes belong to the mandate that started the work. Work the researcher started directly is under no mandate of the
   lead's, so its outcomes wake nobody; the researcher follows them on the pages. This closes Part S's open decision.
2. `INSTRUCTIONS` drops the lines the mandate now enforces ("start one only when a request covers
   it; a request may cover several", "Read a request narrowly…"), replaced by one: "Propose the narrowest mandate that
   answers the request (`mandate_propose`) and name the broader one in its plan." The ratchet goes down.
3. `docs/pi-agent-harness.md` L85–103 describes the mandate and links the register.

**Tests**
- A run the researcher started finishes without waking the lead.
- S3 (narrow request) and S8 (experiment status) pass with the fake harness.
- The ratchet passes with fewer words.

**Done when** the tests pass, and live S3, S8 and S12–S15 on Centinels pass at least as often as the Phase 2 baseline.

### R7 — The mandate dial in the chat

**Depends on:** R1, R2. **Size:** M.

**Read first:** `frontend/src/chat/Composer.tsx`, `frontend/src/inbox/InboxPage.tsx`, `frontend/tests/compute-thresholds.spec.ts`,
`src/balsamic/setup/service.py` (the `autonomy` field: manual, guided, delegated), `src/balsamic/autopilot/settings.py`
L41–47, `evaluation/confirmation.py` L71 and L117 (the two places that still read `autonomy`).

**Today** graded delegation is autopilot (on or off) plus two thresholds in the campaign settings. The original plan's
guided and delegated modes survive only as the `autonomy` field, read in two places.

**Change**
1. The composer offers the four templates as a chip beside the send button, defaulting to the campaign's default
   template. A message sent with Screen or Run the campaign opens a small form for the envelope and deadline, and grants
   the mandate with the message, so the lead does not have to propose one.
2. The active mandate shows above the chat (template, what is left, deadline), with "close" for the researcher.
3. The campaign's default template is a setting. `autonomy` maps onto it (manual → Answer, guided → Explore,
   delegated → Screen), and the two readers in `evaluation/confirmation.py` read the template instead.

**Tests**
- Playwright: a message sent with Screen grants a mandate shown above the chat; closing it refuses the next agent
  command (fake harness).
- `autonomy` values map to templates; the confirmation scheduler's checks are unchanged in effect.

**Done when** the tests pass.

---

## Order and shared files

```
Wave 1  R1 (after B2)
Wave 2  R2 · R5
Wave 3  R3 · R7
Wave 4  R4 · R6
```

| File | Parts |
|---|---|
| `campaigns/compute_consent.py` | R1, R3 (and B2, B5 in Phase 1) |
| `campaigns/approvals.py`, `contracts/commands.py` | R1, R2 |
| `agents/tools.py`, `agents/turn_state.py` | R2, R5, R6 |
| `src/balsamic/autopilot/rounds.py` | R4 |
| `frontend/src/chat/Composer.tsx` | R7 |

## Risks

- **Refusing too much:** a mandate that is too narrow turns every request into a card. The default Explore keeps small work
  free, and "approve as Explore only" keeps the researcher's options simple. Watch the number of cards per request in J3.
- **Two sources of truth during the move:** consents and mandates coexist until R3. R1's view keeps old consents working;
  nothing is migrated in place.
- **Page agents:** a page agent's run must carry the right root, or it is checked against the wrong mandate. R3's tests
  pin both cases.
- **Prompt cuts** (R6): drop only the lines the guard now enforces, and run the live baseline before and after.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, `(cd frontend && npx playwright test)`, `scripts/run_lead_evals.py --fake`.
- Live (Centinels): S1–S15 before and after the phase, compared with the Phase 2 baseline, in the phase's readiness Part.
