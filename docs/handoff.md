# Handoff: the state of the roadmap work on this fork

Written on 27 October 2026 (22:30 UTC), when Phase 4 completed, for an agent taking over `HoseungChoi51/Balsamic`
with none of the earlier context. Everything below was checked against GitHub and `main` at `a0085b3`. PR states move:
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
| 5 | Evidence gates | V3 merged; V1, V4 open; V2, V5 not started | — | `phase-5-evidence-gates.md` |
| 6 | Problem packs; every algorithm family on fair terms | N1, N2, N4, N8, N15 merged; N3, N5, N6, N7, N11 open; N9, N10, N12, N13, N14 not started | — | `phase-6-problem-packs.md` |
| 7 | Fewer standing agents, claims that resolve | K1, K3 merged; T2, K2 open; T1, T3, T4, K4 not started | — | `phase-7-agents-and-claims.md` |

The parts: Phase 1 A1–A4, B1–B7, C1–C3, D1–D3, E1–E5, F1–F4, G1–G2; Phase 2 I1–I3, J1–J4; Phase 3 R1–R7; Phase 4 H1–H8;
Phase 5 V1–V5; Phase 6 N1–N15; Phase 7 T1–T4, K1–K4.

Hoseung paused Phases 4–7 on 27 October ("Complete phase 3. Phase 4 waits."), then resumed them ("Keep working on Phase
4-7"), and asked for this handoff once Phase 4 was ready. Phases 5–7 are resumed and are the next agent's work. Each phase
file ends with "Order and shared files": the waves inside the phase and the files its parts share.

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
  `tests/test_mandates.py` `granted(workspace, campaign_id, template="run_campaign", root=None, worker_seconds=0.0)`. Older
  open PRs were written before this and need it when they merge `main`.
- **Merging:** PRs merge without code review once (1) they merge cleanly and contain the latest `main`, (2) the full suite
  passed on that head with only the known flakes, (3) a PR sharing a file with something merged since its test run has had
  `scripts/test-changed` run on its head, (4) it is not a draft and not waiting on Hoseung. One at a time, merge commits.
  If a merge breaks `main`, revert it at once. The full policy is `docs/releases/README.md`.
- **Conflicts:** the PR's owner fixes its own conflicts without asking: `git merge origin/main` (never a rebase or force
  push on a shared branch; force pushes are refused in cloud sessions), then rerun the tests the conflict touched. The
  owners of the open Phase 5–7 PRs are gone: you are their owner now.
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

### Phases 1–4: complete

