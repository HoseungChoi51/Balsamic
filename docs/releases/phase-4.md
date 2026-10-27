# Phase 4: the coding box, release phase-4

Phase 4 completed on 27 October 2026, when H8 merged (`acd370a`). This release is the commit on `main` that adds these
notes. It holds everything merged by then (listed below). The coding agent now works in a box that is open inside and strict
at its walls: it reaches only its model and the package index (plus hosts the researcher approves), within limits the
researcher sets and a deadline charged to the go-ahead. It works from a written ticket (`TASK.md`, `AGENTS.md`, the
acceptance tests) instead of a JSON dump, through a bridge any harness can use (an MCP server and a CLI), with Pi in its
terminal UI or headless. What it delivers is validated outside the box, on the exact commit, before anything installs: the
library's tests, each method's conformance and protected tests the coder never sees. The researcher can also deliver from
their own coding agent. A commission from the implementation lead is one more such box, run headless on its ticket,
and the box is now the only route that builds code: the library's builder, test designer and validator agents are retired.

## How to run it

```bash
git fetch origin && git checkout phase-4    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

**Rebuild the coding-workspace image** before trying any coding workspace: `start.sh`, the network rule and the harness
adapter are baked into it (H2, H5). Until it is rebuilt, a box runs Pi's terminal UI with the old network and limits.
Validation outside the box needs bubblewrap and pytest in the lab's environment (`uv sync --extra dev`; H6): without them
nothing installs, and the install says why. The coding workspace's ceilings are launcher settings
(`development_max_cpus`, `development_max_memory_gb`, `development_max_gpus`; defaults 4, 8, 0) and so is the harness mode
(`development_harness_mode`: `tui` by default, or `headless`).

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a phase-4 <this release's commit> -m "Phase 4: the coding box"
git push origin phase-4
```

`phase-3` (on `077473f`) waits for its tag too, if it is not created yet.

## Acceptance tests

Use a lab with coding workspaces on, the image rebuilt from this release, and a campaign made from a confirmed charter
whose evaluator is declared (the baking order works), with the lead agent on. Each item links to its part's full steps.

### End to end

- [ ] **A ticket in, a validated library out.**
  1. Ask the lead to implement two of the proposals in one coding workspace, with one extra check the coder must not see
     ("the methods must never return a candidate above the heater limit; keep that test from the coding agent"). Approve
     the one Screen card it sends.
  2. Expect the workspace card on Proposals → Implementations to show a Deadline, Limits "4 CPUs · 8 GB memory · no GPU"
     and a Network row with only the model's host, pypi.org and files.pythonhosted.org; in its editor, `TASK.md`,
     `AGENTS.md`, `CLAUDE.md` and `.balsamic/spec.json`, and the hidden check's text nowhere.
  3. When the coding agent delivers, expect the install to show "checking outside the box", then "installed" with "checked
     outside the box N tests passed · conformance passed for 2 of 2 methods", the proposals bound by Balsamic, the approved
     runs started, and the lead's message saying how many files and lines changed against the generated library.

### The parts

