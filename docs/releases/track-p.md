# Track P: problem set-up in one pass, release track-p

Track P completed on 28 October 2026, when P5 merged (`a586181`). This release is the commit on `main` that adds these
notes. It holds everything merged by then, all seven phases and track L included.

What changes for the researcher: a simple problem is set up with two actions, the message that describes it and one
confirmation. The lead writes the charter itself, in the conversation, with the formulator's checks on every save (P2,
decision 28). The problem note is read from that charter, with nothing to edit or adopt (decision 29). One call reads the
researcher's own words against the charter and lists each difference, which they settle before confirming (P4, decision
30). Code decides whether the problem is simple enough: when a criterion fails (a result that varies between repeats, more
than 3 variables or 10 inputs, a fourth save with a blocking finding, more than two questions or a second round), or when
the researcher asks, the lead's draft goes to the formulator and the full path continues from it with nothing lost (P3,
decision 31). The charter is put before the researcher as a card in the chat, which confirms it in one click: confirming
accepts the assumptions it lists and installs the tasks (P2, P5, decision 32). The evals now measure the set-up, from the
researcher's first message to the confirmed charter (P1).

## How to run it

```bash
git fetch origin && git checkout track-p    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

Nothing to migrate. A note adopted before track P stays on the full path; the lead takes the quick path only on a campaign
whose note was not adopted. The second reading runs on the model of the formulator's tier, else on the lead's (Models).

## Tag to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a track-p <this release's commit> -m "Track P: problem set-up in one pass"
git push origin track-p
```

## Acceptance tests

Use campaigns started from the objective only (no tasks, no note), with the agent team started and a model on the
formulator's tier (Models). Each item links to its part's full steps.

### End to end

- [ ] **A simple problem in two actions.**
  1. In the chat, describe the baking order: "One oven takes 8 bakes, one after another. Their durations in minutes, bake 0
     to 7: 30, 45, 20, 60, 35, 25, 50, 40. Their due times, in minutes from the oven's start: 210, 130, 200, 110, 190, 100,
     40, 120. A bake that ends after its due time is late by the difference. Find the order that minimizes the total
     lateness. Set the problem up so we can start."
  2. The lead replies in a few lines, and a card under its reply shows the problem in plain words: minimize the total
     lateness, the order of the 8 bakes as what is chosen, the durations and due times as you gave them, and any assumption
     confirming accepts. The Problem note shows the "quick path" pill and its sections read from the charter, with no Adopt.
  3. Click "Confirm and set the tasks" on the card.
  Expect: the card says the charter is confirmed and the gate is open, and the Overview's next step moves on from the
  charter. You acted twice (the message and the click), and no formulator ran.
- [ ] **A problem that needs the full path.**
  1. On another campaign, describe a flow reaction: "We run a flow reaction in a 10 mL tubular reactor at 5 bar. I can set
     the flow rate between 0.1 and 20 mL/min and the temperature between 20 and 200 C. The product decomposes above 150 C. We
     measure the isolated yield by HPLC; it varies between repeats, so each condition is run three times. Find the conditions
     of highest yield. Set the problem up."
  2. The lead drafts a charter, then says in one line that the problem needs the full path and why (the yield varies
     between repeats). The Problem note shows its sections written from the lead's draft, editable, with Adopt, and says why
     the quick path ended.
  3. Adopt it, answer the formulator's questions if it asks any, and confirm on the Charter tab.
  Expect: the Charter tab shows one charter, the formulator's revisions following the lead's draft.

### The parts

