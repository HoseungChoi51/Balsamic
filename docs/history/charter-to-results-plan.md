# Plan: after the charter, no harder than a script and a local coding agent

> **Superseded** (2026-10-27). Phase 1 of the roadmap splits this plan into parts checked against the code: see
> [roadmap/phase-1-charter-to-results.md](../roadmap/phase-1-charter-to-results.md) and the [roadmap](../roadmap/README.md).
> This document is kept for its reasoning and history.

| Item | Detail |
|---|---|
| Target | `kc-ml2/balsamic`, branch `workspace-rebuild` |
| Date | 2026-10-27 |
| Status | Plan, not started. Decisions 1–3 are the researcher's. Phase 1 fixes a live bug (baking order's install waits for a needless confirmation). |

## Context

The researcher's bar: for Balsamic to justify itself, the steps after the problem charter must be not much harder than
exporting the charter into a Python script and working there with a local coding agent: write the objective, write a few
algorithm functions, run them, compare. Balsamic should add recording, comparison and provenance, not ceremony.

Baking order (choose the order of 8 bakes to minimize total tardiness) shows how far off that is. Two and a half hours after
the charter was confirmed there are 0 runs. On the way the researcher had to give:
- 5 approvals: 2 raises of the implementation allocation, 3 compute go-aheads; one waited 61 min;
- 5 prompts to keep the work moving.

Along the way:
- 2 agent submissions were refused for extra fields;
- 2 evaluator builds ran, and the first ran out of allocation;
- the lead asked the researcher to run `docker cp` and `uv pip install`;
- Balsamic's automatic install waits for a confirmation it does not need.

The causes found in the code:
- **The evaluator:** a declared evaluator must be built and validated separately in the implementation service. A library's
  evaluator can't serve the task, and an installed problem with the charter's id is refused.
- **Problem plug-ins:** they are discovered only at start-up.
- **The algorithm contract:** it is heavy (propose, observe, checkpoint, restore, inspect, export).
  - A method that finishes counts as a failed run (`worker.py:582`).
  - Methods never see the problem's data, so the agent hard-coded it.
  - There is no permutation type, so built-in random draws invalid orders and fails.
- **The review gate:** it blocks runs of proposals the researcher asked for.
- **Ranking:** the evolution ledger ranks the highest raw score as best even when minimizing (`ledger.py:91`).
- **Charter export:** none exists.

## Decisions (the researcher's, 2026-10-27)

1. **Where the evaluator comes from:** from the library. The coding agent writes the scoring function into the same library
   as the algorithms. Balsamic generates the boilerplate and tests from the charter, and once the library is installed the
   task uses it like any installed problem. No separate evaluator commissioning on the default path.
2. **Concept review:** it does not gate runs of proposals the researcher asked for or approved. Review happens on request and
   is shown when done; proposals agents create on their own still need it.
3. **Approvals:** one go-ahead per request, covering the coding workspace, the evaluator and the runs, with their minutes.
   Implementation compute counts against it, with no separate allocation to raise. The go-ahead threshold still holds; work
   beyond what was approved asks again.

## Target flow for baking order

1. The researcher confirms the charter, asks for 4 algorithms, and the lead records them.
2. "Implement and compare" leads to one go-ahead.
3. The coding workspace starts from a library generated from the charter. The agent fills the objective and four plain
   functions, its tests pass, and it delivers.
4. Balsamic installs the library, the task adopts its problem, and each proposal is bound to its method.
5. The approved runs start by themselves, and the comparison ranks them correctly.

The researcher acts three times: confirm, ask, approve.

## Phase 1 (urgent): the false "needs confirmation" on install

- `agents/library_install.py` `changed_packages()`: parse `name==version [(from url)]` and `name @ url`. A package removed and
  added at the same version or the same url is a reinstall, not a change. Never count the lab's own projects: the root
  `pyproject` name and the editable libraries under `libraries/`.