| Release | Commit on `main` | Notes |
|---|---|---|
| `phase-1` | `334cea8` | `docs/releases/phase-1.md` (#66); tag exists |
| `phase-2` | `975e935` | `docs/releases/phase-2.md` (#61); tag exists |
| `baseline` | `61538de` | the eval baseline; tag exists |
| `phase-3` | `077473f` | `docs/releases/phase-3.md` (#75); **tag to create (Hoseung)** |
| `phase-4` | `a0085b3` | `docs/releases/phase-4.md` (#82); **tag to create (Hoseung)** |

Phase 3's parts: R1 #33, R5 #56, R2 #60, R3 #69, R6 #72, R4 #73, R7 #74. Phase 4's: H1 #54, H5 #41, H3 #77, H2 #78, H6 #67,
H4 #79, H7 #80, H8 #81. Also merged on 27 October: #71 (issue #70: the dev profile's Centinels provider is defined by
`agent-harness/profiles/dev/models.template.json` from `CENTINELS_BASE_URL` and `CENTINELS_API_KEY` in
`~/.config/balsamic/secrets.env`) and #76 (the per-part invariant files and pack modules).

**Decisions Hoseung took on 27 October, beyond the roadmap's §2:**
- R7: the chat's mandate dial starts at the campaign's default template, which follows `autonomy` (delegated → Screen;
  starting the agent team sets delegated, so most campaigns start at Screen). A Screen or Run the campaign granted with a
  chat message covers only its own request (`request_only` consents); agent cards keep decision 4.

**Choices the parts made where the roadmap was open** (each part's readiness file lists its own): a request's own newest
mandate governs it, and once it has ended only answering, asking and recording are allowed (R3); a request never narrows its
own mandate and has one Explore (R3); experiment rules and hiding runs stay `configure` (only Run the campaign) because the
short-run threshold is part of decision 14's assessment minimums, while `issue.resolve` moved to `record` and
`resources.plan` to `run` (R3); outcomes of work the researcher started directly wake nobody (R6); autopilot's mandate is
closed only by switching autopilot off (R4, R7). In Phase 4: a commission runs as a headless coding box only when coding
workspaces are on, and needs at least one protected test (H7); a commission with coding workspaces off, one that imports a
package, and an evaluator for a task no charter declares are refused with what to do instead, not sent to the retired
service (H8); a commission's compute is charged once, at the command (H7).

### Phase 5: in progress

| Part | State |
|---|---|
| V3 fidelity before finalist or library | merged (#43) |
| V1 typed stop outcomes | PR #32, branch `claude/project-thread-7cvw7y` |
| V4 locked results unreadable until release | PR #38, branch `claude/project-thread-bd92n8` |
| V2 adequate assessment before a stop | not started; needs V1 |
| V5 the gates on the page | not started; needs V1, V2, V3 |

### Phase 6: in progress

| Part | State |
|---|---|
| N1, N2, N4, N8, N15 | merged (#30, #31, #51, #46, #39) |
| N3 pack procedures and presentation | PR #48, `claude/project-thread-6kqiyf` |
| N5 pack estimators and fidelity ladders | PR #49, `claude/project-thread-l64nj9` |
| N6 pack references for coding workspaces | PR #47, `claude/project-thread-i0s51s` (Phase 4 rebuilt the coding box since, so expect the most adaptation here) |
| N7 no MEENT paths in execution | PR #52, `claude/project-thread-43xhtl` |
| N11 access and cost model per problem | PR #53, `claude/project-thread-35mzpf` |
| N13 bounds and optimality | not started; needs A3, N11 |
| N14 size ladders | not started; needs N5, N11 |
| N9, N10, N12 (M5, problem-owned candidates) | not started; **blocked on decision 20**: they start only after G1 passes and Hoseung confirms the narrower framework end to end. Ask Hoseung |

Each open Phase 6 PR, when it merges `main`, moves its keyed invariant rows into `docs/invariants/<part>.md` and its pack
additions into `src/dqn_meent/pack/<part>_<topic>.py` (the hotspots fix, #76), and adapts its tests to Phase 3's mandate
guard.

### Phase 7: in progress

| Part | State |
|---|---|
| K1, K3 | merged (#34, #37) |
| T2 the moderator's synthesis checked | PR #44, `claude/project-thread-fg1yhl` |
| K2 numeric claim checks | PR #59, `claude/project-thread-f78zv8` |
| T1 roles as calls with assembled context | not started; needs V4 |
| T3, T4 | not started; judged against the Phase 2 baseline by Hoseung's live evals |
| K4 negative library entries | not started; needs V1, V2 |

**Every one of the nine open PRs conflicts with `main`** (`git merge-tree` at `a0085b3`): each is 131 to 152 commits
behind and was written before Phases 3 and 4, so each needs `main` merged in, its conflicts resolved, its tests adapted to
the mandate guard (and, where they touch it, to Phase 4's coding box and the retired implementation service), and
the full suite rerun before it can merge. Read the PR's body
first: it says what the part does and how its "Done when" items were met.

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

- Last full run: on H8's head `e8018be`, the same tree as `main` at `acd370a` (only docs changed since), from the main
  checkout: 1354 passed, 93 skipped, 0 failed, in about 6 minutes with `-n 4`.
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

1. Tag `phase-3` on `077473f` and `phase-4` on `a0085b3`.
2. The UAT checklists of `docs/releases/phase-1.md` to `phase-4.md`, and their live evals: G2's live run of lead scenario
   S19 (`docs/readiness/G2.md`; from a separate worktree, because a live S19 run installs into its checkout); Phase 3's lead
   evals S1–S15 against the baseline; Phase 4's J4 on the ticket route and headless (`docs/releases/phase-4.md`).
3. Rebuild the coding-workspace image before trying Phase 4.
4. Decision 20: confirm G1 end to end, which N9, N10 and N12 wait for.

## 7. Next steps, in order

1. Bring each open PR up to `main`, one branch at a time (merge `main`, resolve, move keyed invariant rows to
   `docs/invariants/<part>.md` and pack additions to `src/dqn_meent/pack/<part>_<topic>.py`, adapt tests to the mandate
   guard, rerun), and merge one at a time: Phase 5 V1 #32 and V4 #38; Phase 7 T2 #44 and K2 #59; Phase 6 N3 #48, N5 #49,
   N6 #47, N7 #52, N11 #53. They can be worked in parallel by agents in worktrees; merge them sequentially.
2. Then the parts not started, in dependency order: V2 (V1), then V5 (V1, V2, V3); T1 (V4), K4 (V1, V2), T3, T4; N13 (N11),
   N14 (N5, N11); N9 → N10 → N12 once Hoseung confirms decision 20 (ask them when you get there).
3. When a phase's parts have all merged: its release notes, `docs/status.md`'s phase table, and the commit to tag.
