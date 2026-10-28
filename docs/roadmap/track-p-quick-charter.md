# Track P — Problem set-up in one pass: the lead writes the charter of a simple problem

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | Hoseung's question of 28 October 2026 (the set-up is too slow for the difficulty of a simple problem; could the lead write the note and the charter in one shot?) and the opinion written for it, which Hoseung took with all five of its recommendations (decisions 28–32) |
| Decisions it needs | 1 (the evaluator comes from the library), 9 (fixed generated files), 22 (white box by default), 28–32 |
| Start after | Phase 7 and track L are released; P1 first |
| Status | In progress: P1, P2 and P3 done (2026-10-28); P4–P6 to do |

## Why

From the researcher's words to a confirmed charter, today's path has two agents write two artifacts about the same problem,
with the researcher acting between them (`main` at `c6c4c32`):

| Step | Who acts | What happens | Code |
|---|---|---|---|
| 1. Describe | Researcher | The objective at set-up, then messages in the chat | `setup/service.py` |
| 2. Draft the note | Lead | Seven prose sections, one at a time when an answer is needed | `procedures/problem-formulation` |
| 3. Answer, agree skips | Researcher | Answers the lead's questions; agrees each proposed skip on a card | `notes/skips.py` |
| 4. Adopt | Researcher | Only the researcher adopts; Adopt starts the formulator | `notes/service.py` `adopt()` |
| 5. Formulate | Formulator | A new run with fresh context and the 24 KB guideline reads the note and the researcher's words again, writes the charter, fixes the code's findings, may ask | `problem_import/service.py` |
| 6. Answer again | Researcher | Answers the formulator's questions, which start another formulator run | `problem_charter/service.py` |
| 7. Confirm | Researcher | "Confirm and set the tasks" compiles the setups and installs the tasks | `frontend/src/note/CharterPanel.tsx` |

The gate (`evolution/stages.py` `definition()`) checks steps 2–7 in order. The note and the charter overlap section for
section: objective, knobs (variables and inputs), observables (objective and metrics), noise (`evaluator.deterministic`)
and constraints all reappear in the charter; only confounders and open questions have no twin. For a small closed-form
problem such as baking order (8 bakes, every number given) the researcher acts three to five times, there are two question
rounds and a second agent's cold start, and the model time is a small part of the whole.

Nothing measures this today: the G1 replay and eval S19 both start from a confirmed charter. Two costs of the
formulator are not visible anywhere: its spend is kept on its import record, not in `llm_usage`, so neither the campaign's
model budget nor the evals count it; and its manifest says nothing of `extension_host`, so the harness gives it the
Balsamic extension, whose continuation asks every formulator run that ends to call `yield_work`, a tool it does not have
(one more model call per run).

The design: for a simple problem the lead writes the charter itself, in the conversation, with the code's checks on every
save. The note becomes a read-only view rendered from that charter. One cheap call reads the researcher's own words against
the charter, in place of the formulator's second reading. The researcher confirms once. When the problem turns out not to be
simple, the lead's draft and the researcher's words go to the formulator and the full path continues with nothing lost.

```
researcher's words ──▶ lead: charter_write ──▶ code checks (findings) ──▶ criteria (P3) ──▶ words vs charter (P4) ──▶ one confirm (P2, P5)
                              │                                              │ a criterion fails, or the researcher asks
                              ▼                                              ▼
                     the note, rendered from the charter (P2)        full path: note written from the draft, Adopt,
                                                                     the formulator revises the lead's draft (P3)
```

## Decisions (Hoseung, 28 October 2026)

The opinion named them Q1–Q5; Hoseung answered "Go ahead", which took the recommended answer to each.