- `DevelopmentWorkspaces.install_delivered`: also retry once when the latest record is Balsamic's own, its status is
  `needs_confirmation`, and re-parsing its `log_tail` now finds no change (`request_key="automatic:reparsed"`, record
  `retry_of`).
- Tests (`tests/test_library_install.py`):
  - the exact uv lines give no change;
  - a numpy upgrade still waits;
  - a stale record is retried exactly once.
- Then check that the live `baking-order` install completes.

## Phase 2: correct ranking, and a method that finishes

- **Ranking:** `src/balsamic/evolution/ledger.py` takes the direction from the run's objective and picks the best with
  `Objective.better`; rows carry the direction. The same fix applies to `api/evolution.py` `best_so_far`,
  `panels/service.py`, and the sort in `EvolutionPage.tsx`.
- **Comparison report:** `analysis/general.py` ranks by direction and adds `rank`. Finished runs are left out when choosing
  the matching cost, since they hold their final value afterwards.
- **A method that finishes:** new `optimizers/finish.py` `MethodFinished`. `worker.run` treats it as `completed` /
  `method_finished`: final checkpoint and outputs kept, resumable. `PackagedOptimizer.propose` raises it when the module
  raises `StopIteration` or returns `[]`.
- Tests: minimize ranking in the ledger and the report, and a finished run's result.

## Phase 3: one go-ahead per request, fewer refusals

1. **Review not required:**
   - A hypothesis the lead records in a turn answering a researcher message gets `requested_by`.
   - Approving a compute plan sets `approved_by` on the hypotheses it names.
   - `campaigns/proposals.py` readiness returns `not_required` when either is set; this covers `trial.create` and draft launch.
2. **One consent per plan:**
   - The compute `approval.request` names `hypothesis_ids` and `runs`; the consent records `workspace_ids` and `launched`.
   - `implementations/bridge.py` no longer requires `implementation_compute_budget_seconds`: commissions are checked and
     charged against the consent. A positive value stays as the researcher's optional ceiling; 0 means none.
   - An agent asking to raise that limit is told to ask for a compute go-ahead instead.
   - A consent stays in force while a workspace it opened is live.
3. **Automatic binding:** after an install, each `report.methods[]` with a `hypothesis_id` is bound (`builtin.bind`,
   `actor="balsamic"`) on the first compatible current task. Proposals the researcher bound are skipped. The record lists
   `bindings`, and review hashes use the configuration from before the binding.
4. **Approved runs start themselves:** new `campaigns/plan_runs.py`, run on each sync. Each planned run whose proposal is
   now runnable is created once per seed under that consent, exactly the approved runs and no more. When all have finished,
   the lead is woken to write the comparison (`comparison.report`).
5. **Unknown fields are reported, not refused:**
   - Manifest: `snapshot` drops unknown keys and returns `ignored_fields` to the coding agent. With no manifest, the
     commit's one `libraries/<name>/` is used.
   - Commands: `commands.execute` strips unknown top-level keys into the receipt's `ignored_fields`, but refuses a near-miss
     with "did you mean wall_seconds?".
6. **Instructions:**
   - `INSTRUCTIONS` gains one line: "implement and compare" covers building, running and comparing under one compute
     request listing the workspace, any evaluator and the runs; never ask the researcher to run commands.
   - The implementation-supervision procedure drops binding and allocation.
   - Stay within the prompt-size limits in `tests/test_harness_contract.py`.

## Phase 4: permutations

- **The type:**
  - `CandidateSchema` gets `representation="permutation"` (each value exactly once; `canonicalize` checks it).
  - The same goes into `contracts/capabilities.py`, the charter's `DecisionVariable`, `charter.manifest`, the
    representation picker in `CharterPanel`, and the formulation guidance ("an order is a permutation").
- **Built-in methods:**
  - `random` draws `rng.permutation(values)`, and `replay` and `evaluate_asset` accept permutations.
  - New built-in `swap_search`: swap and insert moves, first improvement, with restarts.
