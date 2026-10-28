# Handoff: an algorithm library for Balsamic, and a catalog over it

Written 2026-10-28 from a working session on one machine, to be continued on another. It records what was tested, what was
found and changed, what was decided, and what is next. Nothing here is a roadmap item yet; the roadmap is
`docs/roadmap/`.

## 1. Goal

Turn the algorithm implementations that Balsamic's coding workspaces have produced (scattered across run folders and
worktrees, and more on a second machine) into **one reusable library of optimization methods**, then build a **catalog**
of what is available so that

- the **coder** (a coding workspace agent) knows what building blocks exist and writes a script around them instead of
  rewriting them, and
- the **hypothesis generator** can propose "test X, already installed" or "build Y from blocks A and B".

## 2. What was tested

A baking-order problem (8 orders, one oven, minimize total tardiness, in Korean) was run through Balsamic from Phase 2 to
Track L: charter, coding workspace, delivery, install, report, review. Three campaigns on this problem exist in the data:

| Campaign | Id | Package delivered | Methods |
|---|---|---|---|
| baking | `baking` | `single-oven-total-tardiness` 0.2.0 (failed install), 0.2.1 (installed) | `subset_dp_exact_scheduling`, `due_date_insertion`, `swap_insert_restarts`, plus the grating methods listed in the install record |
| 빵집 | `campaign` | 0.1.1 (never installed: validation failed) | DP, harness, comparison |
| campaign-2 | `campaign-2` | 0.1.1 (delivered 07:32 UTC; install failed on a protected test, see 4.3) | `oven_subset_dp`, `oven_mdd` |

Versions of Balsamic run, each on a copy of the previous data folder (the old one kept as a rollback):
`334cea8` (tag `phase-1`) → `975e935` (tag `phase-2`, which is *older* than `phase-1`: the tags look inverted) →
`36dd27c` (Phase 5 release) → `1dd7aa3` (Phases 6 and 7 released) → `c6c4c32` (Track L, "code libraries that last").

## 3. How to run what was run

```bash
uv sync --extra dev --extra libraries
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
docker build -t grating-implementation-workspace:pi-1.3.0 deploy/implementation-workspace   # coding workspaces
GRATING_DEVELOPMENT_ENABLED=true scripts/start --no-tailnet --dir runs/live
```

Notes:
- Coding workspaces are off unless `GRATING_DEVELOPMENT_ENABLED=true`. With them off, the lead falls back to
  `implementation.commission`, which fails if the problem's evaluator is not already an installed package.
- Validation outside the box needs `bubblewrap` (`bwrap`).
- The harness reads the researcher's own Pi setup (`~/.pi/agent/models.json`, `auth.json`). A model failure ("Model
  unavailable", "No API key found for <provider>") was a Pi configuration problem, not a Balsamic one. The error text
  appears only in `runs/<dir>/pi/<lead>/events.jsonl`; the chat shows a generic message.