| # | Decision | Settled | Parts |
|---|---|---|---|
| 28 | Who writes the charter of a simple problem | The lead, in the conversation, with the formulator's charter checks; not a formulator run after Adopt. Not chosen: send the researcher's words straight to the formulator | P2 |
| 29 | The problem note on the quick path | Rendered read-only from the charter (objective, knobs, observables, noise, constraints), with confounders and open questions; no second artifact to agree, and no Adopt | P2, P5 |
| 30 | What replaces the formulator's second reading | A one-shot check of the researcher's own words against the charter; each mismatch is shown before confirmation and the researcher settles it | P4 |
| 31 | Who decides that a problem is simple | Code criteria on the lead's draft: the lead tries the quick path and falls back to the formulator, with its draft, when a criterion fails; the researcher can ask for the full path at any time. Not chosen: the researcher picks quick or full at set-up | P3 |
| 32 | The researcher's actions on the quick path | One: confirm the charter, which accepts the assumptions it lists and installs the tasks. Not chosen: a separate Adopt; folding the confirmation into the first compute go-ahead (it would remove the approval the rest of the roadmap rests on) | P2, P5 |

**Names on screen.** The two ways to a charter are the **quick path** (the lead writes it) and the **full path** (the note,
Adopt, the formulator). In code a note's `path` is `quick` or `full`.

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| P1 | Measure first: from words to a confirmed charter | Nothing measures the set-up: G1 and S19 start from a confirmed charter, and the formulator's turns and spend are counted nowhere | — | S–M | 1 |
| P2 | The lead writes the charter; the note is rendered from it; one confirmation | Two agents write two artifacts about one simple problem, and the researcher acts three to five times | P1 | L | 2 |
| P3 | When the quick path holds, and the fall back | Nothing decides whether a problem is simple, or hands the lead's draft to the formulator when it is not | P2 | M | 3 |
| P4 | A second reading: the researcher's words against the charter | On the quick path nothing checks that the lead's retelling kept what the researcher said | P2 | M | 3 |
| P5 | Screens: the quick note and the confirm card | The pages show the full path only | P3, P4 | M | 4 |
| P6 | Release | — | P1–P5 | S | 5 |

The thresholds of P3 (variables, inputs, saves, questions) are set from the baseline P1 records, and revised after it.

---

## Parts

### P1 — Measure first: from words to a confirmed charter

**Depends on:** nothing. **Size:** S–M.

**Read first:** `scripts/run_lead_evals.py` (steps, checks, `metrics()`), `evals/lead/seeds.py`, `evals/lead/fakes.py`,
`tests/fake_harness.py`, `notes/service.py` (`adopt()`, `researcher_words()`), `problem_charter/service.py` (`answer()`,
`accept_assumptions()`, `confirm()`), `frontend/src/note/CharterPanel.tsx` (what "Confirm and set the tasks" sends).

**Today** every scenario starts from a defined problem or stops at the gate (S6, S7 seed the note directly). The runner cannot
play the researcher through the set-up, counts no formulator turn, and its cost metric reads `llm_usage`, which the formulator
does not write to.

