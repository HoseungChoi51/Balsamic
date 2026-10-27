# Phase 1 — Charter to results: no harder than a script and a local coding agent

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| Replaces | `docs/charter-to-results-plan.md` (`cc0e693`): the same goal, the same decisions 1–3 and the same phases, split into PR-sized parts and checked against the code at `cc0e693` |
| Also includes | `docs/suggestions.md` S2 (part A4) |
| Decisions it needs | 4–7 and 9 (README §2.2); 22 and 23 for the D1 and F1 notes on white-box problems (§2.3) |
| Status | Not started. A1 fixes a live bug: do it first |

## Summary

Size: S is under about 200 changed lines including tests, M about 200–600, L more.

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| **A** | **Unblock and correct** | | | | |
| A1 | Install without a false "needs confirmation" | Baking order's install waits for a confirmation it does not need (live bug) | — | S | 1 (first) |
| A2 | Rank by the objective's direction | The ledger, the progress line, the chart and the Evolution table rank the highest raw score best, even when minimizing | — | S–M | 1 |
| A3 | A method that finishes | A method that stops on its own counts as a failed run, and shrinks every method's matched cost | — | M | 1 |
| A4 | Checkpoints go to whoever opened the workspace, as notices | Every checkpoint wakes the lead with raw JSON (suggestions.md S2) | — | S | 1 |
| **B** | **One go-ahead per request** (decisions 2 and 3) | | | | |
| B1 | No concept review for proposals the researcher asked for or approved | The review gate blocks runs the researcher asked for | decision 7 | S | 1 |
| B2 | A consent names what it covers | Consents are campaign-wide; nothing records which proposals, workspaces and runs a go-ahead was for | decision 4 | M | 1 |
| B3 | The implementation allocation becomes an optional ceiling | Every commission needs a separate allocation raise on top of the go-ahead | — | S | 1 |
| B4 | Proposals are bound to delivered methods automatically | After an install the lead must bind each proposal by hand; binding also voids a concept review | decision 6 | S–M | 1 |
| B5 | Approved runs start by themselves | Approved runs wait for the lead to notice the install, bind and launch | B2, B4, decision 6 | M | 2 |
| B6 | Unknown fields reported, not refused, at agent boundaries | Two submissions refused for an extra field; agent commands refused the same way | decision 5 | S–M | 1 |
| B7 | The lead's instructions and the supervision procedure | Prose still tells the lead to bind and to raise allocations | B1, B2, B4, B5 | S | 4 |
| **C** | **Problems that are orders** | | | | |
| C1 | Permutation representation | No permutation type, so built-in random draws invalid orders and fails | — | M | 1 |
| C2 | Built-in methods for permutations | Nothing in the lab searches orders | C1 | S–M | 2 |
| C3 | Library methods say what they accept | A library method that declares no representation is treated as binary-only | — | S | 1 |
| **D** | **Methods as plain functions** | | | | |
| D1 | `FunctionMethod`: a function becomes a method | The optimizer_v1 contract (propose, observe, checkpoint, restore, inspect, export) is heavy for a few lines of search | A3 | M | 2 |
| D2 | `FunctionPlugin`, function conformance, seeded workers | A function library needs listing without import, a contract check and reproducible hashing | D1 | M | 3 |
| D3 | Declared problems show their data to methods | Methods never see the problem's data, so the agent hard-coded it | — | S | 1 |
| **E** | **Libraries that provide the problem** (decision 1) | | | | |
| E1 | The problem registry picks up installs | Problem plug-ins are discovered only at start-up | — | S–M | 1 |
| E2 | The installer accepts problem libraries | The installer refuses a library with no optimizer entry point | E1 | S | 2 |
| E3 | The charter recognizes an installed declared problem | A declared problem whose id is installed is a blocking finding | — | M | 1 |
| E4 | Tasks adopt a library's problem | Existing tasks keep pointing at the declared problem and its separate evaluator | E2, E3 | M | 3 |
| E5 | Adoption happens by itself after an install | Someone would have to ask for each adoption | E4 | S | 4 |
| **F** | **A project generated from the charter** | | | | |
| F1 | A standalone Python project from the charter | The coding agent starts from a JSON dump of one proposal; there is no charter export | — | M | 1 |
| F2 | Export as a Python project | The researcher cannot take the charter to their own tools | F1 | S | 2 |
| F3 | Balsamic glue in the generated library | The generated project must also be an installable Balsamic library | F1, D2, E2 (C1 for orders) | S–M | 4 |
| F4 | Coding workspaces start from the generated library | The brief names one proposal, no charter, and grating references | F3 | M | 5 |
| **G** | **End to end** | | | | |
| G1 | Baking order replayed offline | Nothing checks the whole path | most of A–F (listed in G1) | M | 6 |
| G2 | The same flow as a live quality scenario | Nothing measures it with a real model | G1 | S | 6 |

---

## 1. Background

### 1.1 The researcher's bar

After the charter, Balsamic should be no harder than exporting the charter into a Python script and working there with a
local coding agent: write the objective, write a few algorithm functions, run them, compare. Balsamic adds recording,
comparison and provenance, not ceremony.

Baking order (choose the order of 8 bakes to minimize total tardiness) shows how far off that is. Two and a half hours
after the charter was confirmed there were 0 runs. The researcher had to give 5 approvals (2 raises of the implementation
allocation, 3 compute go-aheads, one of which waited 61 minutes) and 5 prompts. Two submissions were refused for extra
fields, two evaluator builds ran, the lead asked the researcher to run `docker cp` and `uv pip install`, and the automatic
install waits for a confirmation it does not need.

### 1.2 Target flow

| Step | Who | Parts |
|---|---|---|
| 1. The researcher confirms the charter and asks for four algorithms; the lead records them | researcher, lead | B1 |
| 2. "Implement and compare" becomes one compute request naming the workspace, the proposals and the runs; one go-ahead | researcher, lead | B2, B7 |
| 3. The coding workspace starts from a library generated from the charter. The agent fills the objective and four plain functions; the generated tests pass; it delivers | coding agent | F1, F3, F4, D1, D2, B6 |
| 4. Balsamic installs the library, picks up its problem, the task adopts it, each proposal is bound | Balsamic | A1, E1–E5, B4 |
| 5. The approved runs start by themselves; finished methods end cleanly; the comparison ranks by direction; the lead is woken once to write it | Balsamic, lead | B5, A3, A2 |

The researcher acts three times: confirm, ask, approve.

### 1.3 What changed from `charter-to-results-plan.md`, and why

Every claim of the earlier plan was checked against the code at `cc0e693`. It holds, with these corrections and additions:

