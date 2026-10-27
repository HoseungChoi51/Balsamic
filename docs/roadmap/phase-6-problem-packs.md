# Phase 6 — Problem packs: domain knowledge out of the core

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §08 C ("problem packs: flexibility as data"), §05 ("domain knowledge out of the core"), §01 finding 4; `docs/problem-setup.md` "Next step: problem-agnostic constraints" (M5) |
| Decisions it needs | 17; 20 for N9 and N10 |
| Start after | N1 at any time (it only freezes today's list). N2–N8 in any order after N2. N9 and N10 after G1 and decision 20 |
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
   section. A problem without one races at its declared fidelity, with cost measured by evaluations.
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

---

## Order and shared files

```
Wave 1  N1 · N2
Wave 2  N3 · N4 · N5 · N6 · N7 (each after N2)
Wave 3  N8
Wave 4  N9 (after G1 and decision 20)
Wave 5  N10
```

| File | Parts |
|---|---|
| `tests/balsamic/test_layering.py` | N1, and every part that shrinks the allowlist |
| `agents/tools.py` | N4 (and B6, B7, R2, R6, V4) |
| `execution/service.py` | N7 (and D2, E4) |
| `optimizers/registry.py` | N8 (and C1, C2) |
| `problem_charter/charter.py`, `contracts/problems.py` | N9, N10 (and C1, D3, E3) |
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

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, Playwright when the Charter page changes (N9).
- N1's allowlist after the phase: only the files Hoseung agrees stay (ideally none).
- J2 on `deflector_2d` and `quadratic` before and after the phase: no regression.
