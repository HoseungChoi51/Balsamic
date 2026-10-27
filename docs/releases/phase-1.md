# Phase 1: charter to results, release phase-1

Phase 1 completed on 27 October 2026, when G2 merged (`9e87daa`). This release is the commit on `main` that adds these
notes. It holds everything merged by then (listed below). A researcher can now go from a confirmed charter to ranked
results with three actions: confirm the charter, ask for the methods, approve one plan. Balsamic installs the library the
coding agent writes, has the tasks adopt the problem it provides, binds the proposals and starts the approved runs by
itself. Orders (permutations) are a problem type, methods can be plain functions, the charter exports as a Python project,
and coding workspaces start from that project. Minimized objectives rank lowest first everywhere.

## How to run it

```bash
git fetch origin && git checkout phase-1    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

Coding workspaces need Docker on your machine (F4's workspace setup is not run in the cloud tests). Campaigns made before
this release keep their old tasks; confirm the charter again and make a new task to see D3 and E3–E5.

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a phase-1 <this release's commit> -m "Phase 1: charter to results"
git push origin phase-1
```

## Acceptance tests

Start with the end-to-end check; it covers most parts at once. The per-part checks below it isolate one change each, and
each links to its part's full steps.

### End to end

- [ ] **Charter to ranked results in three actions** (the phase's goal; G1 replays it offline).
  1. Open a new campaign on an order problem, such as baking order (8 bakes, minimize total tardiness), with its charter
     written as an order and its evaluator declared ("to be built"). Confirm the charter. *(action 1)*
  2. Write only: "Implement earliest due date, swap search and exact enumeration, and compare them: 2 seeds each,
     5 minutes per run." *(action 2)*
  3. Expect one approval card naming the coding workspace and the runs. Approve it. *(action 3)*
  4. Expect, with nothing more from you: the workspace starts from the generated library; the delivery installs; the
     task adopts the library's problem ("Balsamic had 1 task adopt its problem"); the proposals are bound "by Balsamic";
     the approved runs appear on Experiments, started by Balsamic; the methods that stop on their own end as finished,
     not failed.
  5. Expect one comparison from the lead, ranking the lowest tardiness first, matching Evolution → Frontier.

### Unblock and correct (A)

- [ ] **A1: install without a false "needs confirmation".** Baking order's pending install completes, and its four methods
  appear on Hypotheses → Implementations. [A1](../readiness/A1.md)
- [ ] **A2: rank by the objective's direction.** In a minimize campaign, Evolution → Frontier lists the lowest score first
  and says "lower is better"; a maximize campaign is unchanged. The lead names the lowest mean as best.
  [A2](../readiness/A2.md#acceptance-test)
- [ ] **A3: a method that finishes.** Run a library method that stops early beside a longer one. The early one ends as
  finished, not failed, and the comparison does not shrink the other's matched cost. [A3](../readiness/A3.md)
- [ ] **A4: checkpoints as notices.** While a coding agent works, Implementations shows its progress; the thread gets one
  message per question, blocker, delivery and install, with no raw JSON. [A4](../readiness/A4.md#acceptance-test)

### One go-ahead per request (B)

- [ ] **B1: no review for what you asked for.** "Record a proposal for simulated annealing and run it for 2 minutes"
  runs without a concept review; the proposal shows "asked for". Autopilot's own proposals still wait for review.
  [B1](../readiness/B1.md#acceptance-test)
- [ ] **B2: a go-ahead names what it covers.** Approve a run for proposal A; a later run for B asks for a new go-ahead.
  [B2](../readiness/B2.md#acceptance-test)
- [ ] **B3: no allocation card.** Asking for an implementation job gives one compute go-ahead and no card to raise the
  implementation allocation. [B3](../readiness/B3.md#acceptance-test)
- [ ] **B4: binding by Balsamic.** After a delivery, the install box shows each proposal "bound … by Balsamic"; a proposal
  the lead bound earlier keeps its method. [B4](../readiness/B4.md#acceptance-test)
- [ ] **B5: approved runs start by themselves.** After install, the planned runs appear on Experiments, started by
  Balsamic, none twice; the lead writes once when they all end. [B5](../readiness/B5.md#acceptance-test)
- [ ] **B6: unknown fields reported, not refused.** An extra field in an agent command is ignored and said so; a misspelt
  field is refused with "did you mean …". [B6](../readiness/B6.md#acceptance-test)
- [ ] **B7: the lead follows the new flow unprompted.** "Implement a pattern search and a cross-entropy method and compare
  them: 2 seeds each, 5 minutes per run" gives one card, no binding or allocation steps, and one comparison.
  [B7](../readiness/B7.md#acceptance-test)

### Problems that are orders (C)

- [ ] **C1: permutation variables.** The Charter's Variables table shows "an order of n_bakes items" with no bounds; a
  bound on it is a blocking check; "Uniform random" draws only valid orders; binary-only methods say "requires binary
  candidates". [C1](../readiness/C1.md#acceptance-test)
- [ ] **C2: methods for orders.** "Swap search" is offered on order problems and typically beats random; listed orders
  are evaluated as written, and a repeated bake is refused. [C2](../readiness/C2.md#acceptance-test)
- [ ] **C3: library methods say what they accept.** A library method that declares no representations is listed under
  "methods that cannot run here" with the reason; the grating campaign's methods are unchanged.
  [C3](../readiness/C3.md#acceptance-test)

### Methods as plain functions (D)

- [ ] **D1, D2: function methods.** No screen of their own. They show in the end-to-end check: the generated library's
  plain functions appear as methods and run. [D1](../readiness/D1.md), [D2](../readiness/D2.md)
- [ ] **D3: methods see the problem's data.** A method built for a declared problem reads the due times from the problem,
  not from its code; change one due time, confirm, rerun, and the results follow it.
  [D3](../readiness/D3.md#acceptance-test)

### Libraries that provide the problem (E)

- [ ] **E1, E2: a problem library installs, and the problem is listed without a restart.** A library that reuses an
  existing problem id is refused before anything changes. [E2](../readiness/E2.md#acceptance-test)
- [ ] **E3: the charter recognizes the installed problem.** The Charter shows "provided by a library" with the package
  and version, and confirms without asking for an evaluator; a direction mismatch blocks Confirm.
  [E3](../readiness/E3.md#acceptance-test)
- [ ] **E4: tasks adopt the library's problem.** Asking the lead to adopt raises the campaign's revision by one; asking
  again changes nothing. [E4](../readiness/E4.md#acceptance-test)
- [ ] **E5: adoption by itself.** After install the notice says "Balsamic had 1 task adopt its problem"; with an evaluator
  already bound it says why not and names `campaign.adopt_problem`. [E5](../readiness/E5.md#acceptance-test)

### A project generated from the charter (F)

- [ ] **F1, F2: export as a Python project.** On the Charter tab, **Export as Python project** downloads
  `<problem>-r<revision>.zip` with `README.md`, `pyproject.toml`, `charter.json`, the package and `tests/`; the same
  revision exports identical files. [F2](../readiness/F2.md#acceptance-test)
- [ ] **F3, F4: workspaces start from the generated library.** The workspace editor shows `libraries/<problem id>/`;
  `.campaign/assignment.md` names the problem and both proposals with no grating references; changing `data.py` makes
  the install fail with "The library's data no longer matches the charter revision".
  [F4](../readiness/F4.md#acceptance-test)

## Live evals (Hoseung)

These use a real model; run them at this release's tag and commit the baseline files they write.

| Part | Command | Compare with |
|---|---|---|
| B7 | `uv run python scripts/run_lead_evals.py --scenarios S18 --repeats 3` | the same run at `baseline` (`61538de`) |
| G2 | `uv run python scripts/run_lead_evals.py --scenarios S19 --record-baseline`, from a worktree of its own (about an hour; Docker and the workspace image needed; setup in [G2](../readiness/G2.md#acceptance-test)) | the summary's "Go-ahead to ranked results" is Phase 1's time; every check in the transcript passes, with exact enumeration ranked first |

## In this release

| Part | What changed | PR |
|---|---|---|
| A1 | An install no longer waits for a confirmation it does not need | #3 |
| A2 | The ledger, progress line, chart and Evolution rank by the objective's direction | #17 |
| A3 | A method that stops on its own finishes instead of failing | #6 |
| A4 | Coding checkpoints go to whoever opened the workspace, as notices | #19 |
| B1 | No concept review for proposals the researcher asked for or approved | #21 |
| B2 | A consent names the proposals, workspaces and runs it covers | #4 |
| B3 | The implementation allocation is an optional ceiling | #22 |
| B4 | Balsamic binds proposals to delivered methods | #28 |
| B5 | Approved runs start by themselves | #50 |
| B6 | Unknown fields are reported, not refused, at agent boundaries | #20 |
| B7 | The lead's instructions and the supervision procedure follow the new flow | #58 |
| C1 | Permutation representation | #9 |
| C2 | Built-in methods for permutations (swap search) | #24 |
| C3 | Library methods say what they accept | #12 |
| D1 | `FunctionMethod`: a function becomes a method | #14 |
| D2 | `FunctionPlugin`, function conformance, seeded workers | #35 |
| D3 | Declared problems show their data to methods | #26 |
| E1 | The problem registry picks up installs | #13 |
| E2 | The installer accepts problem libraries | #36 |
| E3 | The charter recognizes an installed declared problem | #27 |
| E4 | Tasks adopt a library's problem | #55 |
| E5 | Adoption happens by itself after an install | #64 |
| F1 | A standalone Python project from the charter | #16 |
| F2 | Export as a Python project | #40 |
| F3 | Balsamic glue in the generated library | #57 |
| F4 | Coding workspaces start from the generated library | #63 |
| G1 | Baking order replayed offline | #62 |
| G2 | The same flow as a live quality scenario | #65 |

Also included: all of Phase 2 (released as `phase-2`), and from phases not complete yet R1, V3, N1, N2, N4, N8, N15, K1
and K3.

## Known gaps

- **Not checked live in the cloud.** Most parts were checked by tests and the scripted lead only; the acceptance tests
  above are their first live run. F4's Docker workspace setup has no cloud test.
- **Planned runs that name only an algorithm, no proposal,** are still started by an agent, not by Balsamic (B5, B7).
  Runs start at the next workspace sync (about once a minute), and why a planned run waits is not shown on a page.
- **Adoption** is automatic only when the old task has no bound evaluator and no live runs; otherwise ask the lead (E4,
  E5). No page has a button for it.
- **Generated libraries:** the evaluator reports only the primary objective, not the charter's other metrics (F3). Two
  workspaces in one campaign share one library folder, so the lead should open one workspace for all proposals (F4). A
  charter revised after the campaign was made is not followed (F4).
- **No `oracle` (black-box) problems yet:** every generated project is white-box (decision 22); the flag is N11 (Phase 6).
- **Function libraries are not conformance-checked before they enter the lab** (D2; INV-23 stays `none` until H6).
- **The adaptive race still ranks by the largest mean** (A2); it moves with the problem packs (Phase 6).
- **Old campaigns** keep methods blind to the problem's data until their task is compiled again (D3).
- **Display gaps:** the comparison report's ranks are read by the lead, not shown on a page (A2); receipts' ignored fields
  are not shown (B6); approval cards still say "Implementation allocation" (B3).
