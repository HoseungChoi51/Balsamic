# Phase 6 — Problem packs: domain knowledge out of the core, every algorithm family on fair terms

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §08 C ("problem packs: flexibility as data"), §05 ("domain knowledge out of the core"), §01 finding 4; `docs/problem-setup.md` "Next step: problem-agnostic constraints" (M5); the algorithm-family review of 2026-10-27 (N11–N15) |
| Decisions it needs | 17; 20 for N9 and N10; 22–24 for N11–N15 |
| Start after | N1 at any time (it only freezes today's list). N2–N8 in any order after N2. N9 and N10 after G1 and decision 20. N11 after N2; N13 after N11 and A3; N14 after N5 and N11; N12 after N9; N15 at any time |
| Status | Not started |

## Why

The consolidation plan's central change was to move MEENT's assumptions into its adapter. It is unfinished. Besides the
`GRATING_*` environment variables (the project's old name, not domain logic), about 25 files of the core still name the
domain. The main ones:

- `problems.resolve("meent_grating", …)` as a fallback (`execution/service.py` L649, L941, L955; `execution/runtime_profile.py`
  L213), `meent_grating` as a default problem id (`implementations/models.py` L56, `implementations/bridge.py` L156, L165),
  and the legacy worker `dqn_meent.workspace.worker` (`execution/service.py` L1327, L1362);
- `execution/rcwa_memory.py` ("Plan MEENT 0.13.2 CPU memory"), called by `execution/observability.py` L481–493 with RCWA
  orders and a 256×128 grid written into the call;
- the adaptive race's RCWA fidelity ladder, limit, cost model and preferred FLRL methods (`execution/racing.py` L25–54,
  L162, L737–747);
- `mask_create` in every agent's tool set (`agents/tools.py` L446) and `fixed_mask.run` among the experiment operator's
  operations;
- the FLRL reference copied into every coding workspace (`agents/development_runtime.py` L158–168), and `/references/flrl`
  and `libraries/grating-mask-search` in the coding brief (F4 removes these from the generic brief);
- the FLRL Fourier methods inside the core's optimizer registry (`optimizers/fourier_specs.py`, the `dqn_meent` import at
  `optimizers/registry.py` L203);
- two MEENT procedures among the service layer's generic ones (`src/balsamic/procedures/meent-problem-setup`,
  `rcwa-convergence-check`), and "silicon"/"air" labels for any problem whose id starts with `meent`
  (`campaigns/experiment_rules.py` L103).

A **problem pack** is the problem plug-in's package declaring what its problem brings: its tools, procedures, validation,
estimators, fidelity ladder, presentation and reference material. The core loads them for the campaigns that use that
problem and names no domain itself. Each problem brings its own guardrails: the pack, not the prompt, says which
validation a score needs (V3 declares it on the problem definition) and which tools make sense.

M5 (decided on 21 October, deferred until the narrower framework is confirmed end to end) belongs here too: its
constraint forms live in the charter contract and the pack's evaluator.

**Every algorithm family on fair terms (N11–N15).** The charter states a problem the way a MILP is stated (variables,
bounds, linear constraints, one objective), which is fine as a statement. What tilts results is how methods are run and
judged: as black-box searches that propose one fixed-length vector at a time to an evaluator they cannot see into,
ranked by the best value so far. That suits the built-in metaheuristics and works against dynamic programming, branch and
bound, constraint programming, MILP solvers and specialized algorithms, which use the problem's structure, compute
internally, finish, and often prove optimality. Phase 1 removes the hard blockers (C1 permutations, A3 a method that
finishes, D1 plain functions, D3 the data visible to methods). N11–N15 remove the rest:

- the problem does not say whether its objective is an oracle or known code, so evaluations are counted as the cost even
  where a method should use the objective freely (N11, decisions 22 and 23);
- there is no place for a proven bound or optimality, so "proved 412 optimal" and "found 412" look the same (N13);
- instance size is not an axis, though the crossover between exact and heuristic methods is the finding (N14);
- representations stop at vectors and orders (N12, decision 24);
- the prompts ask which installed *search* method fits, and nothing asks for the problem's class or known algorithms (N15).

