# Handoff: the state of the roadmap work on this fork

Written on 27 October 2026 when Phase 4 completed, and updated on 28 October 2026 (about 02:30 UTC) when Phases 5, 6
and 7 were released, for an agent taking over `HoseungChoi51/Balsamic` with none of the earlier context. Everything below
was checked against GitHub and `main` at `77b6e9f`. PR states move:
check them again before acting (`git fetch` and the PR list), and trust GitHub over this page.

## 1. What this is

Balsamic is a research harness in which a researcher and a team of LLM agents (Pi agents) develop problem-specific
optimizers: the researcher writes a charter for a problem, a lead agent turns requests into proposals, coding workspaces,
runs and comparisons. Start with `README.md`, `docs/ui-workspace.md` and `docs/pi-agent-harness.md`. `docs/status.md` is
the status page (its phase table is updated by the part that completes a phase).

This repository is Hoseung's fork of `kc-ml2/Balsamic`. Its `main` started as kc-ml2's `workspace-rebuild` branch
(`af41ae7`). Work happens only here, on `main`; the Claude GitHub app cannot write to kc-ml2.

**Hoseung** (GitHub `HoseungChoi51`) owns the project. They do not read code changes: they judge each phase by using the
app, from a user acceptance test (UAT) checklist. Decisions only they can make go to them as one question with a
recommended option; everything else, including merge conflicts, you handle yourself.

## 2. The roadmap

`docs/roadmap/` holds the plan: `README.md` (instructions for coding agents in §0, principles §1, decisions §2) and one
file per phase. 78 parts, each a letter (its track) and a number. Decisions 1–24 in README §2 are settled: do not reopen
them; ask Hoseung when a part needs a choice §2 does not cover. Line numbers in the roadmap refer to `cc0e693`; find code by
function name.

| Phase | Goal | State | Release | File |
|---|---|---|---|---|
| 1 | Charter to results | Complete | `phase-1` (`334cea8`) | `phase-1-charter-to-results.md` |
| 2 | Measure first: invariant register, trap evals, the eval baseline | Complete | `phase-2` (`975e935`); `baseline` (`61538de`) | `phase-2-measure-first.md` |
| 3 | A mandate for every request | Complete | `phase-3` on `077473f`, tag to create (Hoseung) | `phase-3-mandates.md` |
| 4 | The coding box | Complete | `phase-4` on `a0085b3`, tag to create (Hoseung) | `phase-4-coding-box.md` |
| 5 | Evidence gates | Complete | `phase-5` on `3d27d46`, tag to create (Hoseung) | `phase-5-evidence-gates.md` |
| 6 | Problem packs; every algorithm family on fair terms | Complete | `phase-6` on `77b6e9f`, tag to create (Hoseung) | `phase-6-problem-packs.md` |
| 7 | Fewer standing agents, claims that resolve | Complete | `phase-7` on `0fd9b0e`, tag to create (Hoseung) | `phase-7-agents-and-claims.md` |

The parts: Phase 1 A1–A4, B1–B7, C1–C3, D1–D3, E1–E5, F1–F4, G1–G2; Phase 2 I1–I3, J1–J4; Phase 3 R1–R7; Phase 4 H1–H8;
Phase 5 V1–V5; Phase 6 N1–N15; Phase 7 T1–T4, K1–K4.

All 78 parts are merged and every phase is released (Phase 7 was released before Phase 6, which waited on decision 20).
No roadmap work is left. What remains is Hoseung's: the tags, the UAT checklists and the live evals (§6). Work after that
starts from Hoseung's findings, or from a new part added to the roadmap. Each phase file ends with "Order and shared
files": the waves inside the phase and the files its parts share.

## 3. How the work is run

- **One part = one branch = one PR into `main`.** The PR title is commit-style with the part id, e.g.
  `feat(mandates): mandate_propose, the lead's first act on a request (roadmap R2)`. The body says what was wrong, what
  changed, how each "Done when" item holds, the test commands and counts on the PR's head, what is not done, and the
  acceptance test. Assign Hoseung (a review request fails because PRs are opened under their account). Good models: #69
  (R3), #67 (H6).
- **The fork has no CI.** The test counts in the PR, run on a head that contains the latest `main`, are the evidence.
- **Readiness file per part:** `docs/readiness/<id>.md`, format in `docs/readiness/README.md`: a State line, then What
  was wrong (with `Layer:` and `Invariant:` lines) / What changed / Checked / Not done / Acceptance test. The acceptance
  test is written for someone using the app (where to go, what to do, what to see), never code. Do not add lettered Parts
  to `docs/lead-agent-readiness.md`.
