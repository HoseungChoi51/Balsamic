# Phase 6: problem packs and every algorithm family on fair terms, release phase-6

Phase 6 completed on 28 October 2026, when N12 merged (`e92acd5`). This release is the commit on `main` that adds these
notes. It holds everything merged by then, Phases 5 and 7 included (`phase-5`, `phase-7`), so every roadmap phase is now
released.

The core no longer names a domain. What a problem brings is declared in its pack, and MEENT's comes from its own pack:
its procedures, its tools, its fidelity ladder and memory planner, its coding references, its FLRL methods and its cost
model. Problems state how methods may reach the objective. They are `white box` by default, judged by time, or `oracle`,
reached only through evaluations, as for MEENT (decision 22). A problem can now state more than a box of numbers:

- whole-number variables beside continuous ones;
- rules on the design that are checked on every candidate (M5);
- conditions on what the evaluator measures, where a result that breaks one never counts as the best;
- a candidate the problem's own library owns, such as a schedule, an order or a set (decision 24).

Exact methods get fair terms: a built-in `enumerate` with proved bounds and optimality, size ladders that show where a
heuristic overtakes an exact method, and proposals that name their family (exact, constructive, local search and so on)
first.

## How to run it

```bash
git fetch origin && git checkout phase-6    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

N7 adds a migration that gives every old record its problem. Before you run this release on the live lab, run it on a copy
of the data folder: `python -m optimization_framework.execution.problem_migration <copy of the data folder>`. Expect
an empty `unresolved` list. Old experiments run under the earlier execution contract stay readable but cannot be resumed.
For N6, put the FLRL checkout beside the Balsamic repository, or set `GRATING_FLRL_REFERENCE`, so that MEENT coding
workspaces get it under `/references/flrl`.

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a phase-6 <this release's commit> -m "Phase 6: problem packs; every algorithm family on fair terms"
git push origin phase-6
```

`phase-3` (`077473f`), `phase-4` (`a0085b3`), `phase-5` (`3d27d46`) and `phase-7` (`0fd9b0e`) wait for their tags too,
if they are not created yet.

## Acceptance tests

Each item links to its part's full steps. N1, N2 and N5 change nothing you can see in the app; their tests pin it.

### End to end