Balsamic's goal is to solve the researcher's practical problem as efficiently as possible, not to run a benchmark, so a
problem is `white_box` unless it declares otherwise (decision 22). The review is
[Is Balsamic biased toward MILP?](https://claude.ai/artifact/LwiujDQ7GTZqyoqDJK7mtV).

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| N1 | The domain-names ratchet | Nothing stops new domain names entering the core | — | S | 1 |
| N2 | The pack manifest and its loader | A problem cannot declare what it brings besides its evaluator | decision 17 | M | 1 |
| N3 | Pack procedures and presentation | MEENT procedures sit among the generic ones; MEENT labels are keyed on an id prefix | N2 | S | 2 |
| N4 | Pack tools | Mask tools are in every agent's tool set, whatever the problem | N2 | S–M | 2 |
| N5 | Pack estimators and fidelity ladders | The memory planner and the race's ladder are MEENT's, in the core | N2 | M | 2 |
| N6 | Pack references for coding workspaces | Every coding workspace gets the FLRL repository | N2 | S | 2 |
| N7 | No MEENT paths in execution | MEENT fallbacks and defaults in the execution and implementation paths | N2 | M | 2 |
| N8 | Domain optimizers leave the core registry | The 2D deflector's FLRL methods are built into the core | N2 | M | 3 |
| N9 | Design constraints and per-variable values (M5, part 1) | Non-linear design constraints have no checkable form; one value list for all variables | G1, decision 20 | L | 4 |
| N10 | Outcome constraints (M5, part 2) | A constraint on a measured outcome has no form at all | N9 | M | 5 |
| N11 | Access and cost model per problem | Every problem is treated as a black-box oracle and methods are counted by evaluations; a threaded solver cannot be compared with single-thread runs | N2, decisions 22, 23 | M | 3 |
| N12 | Problem-owned candidates | Assignments, several orders, sequences of variable length, graphs and scheduling constraints have no form | N9, decision 24 | M | 5 |
| N13 | Bounds and optimality | A proven optimum or a dual bound cannot be recorded; nothing exact is available as a baseline | A3, N11 | M | 4 |
| N14 | Size ladders | Instance size is not an axis of the comparison | N5, N11 | M | 4 |
| N15 | Algorithm families in proposals and prompts | Agents are asked to pick a search method; nobody classifies the problem or looks up known algorithms | — | S–M | 1 |

---

## Parts

### N1 — The domain-names ratchet

**Depends on:** nothing. **Size:** S.

**Read first:** `tests/balsamic/test_layering.py`, `tests/test_harness_contract.py` (the word ratchet as a model).

**Change**
1. A test in `tests/balsamic/test_layering.py`: the files of `src/optimization_framework` whose code names a domain (the
   words `meent`, `rcwa`, `grating`, `flrl`, `deflector`, case-insensitive, not counting `GRATING_*` environment
   variable names) are listed in an allowlist in the test. The test fails when a file not on the list names one, and
   when a listed file no longer does (so the list only shrinks: remove it from the list in the same PR).
2. Generate the allowlist from the code at the commit; do not hand-pick it.

**Tests** the test itself, on a fixture tree with a new domain name and with a cleaned file.

**Done when** the test passes on the current code and the invariant row "the core names no domain" is `code` (with its
allowlist as the known gap).

### N2 — The pack manifest and its loader

**Depends on:** decision 17. **Size:** M.

**Read first:** `contracts/problems.py` (`ProblemDefinition` L85–97, `ProblemAdapter` L165), `evaluation/registry.py`,
`src/dqn_meent/problem.py`, `src/dqn_meent/problem_2d.py`, `src/optimization_benchmarks/problems.py`, the entry points in
the root `pyproject.toml` L44–50.

**Change**
1. `contracts/packs.py` `ProblemPack`: `problem_ids`, `tools` (agent tools and command operations it registers),
   `procedures` (a folder of `SKILL.md` procedures), `estimators` (dotted paths: memory, time), `racing` (the fidelity
   ladder, its limit, a cost model, preferred methods), `presentation` (labels and defaults beside
   `ProblemDefinition.renderer`), `references` (material to mount into coding workspaces), `legacy` (hooks for old
   records, N7).
2. An adapter may define `pack() -> ProblemPack` (decision 17). `evaluation/registry.py` collects the packs of installed
   problems (and picks up new ones with E1's reload); `workspace.packs.for_campaign(campaign_id)` gives the packs of the
   campaign's current tasks.
3. `src/dqn_meent/pack/` holds MEENT's pack; it starts empty and N3–N8 fill it. `optimization_benchmarks` declares none.

**Tests**
- A fake problem with a pack is listed; a campaign on it gets that pack and a campaign on another problem gets none.
- A pack's manifest that names a missing module or folder is refused at load with the problem id.

**Done when** the tests pass.

### N3 — Pack procedures and presentation

**Depends on:** N2. **Size:** S.

**Read first:** `src/balsamic/procedures/__init__.py` (`Procedures` L40–60, `register()` L95), `agents/turn_state.py`
`build()` L111, `campaigns/experiment_rules.py` `default_presentation()` L90–107.

**Change**
1. `meent-problem-setup` and `rcwa-convergence-check` move to `src/dqn_meent/pack/procedures/`. Their status stays draft
   until Hoseung reviews them.
2. The role catalogs in the static instructions stay generic (they are cached per role). The state block lists the
   procedures of the campaign's packs, and `procedure_read` serves them for that campaign only.
3. `default_presentation()` takes labels from the pack (`silicon`, `air` for MEENT) instead of the id prefix.

**Tests**
- A MEENT campaign's state block lists the two procedures and `procedure_read` serves them; a `bounded_continuous`
  campaign lists neither and is refused them.
- The labels come from the pack; a problem without one gets none.
- The prompt ratchet passes (the role catalogs shrink).

**Done when** the tests pass.

### N4 — Pack tools

**Depends on:** N2. **Size:** S–M.

**Read first:** `agents/tools.py` (`PiTools.names()` L446–480, the `mask_create` handler L989, `ROLE_OPERATIONS` L33–40,
`register_tool` and `EXTRA_TOOLS`), `agents/diagnostics.py` (`FixedMaskInput`, `reserve()`), `campaigns/commands.py`
L338–340, `campaigns/compute_consent.py` (`SAME`, `WORDS`), `evaluation/registered_recipes.py` (`reevaluate:v1`,
`fidelity_comparison:v1`).

**Today** `mask_create` is in every agent's base tool set, and `fixed_mask.run` (evaluate saved masks at several
fidelities) is one of the experiment operator's operations, for any problem. The generic recipes `reevaluate:v1` and
`fidelity_comparison:v1` already do the problem-agnostic part.

**Change**
1. `mask_create` and `fixed_mask.run` move into MEENT's pack and are registered by it (`register_tool`,
   `commands.register`). They are offered only to agents of campaigns whose pack declares them; `ROLE_OPERATIONS` gains
   them per campaign.