- `scripts/stop` does not stop the services (it records the `setsid` wrapper's pid). Kill the listeners by pid
  (`ss -ltnp | grep :<port>`), or `scripts/start` finds the old stack healthy and reuses it, so restarts do nothing.
- Port 8765 may be held by another project; `BALSAMIC_PORT`, `BALSAMIC_LIBRARY_PORT`, `BALSAMIC_PI_PORT` change them.

## 4. Findings

### 4.1 Reuse across campaigns does not work (issue #101)
A new campaign could not find the previous campaign's delivered implementation or evaluator.
- A coding-workspace delivery has no `version_id`, which `implementation.attach` and `evaluator.attach` need.
- The install put the package into one checkout's `.venv` and `libraries/` (untracked), so another worktree did not have it.
- The evaluator was never a deliverable: the first package registered only the `optimization_framework.optimizers` entry
  point. Only `campaign-2`'s delivery also registers a problem adapter.
- Track L (L1 to L6) addresses part of this but assumes the lab already holds the library. `base` was null in all three
  workspaces, so "builds on the latest installed version" never applied. The live workspace rebuilt the DP and the
  due-date construction that 0.2.1 already had.

### 4.2 Validation outside the box failed for every delivery on this machine (fixed here)
`No module named 'encodings'` when the sandbox started Python. Cause: with uv-managed Python the venv's interpreter is a
link into `cpython-3.13-...`, itself a symlinked directory; the sandbox bound only the single file at that path, so Python
could not find its standard library. Reproduced with the repo's own builder; fixed in
`src/optimization_framework/agents/library_validation.py` (the link is recreated in the sandbox) with a regression test.
After the fix the sandbox ran `campaign-2`'s delivery: 50 of 50 library tests, both methods host-conformant, 4 of 5
protected tests passed.

### 4.3 A protected test from another campaign blocked an install (not fixed)
What "protected" means: the implementation lead writes acceptance tests the **coding agent cannot see**. Their source is
stored on the host (`development_protected_test` records), never written into the workspace or the ticket, and Balsamic
runs them in the sandbox on every delivery, reporting only name and pass or fail. It stops the coder from passing only its
own tests.

Track L's L4 runs every earlier workspace's protected tests against the same library name. `빵집`'s protected test
(`test_independent_oven.py::test_relative_clock_and_invalid_permutations`) calls the evaluator with that campaign's own
variable names (`p_bread`, `d_bread`, `order_names`, `start_minutes`). `campaign-2` has the same problem id with other
variable names, so the evaluator answers `single_oven_total_tardiness has no field d_bagel, ...`. The test checks naming,
not behaviour. I did not remove or edit the test.

### 4.4 Other defects seen on `36dd27c` / `c6c4c32` (issues filed)
- #95: Files → Reports rows are not clickable (only the small "open" link), reports are named by hash, and "nothing to fix"
  marks nothing final and tells nobody.
- #98: after "Submit feedback" there is no visible next step. A revision is a second action, the button
  "Revise draft with writer", at the bottom of the sidebar. It exists and works in Chrome at 1400x900.
- #70 (the `centinels` dev profile) was fixed on `main` (`4da0f04`); the report there is probably obsolete.

### 4.5 Implementation speed
Measured per coding workspace (first code written, submission): `baking` 1.2 / 8.7 min, `빵집` 2.6 / 5.5 min,
`campaign-2` 7.1 / about 13 min. The newest workspace spent seven minutes orienting, restarted the agent five times in
nine minutes (each restart rereads the ticket, about 43k cached tokens), made four `read` calls without a `path`, and hit
`uv: command not found` inside the image although the ticket tells the agent to run `uv`. Dependency installs were not the
main cost.

## 5. Changes made on this branch

| Change | Where |
|---|---|
| Sandbox symlink fix | `src/optimization_framework/agents/library_validation.py`, test in `tests/test_library_validation.py` |
| Warm start: a new workspace's home takes the package caches and installed packages (`.cache`, `.local/lib`, `.local/bin`) from the newest earlier workspace whose library has the same dependency names; writes `home/.warm_from`. Not exercised live yet | `DockerWorkspace.warm()`, `dependency_names()` in `src/optimization_framework/agents/development_runtime.py`, `tests/test_development_warm_home.py` |
| The `baking` 0.2.1 package installed as a library of this checkout | `libraries/single_oven_total_tardiness/`, `pyproject.toml` (`libraries` extra, `tool.uv.sources`), `uv.lock` |
| The three oven implementations archived as plain source (they exist only in run folders) | `docs/handoff/algorithm-library/sources/{baking-0.2.1,bbangjip-0.1.1,campaign-2-0.1.1}/` |

Test results: `tests/test_library_validation.py` (9), `tests/test_development_warm_home.py` (3),
`tests/test_pi_development_workspaces.py`, `tests/test_own_session.py`, `tests/test_development_ticket.py` pass (41 in the
combined run). The warm start has no live check.

## 6. Design direction (agreed in the session)

Rejected: a thin "binding" per campaign inside the shared library. It copies each campaign's variable names into the
package, which caused 4.3. A data scientist writing a statistics script builds around SciPy; there is no binding.

Agreed:
1. The library holds **building blocks**: plain functions with typed signatures and a one-line docstring each (for example
   `subset_dp(p, d)`, `due_date_insertion(...)`, `total_tardiness(perm, p, d)`), with no campaign variable names.
2. A campaign writes **its own script** around them. The small glue Balsamic's runner needs (host evaluation, charging,
   caching) belongs to the campaign, not the shared package. A thin wrapper is for *extending* an algorithm, in the new
   campaign.