| Earlier phase | In this plan | Found in the code |
|---|---|---|
| 1 Install | A1, unchanged in scope | In the code: `changed_packages()` returns every removed package, so a reinstall at the same version (`-x==1.0`, `+x==1.0`) counts as a change. `name @ url` lines are not parsed at all |
| 2 Ranking and finishing | Split into A2 and A3 (different files) | Also `worker.py` L456: `scientific_complete = primary_count >= completion["count"]`, so a finished method would still be reported as censored |
| 3 One go-ahead | Split into B1–B7 | `covering()` lets any plan's leftover time cover any work (decision 4). The bus guard already requires a consent for agent commissions, so the separate allocation is a second gate (B3). `_execute` accepts only researcher, manager and autopilot, so automatic binding and launching need a named system actor (decision 6) |
| 4 Permutations | C1, C2, plus C3 | `CharterPanel.tsx` has no representation picker; it only displays the representation (set by the formulator). `PackagedPlugin.methods()` defaults every library method to `["binary"]` |
| 5 Plain functions | Split into D1–D3 | The data fix is one line: `EvaluatorManifest.public_configuration_keys` exists, `charter.manifest()` never sets it |
| 6 Problem libraries | Split into E1–E5 | Optimizer plug-ins already re-check installs every second (`optimizers/plugins.py`); only problems do not. The `evaluator_requirement_satisfaction` record is new |
| 7 Scaffold and export | Split into F1–F4; the standalone generator and the export need nothing else and can ship first | The coding agent's brief carries only the first proposal (`development.py` L460) and no charter; `DEVELOPMENT_INSTRUCTIONS` names `/references/flrl` and `libraries/grating-mask-search` |
| 8 End to end | G1, plus a live scenario G2 | — |
| — | A4 added | suggestions.md S2: `_apply_event` wakes the lead on every checkpoint |
| — | Track H moved to Phase 4 | The design review's coding box: the bridge becomes harness-independent ([phase-4-coding-box.md](phase-4-coding-box.md)) |

---

## 2. Parts

### A1 — Install without a false "needs confirmation"

**Depends on:** nothing. **Size:** S. Do this first: it unblocks the live baking-order campaign.

**Read first:** `agents/library_install.py` (`CHANGE`, `changed_packages()`, `Installer.install()` L195–200, `automatic()`),
`agents/development.py` `install_delivered()` L203–213, `tests/test_library_install.py`.

**Today**
- `CHANGE = ^\s*([-+~])\s+([A-Za-z0-9_.\-]+)==(\S+)`. `changed_packages()` returns every removed package with its added
  version, so a reinstall at the same version or url counts as a change. `name @ url` lines are not parsed.
- Only the package being installed is excluded. The lab's root project and its editable `libraries/*` count.
- `install_delivered()` skips any submission that has any `library_install`, so a stale `needs_confirmation` is never retried.

**Change**
1. Parse `name==version`, `name==version (from url)` and `name @ url`. A package removed and added at the same version, or
   the same url, is a reinstall: not a change.
2. Never count the lab's own projects: the root `pyproject.toml` name and every `libraries/*/pyproject.toml` name.
3. `install_delivered()`: when a submission's latest install is Balsamic's own (`actor == "balsamic"`), its status is
   `needs_confirmation`, and re-parsing its `log_tail` with the new parser finds no change, request it once more with
   `request_key="automatic:reparsed"` and `retry_of=<record id>`. Never twice: a record with `retry_of` ends it.

**Tests** (`tests/test_library_install.py`)
- Copy the exact dry-run lines from the live record's `log_tail` (the baking-order campaign's `library_install` rows) into
  a fixture; do not invent uv's format. If you cannot read the live store, ask Hoseung for the `log_tail`. They give no
  change.
- A numpy upgrade (`- numpy==2.1.0`, `+ numpy==2.2.0`) still needs confirmation.
- A stale record is retried exactly once; a second sync does nothing.

**Done when**
- The tests pass.
- Hoseung checks live: baking order's pending install completes and its four methods appear on the Implementations page.

### A2 — Rank by the objective's direction

**Depends on:** nothing. **Size:** S–M.

**Read first:** `src/balsamic/evolution/ledger.py` (`score_of()`, the loop at L86–92), `src/balsamic/api/evolution.py` L30–40,
`src/balsamic/panels/service.py` `_chart_points()` L226–231, `frontend/src/evolution/EvolutionPage.tsx` L83,
`analysis/general.py` `report()`, `contracts/problems.py` `Objective` (`utility`, `better`).

**Today**
- Within a run, `best_objective` is already correct: the worker sorts its archive by `utility` (worker.py L425), and each
  result carries `objective_definition` with its direction (L447).
- Across runs, every reader takes the largest value: `ledger.py` L91 (`score > best`), `src/balsamic/api/evolution.py` L35
  (`max`), `src/balsamic/panels/service.py` L230 (`max(..., key=best_objective)`), `EvolutionPage.tsx` L83
  (`b.best.score - a.best.score`).
- `analysis/general.py` method summaries have a mean and a median but no order.

**Change**
1. Ledger: take the direction from the run's `result.objective_definition` (falling back to its task's primary objective)
   and choose the best with `Objective.better`. Each row's `best` carries `direction`.
2. `src/balsamic/api/evolution.py` `best_so_far` and `src/balsamic/panels/service.py` `_chart_points`: the same rule. If
   a campaign's rows disagree on direction, there is no single best (return `None`), never a mixed comparison.
3. `EvolutionPage.tsx`: sort by the row's direction and say "lower is better" beside the column when minimizing.
4. `analysis/general.py`: each group gets `direction`; each method summary gets `rank` (1 is best by mean under that
   direction; ties share a rank; methods without an observed value have none).

**Tests**
- Ledger and `best_so_far` on a minimize campaign pick the lowest score.
- The report ranks the lowest mean first when minimizing and the highest when maximizing.
- Playwright `evolution.spec.ts`: a minimize campaign lists the lowest score first.

**Done when** the tests pass and no other reader of `best.score` assumes maximize (search `best.score`, `best_objective`,
`max(`, `sorted(` in `src/balsamic/evolution`, `src/balsamic/api`, `src/balsamic/panels`, `frontend/src/evolution`).

### A3 — A method that finishes

**Depends on:** nothing. **Size:** M.

**Read first:** `execution/worker.py` (`one_step()` L365, `progress()` L440–466, `run()` L551–588),
`optimizers/packaged.py`, `optimizers/lifecycle.py` (`AskTellAdapter`), `analysis/general.py` (`observed_at()` L30,
the horizon at L185–190), `docs/optimizer-plugins.md`.

**Today**
- `run()` turns any exception into `failed` (L582–583). `PackagedOptimizer.propose` raises `ValueError` when the module
  returns no proposal (L30–32). So a method that stops on its own (a one-shot heuristic, an exhausted enumeration) fails.
- `progress()` marks a run `scientific_complete` only when its evaluation count reaches the completion count (L456), so a
  method that ended early would be reported as censored.
- The report compares methods at `horizon = min(last cost of every usable run)` (L187), and `observed_at()` has no value
  past a curve's end. One early finisher shrinks every method's matched cost.

**Change**
1. New `optimizers/finish.py`: `class MethodFinished(Exception)`, with an optional reason.
2. `PackagedOptimizer.propose`: a module that raises `StopIteration` or returns `[]` raises `MethodFinished`. The legacy
   `AskTellAdapter` does the same for an `ask()` that raises `StopIteration`. Document "return `[]` to finish" in
   `docs/optimizer-plugins.md`.
3. `worker.run()`: `except MethodFinished` gives `status="completed"`, `reason="method_finished"`; the final checkpoint and
   outputs are kept as on any completion. `progress()` sets `method_finished: true` and `scientific_complete: true` for it.
   A continuation of such a run finishes at once.
4. `analysis/general.py`: a run with `method_finished` holds its final value after its last point (`observed_at`), and the
   horizon is taken over the runs that did not finish (over all runs when every one finished). Its trial row says
   `held_after_finish: true`.
5. Check the readers of trial status for `completed` vs `failed` (`src/balsamic/evolution`, `analysis/standard_rules.py`):
   a finished run is a completed run.
6. The final inspection of a finished method is kept in `progress` as `final_inspection`. A method may put
   `{"bound": x, "proved_optimal": true}` in it (an exact method's proof, a solver's dual bound). This part only records
   it; N13 shows and checks it.