2. Their records (`fixed_mask_job`, `fixed_mask_report`) keep their kinds, so history reads as before.
3. For other problems the operator's procedure names the generic recipes (`validation.run` with `reevaluate:v1` or
   `fidelity_comparison:v1`).

**Tests**
- A MEENT campaign's operator has both; a `bounded_continuous` campaign's agents have neither.
- Old `fixed_mask_job` records still render.

**Done when** the tests pass and N1's allowlist shrinks.

### N5 — Pack estimators and fidelity ladders

**Depends on:** N2. **Size:** M.

**Read first:** `execution/rcwa_memory.py`, `execution/observability.py` L440–495, `execution/racing.py` (`PREFERRED` L25,
`FINAL_VALIDATION_LIMIT` L26, the cost model L37–54, L162, the default ladder L737–747), `docs/adaptive-algorithm-testing.md`.

**Change**
1. `rcwa_memory.py` moves to `src/dqn_meent/pack/memory.py`. `observability.py` asks the campaign's pack for its memory
   estimate and for the fidelities to check; with no estimator it reports measured peaks only.
2. The race takes its fidelity ladder, its limit, its cost model and its preferred methods from the pack's `racing`
   section. A problem without one races at its declared fidelity, with cost measured on the problem's cost axis (N11;
   evaluations until N11 lands).
3. The MEENT values are unchanged (the same ladder and limits), so MEENT races behave as before.

**Tests**
- The MEENT race and memory forecasts give the same results as before (fixtures from the current code).
- A `bounded_continuous` race runs with no ladder.

**Done when** the tests pass and N1's allowlist shrinks.

### N6 — Pack references for coding workspaces

**Depends on:** N2 (F4 has removed the references from the generic brief). **Size:** S.