3. Protected tests check the blocks (DP optimum, objective value), so they hold for every campaign.
4. A **catalog** built from the code (docstrings and signatures: name, signature, purpose, problem family, version, source
   campaign) goes to the coder (a short summary in `TASK.md` plus a tool for the full docstring, like an MCP router's tool
   listing) and to the hypothesis generator. A required one-line docstring on public functions, checked at install, keeps
   it from going stale. Reuse-first (L5, refuse a workspace for an installed method) stays.

What exists today (L5): the method list names each method's package and version, and a workspace for an installed named
method is refused with "bind it instead". Nothing lists building blocks, and neither the coder nor the hypothesis
generator sees them.

## 7. Inventory of implementations (this machine)

Run folders hold many duplicate copies of the same three workspaces (from copying data between versions). Distinct sources:

- **Balsamic built-ins**, `src/optimization_framework/optimizers/` (15): `random`, `swap_search`, `coordinate`,
  `enumerate`, `hillclimb`, `annealing`, `block_tabu`, `population`, `surrogate`, `refinement`, `dqn`, and the
  infrastructure entries `evaluate_asset`, `replay`, `artifact_inference`, `frozen_policy`. Tied to the framework's
  optimizer interface, not standalone.
- **`libraries/grating-mask-search`** 0.1.2 (tracked): `conditional_mirror_search`, `cyclic_geometric_vnd`,
  `elite_spread_relinking`.
- **Single-oven total tardiness, three independent implementations**, archived in `sources/`:
  `baking-0.2.1` (990 lines), `bbangjip-0.1.1` (1,149 lines), `campaign-2-0.1.1` (1,459 lines).
- **Outside Balsamic, under `~/Work`**: `flrl` (8 files, grating scripts with autograd), `dqn-meent-framework` (80 files),
  `math_opt` (6 scripts, marimo notebooks), `genui_opt_demo` (61 files), and `mask-optimizers` (kc-ml2, a git dependency).
  Research code rather than reusable blocks; needs triage, not bulk import.

More algorithms are on the second machine; list them in the same shape (source, what it solves, size, tests, whether it
runs).

## 8. Plan

1. **One library repo**, one package per family (for example `permutation-scheduling`, `grating-mask-search`), local git
   first. Location and name still to decide (proposal: `~/Work/balsamic-libraries`).
2. **Merge the three oven implementations, using each as the others' oracle.** Run all three on random instances and
   compare optimum and objective values; where they disagree one is wrong. Keep the best-tested version of each block and
   keep the others' tests as extra cross-checks. Write the merge as new code; leave the sources untouched.
3. **Catalog generator** reading docstrings and signatures into `catalog.json`; put its summary in `TASK.md` and expose a
   catalog tool to the coder, then the hypothesis generator, then the docstring rule at install.
4. Catalog Balsamic's built-ins in place (no refactor of the framework's optimizers).
5. Triage the external repos and the second machine's algorithms.

## 9. Open decisions

- Library repo location and name, and local-only or GitHub.
- Order: oven merge, then `grating-mask-search`, then the catalog, then built-ins and external code?
- The protected-test conflict in 4.3: under the building-block design, tests for the blocks are shared and a campaign's
  own tests stay with it. The `빵집` test needs a decision (keep with its campaign, or rewrite at block level). Not
  removed.
- Whether to file the design as roadmap items; no issue was filed for it on request.

## 10. State on the first machine