**Tests**
- A packaged module that returns `[]` after three proposals: completed, `method_finished`, best kept, `scientific_complete`.
- A method that raises any other exception still fails, with its message.
- A finished method's `bound` and `proved_optimal` are kept in `final_inspection`.
- A report with one finished run and one long run compares at the long run's cost, the finished value held.

**Done when** the tests pass and `docs/optimizer-plugins.md` documents finishing.

### A4 — Checkpoints go to whoever opened the workspace, as notices

**Depends on:** nothing. **Size:** S. This is `docs/suggestions.md` S2, scoped to this stage.

**Read first:** `agents/development.py` (`create()` L268–326, `notify()` L399–406, `_apply_event()` L559–598),
`agents/controller.py` (`enqueue()` L405, `request_root()` L397), `agents/turn_state.py` L29, `agents/models.py` (`NOTICE`).

**Today**
- `create()` records `opened_by` (actor, agent id, role) but sets `parent_agent_id` to the lead whoever opened it.
- `notify()` always enqueues to the lead, and the text does not start with `NOTICE`, so the lead's state block calls it
  "a request".
- `_apply_event()` calls `notify(record, key, json.dumps(payload))` for every checkpoint: 35 relay turns on `lead_2d-gratnig`.

**Change**
1. `create()` records the request root of the opening turn (`request_root`) on the workspace.
2. `notify()` enqueues to `opened_by.agent_id` when it is a live agent session of this campaign, else to the lead. The text
   starts with `NOTICE`; the run's origin carries the workspace's request root, so the notice continues that request.
3. Notify only on a state change: a question, a blocker, a submission, an install result, a failure, a finish. Progress
   checkpoints still update the record and the timeline, which is where the researcher follows them.
4. The text names what changed and which part of `implementation_workspace_inspect` to read, not the raw JSON.

**Tests** (fake harness)
- A workspace opened by the implementation lead sends its notices there.
- Five progress checkpoints in the same phase send none; a question sends one.
- The notice turn's state block reads "a platform notice, not a request".

**Done when** the tests pass.

### B1 — No concept review for proposals the researcher asked for or approved

**Depends on:** decision 7. **Size:** S.

**Read first:** `campaigns/proposals.py`, `campaigns/commands.py` L341–352, `src/balsamic/library/service.py` L95–105,
`campaigns/drafts.py` L84–91, `execution/service.py` L564–576, `agents/controller.py` `request_root()`,
`contracts/commands.py` `CommandOrigin`.

**Today**
- Every `hypothesis.create` by the `manager` actor sets `requires_concept_review=True` (commands.py L348), as do library
  imports (library/service.py L101).
- `proposals.readiness()` then blocks `trial.create` (service.py L570) and draft launches (drafts.py L89) until an
  independent review of the exact revision says "test".

**Change**
1. On `hypothesis.create` by the manager: when the command's run (`origin.run_id`) has a request root that is a
   researcher message (decision 7), record `requested_by = {thread_id, message_id}`.
2. On the go-ahead of a compute plan (`approvals.resolve`, the `compute` branch), set `approved_by = {decision_id,
   consent_id}` on each proposal the plan names (`hypothesis_ids` from B2, else the `runs[].hypothesis_id` already in the
   request).