**Change**
1. Two presets without a charter: `baking_words` (S19's campaign before its charter: the objective only) and `reactor_words`
   (the flow reaction's objective).
2. A step `define` plays the researcher until the gate opens, as the pages let them: each time the campaign's agents and its
   formulator are idle, it reads the gate's step and takes its action. A question of the lead gets the scenario's answer;
   proposed skips are agreed; Adopt adopts the current revision; on the charter, open questions are answered with their
   recommended option, assumptions are accepted, and "Confirm and set the tasks" confirms and installs the tasks (one
   action, two requests, as the page sends them). A blocking finding the researcher cannot settle on the page fails the
   step, naming it. The step reads the gate, not the path, so the same scenario runs on the quick path once P2 lands.
3. Metrics of the set-up (`setup`): the researcher's actions, by kind, and their rounds (an action or a group of actions
   after the agents went idle); lead turns; formulator turns, model calls and cost, read from the campaign's problem
   imports; the seconds from the researcher's first message to the gate opening (`words_to_charter_s`). `summary.md` gives
   them in a section "Words to a confirmed charter"; baselines record them.
4. Checks: `definition_ready` (the gate opened), `charter_matches` (the confirmed charter contains a JSON subset: the
   objective's name and direction, a variable's representation, input values), `setup_actions_at_most`.
5. Scenarios S20 (baking order, every number in the first message) and S21 (the flow reaction: noisy lab measurements in
   repeats, a constraint and a derived residence time, which must take the full path once P3 lands), with scripted turns of
   today's path: the lead writes the note in one turn and asks to adopt; the formulator (role `formulator`) reads
   `documents/researcher.md.txt` and saves the charter; in S21 it first asks one round of questions.
6. On the scripted harness the lab's model tiers name the harness's model, so Adopt can start a formulator (its model comes
   from the tiers, and without a dev profile there is none).
7. `evals/lead/README.md`: the scenarios, the step, the metrics, and how to record the live baseline of the code before
   track P (`--source` a worktree of `c6c4c32`).

**Tests**
- S20 and S21 pass on the scripted harness on today's path: the gate opens, the charter matches, at least three researcher
  actions for S20 (the message, Adopt, the confirmation), formulator turns counted.
- `define` fails with the finding when a blocking finding is left that the page cannot settle; it times out with what it was
  waiting for.
- The setup metrics read the formulator's turns and cost from its import, and `summary.md` shows them.

**Done when** the tests pass. Live (Hoseung): S20 and S21 on the code before track P, recorded as the baseline.

### P2 — The lead writes the charter; the note is rendered from it; one confirmation

**Depends on:** P1. **Size:** L.

**Read first:** `src/balsamic/lead/tools.py`, `problem_charter/service.py` (`create()`, `submit()`, `_save()`,
`from_formulator()`, `_send_round()`, `request()`, `confirm()`), `problem_import/service.py` (`_charter_tool()`: what
`charter_submit` returns), `problem_import/guideline.md`, `src/balsamic/notes/service.py` (`view()`, `revise()`, `adopt()`),
`src/balsamic/evolution/stages.py` (`definition()`), `src/balsamic/lead/state.py` (`gate_line()`),
`src/balsamic/procedures/problem-formulation/SKILL.md`, `campaigns/mandates.py` (`CLASSES`).

**Today** the lead writes only the note. The charter is the formulator's, after Adopt, and the researcher confirms it on the
Charter tab after accepting each assumption.

**Change**
1. The lead gets `charter_write` (a whole charter: the first call creates the campaign's charter, later calls revise it) and
   `charter_read`. `charter_write` returns what `charter_submit` returns the formulator (computed values, rendered texts,
   findings) and keeps the same rules: values the researcher set are kept, and only the researcher answers, accepts,
   waives and confirms. Its charter names its writer (`writer: lead`) and campaign; its revisions are by `lead`. It is
   refused once the note is adopted (the formulator writes the charter) and once the charter is confirmed (a change is
   asked for on the Charter tab).
2. The first `charter_write` puts the campaign's note on the quick path (`path: quick`) and links the charter. The note's
   view renders its sections from the charter's current revision: objective (objective and text), knobs (variables and the
   input quantities with their values), observables (objective and metrics), noise (deterministic or not, fidelity),
   constraints, confounders (the lead's, given with `charter_write`) and open questions (the charter's questions and
   assumptions, or none). The stored revisions are left as they are; on the quick path the note cannot be revised.
3. Questions on the lead's charter (at most two, one round) and a researcher's request for a change go to the lead: when
   the round is sent, a lead turn starts with the answers, as a formulator's does.
4. The gate on the quick path: the sections and Adopt are not steps (the charter states them); the step is "Confirm the
   charter" until it is confirmed, then the tasks. The state block's gate line names the path.
5. One researcher action, `problem_note.confirm` (researcher only; the charter's id and the revision shown): it accepts the
   assumptions the revision lists, confirms the revision and installs the tasks (`campaign.update` with the charter), in one
   command, refused on a stale revision or a blocking finding other than an unaccepted assumption. Mandate class `decide`.
6. A procedure `quick-charter` (lead): when to try the quick path, how to write the charter (a condensed form of the
   formulator's guideline: quantities, variables (an order is a permutation), objective, an evaluator declared with a new
   lowercase `problem_id` or an installed one, instances, texts with `{name}` references, citations of the researcher's
   message), the question round, and the reply (one line per assumption, the confirm link). `problem-formulation` names it
   first; `charter_write` hints it.

**Tests**
- `charter_write` creates a charter written by the lead, links it to the note on the quick path and returns the findings; a
  second call revises it; refused after Adopt and after confirmation; a value the researcher set is kept.
- The note's view renders the five sections from the charter and the other two from the lead and the charter; a revision of
  a quick note is refused.
- The gate on the quick path: confirm, then open, without Adopt; the gate line names the path.
- `problem_note.confirm` accepts the assumptions, confirms and installs the tasks in one command; it is the researcher's
  only; a stale revision and an open question are refused.
- Answering the quick charter's questions starts a lead turn with the answers.
- S20 on the scripted harness takes the quick path: two researcher actions (the message and the confirmation), no
  formulator turn.

**Done when** the tests pass and the lead's instructions stay under the ratchet (the procedure is read on demand).

### P3 — When the quick path holds, and the fall back

**Depends on:** P2. **Size:** M.

**Read first:** P2, `problem_charter/charter.py` (`findings()`), `contracts/problem_charter.py` (`EvaluatorBinding`),
`notes/service.py` (`adopt()`), `problem_import/service.py` (`create()`, `_first_prompt()`, `manifest()`).

**Today** (after P2) nothing keeps the lead from the quick path on a problem that needs the formulator's full reading, and
nothing hands its draft over when the problem is not simple.

**Change**
1. Criteria in code, assessed on each `charter_write` and shown in its result and the note's view. The quick path holds
   when: the problem was given in the conversation (no problem import, no documents or code); the evaluator is installed,
   or declared with a closed-form definition, with `white_box` access and no fidelity fields; it is deterministic; the
   charter has at most 3 variables and 10 input quantities; it has no blocking finding after at most 3 saves; and it asks
   at most one round of at most two questions. P4 adds its check.
2. When a criterion fails, the quick path ends: the note goes to the full path, its sections written from the lead's draft
   as a lead revision, and the lead tells the researcher in one line why. At Adopt the formulator gets the note, the
   researcher's words and the lead's draft as its charter (its first prompt says why the quick path did not hold), so its
   `charter_submit` revises the same charter.
3. The researcher can take the full path at any time (`problem_note.full_path`): the same hand-over, without a failed
   criterion.
4. The formulator's manifest hosts no extension (`extension_host: false`): it has no `yield_work`, so the continuation that
   asks for one costs a model call and nothing else.

**Tests**
- Each criterion, failed (a nondeterministic evaluator, `oracle` access, a fidelity field, four variables, eleven inputs, a
  fourth save with a blocking finding, three questions, a second round), ends the quick path with that reason.
- The hand-over writes the note from the draft and turns the path to full; Adopt then starts a formulator on the same
  charter, whose first prompt names the reason.
- `problem_note.full_path` is the researcher's only.
- S21 on the scripted harness falls back: the draft fails "deterministic", the researcher adopts, the formulator revises the
  draft, the researcher confirms.
- The formulator's manifest says `extension_host: false`.

**Done when** the tests pass.

### P4 — A second reading: the researcher's words against the charter

**Depends on:** P2. **Size:** M.

**Read first:** `agents/calls.py` (a one-shot call: assembled input, one bounded call, its record), `notes/service.py`
(`researcher_words()`), `problem_charter/charter.py` (`describe()`, `render()`).

**Today** the formulator's re-reading of the researcher's verbatim words is what keeps the lead's retelling from changing
the problem. The quick path has no formulator.

**Change**
1. A one-shot check with no tools reads the researcher's words (`researcher_words()`) against the charter's revision (its
   values, variables, objective, constraints, evaluator and texts) and lists each mismatch: what the researcher said (a
   quote), what the charter says (a path), and whether it is missing, different or added. One call per revision without
   blocking findings, on the formulator's tier, within the campaign's model budget; its instructions, input, output and
   usage are saved as a `charter_reading` record before it is shown.
2. A mismatch is a finding of the quick path, shown with the charter and its quote. The researcher settles each: the
   charter is right (recorded, with who), or the lead is asked to fix it (a lead turn naming it). An unsettled mismatch
   refuses `problem_note.confirm`.
3. A check that cannot run (no model, a failed call) ends the quick path (P3's fall back), so no quick charter is confirmed
   without its second reading.

**Tests**
- The check's input holds the words and the charter and nothing else; its output is checked against its schema.
- A mismatch refuses the confirmation until settled; settling records who and how; asking the lead starts a turn.
- A failed check falls back. S20's scripted check finds nothing; a variant whose lead changes a due time is caught.

**Done when** the tests pass.

### P5 — Screens: the quick note and the confirm card

**Depends on:** P3, P4. **Size:** M.

**Read first:** `frontend/src/note/ProblemNotePage.tsx`, `frontend/src/note/CharterPanel.tsx`, `frontend/src/note/Skips.tsx`
and `frontend/src/chat/Turn.tsx` (a card in the chat), `frontend/tests/`.

**Change**
1. The note page on the quick path shows the sections rendered from the charter, read-only, with the revision they come
   from, whether the quick path holds (or why it fell back), and "Use the full path". It has no Adopt.
2. When the lead's charter has no blocking finding but the researcher's own (questions, assumptions, mismatches), a card in
   the chat shows it in plain words: the objective, the variables, the inputs with their values, the constraints, the
   evaluator; the questions to answer; the assumptions confirming accepts; the mismatches to settle. One button confirms
   (`problem_note.confirm`). A card whose revision is no longer current says so and points at the newest.
3. The Charter tab confirms a quick charter with the same command.

**Tests (Playwright)**
- A quick note renders read-only, without Adopt; "Use the full path" makes it editable with Adopt.
- The card confirms in one click and the gate opens; a stale card is disabled; a question answered on the card.

**Done when** the tests pass.

### P6 — Release

**Depends on:** P1–P5. **Size:** S.

**Change** `docs/releases/track-p.md`: what changed, the UAT checklist (the readiness files' acceptance tests), and the live
comparison: S20 and S21 against P1's baseline (researcher actions, rounds, agent turns, model calls, minutes from words to a
confirmed charter). The status line of the roadmap.

---

## Order and shared files

```
Wave 1  P1
Wave 2  P2 (P1)
Wave 3  P3 (P2) · P4 (P2)
Wave 4  P5 (P3, P4)
Wave 5  P6
```

| File | Parts |
|---|---|
| `src/balsamic/notes/service.py` | P2, P3, P4 |
| `src/balsamic/evolution/stages.py` | P2, P3 |
| `problem_charter/service.py` | P2, P3, P4 |
| `src/balsamic/lead/tools.py` | P2, P3 |
| `scripts/run_lead_evals.py`, `evals/lead/` | P1, P2, P3, P4 |
| `frontend/src/note/` | P5 |

## Risks

- **A plausible retelling.** The lead may write a charter that reads well and states a different problem. The code's checks
  catch bad numbers, not a changed problem: P4's reading of the researcher's own words is the guard, and the researcher's
  confirmation stays.
- **Criteria too loose or too tight.** Too loose, a problem that needed the formulator is confirmed from a thin draft; too
  tight, the quick path never runs. The thresholds come from the baseline and are revised on the live comparison.
- **Two ways in.** Each page must say which path a campaign is on; the gate line and the note page do.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`; `uv run python scripts/run_lead_evals.py --fake`; Playwright for P5.
- Live (Hoseung): S20 and S21 on the code before track P and after it, compared.