- **Invariants (changed on 27 October, #76):** numbered rows (INV-01 to INV-32) stay in `docs/invariants.md` and are edited
  in place. A part's new rows are `INV-<part>-<n>` in the part's own file, `docs/invariants/<part>.md` (one table, the
  register's columns; copy the header of an existing file). `tests/test_invariants.py` reads all the files and fails on a
  keyed row in the numbered table, a part file holding another part's id, an id in two files, or a pin that does not exist.
- **MEENT's pack (changed on 27 October, #76):** one module per part, `src/dqn_meent/pack/<part>_<topic>.py`, defining
  `CONTRIBUTION` (a mapping of `ProblemPack` fields); `pack/__init__.py` assembles them in name order (lists joined,
  mappings merged, a key two modules both set refused). N4's is `n4_tools.py`.
- **Phase 3's mandate guard applies to every agent command.** The bus checks an agent's command (actor `manager` and
  `autopilot`) against its request's mandate (`campaigns/mandates.py` `require()`, `governing()`). With no mandate a request
  has Explore, which does not allow `implement`, `decide` or `configure` work (stops, promotions, adopting a library's
  problem, coding workspaces, experiment rules). Tests that drive agents through such work grant a mandate first:
  `tests/test_mandates.py` `granted(workspace, campaign_id, template="run_campaign", root=None, worker_seconds=0.0)`.
- **Merging:** PRs merge without code review once (1) they merge cleanly and contain the latest `main`, (2) the full suite
  passed on that head with only the known flakes, (3) a PR sharing a file with something merged since its test run has had
  `scripts/test-changed` run on its head, (4) it is not a draft and not waiting on Hoseung. One at a time, merge commits.
  If a merge breaks `main`, revert it at once. The full policy is `docs/releases/README.md`.
- **Conflicts:** the PR's owner fixes its own conflicts without asking: `git merge origin/main` (never a rebase or force
  push on a shared branch; force pushes are refused in cloud sessions), then rerun the tests the conflict touched. A
  release manager may merge `main` into a ready PR itself when the part's thread is idle, then run `scripts/test-changed`
  (or the full suite when both sides changed the same code) before merging.
- **Releases:** when every part of a phase has merged, run the full suite on `main`, then add `docs/releases/phase-<n>.md`
  (template in `docs/releases/README.md`) in its own PR with the phase table of `docs/status.md`, and merge it. Cloud
  sessions cannot push tags, so tell Hoseung the commit to tag (`git tag -a phase-<n> <commit> -m "Phase <n>: <goal>"`).
- **No model calls and no live lab.** Tests run with `GRATING_LLM_DISABLED=true`. Live checks and live evals (on the
  Centinels provider, which needs no approval; any other provider needs Hoseung's) are Hoseung's and go in the release's
  UAT. Phases 3, 4, 5 and 7 (except K1–K3) are judged against the eval baseline at `61538de`.
- **Parallel parts.** Parts that do not depend on each other can be built at once by agents in their own git worktrees,
  each on its own branch; merge them one at a time, bringing `main` into each before its merge. The phase files list the
  files parts share. Verify each from the main checkout before merging (§5). A container restart stops background agents
  but keeps their worktrees: commit what a worktree holds as a WIP commit, push it, and resume the agent (or a new one)
  from there; H8 was finished that way.

## 4. Status, phase by phase

All phases are complete. The parts' PRs, by phase:

| Phase | Parts (PR) | Release notes |
|---|---|---|
| 1 | 28 parts, A1–G2 | `docs/releases/phase-1.md` (#66) |
| 2 | I1–I3, J1–J4 | `docs/releases/phase-2.md` (#61) |
| 3 | R1 #33, R5 #56, R2 #60, R3 #69, R6 #72, R4 #73, R7 #74 | `docs/releases/phase-3.md` (#75) |
| 4 | H1 #54, H5 #41, H3 #77, H2 #78, H6 #67, H4 #79, H7 #80, H8 #81 | `docs/releases/phase-4.md` (#82) |
| 5 | V3 #43, V4 #38, V1 #32, V2 #84, V5 #90 | `docs/releases/phase-5.md` (#92) |
| 6 | N1 #30, N2 #31, N4 #51, N8 #46, N15 #39, N5 #49, N7 #52, N3 #48, N11 #53, N6 #47, N13 #86, N14 #87, N9 #94, N10 #96, N12 #97 | `docs/releases/phase-6.md` (#99) |
| 7 | K1 #34, K3 #37, K2 #59, T2 #44, T1 #85, T3 #88, K4 #89, T4 #91 | `docs/releases/phase-7.md` (#93) |

Also merged on 27 October: #71 (issue #70: the dev profile's Centinels provider is defined by
`agent-harness/profiles/dev/models.template.json` from `CENTINELS_BASE_URL` and `CENTINELS_API_KEY` in
`~/.config/balsamic/secrets.env`) and #76 (the per-part invariant files and pack modules).

**Decisions Hoseung took beyond the roadmap's §2:**
- R7 (27 October): the chat's mandate dial starts at the campaign's default template, which follows `autonomy` (delegated →
  Screen; starting the agent team sets delegated, so most campaigns start at Screen). A Screen or Run the campaign granted
  with a chat message covers only its own request (`request_only` consents); agent cards keep decision 4.
- Decision 20 (28 October, 01:16 UTC): confirmed. "I have done an example problem end to end in phase 1/2. The workflow
  was smooth." That released N9, N10 and N12.

**Choices the parts made where the roadmap was open** (each part's readiness file lists its own). In Phase 3, a request's
own newest mandate governs it, and once that mandate has ended only answering, asking and recording are allowed (R3). A
request never narrows its own mandate and has one Explore (R3). Experiment rules and hiding runs stay `configure`, which only
Run the campaign allows, because the short-run threshold is part of decision 14's assessment minimums. `issue.resolve`
moved to `record` and `resources.plan` to `run` (R3). Outcomes of work the researcher started directly wake nobody (R6).
Autopilot's mandate is closed only by switching autopilot off (R4, R7).

In Phase 4, a commission runs as a headless coding box only when coding workspaces are on, and needs at least one protected
test (H7). Three requests are refused with what to do instead rather than sent to the retired service: a commission with
coding workspaces off, one that imports a package, and an evaluator for a task no charter declares (H8). A commission's
compute is charged once, at the command (H7).

In Phases 5–7, V2 closes INV-15, the last row at `none`, so `tests/test_invariants.py` accepts a register with no row left
at `none`. N13's refusal of more time after a checked proof applies only to the proved task, so "Run on the next size"
(N14) stays allowed. INV-13 (T2) and INV-19 (K2) stay `prompt`: both are badged, never refused.

**Open, decided by Hoseung's live comparisons:**
- ADR 0009 (T3: one-shot review specialists, and the harness plan's D2, one merged analyst) is Proposed. Until the three-arm
  comparison runs, the proposal reviewer and both specialists are one call each (`DEFAULT_ONE_SHOT`).
- ADR 0010 (T4: page agents folded into the lead) is Proposed. Until the comparison runs, the page agents stand
  (`GRATING_PAGE_AGENTS=standing`). The fold itself, which removes a session and its page's routing, is a new part, added
  to the roadmap once Hoseung accepts the ADR.

## 5. Testing fast in a cloud container

`.claude/hooks/session-start.sh` runs at the start of a cloud session (`CLAUDE_CODE_REMOTE=true`): it installs
bubblewrap, `uv sync --extra dev`, then scipy, matplotlib and pytest-xdist into `.venv`, makes the checkout readable by
the normal user, and sets `GRATING_LLM_DISABLED=true`. In a session that started without it, run
`CLAUDE_PROJECT_DIR=$PWD bash .claude/hooks/session-start.sh` from the checkout (without the variable it fails with
`unbound variable`).

```bash
scripts/test-changed                 # changed tests + tests importing changed src modules, in parallel (vs origin/main)
scripts/test-changed --list          # just list them (it includes the launcher's tests, which refuse root: run those apart)
# the full suite, about 6 minutes with -n 4; run once on a PR's head
GRATING_LLM_DISABLED=true .venv/bin/python -m pytest -q -n 4 --dist worksteal -p no:warnings --ignore=tests/test_server_launcher.py
# the launcher refuses root, so its tests run as the container's user `claude`
runuser -u claude -- env HOME=/home/claude GRATING_LLM_DISABLED=true .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_server_launcher.py
(cd agent-harness && npm ci && npm test)
(cd frontend && npm ci && npx tsc -b && npx playwright test)   # when the UI changes; then git checkout frontend/tsconfig.tsbuildinfo
.venv/bin/python scripts/run_lead_evals.py --fake               # eval plumbing, no model calls
```

- Last full run: on `main` at `e92acd5` (N12, the last part) with Phase 6's notes, from the main checkout: 1522 passed,
  93 skipped, 0 failed, in about 6 minutes with `-n 4`.
- **Playwright** needs Chrome: `CHROME_PATH=$(ls -d /opt/pw-browsers/chromium-*/chrome-linux64/chrome | head -1)`. When
  another agent's dev server holds port 5173, the default config reuses it and tests the wrong checkout: use a temporary
  config on a free port (`webServer: npx vite --port <n> --strictPort`, `reuseExistingServer: false`) and delete it after.
- **Worktrees.** An agent in a git worktree can share the main checkout's `.venv` (pytest's `pythonpath` puts the
  worktree's `src` first, so run `/home/user/Balsamic/.venv/bin/python -m pytest` from the worktree root; never `uv sync`
  there). Two things differ: `tests/test_pi_agents.py::test_an_agent_analyses_its_experiments_with_its_own_script_in_a_sandbox`
  fails (the sandbox does not mount the venv's editable `src`), and `runuser` is refused; run both from the main checkout
  before merging. Keep worktrees out of commits (`.claude/worktrees/` in `.git/info/exclude`).
- `scripts/test-changed` misses tests that reach a changed module only through another one; the full run catches them.
- **Known flakes**, rerun before treating them as yours: `tests/test_tracking.py`;
  `tests/test_framework_isolated_host.py::test_supervisor_death_retains_committed_evidence_and_reconciles_without_execution`
  (fails about 2 runs in 3 even alone); under heavy load, `tests/balsamic/test_e2e_fake_harness.py` and
  `tests/balsamic/test_partnership.py` can time out and pass alone.
- **Docker** is not available in the cloud container: the coding box's tests use fake drivers, and its live checks are
  Hoseung's.
- **Stale `.venv` after an entry point changes:** when `main` adds an entry point to `pyproject.toml`, tests fail with
  errors such as `KeyError: 'flrl'`. Run `uv pip install --python .venv/bin/python -e . --no-deps`. Avoid a plain `uv sync`,
  which removes scipy and matplotlib (reinstall them if you do).
- `chown -R claude .` on the checkout breaks root's git ("dubious ownership"); undo with `chown -R root:root .`.
- scipy and matplotlib are installed by hand because the `meent` extra pulls `meent` from a private repository the cloud
  cannot reach; MEENT tests skip. `uv lock` fails for the same reason, so pytest-xdist is not in the dev extra.

## 6. Open for Hoseung

1. Tag `phase-3` on `077473f`, `phase-4` on `a0085b3`, `phase-5` on `3d27d46`, `phase-6` on `77b6e9f` and `phase-7` on
   `0fd9b0e`.
2. The UAT checklists of `docs/releases/phase-1.md` to `phase-7.md`. Hoseung reported on 28 October that an example
   problem ran end to end on Phases 1 and 2 ("The workflow was smooth").
3. The live evals, on Centinels, each against the `baseline` tag:
   - G2's live run of S19 (`docs/readiness/G2.md`), from a separate worktree, because a live S19 run installs into its
     checkout.
   - Phase 3's S1–S15.
   - Phase 4's J4, on the ticket route and headless.
   - Phase 5's S13, S14 and S15.
   - Phase 6's S17.
   - Phase 7's S12, S14 and S16, then T3's three arms and T4's two arms, which settle ADR 0009 and ADR 0010.
4. Rebuild the coding-workspace image before trying Phase 4 or later.
5. Before running Phase 6 or later on the live lab, run N7's migration on a copy of the data folder:
   `python -m optimization_framework.execution.problem_migration <copy>`. Expect an empty `unresolved` list.

## 7. Next steps, in order

1. Remind Hoseung of the tags (§6.1) if they have not been created (`git ls-remote --tags origin`).
2. Act on what Hoseung reports from the UAT and the live evals. Each finding is a fix PR under the rules of §3, or a new
   roadmap part when it needs a choice §2 does not cover. Ask Hoseung that choice as one question with a recommended
   option.
3. When ADR 0009 or ADR 0010 is decided, apply its result: the default in `DEFAULT_ONE_SHOT`, or a new part for the fold.
   Record the measurements in the parts' readiness files.
4. Keep `docs/status.md` and this page current when a phase-level fact changes.