- [ ] **P1: the set-up is measured.** The live baseline and comparison below. [P1](../readiness/P1.md#acceptance-test)
- [ ] **P2: the lead writes the charter; the note is read from it.** The quick note is read-only, with the "quick path"
  pill and no Adopt; "Confirm and set the tasks" on the Charter tab confirms it too, and the gate opens.
  [P2](../readiness/P2.md#acceptance-test)
- [ ] **P3: when the quick path holds, and the fall back.** The flow reaction ends the quick path on "deterministic"; its
  note is written from the lead's draft and adopted as before. [P3](../readiness/P3.md#acceptance-test)
- [ ] **P4: the second reading.** The lead's reply says the reading found no difference, or names each it left; a
  difference keeps the confirmation waiting and names it. [P4](../readiness/P4.md#acceptance-test)
- [ ] **P5: the card and the quick note page.** If the card lists a difference, settle it on the card ("The charter is
  right", or "Ask the lead to fix it" with your words): asking the lead brings a new card, and the old one says it is out of
  date, with "Show the newest". To see a question on the card, leave the due times out of the message: the lead asks for
  them (or lists what it assumed); answer on the card, which waits for the lead's revision. On a quick note, "Use the full
  path" asks once more, then makes the note editable with Adopt and says why the quick path ended.
  [P5](../readiness/P5.md#acceptance-test)

## Live evals

The measure of the track: S20 (the baking order, which should take the quick path) and S21 (the flow reaction, which
should take the full path) on the code before track P (`c6c4c32`) and on this release, with the dev profile's default
model. Each run costs money.

```bash
# 1. The baseline, once: the code before track P, from a worktree
git worktree add ../balsamic-c6c4c32 c6c4c32
(cd ../balsamic-c6c4c32/agent-harness && npm ci --ignore-scripts && npm run build)
uv run python scripts/run_lead_evals.py --source ../balsamic-c6c4c32 --scenarios S20,S21 --record-baseline
# 2. This release, compared with it (the file step 1 wrote: evals/lead/baselines/c6c4c32-<model>.json)
uv run python scripts/run_lead_evals.py --scenarios S20,S21 --compare evals/lead/baselines/c6c4c32-<model>.json
```

Compare the section "Words to a confirmed charter" of `summary.md`. On the scripted harness (`--fake`), which counts steps
but not model time, today's path (`40a6c2e`: the code before track P with P1's evals) and this release give:

| Scenario | Code | Researcher actions | Rounds | Lead turns | Formulator turns | Model calls: agents + formulator |
|---|---|---|---|---|---|---|
| S20 | before | 3: message, Adopt, confirm | 3 | 1 | 1 | 1 + 1 |
| S20 | this release | 2: message, confirm | 2 | 1 | 0 | 2 + 0 (the lead's, the second reading's) |
| S21 | before | 4: message, Adopt, an answer, confirm | 4 | 1 | 2 | 1 + 2 |
| S21 | this release | 4: message, Adopt, an answer, confirm | 4 | 1 | 2 | 1 + 2 |

Live, S20 should show two researcher actions, no formulator turn, one reading call and fewer minutes from words to a
confirmed charter than the baseline; S21 should end the quick path on "deterministic" and take about the baseline's
minutes. The quick path's thresholds (3 variables, 10 inputs, 3 saves, two questions in one round) are the roadmap's: if
S20 falls back live, the criterion it names is the one to revise.

## In this release

| Part | What changed | PR |
|---|---|---|
| — | Track P added to the roadmap with decisions 28–32 and a readiness file per part | #110 |
| P1 | Scenarios S20 and S21 start from the researcher's words; a `define` step plays the researcher through the set-up; the set-up's actions, rounds, turns, model calls, cost and minutes in `summary.md` and the baselines | #111 |
| P2 | The lead's `charter_write` and `charter_read`; a note on the quick path is read from the lead's charter; `problem_note.confirm` accepts the assumptions, confirms and installs the tasks in one command; the `quick-charter` procedure | #112 |
| P3 | Code criteria decide when the quick path holds; when one fails, or on `problem_note.full_path`, the note goes to the full path written from the lead's draft and the formulator revises that charter; the formulator's runs host no extension | #113 |
| P4 | The second reading: one call with no tools reads the researcher's words against each revision the lead writes; each difference is settled (`problem_note.settle`) before confirming | #114 |
| P5 | The confirm card in the chat; what the confirmation waits on; it waits while the lead revises from the researcher's answers; the quick note page with its criteria and "Use the full path"; differences settled on the card and the Charter tab | #115 |

New invariants: INV-P2-1 to INV-P2-5, INV-P3-1 to INV-P3-4, INV-P4-1 to INV-P4-4, INV-P5-1, INV-P5-2
(`docs/invariants/P<n>.md`).

## Known gaps

- The thresholds of the quick path are the roadmap's, not yet revised on a live run (P3).
- The `define` step answers with fixed words (the recommended option of a charter question, "use what you suggest" to the
  lead); the formulator's spend is measured by the eval runner, still not in `llm_usage` (P1).
- Once confirmed, a change asked for in words on the lead's charter goes to a formulator, as for any confirmed charter (P2).
- The reading of a revision the researcher completed on the Charter tab after the lead left a blocking finding is not
  started for them: the confirmation asks them to have the lead write it again (P4).
- The card does not list the tasks confirming installs (the Charter tab and the gate show them once confirmed). A turn of
  the lead that stays queued (the team paused, the agent service down) keeps the confirmation waiting until it ends; the
  researcher can stop it or take the full path (P5).