3. `readiness()` returns `eligible: true` with state `not_required` and the reason ("asked for by the researcher", "in an
   approved plan") when either is set. A review that exists is still returned, as information: an objection shows as
   `advisory`, it does not block.
4. The proposal card shows "asked for" or "approved" with a link to the message or the decision.

**Tests**
- A proposal the lead records answering a researcher message runs with no review.
- A proposal created in an autopilot turn, or in a notice turn with no researcher root, is still blocked.
- A proposal named in an approved plan runs; a reviewer's objection to it shows as advisory.

**Done when** the tests pass.

### B2 — A consent names what it covers

**Depends on:** decision 4. **Size:** M.

**Read first:** `campaigns/compute_consent.py` (all of it, 166 lines), `campaigns/approvals.py` `resolve()` L30–95,
`contracts/commands.py` `ApprovalRequestInput` L271–300 and `PlannedRun` L259, `agents/development.py` `create()`.

**Today**
- `grant()` stores the plan text, worker and wall seconds and the number of coding workspaces. It does not store the
  proposals or the runs, although the request carries `runs`.
- `covering()` returns the first consent in the campaign with time left, so leftover time from one plan covers unrelated
  work.
- A consent expires `max(3600, 3 × wall_seconds)` after its grant, even while the workspace it opened is still building.

**Change**
1. `ApprovalRequestInput` gains `hypothesis_ids` (compute only; each a proposal of this campaign).
2. `grant()` stores `hypothesis_ids` (plus those its `runs` name), `runs`, the request root of the asking turn, and empty
   `workspace_ids` and `launched` lists.
3. `charge()` appends what it charged to: workspace ids for coding workspaces, trial ids for runs.
4. `covering()` and `require()` take the proposals the work is for. Under decision 4, a consent that names proposals covers only work
   for them: a workspace whose `hypothesis_ids` it names, a run or commission of a proposal it names. Work for no proposal
   (a runtime profile, a validation) is covered by a consent of the same request root. A consent that names no proposals
   covers anything, as today. Callers pass the proposals: the bus guard (from the payload's `hypothesis_id`, or the draft's),
   `development.create()` (the served proposals), and the validation path.
5. The refusal text says which approved plan would cover the work, or that none does.
6. A consent stays in force while a workspace in its `workspace_ids` has `desired_status == "running"`, and for
   `3 × wall_seconds` after the last one stops.

**Tests**
- A plan for proposals H1–H4 does not cover a run of H5, and the refusal says so.
- A consent outlives its expiry while its workspace builds.
- A consent recorded before this change (no `hypothesis_ids`) still covers campaign-wide.
- `charge()` records the workspace and the trial ids.

**Done when** the tests pass.

### B3 — The implementation allocation becomes an optional ceiling

**Depends on:** nothing. **Size:** S.

**Read first:** `implementations/bridge.py` L260–275 and L315–325, `campaigns/compute_consent.py` `estimate()` and
`register()`, `contracts/requests.py` L80 and L110, `agents/development.py` `capture_submission()` (its notice text).

**Today**
- `bridge.py` refuses a commission (L265) or a revalidation (L320) when committed plus requested seconds exceed
  `implementation_compute_budget_seconds`, which defaults to 0. So every commission first needs a raise; baking order
  needed two.
- The bus guard already requires a consent for an agent's `implementation.commission`, `evaluator.commission` and
  `implementation.revalidate` (`estimate()` reads their `compute_seconds`). The allocation is a second gate.

**Change**
1. Both checks apply only when the limit is positive: it becomes the researcher's optional ceiling. 0 means none.
2. An agent's `approval.request` of kind `campaign_limits` that raises `implementation_compute_budget_seconds` is refused:
   "ask for a compute go-ahead (kind compute) instead; the implementation allocation is only an optional ceiling".
3. Texts that mention "the remaining implementation allocation" (`capture_submission()`, the supervision procedure) are
   updated; `docs/implementation-service.md` and `docs/resource-allocation.md` say the same.

**Tests**
- With the limit 0, an agent's commission covered by a consent goes through; without a consent it is refused by the guard.
- A positive limit still caps.
- The raise request is refused with the redirect.

**Done when** the tests pass.

### B4 — Proposals are bound to delivered methods automatically

**Depends on:** decision 6. **Size:** S–M.

**Read first:** `agents/library_install.py` `install()` L195–216, `campaigns/method_catalog.py` (`served()`,
`methods_for()`, `development_readiness()`), `implementations/builtin.py` (`BuiltinBindingInput`, `bind()`),
`optimizers/registry.py` `capability_reason()` L149, `campaigns/proposals.py` `hypothesis_revision()`,
`campaigns/commands.py` `_execute()` L205–207, `contracts/commands.py` `CommandOrigin`.

**Today**
- After an install the lead is told: "Bind each proposal to its method (implementation.bind_builtin)".
- `method_catalog` already knows which installed method serves which proposal (`served`, `methods_for`).
- `bind()` rewrites `algorithm_config`, which `hypothesis_revision()` hashes, so binding voids a concept review.
- `_execute()` accepts only `researcher`, `manager` and `autopilot`.

**Change**
1. Add the `balsamic` system actor (decision 6): accepted by `_execute()` for `implementation.bind_builtin` and (B5) `trial.create`
   only; `CommandOrigin.actor` gains `"balsamic"`.
2. After a successful install, for each proposal the submission serves: if exactly one of its methods is installed and
   runnable on a current task (`capability_reason` is `None`), bind it through the bus as `balsamic`, citing the install.
   Skip a proposal the researcher bound, one bound to another method, and one with several candidate methods.
   Put this in one post-install step, `after_install()` in `library_install.py`: E5 adds adoption before the binding, and
   B5 adds launching after it, so the order is always adopt, bind, launch.
3. The install record lists `bindings` (proposal, method, task, binding id) and `skipped` (proposal, reason). The notice
   names both and no longer asks the lead to bind.
4. `bind()` stores the configuration it replaced, once (`pre_binding_config`); `hypothesis_revision()` hashes that value for
   a bound proposal, so a binding does not void a review.

**Tests**
- A library with two methods serving two proposals binds both, with receipts by `balsamic`.
- A proposal the researcher bound is untouched; an incompatible method is skipped with its reason.
- A review recorded before the binding stays valid after it.
- `balsamic` cannot run any other operation.

**Done when** the tests pass.

### B5 — Approved runs start by themselves

**Depends on:** B2, B4, decision 6. **Size:** M.

**Read first:** `campaigns/compute_consent.py`, `contracts/commands.py` `PlannedRun`, `agents/development.py` `sync()`
L428–447, the `trial.create` path in `campaigns/commands.py`, `campaigns/method_catalog.py`.

**Today** nothing starts approved runs; `grant()`'s docstring says "the requester starts the work". The lead must notice the
install, bind, hand the runs to the operator, and the operator launches.

**Change**
1. New `campaigns/plan_runs.py` `launch_ready(workspace, campaign_id)`, called after `install_delivered()` in `sync()` and
   after each automatic binding.
2. For each consent in force with `runs`, for each planned run whose proposal is now runnable (bound, method installed,
   compatible, evaluator ready, `readiness()` eligible), create one trial per seed that is not yet in `launched`:
   `trial.create` through the bus as `balsamic`, with the planned `task_id`, seed, `wall_seconds`, `max_evaluations` and
   `device`. The origin carries the consent's id (`CommandOrigin` gains `consent_id`) and its request root. The command id
   derives from (consent, run index, seed), so a replay creates nothing. A planned task that was superseded (E4) runs on
   its successor (`superseded_by_task_id`).
3. The bus guard checks a `balsamic` `trial.create` against the consent its origin names, and charges it there.
4. Never more than the plan: a run the plan does not list is never created, and when the consent's worker time is spent
   launching stops and the lead is told.
5. When every planned run of a consent has a terminal status, wake the lead once (a notice under the request root):
   "All N approved runs finished; write the comparison (`comparison.report`)".

**Tests**
- A plan of 4 runs × 2 seeds: after two proposals are bound, exactly their 4 trials start; another sync starts none.
- The other 4 start when their library is installed.
- A planned run of an unbound proposal never starts; a trial outside the plan is never created.
- When all finish, the lead gets exactly one notice.

**Done when** the tests pass.

### B6 — Unknown fields reported, not refused, at agent boundaries

**Depends on:** decision 5. **Size:** S–M.

**Read first:** `contracts/base.py` (`Contract`, `extra="forbid"`), `agents/development_runtime.py` `snapshot()` L231–252,
`agents/development.py` `SubmissionManifest` L39–44 and `capture_submission()`, the agent command tool in
`agents/tools.py` (where payloads reach `commands.execute`), `campaigns/commands.py` `describe()` L125 (each operation's
payload model).

**Today** every contract forbids extra keys. `snapshot()` refuses a manifest with any extra key, and an agent command whose
payload has one is refused.

**Change** (agent paths only; the researcher's HTTP API stays strict)
1. Manifest: `snapshot()` splits the manifest's keys into known and unknown. A near-miss
   (`difflib.get_close_matches(key, known, n=1, cutoff=0.8)`) is refused with "did you mean files?". Other unknown keys are
   dropped and returned to the coding agent as `ignored_fields` in its result file.
2. With no manifest file, derive one: every tracked file of the commit's single `libraries/<name>/`, contract
   `optimizer_v1`, the default entry point.
3. Commands: in the agent tool path, before `commands.execute`, compare the payload's top-level keys with the operation's
   payload model. A near-miss is refused with the suggestion; other unknown keys are stripped and recorded as
   `ignored_fields` on the receipt and in the tool result.
4. Nested objects stay strict.

**Tests**
- A manifest with `"description"` is accepted and reports it ignored; one with `"file"` is refused with "did you mean files".
- A command with `wall_secs` is refused with "did you mean wall_seconds"; one with `note` runs, and its receipt lists it.
- The researcher's HTTP API still refuses an extra key.

**Done when** the tests pass.

### B7 — The lead's instructions and the supervision procedure

**Depends on:** B1, B2, B4, B5. **Size:** S.

**Read first:** `agents/tools.py` `INSTRUCTIONS`, `src/balsamic/lead/instructions.py`,
`src/balsamic/procedures/implementation-supervision/SKILL.md`, `campaigns/method_catalog.py` (its `next_action` texts),
`tests/test_harness_contract.py`.

**Change**
1. `INSTRUCTIONS` gains one line: "Implement and compare" is one compute request listing the coding workspace, any
   evaluator, the proposals and the runs; Balsamic installs, binds and starts the approved runs; never ask the researcher to
   run commands.
2. The supervision procedure drops step 4's binding and the allocation paragraph: the runs start themselves, and the lead
   writes the comparison when told.
3. `method_catalog`'s "Bind … (implementation.bind_builtin)" next action stays only for a proposal B4 skipped.
4. Offset the added words so the ratchet holds.

**Tests**
- The ratchet passes.
- Fake harness: one researcher request leads to one compute request with runs, and no `implementation.bind_builtin` by the
  lead.

**Done when** the tests pass.

### C1 — Permutation representation

**Depends on:** nothing. **Size:** M.

**Read first:** `contracts/problems.py` `CandidateSchema` L42–75, `contracts/capabilities.py` L46,
`contracts/problem_charter.py` `DecisionVariable` L78–89, `problem_charter/charter.py` (`findings()` L440–458,
`evaluator_findings()` L715–789, `manifest()` L1021–1078, `from_setups()` L1144–1150), `optimizers/lifecycle.py`
(`BoundedSearch.ask()`, the dtype in `observe()` L41), `optimizers/registry.py` (`BUILTINS` L13; the representation checks at L128, L159 and L228),
`frontend/src/note/CharterPanel.tsx` L262–270 and L372–380, `problem_import/guideline.md` L41,
`src/balsamic/procedures/problem-formulation/SKILL.md`, `agents/roles/methodology_specialist.md` L11.

**Change**
1. `CandidateSchema.representation` gains `"permutation"`: a candidate is an order of the items `0 … dimensions−1` (indices
   into the instance's data), each exactly once. `values` and `bounds` stay empty; linear constraints are refused for it.
   `canonicalize` checks that `sorted(candidate) == list(range(dimensions))` and returns ints.
2. `InferenceDescriptor.representations` and `DecisionVariable.representation` gain it.
3. Charter: a permutation variable has a one-dimensional shape (its size is the number of items) and no bounds or values
   (findings say so). `manifest()` builds the permutation schema; `from_setups()` maps it back; `evaluator_findings()`'s
   "one representation" rule is unchanged.
4. `BoundedSearch.ask()` draws `rng.permutation(n)`; `observe()` uses an integer dtype. `random` lists the representation;
   check that the binary-only branches in `registry.py` (L128, L228) route it correctly.
5. `CharterPanel.tsx`: a permutation variable reads "an order of N items", with no bound inputs.
6. Formulation guidance (`guideline.md`, `src/balsamic/procedures/problem-formulation/SKILL.md`,
   `methodology_specialist.md`): "an order or a ranking is a permutation; do not encode it as discrete values".

**Tests**
- `canonicalize` accepts a rearrangement and refuses a repeat, a missing item and an out-of-range item.
- A permutation charter gives the right manifest (dimensions, no bounds) and refuses a two-dimensional shape.
- `random` proposes only valid orders.

**Done when** the tests pass.

### C2 — Built-in methods for permutations

**Depends on:** C1. **Size:** S–M.

**Read first:** `optimizers/registry.py` (`BUILTINS`, `PROPERTIES`, `create`), `optimizers/reference.py` (`Replay`,
`FixedSolution`), `optimizers/conformance.py` `check()`.

**Change**
1. `replay` and `evaluate_asset` accept permutation candidates.
2. New built-in `swap_search` (its own module): swap and insertion moves, first improvement, random restarts after a plateau
   (parameter `restarts_after`). Registered with `representations: ["permutation"]`.

**Tests**
- `swap_search` on an 8-job tardiness instance reaches the enumerated optimum within a fixed number of evaluations for a
  fixed seed.
- `conformance.check()` passes for it.
- `replay` of a list of orders evaluates each.

**Done when** the tests pass.

### C3 — Library methods say what they accept

**Depends on:** nothing. **Size:** S.

**Read first:** `optimizers/packaged.py` L19–24 and L66–83, `libraries/grating-mask-search/src/grating_mask_search/plugin.py`,
`optimizers/registry.py` `capability_reason()`.

**Today**
- `PackagedPlugin.methods()` gives every method that declares no `representations` the value `["binary"]`. The grating
  library relies on that default; any other library's methods show as incompatible with a non-binary problem, with no hint.
- The optimizer_v1 context passes the dimension count as `n_cells`, the grating's word.

**Change**
1. `PackagedPlugin` gains a class attribute `REPRESENTATIONS`. A method takes its own `representations`, else the class
   value, else `["binary"]` as before; the grating library keeps working unchanged.
2. When a method is incompatible only because it took the binary default, `capability_reason()` says "the library declares
   no representations, so it is treated as binary; declare REPRESENTATIONS".
3. The context gains `dimensions`; `n_cells` stays for existing libraries and is marked deprecated in
   `docs/optimizer-plugins.md`.

**Tests**
- A library with `REPRESENTATIONS = ["continuous"]` is compatible with a continuous problem.
- The binary-default reason reads as above.
- The grating library's methods are listed as before.

**Done when** the tests pass.

### D1 — `FunctionMethod`: a function becomes a method

**Depends on:** A3. **Size:** M.

**Read first:** `optimizers/packaged.py` (the adapter pattern to mirror), `execution/worker.py` (`one_step()`, the pause and
checkpoint path), `optimizers/finish.py` (from A3), `contracts/problems.py` (`ProblemInstance.descriptor()`, `Proposal`,
`Observation`).

**The contract**
- A method is a function `def <method_id>(problem, evaluate, rng) -> None`.
- `evaluate(candidate) -> float` returns the primary objective in the charter's own units and direction. It raises
  `ValueError` for an invalid candidate (the method may catch it and try another), and `StopSearch` once a cap (evaluations
  or wall time) is reached.
- `StopSearch` derives from `BaseException`, so a method's `except Exception` cannot swallow it.
- Returning ends the method: the run finishes as `method_finished` (A3).
- `rng` is a seeded `numpy.random.Generator`; `random` and `np.random` are seeded from the same seed.
- `problem` is the library's own problem object when the plug-in provides one (F3), else a read-only mapping of
  `instance.descriptor()`.
- On a white-box problem (the default, decision 22) the method may compute the objective itself, as often as it likes:
  through `problem.objective(candidate)`, or the library's `objective.py`. Such calls are not observations and are not
  counted; the run is judged on time (decision 23). `evaluate` records a candidate, and the best known to Balsamic is the
  best of those recorded. N11 adds the `oracle` case, where `problem` has no objective.

**Change:** new `optimizers/functions.py`:
1. `StopSearch(BaseException)`.
2. `FunctionMethod(fn, instance, parameters, seed)`, exposing what the worker expects (as `PackagedOptimizer` does). `fn`
   runs in a daemon thread; `evaluate` puts the candidate on a queue and blocks for its score. `propose(1)` returns the next
   candidate, raises `MethodFinished` when `fn` returned, and re-raises `fn`'s exception as a failure. `observe()` hands back
   the score, or the error for an invalid candidate.
3. A checkpoint is `{"contract": "function_v1", "seed": …, "log": [[candidate_hash, status, score], …]}`. `restore()` runs
   `fn` again from the start with the same seed and answers `evaluate` from the log without evaluating, checking each
   candidate's hash; a mismatch refuses the resume ("not deterministic for its seed"). After the log, it continues live.
4. `close()` makes the next `evaluate` raise `StopSearch`. Each trial's worker is its own process (`execution/service.py`
   L1363), and the global seeds are per process, so a second live `FunctionMethod` in one process is refused.

**Tests**
- A one-shot method (three evaluations, then returns) ends as `method_finished` with its best.
- An endless method is stopped by the evaluation cap and the wall cap.
- Pause and resume reproduce the journal; a method that uses the clock is refused on resume.
- A method that raises `ValueError` fails with its message; one that wraps `evaluate` in `except Exception` still stops.

**Done when** the tests pass.

### D2 — `FunctionPlugin`, function conformance, seeded workers

**Depends on:** D1. **Size:** M.

**Read first:** `optimizers/plugins.py` (`OptimizerPlugin`, `REQUIRED`), `optimizers/packaged.py` `PackagedPlugin`,
`optimizers/conformance.py`, `libraries/grating-mask-search/tests/test_contract.py`, the worker's environment in
`execution/isolation.py` L193–201 and the `env.update(...)` before the worker's `Popen` in `execution/service.py` L1352–1364,
`docs/optimizer-plugins.md`.

**Change**
1. `FunctionPlugin` in `optimizers/functions.py`: a library subclasses it and sets `MODULE = "<pkg>.methods"` and
   `REPRESENTATIONS`. `methods()` reads the `METHODS = {id: {name, description, hypothesis_id?, parameters?}}` literal from
   the module's source (`importlib.util.find_spec(MODULE).origin`, then `ast.literal_eval`) and never imports it, so agent
   code does not run in the server. `create()` imports the module (in the worker only) and wraps the function in a
   `FunctionMethod`.
2. `conformance.check_function(plugin, method_id, instance, *, seeds=(0, 7), max_evaluations=50)`: valid candidates only,
   the same sequence for the same seed, continuing from a checkpoint, and a clean end (return or cap). It uses the problem
   the instance resolves to, so a library's own evaluator is what it runs.
3. Workers start with `PYTHONHASHSEED=0`, in both launch paths.
4. `docs/optimizer-plugins.md` gains "Plain-function methods".

**Tests**
- Listing a `FunctionPlugin` does not import its module (`sys.modules`).
- `create()` works in a worker; `check_function` passes for a good method and fails for one that is nondeterministic.
- The worker's environment has `PYTHONHASHSEED=0`.

**Done when** the tests pass.

### D3 — Declared problems show their data to methods

**Depends on:** nothing. **Size:** S.

**Read first:** `problem_charter/charter.py` `manifest()` L1021–1078, `contracts/evaluators.py` L26, L40–41 and L82,
`contracts/problems.py` `descriptor()` L119–124.

**Today** `manifest()` builds the `EvaluatorManifest` without `public_configuration_keys`, so `descriptor()["public"]` is empty:
methods see none of the problem's data. In baking order the coding agent hard-coded the due dates.

**Change**
1. `manifest()` sets `public_configuration_keys=sorted(binding.configuration)`. The configuration is the instance's input
   data, and a method may use it; fidelity stays private.
2. This changes the manifest's digest, so only tasks compiled after the change get it. Existing tasks keep theirs; no
   migration.

**Tests**
- A task compiled from a declared charter gives methods its configuration in `descriptor()["public"]`.
- An existing task's digest is unchanged.

**Done when** the tests pass.

### E1 — The problem registry picks up installs

**Depends on:** nothing. **Size:** S–M.

**Read first:** `evaluation/registry.py` (all of it, 94 lines), `optimizers/plugins.py` (`pick_up_installs()`, `_reload()`,
`_installed()`, `_forget_changed()`), `tests/test_optimizer_plugins.py`
`test_a_plugin_installed_while_the_service_runs_is_listed_without_a_restart`.

**Today** `problems = ProblemRegistry().discover()` reads the `optimization_framework.problems` entry points once, at import.
Optimizer plug-ins already re-check at most once a second, reload changed ones and never drop the lab's own modules.

**Change**
1. Move the installed-package helpers (`pick_up_installs`, the entry-point and version snapshot, the module dropping) to a
   shared module, e.g. `src/optimization_framework/installed.py`, used by both registries.
2. A discovered `ProblemRegistry` re-checks on `ids()` and `get()` at most once per second, updating itself in place (other
   modules hold a reference to `problems`): it adds new loaders, and for a changed entry or version it drops the cached
   adapter and the package's modules. Never the lab's own package.
3. Registries built with `from_entries()` (frozen hosts) or `extended()` never re-check.

**Tests**
- A problem package installed into a temporary site directory is listed within a second, without a restart.
- A version bump reloads it; the lab's own problem modules are never dropped.
- A frozen registry does not change.

**Done when** the tests pass.

### E2 — The installer accepts problem libraries

**Depends on:** E1. **Size:** S.

**Read first:** `agents/library_install.py` `prepare()` L80–118 and `install()`.

**Today** `prepare()` refuses a library whose `pyproject.toml` names no `optimization_framework.optimizers` entry point.

**Change**
1. Accept a library that names either group, or both.
2. Refuse, before uv runs, a problem id or method id that another installed distribution provides ("problem <id> is
   provided by <distribution>").
3. Record `problems_added`, and `missing_problems` (entry points that did not load), beside `methods_added`; the notice
   names them.

**Tests**
- A problems-only library installs and records `problems_added`.
- An id clash is refused before any uv command.

**Done when** the tests pass.

### E3 — The charter recognizes an installed declared problem

**Depends on:** nothing (tests use a registry fixture). **Size:** M.

**Read first:** `problem_charter/charter.py` (`evaluator_facts()` L378, `evaluator_findings()` L715–789, `describe()` L797,
`compile_setups()` L998–1018, `manifest()`), `contracts/problem_imports.py` `ProblemSetup`.

**Today** a declared binding whose `problem_id` is installed gets the blocking finding `evaluator.declared_id` (L727–729),
and `compile_setups()` always emits the declared setup with its `evaluator_manifest`.

**Change**
1. A pure function `compare_provided(manifest, instance) -> list[difference]`: candidate schema (representation,
   dimensions, bounds, values, constraint names), primary objective (name, direction, units), metric names, configuration
   field names. F3's generated contract test calls it too.
2. When a declared `problem_id` is installed, resolve it with the charter's values and compare:
   - no difference: an informational finding `evaluator.provided` ("provided by <distribution> <version>"), and
     `compile_setups()` emits an installed setup (`problem_id`, configuration, fidelity);
   - any difference: a blocking finding `evaluator.provided_mismatch` listing each one (what the charter says, what the
     library computes).
3. `describe()` says whether the evaluator is declared or provided by a library.

**Tests**
- A matching library gives an installed setup.
- A library that maximizes what the charter minimizes is blocking, with that difference listed.
- Not installed: the declared path is unchanged.

**Done when** the tests pass.

### E4 — Tasks adopt a library's problem

**Depends on:** E2, E3. **Size:** M.

**Read first:** `execution/service.py` (`current_tasks()` L501, task creation from setups), `evaluation/commissioning.py`
(`readiness()` L116, `evaluator_requirement`), how a campaign's tasks are compiled from its charter (`compile_setups` callers),
`campaigns/method_catalog.py` `catalog()`.

**Today** a declared task carries an `evaluator_requirement_id`, and `commissioning.readiness()` wants a validated evaluator
binding for it. Re-compiling the charter after an install (E3) would give installed setups, but existing tasks keep their
declared problem.

**Change**
1. `ExecutionService.adopt_library_problem(campaign_id, install_id)`: when an install added a problem the campaign's
   charter declares, recompile the tasks from the charter and create new tasks, opening a new study and bumping the campaign
   version once. Never rebind an old task.
2. The old task gets `superseded_by_task_id`. The new one gets `provided_by` (package, version, commit, submission, install).
   A new immutable `evaluator_requirement_satisfaction` record links the old requirement to the install.
3. A new command `campaign.adopt_problem` (researcher or lead; it starts no compute) calls it. That is baking order's path,
   since its old task already has an evaluator.
4. `current_tasks()` leaves superseded tasks out; B4 and B5 then work on the new task.
5. Check the code that re-validates archived declared tasks through `TaskInput` (risk in §4).

**Tests**
- Adopting creates a new task with `provided_by`, supersedes the old one and bumps the campaign version once.
- Adopting the same install again changes nothing.
- A superseded task is not in `current_tasks()`.

**Done when** the tests pass.

### E5 — Adoption happens by itself after an install

**Depends on:** E4. **Size:** S.

**Read first:** `agents/library_install.py` (`after_install()` from B4, or `install()` if B4 has not landed),
`execution/service.py` `adopt_library_problem()` (E4).

**Change**
1. After an install that added a problem the campaign's charter declares, adopt it automatically when the old task has no
   bound evaluator and no live runs. This runs first in the post-install step: adopt, then bind (B4), then launch (B5).
2. Otherwise skip it and tell the lead why, naming `campaign.adopt_problem`.
3. The install record lists `adopted` (old task, new task) or `adoption_skipped` (reason).

**Tests**
- An install adopts a task with no evaluator and no live runs.
- A task with live runs is not adopted and the lead is told; `campaign.adopt_problem` then adopts it.
- Replaying the install adopts nothing more.

**Done when** the tests pass.

### F1 — A standalone Python project from the charter

**Depends on:** nothing. **Size:** M.

**Read first:** `problem_charter/charter.py` (`resolve()`, `render()`, `texts()`, `manifest()`), `contracts/problem_charter.py`
(`ProblemCharter`, `Instance`, `ReferenceResult`, `Constraint`).

**Change:** new `problem_charter/scaffold.py` `scaffold(charter, revision, *, name=None) -> dict[str, bytes]`, a pure
function: the same charter revision always gives the same bytes. No generated file imports Balsamic.
- **Generated:**
  - `pyproject.toml`: the project (name from the problem id, version `0.1.0`), numpy, pytest as a test extra;
  - `charter.json`: charter id, revision, content hash, and the charter;
  - `README.md`: what the problem is, and how to run the tests and the comparison;
  - `<pkg>/data.py`: each instance's resolved values, the candidate schema and the objective (name, direction, units);
  - `<pkg>/problem.py`: a typed `Problem` per instance and `is_valid(candidate)` for the schema and the linear constraints;
  - `<pkg>/harness.py`: `StopSearch(BaseException)` and `run(method, problem, seed, max_seconds=None, max_evaluations=None)`
    returning the log, the best and the elapsed time; at least one cap is required;
  - `<pkg>/compare.py`: `python -m <pkg>.compare [--seeds N --seconds S --evaluations M]` runs every method on every instance
    and prints a table ranked by the objective's direction, with each run's time and evaluations. The default cap is
    `--seconds`, since a white-box method (decision 22) may compute the objective without calling `evaluate`; deterministic
    methods run once whatever `--seeds` says (decision 14).
- **For the agent to fill:**
  - `<pkg>/objective.py`: `def objective(problem, candidate) -> float`, raising `NotImplementedError`, its docstring the
    charter's objective definition with the values filled in, and the constraint statements;
  - `<pkg>/methods.py`: `METHODS = {}`, with one example in a comment.
- **Generated tests:**
  - `tests/test_problem.py`: the data matches `charter.json`; dimensions; `is_valid` on a valid candidate; the objective is
    finite and deterministic. Each charter reference result with a candidate becomes a test of its value; one without a
    candidate becomes a skipped test naming the number;
  - `tests/test_methods.py`, parametrized over `METHODS`: valid candidates, the same sequence for the same seed, the cap
    respected.
- Representations: binary, discrete and continuous. Permutation once C1 has landed (a small follow-up in this module).

**Tests**
- Golden tests for a small continuous charter and a discrete one (the file list and key contents).
- The generated project, with a trivial objective and method filled in, passes its own tests in a temporary directory.
- No generated file imports `optimization_framework` or `balsamic`.
- `compare.py` ranks a minimize problem correctly, and stops a method on `--seconds`.

**Done when** the tests pass.

### F2 — Export as a Python project

**Depends on:** F1. **Size:** S.

**Read first:** `problem_charter/api.py` `install()` L81–166, `frontend/src/note/CharterPanel.tsx`.

**Change**
1. `GET /api/v1/problem-charters/{id}/revisions/{n}/export.zip` returns `scaffold()` as a zip under `<project-name>/`, named
   after the problem and the revision.
2. An "Export as Python project" button on the Charter tab.

**Tests**
- The endpoint returns a zip with `pyproject.toml` and `charter.json` for the right revision.
- Playwright `charter.spec.ts`: the button downloads it.

**Done when** the tests pass.

### F3 — Balsamic glue in the generated library

**Depends on:** F1, D2, E2; C1 for permutation charters. **Size:** S–M.

**Read first:** `problem_charter/scaffold.py` (F1), `optimizers/functions.py` (D1, D2), `contracts/problems.py`
(`ProblemAdapter`), `evaluation/registry.py`, `compare_provided()` (E3), `docs/optimizer-plugins.md`.

**Change**
1. `scaffold(..., balsamic=True)` adds `<pkg>/adapter.py`:
   - the Balsamic problem adapter: its id is the charter's `problem_id`; `describe()` matches `charter.manifest()`;
     evaluation calls `objective.objective(problem, candidate)`;
   - a `FunctionPlugin` subclass (`MODULE = "<pkg>.methods"`, `REPRESENTATIONS` from `data.py`).
   It imports Balsamic only inside its functions, so `import <pkg>` works without Balsamic.
2. `pyproject.toml` gains both entry points (`optimization_framework.problems` and `optimization_framework.optimizers`).
3. `tests/test_contract.py` runs `check_function` for each method and `compare_provided` against the charter. It uses
   `pytest.importorskip("optimization_framework")`, so the project still runs alone.

**Tests** with a filled objective and method: load the generated adapter from a temporary directory, register it with
`ProblemRegistry.extended()`, then `check_function` passes and `compare_provided` finds no difference.

**Done when** the tests pass.

### F4 — Coding workspaces start from the generated library

**Depends on:** F3, decision 9. **Size:** M.

**Read first:** `agents/development_runtime.py` `prepare()` L119–175, `agents/development.py` (`_sync_one()` L449–470,
`DEVELOPMENT_INSTRUCTIONS` L726–779, `create()`), `agents/library_install.py` `prepare()`.

**Today**
- The brief is the first proposal's JSON (`record["hypothesis_id"]`) plus `DEVELOPMENT_INSTRUCTIONS`, although the workspace
  may serve several (`hypothesis_ids`). The coding agent gets no charter.
- `DEVELOPMENT_INSTRUCTIONS` tells it to copy `libraries/grating-mask-search` and names `/references/flrl`.

**Change**
1. When the campaign has a charter, `prepare()` writes `scaffold(charter, revision, balsamic=True)` into
   `libraries/<problem-id>/` of the worktree, never overwriting an existing file (recovery), and records each generated
   file's hash in `prepared.json`.
2. The brief lists every served proposal: title, mechanism, and the `METHODS` key to use with its `hypothesis_id`. It also
   gives the charter's summary.
3. `DEVELOPMENT_INSTRUCTIONS` shrinks to: fill `objective.py`; one function per proposal in `methods.py`; make
   `pytest libraries/<name>` pass; commit; `campaign_submit` with the report; raise the version on every redelivery. One
   paragraph keeps the optimizer_v1 route for methods that need it, pointing to `docs/optimizer-plugins.md`.
4. References are mentioned only when present: the generic brief names no grating repository or paper.
5. Under decision 9 the install refuses a library whose `charter.json` or `data.py` differ from the generated ones ("the library's
   data no longer matches the charter revision"), and lists every other generated file the agent changed
   (`changed_generated_files`).

**Tests**
- `prepare()` writes the scaffold once; a second `prepare()` keeps an edited file.
- The brief lists all served proposals.
- The install refuses an edited `data.py` and lists an edited `harness.py`.
- `DEVELOPMENT_INSTRUCTIONS` is shorter than at `cc0e693`.

**Done when** the tests pass.

### G1 — Baking order replayed offline

**Depends on:** A1–A3, B1–B6, C1–C2, D1–D3, E1–E5, F1, F3, F4. **Size:** M.

**Read first:** `tests/balsamic/test_e2e_fake_harness.py`, `tests/fake_harness.py`, `tests/test_library_install.py` (the
fake uv), `scripts/charter_test_fixtures.py`.

**`tests/test_baking_order_e2e.py`**
1. A permutation charter (8 bakes with durations and due dates; minimize total tardiness) with a declared evaluator.
2. Confirm it and create the campaign; a researcher turn records 4 proposals.
3. One compute plan (the workspace and 4 × 2 runs) is approved.
4. A fake coding agent fills the scaffold (the objective; earliest due date, swap search, random restarts, exact
   enumeration), commits and submits a `ready` report.
5. A fake uv installs it.

**Asserted**
- The problem is picked up and the task adopted (`provided_by`).
- The 4 proposals are bound by `balsamic`, and exactly 8 runs start under the one consent.
- Earliest due date and exact enumeration end as `method_finished`.
- The report and the ledger rank exact enumeration best (lowest tardiness).
- The researcher acted 3 times (the charter confirmation, one message, one decision), and the lead was woken once for the
  comparison.

**Playwright:** `charter.spec.ts` (the export), `evolution.spec.ts` (minimize order), `implementations.spec.ts` (a problem
from a library, automatic binding).

**Done when** the test and the specs pass.

### G2 — The same flow as a live quality scenario

**Depends on:** G1. **Size:** S.

**Read first:** `evals/lead/README.md`, `scripts/run_lead_evals.py`, `docs/suggestions.md` S7.

**Change:** `evals/lead/scenarios/charter-to-results.json`. Seed a confirmed small permutation charter, then say "Implement
earliest due date, swap search and exact enumeration, and compare them".
- Checks: one compute request; no binding by the lead; runs started by `balsamic`; a comparison report; two researcher actions
  after the seed (ask, approve); the lead's reply ranks by tardiness with the report's numbers.
- Record the time from the go-ahead to ranked results in the summary. If Q8 of suggestions.md is settled, grade the reply
  with its rubric.

**Done when** the scenario passes on Centinels (no approval needed) and its time is in the summary.

---

## 3. Order and parallel work

### 3.1 Waves

```
Wave 1  A1 (first) · A2 · A3 · A4 · B1 · B2 · B3 · B4 · B6 · C1 · C3 · D3 · E1 · E3 · F1
Wave 2  B5 (B2, B4) · C2 (C1) · D1 (A3) · E2 (E1) · F2 (F1)
Wave 3  D2 (D1) · E4 (E2, E3)
Wave 4  F3 (F1, D2, E2, C1) · B7 (B1, B2, B4, B5) · E5 (E4)
Wave 5  F4 (F3)
Wave 6  G1, then G2
Later: Phase 4 (the coding box) starts after F3 and F4
```

The critical path is A3 → D1 → D2 → F3 → F4 → G1. F1 and F2 meet the researcher's bar on their own (export the charter and
work locally), so they are worth shipping early.

### 3.2 Shared files: merge these parts one after another

| File | Parts |
|---|---|
| `agents/library_install.py` | A1, B4, E2, E5, F4 |
| `agents/development.py` | A1, A4, B2 (`create()` only), B3, B5, F4 |
| `campaigns/compute_consent.py` | B2, B5 |
| `campaigns/commands.py`, `contracts/commands.py` | B1, B2, B4, B5, B6, E4 |
| `execution/service.py` | D2, E4 |
| `campaigns/proposals.py` | B1, B4 |
| `analysis/general.py` | A2, A3 |
| `optimizers/packaged.py` | A3, C3 |
| `optimizers/lifecycle.py` | A3 (`AskTellAdapter`), C1 (`BoundedSearch`) |
| `optimizers/registry.py` | C1, C2 |
| `problem_charter/charter.py` | C1, D3, E3 |
| `agents/tools.py` | B6, B7 |
| `frontend/src/note/CharterPanel.tsx` | C1, F2 |
| `docs/optimizer-plugins.md` | A3, C3, D2, F4 |

---

## 4. Risks

- **Replay on resume** (D1): resuming costs the method's own compute again, and hidden nondeterminism only shows then. The
  hash check refuses the resume rather than continuing wrongly.
- **Agent code in the lab:** it runs in workers, as libraries already do. The `ast` listing and lazy imports keep it out of
  the server, and the generated adapter imports only generated modules.
- **The system actor** (B4, B5): its reach is two operations, each tied to an install or a consent, each with a receipt. A
  test pins that it can do nothing else.
- **Consent scoping** (B2): work that used to pass under another plan's leftover time is now refused. The refusal names the
  plan that would cover it, and old consents keep their campaign-wide reach.
- **Public configuration** (D3): methods see the instance's data. In optimization the instance is the input of the
  algorithm, so this is intended; fidelity and protected validation stay private.
- **Task adoption** (E4): it bumps the campaign version and opens a new study. Check the code that re-validates archived
  declared tasks through `TaskInput`.
- **Registry reload** (E1): it must never drop the lab's own modules; id clashes are refused at install (E2).
- **The automatic launcher** (B5): exactly the approved runs, never more; the command ids make a replay start nothing.
- **Lenient fields** (B6): a near-miss is always refused, so a misspelled field cannot silently change a run.
- **Prompt size:** new lead lines need offsetting cuts (B7, F4).

## 5. Verification

- **Per part:** its tests; then `GRATING_LLM_DISABLED=true uv run pytest -q` (rerun `tests/test_tracking.py` alone if it
  fails), `(cd agent-harness && npm test)`, and Playwright when the UI changed.
- **Live, after A1** (Hoseung): baking order's pending install completes and its four methods appear.
- **Live, after wave 5** (Hoseung): a new small campaign goes from charter to ranked results with three researcher actions;
  G2 records the time.

## 6. Out of scope here

- `docs/suggestions.md` S1 and S3–S7, except S2 (A4) and S7's scenario format (G2).
- A mandate for every request (Phase 3). B2 is the part of it this phase needs.
- The invariant register and the trap evals (Phase 2), the coding box (Phase 4), evidence gates (Phase 5),
  problem packs (Phase 6), one-shot roles and claim checks (Phase 7).
- The grating fallbacks in the core: `execution/service.py` L649, L941, L955 (`problems.resolve("meent_grating", …)`),
  L1362 (`dqn_meent.workspace.worker`), and `execution/rcwa_memory.py` (Phase 6, N5 and N7).

## 7. Critical files

- `src/optimization_framework/agents/library_install.py`, `agents/development.py`, `agents/development_runtime.py`
- `src/optimization_framework/execution/worker.py`, `optimizers/packaged.py`, new `optimizers/finish.py`,
  new `optimizers/functions.py`, `optimizers/registry.py`, `optimizers/conformance.py`
- `src/optimization_framework/evaluation/registry.py`, `contracts/problems.py`, `contracts/capabilities.py`,
  `contracts/problem_charter.py`
- `src/optimization_framework/problem_charter/charter.py`, new `problem_charter/scaffold.py`, `problem_charter/api.py`
- `src/optimization_framework/campaigns/compute_consent.py`, `campaigns/approvals.py`, `campaigns/proposals.py`,
  `campaigns/commands.py`, new `campaigns/plan_runs.py`, `campaigns/method_catalog.py`, `implementations/bridge.py`,
  `implementations/builtin.py`
- `src/balsamic/evolution/ledger.py`, `src/balsamic/api/evolution.py`, `src/balsamic/panels/service.py`,
  `analysis/general.py`
- `agents/tools.py` (`INSTRUCTIONS`), `src/balsamic/procedures/implementation-supervision/SKILL.md`
- `frontend/src/note/CharterPanel.tsx`, `frontend/src/evolution/EvolutionPage.tsx`, `frontend/src/hypotheses/Implementations.tsx`