- Tests: built-ins propose only valid orders, and a permutation charter gives the right manifest.

## Phase 5: methods as plain functions

- **The contract:** a library method is `def name(problem, evaluate, rng)`.
  - `evaluate(candidate) -> float` returns the primary objective, and raises `StopSearch` once a cap is reached.
  - Returning ends the method.
  - `rng` is a seeded numpy Generator, and `random`/`np.random` are seeded too.
- **`optimizers/functions.py` `FunctionMethod`:**
  - `solve` runs in a thread, connected to `propose`/`observe` through queues.
  - When it returns, the run ends as `MethodFinished`; the wall-time and evaluation caps still apply.
  - A checkpoint is `{seed, log of (candidate hash, status, score)}`. `restore` replays the logged scores and checks the
    hashes, refusing a method that is not deterministic for its seed.
- **`FunctionPlugin`:** reads the `METHODS = {id: {name, description, hypothesis_id}}` literal from `methods.py` with `ast`
  and imports the module only in the worker.
- **Data:**
  - Functions see the full problem (the library's own `Problem` with the charter's data).
  - For declared problems, `manifest()` makes every configuration field public; new tasks only.
- **Workers:** start with `PYTHONHASHSEED=0`.
- **Conformance:** `conformance.check_function` uses the library's real evaluator and checks valid candidates, the same
  sequence for the same seed, continuing from a checkpoint, and a clean finish.
- Tests: a one-shot method completes, the cap stops an endless one, pause and resume reproduce the journal, and a
  nondeterministic method is refused on resume.

## Phase 6: libraries that provide the problem

- **Pickup without restart:** `evaluation/registry.py` `ProblemRegistry` (from `discover()`) re-checks entry points at most
  once a second, updating the shared `problems` object in place. It reuses `pick_up_installs` and the module dropping in
  `optimizers/plugins.py`.
- **Installer:** accepts libraries with the `optimization_framework.problems` group and/or the optimizers group. It refuses
  ids another installed package owns, and records `problems_added`.
- **Charter:** when a declared `problem_id` is installed, `charter.py` (`evaluator_findings`, `:727`) compares the
  declaration's `manifest()` with the installed problem's resolved instance: candidate schema, objective name and
  direction, units, metric names.
  - If they match, the finding is informational and `compile_setups` emits an installed setup.
  - If not, a blocking finding lists the differences.
- **Migration:** a new task, never a rebinding.
  - After an install, `ExecutionService.adopt_library_problem` recompiles the tasks from the charter, which opens a new study.
  - The old task gets `superseded_by_task_id`; the new one gets `provided_by` (package, version, commit, submission, install)
    and an `evaluator_requirement_satisfaction` record.
  - Adoption is skipped, and the lead told, when the old task has a bound evaluator or live runs.
  - `campaign.adopt_problem` adopts explicitly, which is the path for baking order, whose old task already has an evaluator.

## Phase 7: a library generated from the charter, and an export