Not on this branch (run data is gitignored): `~/Work/Balsamic-track-l/runs/live` (campaigns `baking`, `빵집`,
`campaign-2`, three coding workspaces), earlier data copies in `Balsamic-latest/runs/live`, `Balsamic-phase-5/runs/p5`,
`Balsamic-phase-2/runs/p2`. `campaign-2`'s delivery is validated but not installed (4.3).

## 11. Continued on the second machine (28 October 2026)

### 11.1 Inventory of this machine
Under `~/Work/*balsamic*`: `kc-ml2-Balsamic` (`workspace-rebuild`, `cc0e693`, the dev stack on `runs/dev`), `balsamic-a7e89b8`
(an eval worktree, no run data) and `__Balsamic_old` (the September Balsamic). In the shape asked for in 7:

| Source | What it solves | Size | Tests | Runs |
|---|---|---|---|---|
| `baking-order-search` 0.1.0, campaign `baking-order`, workspace `development_822ace016be592390fecb2ee`, commit `435a729` | The same bakery problem (8 orders from 06:00; problem id `single_oven_total_pickup_tardiness`): adjacent best improvement, uniform random orders, subset DP, DFS branch and bound, and an `evaluator_v1` evaluator (no `optimization_framework.problems` entry point) | 2,215 lines | 32, pass | Yes. Not installed: its automatic install waited for a confirmation of "`balsamic` 0.3.0 → removed", the editable reinstall of the lab's own project, which this branch's parser no longer counts (`lab_projects`, `Installer.reparsed`) |
| H12, H13, H14, campaign `2d-gratnig`, three workspaces | Binary masks for the deflector | 600, 672, 607 lines | own tests | Already merged as `libraries/grating-mask-search` 0.1.2; the workspace copies lack its later fixes (export kinds, bounded inspection) |
| `__Balsamic_old/runs/campaigns/phase0-*` | Tuning flrl's hyperparameters | — | — | No algorithm of its own: flrl and MEENT snapshots |

### 11.2 The library repository (plan steps 1 and 2)
`~/Work/balsamic-libraries`, the issue's and 8's proposal, pushed to the private repository
`https://github.com/HoseungChoi51/balsamic-libraries` (9's open decision, settled 28 October), one directory per package,
tags `<directory>-v<version>`: `permutation-scheduling-v0.1.0`, `single_oven_total_tardiness-v0.2.1`,
`grating-mask-search-v0.1.2`. `permutation-scheduling` is the oven merge as building blocks (objective, exhaustive, subset DP,
branch and bound, EDD, MDD, due-date insertion, adjacent descent, swap-and-insert search, uniform orders), new code with
neutral names, each block from the implementation that tested it best (`PROVENANCE.md`). `tools/golden_from_sources.py` ran
the four implementations side by side on 61 instances: every exact solver agreed on every optimum (15 on the campaigns'
instance), and the four subset DPs break ties alike; the new blocks reproduce every source's output (567 tests, among them
step-by-step parity with Balsamic's built-in `swap_search`). `tools/catalog.py` writes `CATALOG.md` from the code and checks
that each public name has a docstring (the two delivered libraries have 27 without; their next versions can add them).
`빵집`'s and `campaign-2`'s 0.1.1 are not in the repository: both are `single-oven-total-tardiness` 0.1.1 with different code,
never installed, and kept as sources here.

### 11.3 Issue #101, resolved on this branch
| Requested | What this branch does |
|---|---|
| A reuse path that needs no ids | The `lab_packages` tool (lead, implementation lead; `campaigns/lab_packages.py`): every package the lab has a version of, from any campaign, with versions, methods, problems, the campaigns it came from, its `library_version_id`, where its methods run here and why it concerns this campaign; and the shared repository's building blocks with signatures. The lead's state block names the matches every turn; the implementation procedure starts with it |
| A version identity attach accepts | A delivery's identity is its `library_version` (Track L). `campaign.adopt_problem` takes `library_version_id` (or an install id, from any campaign). `implementation.attach` and `evaluator.attach` given a library id are refused with the command that reuses it (`bind_builtin`, `adopt_problem`). The texts that sent agents to "attach a validated evaluator version" now point to reuse |
| Install into a durable library repository | Every install publishes its version to the shared repository (`agents/shared_libraries.py`; `BALSAMIC_LIBRARY_REPOSITORY`, else `balsamic-libraries` beside the checkout) and records `published`. At start the lab restores what a checkout lacks (`library_install.restore()`): recorded libraries from their tags, the shared repository's packages pinned to their tags (`{ git = "file://…", subdirectory, tag }`), one `uv lock` and `uv sync`, then `import_lab`, so L3's `base` is no longer null until the Packages page is opened |
| The evaluator as a problem package | Already so for a declared problem (the generated library registers `optimization_framework.problems`; a charter naming an installed problem id reuses it, `evaluator.provided`). The commission ticket now says to keep the entry point so later campaigns reuse it; the formulator's `problem_catalog` names the package of each installed problem |
| Tell the lead and the researcher | Once per campaign and package version, a line in the researcher's conversation and a notice to the lead, for a package that provides a problem the campaign names, whose library carries that problem's name, or whose methods run on its tasks; not for a package only that campaign built |

Tests: `tests/test_library_reuse_across_campaigns.py` (18). Tests never touch the researcher's repository (`tests/conftest.py`
sets `BALSAMIC_LIBRARY_REPOSITORY=off`).