**Read first:** `agents/development_runtime.py` `prepare()` L119–175 (the FLRL copy L158–168, `GRATING_FLRL_REFERENCE`).

**Change**
1. The pack names its reference material (for MEENT, the FLRL repository, still taken from `GRATING_FLRL_REFERENCE` when
   set). `prepare()` mounts the references of the campaign's packs, read-only, and the brief mentions them only then.
2. A workspace of a campaign whose problem has no pack gets no references.

**Tests** a MEENT workspace gets `references/flrl`; a `bounded_continuous` workspace gets none, and its brief names none.

**Done when** the tests pass and N1's allowlist shrinks.

### N7 — No MEENT paths in execution

**Depends on:** N2. **Size:** M.

**Read first:** `execution/service.py` L640–660, L935–960, L1320–1365, `execution/runtime_profile.py` L205–215,
`execution/source.py` L110–125, `evaluation/legacy_confirmation.py` L170–180, `implementations/models.py` L56,
`implementations/bridge.py` L150–170, `tests/balsamic/test_layering.py` (`REMOVED` lists `dqn_meent.workspace`).

**Today** a trial or task without a stored `problem` falls back to `problems.resolve("meent_grating", trial["physics"])`;
trials of the old execution contract start `dqn_meent.workspace.worker` (a module the layering test lists as removed) and
check a MEENT source hash; an implementation spec without a problem id defaults to `meent_grating`.