- **Generator:** `problem_charter/scaffold.py` `scaffold(charter, revision, name) -> {path: bytes}` produces
  `libraries/<problem-id>/`:
  - **Generated by Balsamic:**
    - `pyproject.toml` with both entry points;
    - `charter.json` (id, revision, hash);
    - `README.md`, which says how to use it outside Balsamic;
    - `data.py`: each instance's values, the schema and the objective;
    - `problem.py`: a typed `Problem`, `is_valid`;
    - `harness.py`: a standalone evaluation loop;
    - `compare.py`: `python -m <pkg>.compare` prints the ranked table without Balsamic;
    - `adapter.py`: the Balsamic problem adapter (id = the charter's `problem_id`) and the `FunctionPlugin`.
  - **For the agent to fill:**
    - `objective.py`: a stub whose docstring is the charter's objective definition, with the values filled in;
    - `methods.py`: `METHODS = {}`.
  - **Generated tests:**
    - `test_problem.py`: data matches the charter, dimensions, constraints, and a finite, deterministic objective; a charter
      reference number becomes a test to complete;
    - `test_methods.py`: valid candidates, determinism, caps;
    - `test_contract.py`: `check_function`, and the adapter matches the manifest.
- **In the workspace:**
  - `development_runtime.prepare` writes the scaffold into the coding workspace without overwriting existing files.
  - The workspace records the generated files' hashes, and an install shows any generated file the agent changed.
  - `DEVELOPMENT_INSTRUCTIONS` shrinks to: fill `objective.py`, write one function per proposal in `methods.py`, make
    `pytest libraries/<name>` pass, commit, `campaign_submit`, raise the version on every redelivery.
- **Export:** `GET /api/v1/problem-charters/{id}/revisions/{n}/export.zip` (`problem_charter/api.py`), and an "Export as
  Python project" button on the Charter tab (`CharterPanel.tsx`).

## Phase 8: end-to-end, baking order replayed

`tests/test_baking_order_e2e.py`:
1. A permutation charter with a declared evaluator.
2. Confirm it, create the campaign; a researcher turn records 4 proposals.
3. One compute plan is approved.
4. A fake coding agent fills the scaffold (objective; earliest-due-date, swap search, random restarts, exact enumeration),
   commits and submits.
5. A fake uv installs it.

Asserted:
- the problem is picked up and the task adopted;
- the proposals are bound, and the runs start under the same consent;
- the one-shot and exact methods end as `method_finished`;
- the report and ledger rank exact enumeration best;
- the researcher acted 3 times.

Playwright: `charter.spec.ts` (the export), `evolution.spec.ts` (minimize order), `implementations.spec.ts` (problem from a
library, automatic binding).

## Risks

- **Replay:** resuming costs the method's own compute again, and hidden nondeterminism only shows on resume. The hash check
  refuses it rather than resuming wrongly.
- **Agent code:** it runs in workers, as libraries already do. `ast` listing and lazy imports keep it out of the server, and
  the generated adapter imports only generated modules.
- **Migrating tasks:** adoption bumps the campaign version and opens a new study. Code that re-validates archived declared
  tasks through `TaskInput` must be checked.
- **Registry reload:** it must never drop the lab's own modules, and id clashes are refused at install.
- **The automatic launcher:** it starts exactly the approved runs, never more.
- **Lenient fields:** a near-miss is refused, so a misspelled field can't silently change a run.
- **Prompt size:** new lead lines need offsetting cuts.

## Verification

- **Per phase:**
  - unit tests as listed;
  - `uv run pytest -q` (the known flaky `tests/test_tracking.py` is run again alone);
  - `cd frontend && npx playwright test`;
  - `cd agent-harness && npm test`.
- **Live, after Phase 1:** baking order's pending install completes, and its four methods appear in Algorithms.
- **Live, after Phases 5–7:** a new small campaign goes from charter to ranked results with three researcher actions.

## Critical files

- `src/optimization_framework/agents/library_install.py`, `agents/development.py`, `agents/development_runtime.py`
- `src/optimization_framework/execution/worker.py`, `optimizers/packaged.py`, new `optimizers/functions.py`, `optimizers/finish.py`
- `src/optimization_framework/evaluation/registry.py`, `contracts/problems.py`, `contracts/requests.py`
- `src/optimization_framework/problem_charter/charter.py`, new `problem_charter/scaffold.py`, `problem_charter/api.py`
- `src/optimization_framework/campaigns/compute_consent.py`, `campaigns/proposals.py`, new `campaigns/plan_runs.py`,
  `implementations/bridge.py`, `implementations/builtin.py`
- `src/balsamic/evolution/ledger.py`, `analysis/general.py`
- `agents/tools.py` (INSTRUCTIONS), `src/balsamic/procedures/implementation-supervision/SKILL.md`
- `frontend/src/note/CharterPanel.tsx`, `frontend/src/evolution/EvolutionPage.tsx`, `frontend/src/hypotheses/Implementations.tsx`