- [ ] **A scheduling problem, solved exactly and fairly.**
  1. Create a campaign and describe "four jobs of 3, 5, 2 and 4 minutes on two identical machines; every job runs once;
     each machine must finish within a 9-minute shift; minimise the makespan". Before writing the note, ask the lead
     what is known about the problem. It should name the class, its complexity and the known algorithms, with sources.
  2. On the Charter page, there is one structured decision variable. Its layout reads as one list of jobs per machine,
     the shift is a design rule over the machines' loads, and "How methods reach the objective" says white box.
  3. On Hypotheses, `/generate 3`: each card names a family first, and one is exact.
  4. Once the coding agent has filled the library, "Uniform random" is refused ("the problem's library owns this
     representation"). The library's methods run, and every schedule they evaluate fits the shift.
  5. On a small countable problem (a baking order of 8 bakes), "Enumerate every candidate" finishes. Evolution →
     Frontier shows "proved, checked by enumeration" with a gap of 0.

### The parts

- [ ] **N3: MEENT's procedures in MEENT campaigns only.** A MEENT campaign's lead lists `meent-problem-setup` and
  `rcwa-convergence-check`. A `bounded_continuous` campaign's lead lists neither, and has no such procedure to read.
  [N3](../readiness/N3.md#acceptance-test)
- [ ] **N4: MEENT's tools from its pack.** A grating campaign's operator makes and evaluates a test mask as before. A
  benchmark campaign's operator has no mask tool and says so. Old fixed-mask results still show.
  [N4](../readiness/N4.md#acceptance-test)
- [ ] **N6: references for coding workspaces.** A MEENT workspace has `/references/flrl` and a "References" section in
  its assignment. A non-MEENT workspace has neither (only a configured paper). [N6](../readiness/N6.md#acceptance-test)
- [ ] **N7: no MEENT paths in execution.** On a copy of the data folder, the app starts and old campaigns open. Resuming
  an experiment from before the current execution contract is refused as read-only history, and current experiments
  start, pause and resume. The migration lists nothing unresolved. [N7](../readiness/N7.md#acceptance-test)
- [ ] **N8: the FLRL methods as MEENT's plug-in.** The six FLRL methods are listed as bundled on the 2D deflector, and
  old proposals that use them still run. On other problems they say they run only on
  `meent_2d_dual_polarization_deflector`. [N8](../readiness/N8.md#acceptance-test)
- [ ] **N9: problem-agnostic constraints.** In the heat-sink note, the number of fins is a discrete variable, and the gap
  and height rules read "design: a condition on the design". An impossible threshold gets a warning. Random search
  evaluates only whole numbers of fins that meet both rules. [N9](../readiness/N9.md#acceptance-test)
- [ ] **N10: outcome constraints.** The fan's pressure limit reads "outcome: a condition on the measured result". A rule
  on a metric the problem doesn't report is blocked. Runs show "N infeasible", and Best and the comparison count only
  results within the limit. [N10](../readiness/N10.md#acceptance-test)
- [ ] **N11: access and cost model.** A benchmark run says "white box … judged by its time", with its curve over
  seconds, and it can switch to evaluations. A MEENT run says "oracle". A new charter offers the choice before you
  confirm it. [N11](../readiness/N11.md#acceptance-test)
- [ ] **N12: problem-owned candidates.** The two-machine schedule above: one structured variable, refused by the
  built-in methods, run by the library's methods. Two schedules that only swap the machines are recorded once.
  [N12](../readiness/N12.md#acceptance-test)
- [ ] **N13: bounds and optimality.** On a countable problem, `enumerate` proves the optimum, shown as "proved optimal"
  with a gap of 0, and "Allocate time…" says more time cannot improve it. On a problem too large to count, it is refused
  with the number of candidates. [N13](../readiness/N13.md#acceptance-test)
- [ ] **N14: size ladders.** Instances of 8, 12 and 20 jobs name a `size`; leaving it out of one is blocked. /compare
  names each method's largest finished size and the crossover. An exact strategy that has finished offers "Run on the
  next size…". [N14](../readiness/N14.md#acceptance-test)
- [ ] **N15: every family in the prompts.** On a knapsack or baking order, the lead names the problem's class and its
  known algorithms, and `/generate 3` gives families with an exact one among them. A proposal with no method says "no
  method chosen" and is refused until one is chosen. [N15](../readiness/N15.md#acceptance-test)

## Live evals (Hoseung)

On Centinels (no approval needed), at this release's commit, compared with the same scenario at the `baseline` tag
(`61538de`):

```bash
uv run python scripts/run_lead_evals.py --scenarios S17
```

S17 is the knapsack DP trap (N11, N15). It is expected to fail at `baseline`. Here, a pass, or a family other than
`local_search` on at least one proposal, shows the effect.

## In this release

| Part | What changed | PR |
|---|---|---|
| N1 | A layering test: no new file of the core names a domain (INV-27) | #30 |
| N2 | `ProblemPack`: where a problem declares what it brings | #31 |
| N3 | MEENT's procedures and cell labels come from its pack | #48 |
| N4 | Pack tool hooks: MEENT's agent tools and page operations only in MEENT campaigns | #51 |
| N5 | The race's fidelity ladder and the memory planner come from the problem's pack | #49 |
| N6 | Coding workspaces get their campaign's pack references only | #47 |
| N7 | No MEENT paths in execution; a migration gives old records their problem | #52 |
| N8 | The FLRL methods are MEENT's own optimizer plug-in | #46 |
| N9 | M5: discrete and mixed variables and design constraints checked on every candidate, in any problem | #94 |
| N10 | Outcome constraints: conditions on measured results; an infeasible result never counts as the best | #96 |
| N11 | Access and cost model per problem: white box by default, judged by time; oracle judged by evaluations or worker-seconds | #53 |
| N12 | Problem-owned structured candidates, canonicalized and checked by the problem's library | #97 |
| N13 | Bounds and optimality claims; a built-in `enumerate` that proves them | #86 |
| N14 | Instance-size ladders: the crossover at matched cost; "Run on the next size" for a finished exact method | #87 |
| N15 | The prompts and the proposal's `family` field: every algorithm family, an exact one where it exists | #39 |

INV-27 is held in code (N1). Keyed rows for the parts are in `docs/invariants/<part>.md`, and MEENT's pack is one module
per part in `src/dqn_meent/pack/`.

## Known gaps

- The layering ratchet still allows 20 core files that name a domain (INV-27's allowlist). `evaluation/legacy_confirmation.py`
  and the legacy grating comparison (`analysis/comparison.py`) still key on MEENT (N4, N6, N7, N10, N11).
- No named types (assignment, set, graph) in the core: they come only when two problems need them (decision 24). A
  structured candidate can be checked only where its library loads, and the Charter page has no editor for one (N12).
- A design constraint is checked whole on every candidate, so no method can prune with it. The binary-mask plug-ins
  declare no constraint support. Random search gives up after 10,000 infeasible draws in a row (N9).
- A soft outcome constraint is treated as hard. An outcome expression reads single numbers, not the charter's tables
  (N10).
- A method can't declare its own threads, and the adaptive race is still MEENT's only. Neither climbs a size ladder yet
  (N11, N14).
- `enumerate` on a white-box problem computes every candidate in one step, so a pause or the wall budget waits for it.
  A run's own page does not show its bound. A claim of optimality is a score like any other at V3's finalist gate (N13).
- "Run on the next size" offers only sizes the campaign already has as tasks. No page draws the comparison's ladder (N14).
- The lead isn't forced to set a family, and `campaign_inspect` doesn't say which family each installed method belongs
  to. Whether agents really propose exact methods is S17's live question (N15).
- References are copied once, when a workspace is first prepared (N6).