**Change**
1. A one-time migration gives every stored task and trial without `problem` its resolved problem (for MEENT records,
   through the pack's `legacy` hook), so the fallbacks can go. Refuse, with the record id, what cannot be resolved.
2. Remove the three `meent_grating` fallbacks and the one in `runtime_profile.py`; `problem_id` becomes required in
   implementation specs (old records keep theirs).
3. Old-contract trials are read-only history: continuing one is refused with a clear message, instead of starting a
   removed worker. The MEENT source hash and the MEENT version in `execution/source.py` move to the pack's `legacy` and
   provenance hooks.

**Tests**
- The migration resolves fixture records of both kinds and is idempotent.
- A trial with no problem after the migration is refused, naming it.
- Continuing an old-contract trial is refused with the message; reading it works.

**Done when** the tests pass, a copy of the live store migrates cleanly (Hoseung runs it on a copy), and N1's allowlist
shrinks.

### N8 — Domain optimizers leave the core registry

**Depends on:** N2. **Size:** M.

**Read first:** `optimizers/registry.py` (`BUILTINS` L13–34, the completion units at L70, `create()` L196–215),
`optimizers/fourier_specs.py` (its methods name the 2D deflector's problem id), `src/dqn_meent/flrl_optimizers.py`,
`src/dqn_meent/mask_library_adapter.py` (an optimizer plug-in already), `optimizers/plugins.py`.

**Change**
1. The FLRL Fourier methods (`fourier_specs.py` and the `dqn_meent.flrl_optimizers` import in `create()`) move into a
   `dqn_meent` optimizer plug-in, as the mask library already is, which declares their parameters and completion units.
   Their ids do not change, so stored runs and proposals still name them.
2. The core keeps its problem-agnostic built-ins (`random`, `coordinate`, `replay`, `evaluate_asset`, the binary searches
   and the DQN, which work on any binary problem).

**Tests**
- Every method id listed before the move is still listed, with the same parameters, when `dqn_meent` is installed.
- The core's registry imports nothing from `dqn_meent`.
- A stored FLRL run continues as before.

**Done when** the tests pass and N1's allowlist shrinks.

### N9 — Design constraints and per-variable values (M5, part 1)

**Depends on:** G1 and decision 20. **Size:** L.

**Read first:** `docs/problem-setup.md` L355–393 (the mixed-values limit and "Next step: problem-agnostic constraints"),
`contracts/problem_charter.py` (`Constraint`, `DecisionVariable` L78–89), `contracts/problems.py` `CandidateSchema` L42–75,
`problem_charter/charter.py` (`findings()`, `manifest()` L1021–1078, `compile_setups()` L998–1018),
`problem_charter/expressions.py` (`evaluate()` L111), `optimizers/lifecycle.py`, `problem_import/guideline.md`,
`frontend/src/note/CharterPanel.tsx`.

**Today** the framework checks two constraint forms: a true/false test on quantities and a linear condition on the
decision variables. Anything else lives in the evaluator or stays words. `CandidateSchema.values` is one list for all
variables, so a whole-number fin count beside continuous variables has to be written as a continuous variable that the
evaluator rounds.

**Change**
1. A `design` constraint form: an expression over the candidate's variables, in the charter's expression language,
   extended with vector functions (`sum`, `min`, `max`, `count`, and a variable's value by name). It is carried in the
   manifest, checked by `canonicalize`, and offered to the optimizers' admission (a built-in method resamples an
   infeasible candidate; a library method gets the check as a function).
2. Per-variable value lists in the candidate schema; the `evaluator.mixed_values` finding's workaround retires.
3. Findings check that a design expression names only decision variables and evaluates on a valid candidate; the Charter
   page shows the form; the formulator's guideline says when to use it.

**Tests**
- A minimum-feature-width rule and a ratio rule as design constraints refuse violating candidates and accept others.
- A schema with a whole-number and a continuous variable canonicalizes each by its own values.
- `random` proposes only feasible candidates.

**Done when** the tests pass and `docs/problem-setup.md` moves M5 to "in progress" (or done after N10).

### N10 — Outcome constraints (M5, part 2)

**Depends on:** N9. **Size:** M.

**Read first:** the same as N9, plus `analysis/general.py`, `src/balsamic/evolution/ledger.py`, `execution/worker.py`
`progress()`.

**Change**
1. An `outcome` constraint form: a condition on metrics the evaluator reports (a floor on a second metric, a cap on a
   measured cost). It is stored in the charter, carried in the manifest, and checked on each observation.
2. An observation that violates it is marked infeasible: it is kept, but it never counts as a run's best, and the
   comparison and the ledger rank feasible results only (and say how many were infeasible).
3. The qualitative form shrinks to policy rules no code can judge.

**Tests**
- A run whose best raw score violates an outcome constraint reports the best feasible one.
- The comparison ranks feasible results and counts the infeasible ones.

**Done when** the tests pass and `docs/problem-setup.md` records M5 as done.

### N11 — Access and cost model per problem

**Depends on:** N2, decisions 22 and 23. **Size:** M.

**Read first:** `contracts/problems.py` (`ProblemDefinition` L85–97, its `resources` L94; `descriptor()` L119–124),
`contracts/problem_charter.py` `EvaluatorBinding` L133, `contracts/evaluators.py` (`EvaluatorManifest`),
`problem_charter/charter.py` `manifest()` L1021–1078, `execution/worker.py` (`costs.jsonl` rows L431–437, `run()`),
`analysis/general.py` (`AXES` L10, the default axis L63), `analysis/comparison.py` (`_condition()` L51–62, the family key
L328), `execution/racing.py` (the cost model L37–54), `optimizers/functions.py` (D1), `problem_charter/scaffold.py` (F1, F3),
`frontend/src/experiments/ExperimentsPage.tsx` L72.

**Today** every problem is treated as a black-box oracle. A method sees the schema, the objective's name and direction, and
(after D3) the instance's data, but not the objective's code. Evaluations are a budget unit everywhere a budget is set:
the worker's step budget, F1's `max_evaluations`, N5's "cost measured by evaluations", and the experiment chart's x axis.
The general report already ranks on `worker_seconds`, and that clock includes the method's own compute (the cost row
charges the time since the previous one). `worker_threads` is part of the comparison's condition, so a run on 8 threads is
never compared with single-thread runs.

**Change**
1. `ProblemDefinition` and `EvaluatorBinding` gain `access: Literal["white_box", "oracle"] = "white_box"` (decision 22) and
   `cost_axis: Literal["worker_seconds", "core_seconds", "evaluations", "solver_calls"] | None` (None: the default of
   decision 23). A pack may set both (N2's manifest gains a `cost` section); MEENT's pack declares `oracle` with today's
   axes, so MEENT campaigns behave as before. `manifest()` carries both, so they are part of the manifest's digest: tasks
   compiled before this part are read as `oracle` (they were built under that rule), new ones as declared.
2. **White-box problems.** The method gets the objective: in D1's `problem` object as `problem.objective(candidate)`, and in
   the generated library (F3) through `objective.py`. Calls it makes itself are not observations and are not counted;
   `evaluate` is still how a candidate is recorded and how the run's best is known. The budget is time: the worker stops
   on its wall budget, and the step budget becomes a safety cap (the frozen experiment keeps it, set high).
3. **Oracle problems.** As today: the objective is reached only through `evaluate`, and the coding brief (F4, H4) says a
   method must not compute it another way. Evaluations or solver calls may be the declared axis.
4. **`core_seconds`.** A method declares `threads` in its descriptor (default 1; capped by the problem's `resources`). The
   worker records `core_seconds = threads × wall seconds` on each cost row. On `core_seconds`, `worker_threads` leaves the
   comparison's condition key, so a threaded solver is compared with single-thread runs at equal core time. On every other
   axis it stays in the key, as today.
5. The report, the race and N5's ladder take the problem's axis instead of a fixed one; N5's "cost measured by evaluations"
   becomes "by the problem's cost axis".
6. UI: the experiment chart's x axis follows the problem's axis (time on white-box problems), with a switch to evaluations;
   the Charter page shows the access and the cost axis, editable before confirmation.
7. The formulator's guideline (`problem_import/guideline.md`) says when to declare `oracle`: the evaluator is expensive (a
   simulator, a measurement), or the researcher wants a black-box comparison. Otherwise leave the default.

**Tests**
- A white-box function method that computes the objective 10,000 times and calls `evaluate` once is ranked by its wall time
  and reports one observation; on an oracle problem the same method's objective is not in `problem`.
- A two-thread run is compared with a one-thread run on `core_seconds`, and kept apart on `worker_seconds`.
- A task compiled before this part keeps its digest and reads as `oracle`; MEENT's report and race give the same results
  as before (fixtures from the current code).
- The experiment chart uses time on a white-box task (Playwright).

**Done when** the tests pass and `docs/optimizer-plugins.md` documents access, the cost axes and `threads`.

### N12 — Problem-owned candidates

**Depends on:** N9 (its admission path), decision 24. **Size:** M.

**Read first:** `contracts/problems.py` `CandidateSchema` L42–75, `problem_charter/charter.py` (`evaluator_findings()`'s
one-representation rule L730–733, `manifest()`), N9 (the design constraint's admission), `optimizers/registry.py`
(`capability_reason()`), `optimizers/functions.py` (D1), `problem_charter/scaffold.py` (F1).

**Today** a candidate is a flat vector (binary, discrete, continuous, and a permutation after C1), and a charter's variables
share one representation. An assignment with an order per machine, several orders, a sequence of variable length, a set,
a tree or a graph has no form; nor do scheduling constraints such as precedence, no-overlap or cumulative resources,
beyond what N9's expressions can say.

**Change**
1. A representation `structured`: the candidate is a JSON value. The problem (its library or pack) provides
   `canonicalize(candidate) -> value` and `is_valid(candidate) -> list[str]` (the broken rules), and an optional
   `describe(candidate) -> str` for pages. The core stores and hashes the canonical value and checks nothing else.
2. A charter may declare one `structured` variable with a `meaning` and a `layout` (prose, required) and no bounds or
   values. Its rules are constraints of form `evaluator` (the library checks them) or N9 `design` expressions over the
   fields the library names.
3. Built-in methods refuse `structured` (`capability_reason()`: "the problem's library owns this representation; use a
   library method"). Library and function methods declare it, and receive the problem's `canonicalize` and `is_valid`
   (as `problem.is_valid`, D1).
4. F1 generates `problem.py` with `canonicalize` and `is_valid` stubs for the agent to fill, and tests that a valid example
   (from the charter's `references`, or one the agent writes) passes them.
5. A named type is added to the core only when two problems need it (decision 24, the rule of two in
   `docs/optimizer-plugins.md`); until then, a problem that needs one uses `structured`.

**Tests**
- A parallel-machine scheduling fixture (an order per machine) canonicalizes, refuses an assignment that drops a job, and
  runs a function method to completion.
- Built-in `random` is refused on it with the reason above.
- A charter with a `structured` variable compiles to a manifest, and its digest covers `meaning` and `layout`.

**Done when** the tests pass.

### N13 — Bounds and optimality

**Depends on:** A3 (the bound in the final inspection), N11. **Size:** M.

**Read first:** `optimizers/finish.py` (A3), `execution/worker.py` `progress()` L440–466, `analysis/general.py`,
`analysis/comparison.py`, `src/balsamic/evolution/ledger.py`, `src/balsamic/evolution/stages.py`,
`contracts/problem_charter.py` (`ReferenceResult`), `optimizers/registry.py` (`BUILTINS`), `optimizers/conformance.py`,
the claims of Phase 7 (K1, K2) and V3 (Phase 5).

**Today** a run's result is its best value so far. An exact method's proof of optimality, or a dual bound from branch and
bound or a MILP or CP solver, has nowhere to go, so the ledger cannot tell a proven optimum from a value found, and it
cannot show a gap. Nothing exact is available as a baseline, not even enumeration on a small instance.

**Change**
1. A method may report `bound` (a value no feasible candidate can beat, in the objective's direction) and
   `proved_optimal: bool`, in `inspect()` at any time and in its final inspection when it finishes (A3). The worker copies
   the latest to `progress` as `best_bound` and `proved_optimal`.
2. The ledger, the comparison and the Evolution table show, per task, the best value, the best bound over all runs, and
   the gap between them (absolute and relative to the bound). A run with `proved_optimal` is marked; the stages treat a
   finished, deterministic, proved-optimal run as fully assessed for that task (no extension).
3. A bound is a claim. It is **checked** when either holds: a built-in `enumerate` run on the same task gives the same
   optimum, or a charter reference result says so. Otherwise it is shown as "claimed by <method>", and V3's finalist gate
   treats a claim of optimality like any other unchecked score. Phase 7's K track resolves these claims to their receipts.
4. Built-in `enumerate`: every candidate of a binary, discrete or permutation problem, in a fixed order, up to a size cap
   (parameter `max_candidates`, default 10⁶, refused above it with the count). It finishes with `proved_optimal` and the
   value as its bound. On white-box problems it enumerates through `problem.objective` and records the optimum with one
   `evaluate`.
5. Conformance: a method that reports a bound must report one that its own best does not beat (`check()` runs this on its
   steps).

**Tests**
- `enumerate` on the 8-job tardiness instance finishes with the optimum C2's test expects, and is refused on 2⁴⁰ candidates.
- A method that reports `proved_optimal` on a value `enumerate` beats is shown as an unchecked claim, not as proved.
- The ledger shows the gap; a task with a checked optimum ranks the methods that reached it first by their cost.

**Done when** the tests pass.

### N14 — Size ladders

**Depends on:** N5 (the pack's `racing` section), N11. **Size:** M.

**Read first:** `contracts/problem_charter.py` (`Instance`), `problem_charter/charter.py` `compile_setups()` L998–1018,
`execution/racing.py` (the ladder L737–747, after N5 the pack's), `analysis/comparison.py`, `analysis/general.py`.

**Today** a comparison is per task. Exact methods win on small instances and run out of time on large ones, and the
crossover is often the finding; nothing reports it. The only ladder is MEENT's fidelity ladder, moving to its pack in N5.

**Change**
1. Charter instances may name a `size` (a quantity whose value grows across them, such as the number of jobs). A pack's
   `racing` section may declare a size ladder instead of, or beside, a fidelity ladder.
2. The comparison groups tasks by size and reports, per pair of methods, the largest size at which each finished within
   its budget and the size where one overtakes the other (the crossover), from the observed runs only.
3. For a finished deterministic method, "Extend" on the Evolution page proposes the next size, not more budget.
4. The race may climb the size ladder as it climbs a fidelity ladder: the methods still in it run on the next size.

**Tests**
- Three sizes, a fixture exact method that finishes on the first two and times out on the third, and a heuristic: the
  comparison names the crossover and the exact method's largest finished size.
- "Extend" on a finished deterministic run proposes the next size.
- A problem with no ladder compares per task, as before.

**Done when** the tests pass.

### N15 — Algorithm families in proposals and prompts

**Depends on:** nothing. **Size:** S–M.

**Read first:** `src/balsamic/procedures/proposal-fields/SKILL.md`, `src/balsamic/procedures/problem-formulation/SKILL.md`,
`src/balsamic/evolution/generate.py` (`PROMPTS`), `agents/roles/methodology_specialist.md`,
`agents/roles/literature_specialist.md`, `contracts/requests.py` L242 (`algorithm = "hillclimb"`),
`problem_import/guideline.md`, `tests/test_harness_contract.py` (the word ratchet).

**Today** the methodology specialist judges "which installed search methods fit", the `algorithm` field is "the installed
search procedure", and hillclimb is recorded when nothing is chosen. `diversify` asks only for "a different mechanism". No
step asks for the problem's class, its complexity or the algorithms known for it.

**Change**
1. Proposals gain `family`: `exact` (DP, enumeration, branch and bound), `solver` (MILP, CP, SAT, through a library),
   `constructive` (greedy and problem-specific rules), `local_search` (metaheuristics), `learning`, `hybrid`. The
   Hypotheses card and the lineage graph show it; the lead sets it in `hypothesis.create`.
2. `diversify` asks for strategies of different families where the problem allows, including an exact or problem-specific
   method when the instance sizes make one plausible, and says why a family is left out.
3. The formulation procedure gains a **known results** step: the problem's class in its field's notation where there is
   one (for example 1||ΣT_j), its complexity, and the algorithms known for it, with sources (the literature specialist
   looks them up). They go into the note's open questions or the charter's references.
4. The methodology specialist judges complexity and scale (how each candidate method grows with the instance), not only the
   representation. The `algorithm` field reads "the installed method"; with nothing chosen it is recorded as `unchosen`,
   and the page asks for a choice instead of recording hillclimb.
5. The added text is paid for under the word ratchet by removing as much elsewhere (§0 rule 8).

**Tests**
- `hypothesis.create` stores `family`, and the card renders it.
- The `diversify` prompt names the families; a proposal without `algorithm` is `unchosen`.
- The prompt ratchet passes.

**Done when** the tests pass; J1's scenario S17 measures the effect.

---

## Order and shared files

```
Wave 1  N1 · N2 · N15
Wave 2  N3 · N4 · N5 · N6 · N7 (each after N2)
Wave 3  N8 · N11 (after N2)
Wave 4  N9 (after G1 and decision 20) · N13 (after A3, N11) · N14 (after N5, N11)
Wave 5  N10 · N12 (after N9)
```

| File | Parts |
|---|---|
| `tests/balsamic/test_layering.py` | N1, and every part that shrinks the allowlist |
| `agents/tools.py` | N4 (and B6, B7, R2, R6, V4) |
| `execution/service.py` | N7 (and D2, E4) |
| `optimizers/registry.py` | N8 (and C1, C2) |
| `problem_charter/charter.py`, `contracts/problems.py` | N9, N10, N11, N12, N14 (and C1, D3, E3) |
| `analysis/comparison.py`, `analysis/general.py`, `src/balsamic/evolution/ledger.py` | N11, N13, N14 (and A2, A3) |
| `execution/racing.py` | N5, N11, N14 |
| `src/balsamic/procedures/`, `agents/roles/` | N3, N15 (and B7, T1, T3) |
| `agents/development_runtime.py` | N6 (and F4, H2, H4, H5) |

## Risks

- **Old records:** removing fallbacks (N7) can strand records that never stored a problem. The migration runs first, on
  a copy of the live store, and refuses by id what it cannot resolve.
- **Unchanged MEENT behaviour:** N5 and N8 move code without changing values or ids; fixtures from the current code pin
  that.
- **Per-campaign tool sets** (N4) change what an agent sees between campaigns; the static instructions stay per role, and
  the state block says what the campaign's pack adds.
- **M5 is large** (N9): it touches the charter, the schema, the optimizers' admission and the UI. Hoseung's 21 October
  decision puts it after the end-to-end check (G1).
- **White box by default** (N11, decision 22): a method on a white-box problem can compute the objective as often as it
  likes. That is intended, and the comparison is on time. A problem whose evaluator must stay a black box (MEENT) declares
  `oracle`; the risk is a new expensive problem that forgets to, so the formulator's guideline and the Charter page name
  the choice.
- **Claims of optimality** (N13) are shown as claims until enumeration or a reference result checks them.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, Playwright when the Charter page changes (N9).
- N1's allowlist after the phase: only the files Hoseung agrees stay (ideally none).
- J2 on `deflector_2d` and `quadratic` before and after the phase: no regression.
- J1's S17 (a problem with a known exact algorithm) before and after N15, and after N11 and N13: the exact method is
  proposed and ranked first.