### 11.4 Findings on this machine
- `scipy` is declared only in the `meent` extra, but the charter compiler imports it (`problem_charter/charter.py`
  `feasibility`, `brentq`): with 3's `uv sync --extra dev --extra libraries` 20 tests error and 36 fail. Sync as the dev
  checkout is: `--extra dev --extra libraries --extra meent --extra learners --extra masks`.
- pytest's temporary folders live in `/tmp`, a RAM-backed tmpfs of 1,048,576 inodes here: one full run writes about 350,000
  files (5 GB), and earlier runs' folders had filled it (no file could be made in `/tmp`). Run the suite with
  `TMPDIR` on disk.
- Two libraries' `tests/test_contract.py` cannot be collected in one pytest run; the library repository uses
  `--import-mode=importlib`. `baking-0.2.1`'s `test_vendored_source_identical` passes only inside a Balsamic checkout's
  `libraries/`.

### 11.5 Next
1. Check the docstring rule at install (`tools/catalog.py --check`). A coding box now imports the shared repository's building
   blocks (11.6).
2. Restore pins every package of the shared repository into every lab; decide whether a lab takes only those whose problems
   or methods concern its campaigns.
3. On the other machine: `git clone https://github.com/HoseungChoi51/balsamic-libraries ~/Work/balsamic-libraries` (beside
   the checkout, or set `BALSAMIC_LIBRARY_REPOSITORY`). Balsamic commits and tags each installed version there but never pushes:
   `git -C ~/Work/balsamic-libraries push --follow-tags` carries new versions to the other machine.
4. 4.3 stays open: the procedure now asks for protected tests written as behaviour, not a campaign's variable names, but
   `빵집`'s test is unchanged.

### 11.6 A coding box imports the building blocks
A box's Python is the image's (3.12, with numpy, scipy, meent and pytest), it mounts only its own folders, and it reaches only
the model's host and PyPI, so it could not import the shared repository's packages. Now the ticket names the building blocks
(packages with neither methods nor problems) at their latest tags; Balsamic exports them into the workspace's `blocks/`,
mounts that read-only at `/opt/libraries` and adds a `.pth` to the box's home, and `TASK.md` lists their functions and the
dependency to declare. Validation outside the box mounts the same copy, and the install pins the dependency to that tag. The
ticket's test command is now `python -m pytest` (the image has no uv, 4.5). No image rebuild is needed. Tests:
`tests/test_development_building_blocks.py` (8, one in the real sandbox); live, a box started from the real image imports
`permutation_scheduling` from `/opt/libraries` and runs its 567 tests (566 pass; the parity test with Balsamic's built-in is
skipped, Balsamic not being importable there).