- [ ] **H1: the bridge as a CLI.** Ask the coding agent to run `balsamic-workspace checkpoint --summary 'Bridge check from
  the CLI' --phase orienting --eta 30`: the card's latest checkpoint and phase follow; `balsamic-workspace ask …` reaches
  you as a question. [H1](../readiness/H1.md#acceptance-test)
- [ ] **H2: Pi headless.** With `"development_harness_mode": "headless"` in the launcher file, a new workspace works with
  nobody attached: its History fills with "Worked …" entries and its terminal shows the runner's log; pause and resume keep
  its session. Without the setting, Pi's terminal UI as before. [H2](../readiness/H2.md#acceptance-test)
- [ ] **H3: your own coding agent.** On the card, "Deliver from your own coding agent" makes a token shown once; on your
  machine `clone`, commit and `submit HEAD` deliver it: "Delivered commit … from your own session", installed and bound by
  Balsamic. A wrong token, a paused or a stopped workspace is refused. [H3](../readiness/H3.md#acceptance-test)
- [ ] **H4: the ticket.** `TASK.md` names the proposals, the acceptance tests, the protected test by name only, the
  go-ahead's worker time, the deadline, the limits and the hosts; `.campaign/assignment.md` is short; the coder's progress
  is not relayed message by message; the delivery message states the diff. [H4](../readiness/H4.md#acceptance-test)
- [ ] **H5: the walls.** `pip install` works and `curl -I https://example.com` is refused from the box's terminal; a host
  named on the mandate card (github.com) is reachable after approval; past a short deadline the workspace pauses ("reached
  its deadline"), the lead tells you once, and "Let it go on for 1 h" resumes it. [H5](../readiness/H5.md#acceptance-test)
- [ ] **H6: validation outside the box.** A deliberately wrong method reported as passing is not installed, named under
  "not installed" with the check that failed, refused on the Algorithms list and when the lead tries to run it; the coder
  gets one message saying what to fix. [H6](../readiness/H6.md#acceptance-test)
- [ ] **H7: commissions as headless boxes.** Ask the implementation lead to commission a proposal with a protected test
  and approve its Screen card: a card with a Commission row appears and works with nobody attached, `TASK.md` has a section
  "The commission" and the protected test's text is nowhere in the box; on delivery it is checked outside the box,
  installed and bound, and the line above the chat shows the commission's minutes used once. An evaluator commission
  installs a library the declared tasks adopt; a wrong fixture fails by name only. [H7](../readiness/H7.md#acceptance-test)
- [ ] **H8: one implementation route.** The Models page lists no builder, test designer or validator; old implementation jobs and
  versions are still listed on the Implementations page; with coding workspaces off a commission is refused with the switch
  that turns them on and no job appears; a commission that imports pasted code is refused, pointing to your own coding
  agent or a workspace with the code as reference. [H8](../readiness/H8.md#acceptance-test)

## Live evals (Hoseung)

On the machine with Docker, the rebuilt image and the harness built, at this release's commit, on Centinels (no approval
needed):

```bash
uv run python scripts/run_coding_evals.py --scenarios C1 --compare evals/coding/baselines/<the Phase 2 baseline>.json
uv run python scripts/run_coding_evals.py --scenarios C1 --harness-mode headless --record-baseline \
  --compare evals/coding/baselines/<the Phase 2 baseline>.json
```

The Phase 2 baseline is J4 run at the `baseline` tag (`61538de`) with `--record-baseline`. No coding baseline is committed
yet (`evals/coding/baselines/` does not exist), so record that first if it is not on your machine. The first command is
J4 on the ticket route (H4): its row beside the baseline, with `metrics.ticket`, the time to the submission and the
messages relayed to the coding agent. The second is J4 on Pi's headless mode (H2, H7): it writes
`evals/coding/baselines/<commit>-headless.json`; commit it.

## In this release

| Part | What changed | PR |
|---|---|---|
| H1 | The workspace bridge as an MCP server and a CLI (`balsamic-workspace`) | #54 |
| H2 | A harness adapter: Pi in its terminal UI or headless (`--mode json`), a harness setting per workspace | #78 |
| H3 | Bring your own session: a one-time token, `clone` and `submit` from your own machine as a Git bundle | #77 |
| H4 | The work ticket: `TASK.md`, `AGENTS.md`, `CLAUDE.md`, `.balsamic/spec.json`, acceptance and protected tests, the diff review | #79 |
| H5 | Walls in code: an egress allowlist, limits within the researcher's ceilings, a deadline charged to the go-ahead | #41 |
| H6 | Validation outside the box: tests, conformance and protected tests on the exact commit before an install counts | #67 |
| H7 | Commissions run as headless boxes on a ticket; their protected tests and an evaluator's fixtures run outside the box; compute charged once | #80 |
| H8 | One route: the box's library is the only way code is built; the builder, test designer and validator agents are retired; commissions it cannot run are refused with what to do instead | #81 |

Also included: the conflict-hotspots change (#76): keyed invariant rows live in `docs/invariants/<part>.md`, and MEENT's pack
is one module per part (`src/dqn_meent/pack/<part>_<topic>.py`). Still paused, with open PRs: V1 (#32), V4 (#38), N3 (#48),
N5 (#49), N6 (#47), N7 (#52), N11 (#53), T2 (#44), K2 (#59); merged earlier: V3, N1, N2, N4, N8, N15, K1, K3.

## Known gaps

- The image must be rebuilt; existing containers keep their old network and limits until they are recreated (H2, H5).
- Egress addresses are resolved when a box starts; a host whose addresses rotate needs a restart. Built-in providers' hosts
  are a list (`PROVIDER_HOSTS`) (H5).
- The chat's mandate dial has no hosts field: a Screen granted with a message approves no extra hosts (H5).
- Headless Pi cannot be steered mid-run; an interrupted instruction is not re-run; a failed headless run is a notice only
  for a commission's box, not for a workspace the researcher or the lead opened (H2, H7).
- A researcher's delivery token does not expire on its own; the start they clone is the generated library, without the
  ticket's files (H3, H4).
- The ticket is fixed once the workspace opens; the Implementations page shows neither the ticket nor the diff (H4).
- Validation runs on the host's Python and is charged without asking first when it exceeds what is left of the go-ahead;
  a refused method's code stays in the installed package, refused where it would be bound or run (H6).
- A commission cannot import a package: code you already have comes in through your own coding agent (H3) or as reference
  code for a workspace. An evaluator for a task no charter declares can only be attached as an already-validated version
  (H8).
- A commission's model-call and dollar caps are recorded on its box, not enforced; `implementation.control` does not reach
  a box (pause, resume or stop it on its card); its specification's behaviour, mechanism and diagnostic checks are shown in
  `TASK.md`, not run as protected tests (H7).
- `scripts/check_revalidation_restart.py`, a live check that commissions a package first, now gets the refusal (H8).
