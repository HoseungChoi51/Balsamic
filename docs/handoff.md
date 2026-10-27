# Handoff: the state of the roadmap work on this fork

Written 2026-10-27 at about 15:30 UTC and updated when Phase 3 completed (17:43 UTC), for an agent taking over `HoseungChoi51/Balsamic` with none of the earlier context.
Everything below was checked against GitHub and `main` (`f70090b`; Phase 3's section and §6 against `3c42487`) at that time. PR states move: check them again
before acting (`git fetch` and the PR list), and trust GitHub over this page.

## 1. What this is

Balsamic is a research harness in which a researcher and a team of LLM agents (Pi agents) develop problem-specific
optimizers: the researcher writes a charter for a problem, a lead agent turns requests into proposals, coding
workspaces, runs and comparisons. Start with `README.md`, `docs/ui-workspace.md` and `docs/pi-agent-harness.md`.
`docs/status.md` is the status page, but its phase table is out of date (it predates the Phase 1 and 2 releases); this
file is newer.

This repository is Hoseung's fork of `kc-ml2/Balsamic`. Its `main` started as kc-ml2's `workspace-rebuild` branch
(`af41ae7`, the same files as `cc0e693`). Work happens only here, on `main`; the Claude GitHub app cannot write to kc-ml2.

**Hoseung** (GitHub `HoseungChoi51`) owns the project. They do not read code changes: they judge each phase by using the
app, from a user acceptance test (UAT) checklist. Decisions only they can make go to them as one question with a
recommended option; everything else, including merge conflicts, you handle yourself.

## 2. The roadmap

`docs/roadmap/` holds the plan: `README.md` (instructions for coding agents in §0, principles §1, decisions §2) and one
file per phase. 78 parts, each a letter (its track) and a number.

| Phase | Goal | Parts | File |
|---|---|---|---|
| 1 | Charter to results | A1–A4, B1–B7, C1–C3, D1–D3, E1–E5, F1–F4, G1–G2 | `phase-1-charter-to-results.md` |
| 2 | Measure first: invariant register, trap evals, the eval baseline | I1–I3, J1–J4 | `phase-2-measure-first.md` |
| 3 | A mandate for every request | R1–R7 | `phase-3-mandates.md` |
| 4 | The coding box | H1–H8 | `phase-4-coding-box.md` |
| 5 | Evidence gates | V1–V5 | `phase-5-evidence-gates.md` |
| 6 | Problem packs; every algorithm family on fair terms | N1–N15 | `phase-6-problem-packs.md` |
| 7 | Fewer standing agents, claims that resolve | T1–T4, K1–K4 | `phase-7-agents-and-claims.md` |

**Decisions 1–24 in README §2 are all settled.** Do not reopen them. If a part needs a choice §2 does not cover, ask
Hoseung. Each phase file ends with "Order and shared files": the waves inside the phase and the files its parts share.
Line numbers in the roadmap refer to `cc0e693`; find code by function name.

## 3. How the work is run

- **One part = one branch = one PR into `main`.** The PR title is commit-style with the part id, e.g.
  `feat(mandates): mandate_propose, the lead's first act on a request (roadmap R2)`. The body says what was wrong, what
  changed, how each "Done when" item holds, the test commands and counts on the PR's head, what is not done, and the
  acceptance test. Assign Hoseung (a review request fails because PRs are opened under their account). PR #60 is a good
  model.
- **The fork has no CI.** The test counts in the PR, run on a head that contains the latest `main`, are the evidence.
- **Readiness file per part:** `docs/readiness/<id>.md`, format in `docs/readiness/README.md`: a State line, then What
  was wrong / What changed / Checked / Not done / Acceptance test. The acceptance test is written for someone using the
  app (where to go, what to do, what to see), never code. Do not add lettered Parts to `docs/lead-agent-readiness.md`.
- **Invariants:** a part edits its rows of `docs/invariants.md` in place; new rows use ids keyed by the part
  (`INV-R2-1`), placed next to related rows, never appended at the end.
- **Merging:** PRs merge without code review once (1) they merge cleanly and contain the latest `main`, (2) the full
  suite passed on that head with only the known flakes, (3) a PR sharing a file with something merged since its test
  run has had `scripts/test-changed` run on its head, (4) it is not a draft and not waiting on Hoseung. One at a time,
  merge commits. If a merge breaks `main`, revert it at once. The full policy is `docs/releases/README.md`.
- **Conflicts:** the PR's owner fixes its own conflicts without asking. Bring `main` in with `git merge origin/main` and
  push normally; force pushes after a rebase are refused in cloud sessions. Then rerun the tests the conflict touched.
- **Releases:** when every part of a phase has merged, run the full suite on `main`, then add
  `docs/releases/phase-<n>.md` (template in `docs/releases/README.md`: how to run, UAT checklist collected from the
  parts' acceptance tests, live evals, parts included, known gaps) in its own PR and merge it. Cloud sessions cannot
  push tags, so tell Hoseung the commit to tag (`git tag -a phase-<n> <commit> -m "Phase <n>: <goal>"`).
- **No model calls and no live lab.** Tests run with `GRATING_LLM_DISABLED=true`. Live checks and live evals (on the
  Centinels provider) are Hoseung's and go in the release's UAT.
- Phases 3, 4, 5 and 7 (except K1–K3) are judged against the eval baseline at `61538de` (the first `main` with J1–J4).

## 4. Status, phase by phase

### Phases 1 and 2: complete

All 28 Phase 1 parts and all 7 Phase 2 parts are merged and released.

| Release | Commit on `main` | Notes |
|---|---|---|
| `phase-1` | `334cea8` | `docs/releases/phase-1.md` (PR #66) |
| `phase-2` | `975e935` | `docs/releases/phase-2.md` (PR #61) |
| `baseline` | `61538de` | the eval baseline |

All three tags exist on GitHub (Hoseung created them by hand; cloud sessions cannot push tags). **Open for
Hoseung:** G2's live run of lead scenario S19 on Centinels (`docs/readiness/G2.md`; run it from a separate worktree, because a live S19 run installs into its checkout).
Their UAT of both releases is also theirs.

### Phase 3: complete (release `phase-3`, waiting for its tag)

Hoseung, 15:07 UTC: "Complete phase 3. Phase 4 waits." All seven parts merged on 27 October; the release notes are
`docs/releases/phase-3.md`. Phases 4 to 7 stay paused: their open PRs stay open and unmerged, and no new part of them starts
until Hoseung says so.

| Part | State |
|---|---|
| R1 mandate record and templates | merged (#33) |
| R5 model-spend envelope | merged (#56) |
| R2 `mandate_propose` | merged (#60) |
| R3 the bus refuses work outside the mandate | merged (#69) |
| R6 who is woken; the instructions drop what the mandate enforces | merged (#72) |
| R4 autopilot as a standing mandate | merged (#73) |
| R7 the mandate dial in the chat | merged (#74) |

Hoseung decided on 27 October, for R7: the dial's default follows `autonomy` (delegated → Screen, so most campaigns start at
Screen), and a Screen or Run the campaign granted with a chat message covers only its own request (`request_only` consents;
agent cards keep decision 4). Issue #70 (the dev profile's Centinels provider) was fixed in #71.

### Phase 4: paused

| Part | State |
|---|---|
| H1 workspace bridge as MCP server and CLI | merged (#54); Hoseung chose to keep it |
| H5 walls in code | PR #41, open, merges cleanly but is 9 commits behind `main` |
| H6 validation outside the box | PR #67, **unfinished draft** (branch `claude/project-thread-00bhmq`). It adds `agents/library_validation.py` (tests, conformance and protected tests in a no-network bwrap sandbox before `Installer.install()`; failing methods go to `refused_methods` and are not bound). Left: the sandbox could not exec Python in the cloud container (`execvp /usr/bin/python3: No such file`, merged `/usr`), it has no tests yet, the existing install tests need stub validators, INV-23 to `code`, docs. `docs/readiness/H6.md` on that branch lists it all |
| H2, H3, H4, H7, H8 | not started |

Waves: H1, H5, H6; then H2 (H1), H3 (H1, F2), H4 (H1, F4); then H7 (H4, H6); then H8 (H7). H4 → H7 → H8 is the longest
chain. Shared: `agents/development_runtime.py` (H2, H4, H5), `agents/development.py` (H4, H5, H6),
`deploy/implementation-workspace/*` (H1, H2, H5), `implementations/bridge.py` and `service.py` (H7, H8).

### Phases 5 to 7: paused

Merged before the pause: V3 (#43), N1 (#30), N2 (#31), N4 (#51), N8 (#46), N15 (#39), K1 (#34), K3 (#37).

Open PRs, checked with `git merge-tree` against `main` at `f70090b`:

| PR | Part | Against `main` |
|---|---|---|
| #32 | V1 typed stop outcomes | merges cleanly, 51 commits behind |
| #38 | V4 locked results unreadable until release | merges cleanly, 51 behind |
| #48 | N3 pack procedures and presentation | **conflicts** |
| #49 | N5 pack estimators and fidelity ladders | merges cleanly, 51 behind |
| #47 | N6 pack references for coding workspaces | **conflicts** |
| #52 | N7 no MEENT paths in execution | merges cleanly, 51 behind |
| #53 | N11 access and cost model per problem | **conflicts** |
| #44 | T2 moderator's synthesis checked | **conflicts** |
| #59 | K2 numeric claim checks | **conflicts** |

"Merges cleanly" is textual only: none of these has been tested on a recent `main`, so each needs `main` merged in and
the full suite rerun before it can merge.

Not started: V2, V5; N9, N10, N12, N13, N14; T1, T3, T4; K4.

**Done before the open Phase 6 PRs merge** (the conflict hotspots): keyed invariant rows live in `docs/invariants/<part>.md`, read with `docs/invariants.md` by `tests/test_invariants.py` (a keyed row in the numbered table fails it), and MEENT's pack is one module per part, `src/dqn_meent/pack/<part>_<topic>.py` with a `CONTRIBUTION`, assembled by `pack/__init__.py` (N4's is `n4_tools.py`). Roadmap README §0.11 and N2's item 3 say so. Each open PR moves its keyed rows and pack additions into its own files when it merges `main`.

## 5. Testing fast in a cloud container

`.claude/hooks/session-start.sh` runs at the start of a cloud session (`CLAUDE_CODE_REMOTE=true`): it installs
bubblewrap, `uv sync --extra dev`, then scipy, matplotlib and pytest-xdist into `.venv`, makes the checkout readable by
the normal user, and sets `GRATING_LLM_DISABLED=true`. In a session that started without it, run
`CLAUDE_PROJECT_DIR=$PWD bash .claude/hooks/session-start.sh` from the checkout (without the variable it fails with
`unbound variable`).

```bash
scripts/test-changed                 # changed tests + tests importing changed src modules, in parallel (vs origin/main)
scripts/test-changed --list          # just list them
# the full suite, about 5 minutes (18-23 serial); run once before a PR
GRATING_LLM_DISABLED=true uv run --extra dev pytest -q -n 4 --dist worksteal --ignore=tests/test_server_launcher.py
# the launcher refuses root, so its tests run as the container's user `claude`
runuser -u claude -- env HOME=/home/claude GRATING_LLM_DISABLED=true .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_server_launcher.py
(cd agent-harness && npm ci && npm test)
(cd frontend && npm ci && npx tsc -b && npx playwright test)   # when the UI changes; then git checkout frontend/tsconfig.tsbuildinfo
uv run python scripts/run_lead_evals.py --fake                 # eval plumbing, no model calls
```

- Last full run on a recent `main` (R7's head, the tree of `phase-3`): 1298 passed, 96 skipped, the one known flake.
- **Parallel parts in worktrees:** an agent in a git worktree can share the main checkout's `.venv` (pytest's `pythonpath` puts the
  worktree's `src` first), but `tests/test_pi_agents.py::test_an_agent_analyses_its_experiments_with_its_own_script_in_a_sandbox`
  then fails (the sandbox does not mount the venv's editable `src`); run it from the main checkout. Keep worktrees out of
  commits (`.claude/worktrees/` in `.git/info/exclude`).
- `scripts/test-changed` misses tests that reach a changed module only through another one; the full run catches them.
- **Known flakes**, rerun before treating them as yours: `tests/test_tracking.py`, and
  `tests/test_framework_isolated_host.py::test_supervisor_death_retains_committed_evidence_and_reconciles_without_execution`
  (fails about 2 runs in 3 even alone).
- **Stale `.venv` after an entry point changes:** when `main` adds an entry point to `pyproject.toml` (e.g. `flrl` under
  `optimization_framework.optimizers`), tests fail with errors such as `KeyError: 'flrl'`. Run
  `uv pip install --python .venv/bin/python -e . --no-deps`. Avoid a plain `uv sync`, which removes scipy and matplotlib
  (reinstall them if you do).
- `chown -R claude .` on the checkout breaks root's git ("dubious ownership"); undo with `chown -R root:root .`.
- scipy and matplotlib are installed by hand because the `meent` extra pulls `meent` from a private repository the cloud
  cannot reach; MEENT tests skip. `uv lock` fails for the same reason, so pytest-xdist is not in the dev extra.

## 6. Next steps, in order

1. Hoseung: tag `phase-3` on the commit that adds `docs/releases/phase-3.md`, run its live evals and its UAT checklist.
2. Remind Hoseung of G2's live run and the UAT of Phases 1 and 2 if they have not reported on them.
3. Only when Hoseung resumes them: Phase 4 (H5 #41 up to date, finish H6 #67, then H2/H3/H4, H7, H8), and Phases 5–7
   (the conflict-hotspots PR from §4 first, then each open PR merged with `main` and retested, then the parts not
   started). Each open PR now also needs Phase 3's mandate guard in mind: an agent's command of a class its request's
   mandate does not allow is refused, so tests that drive agents through decide, implement or configure work grant a
   mandate first (`tests/test_mandates.py` `granted()`).
