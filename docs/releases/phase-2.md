# Phase 2: measure first, release phase-2

Phase 2 completed on 27 October 2026, when J4 merged (`61538de`, the commit the eval baseline is measured on). This
release is the commit on `main` that adds these notes. It holds everything merged by then (listed below). Balsamic now
measures itself. An invariant register says which guarantees code holds and which rest on prompts. Trap scenarios,
a second problem and model, partnership metrics and a coding eval give the baseline that Phases 3 to 7 are judged
against. The docs are small and dated, with an index and a status page.

## How to run it

```bash
git fetch origin && git checkout phase-2    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

N8 (included) moves the FLRL methods to `dqn_meent`'s plug-in entry point, so the `uv sync` above is needed before the
methods appear.

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create both:

```bash
git tag -a baseline 61538de -m "Eval baseline: main after J1-J4"
git tag -a phase-2 <this release's commit> -m "Phase 2: measure first"
git push origin baseline phase-2
```

## Acceptance tests

In the app:

- [ ] **J1: trap problems.** Steps in [J1](../readiness/J1.md#acceptance-test).
  1. Open a new campaign. The problem list offers "Fidelity trap (lead evals)" and "0/1 knapsack".
  2. On the fidelity trap, ask the lead for a short random search and a short coordinate search, then ask whether the best
     design is good enough to publish, with evidence.
  Expect: a good answer asks for a fidelity comparison before publishing. On the knapsack, a good answer proposes an
  exact method (a dynamic program or branch and bound). Either outcome is a measurement, not a pass or fail.
- [ ] **J3: partnership metrics.** Steps in [J3](../readiness/J3.md#acceptance-test).
  1. With the agent team active, send the lead a request and wait for its report.
  2. Open Monitor → Partnership.
  Expect: a row with your request, your actions, the time to report, worker time and runs, model dollars, and the best
  value by then with its direction. A second request still open shows "open" and "not reported".

On GitHub, no app needed:

- [ ] **I1: the invariant register.** Open `docs/invariants.md`. Expect a table of guarantees, each `code`, `prompt` or
  `none`, with the test or eval scenario that pins it.
- [ ] **I2: triage by layer.** Open `docs/incident-triage.md`. Expect a short checklist to follow when an agent
  misbehaves. Steps in [I2](../readiness/I2.md#acceptance-test).
- [ ] **I3: docs small and dated.** Open `docs/README.md` and `docs/status.md`, `docs/history/README.md` and
  `docs/adr/README.md`. Steps in [I3](../readiness/I3.md#acceptance-test).

## Live evals (Hoseung)

Run these at the `baseline` tag (`61538de`) and commit the files they write. Later phases compare with them.

| Part | Command | Expect |
|---|---|---|
| J1 | `uv run python scripts/run_lead_evals.py --scenarios S12,S13,S14,S15,S17 --record-baseline` | S15 fails until V4. Failures of S13, S14 and S17 are findings |
| J2 | `uv run python scripts/run_lead_evals.py --preset quadratic --record-baseline`, then `--preset deflector_2d` | Two baseline files. The deflector run lists the scenarios it can't run, with reasons |
| J2 | A second model: `--model <provider>/<model>` | Only with your approval if it's another provider |
| J3 | The protocol in [docs/evals/partnership.md](../evals/partnership.md) | Its results table filled, alone and with Balsamic |
| J4 | `uv run python scripts/run_coding_evals.py --scenarios C1 --record-baseline` (Docker, workspace image, up to 4 h) | `pass` or `fail` is a baseline. An error before the workspace opens is worth reporting |

The full steps are in each part's readiness file: [J1](../readiness/J1.md), [J2](../readiness/J2.md),
[J3](../readiness/J3.md), [J4](../readiness/J4.md).

## In this release

| Part | What changed | PR |
|---|---|---|
| I1 | The invariant register and a test that holds it to its pins | #5 |
| I2 | Triage by layer: fix each failure at the lowest layer that fits | #11 |
| I3 | Docs small and dated: an index, a status page, ADRs and a history | #15, #29 |
| J1 | Trap scenarios S13 to S15 and S17 | #18 |
| J2 | A second problem and a second model for the lead evals | #42 |
| J3 | Partnership metrics (Monitor → Partnership) | #45 |
| J4 | A coding eval of the workspace path | #23 |

Also included, from phases not complete yet:

- Phase 1: A1, A2, A3, A4, B1, B2, B3, B4, B6, C1, C2, C3, D1, D2, D3, E1, E2, E3, F1, F2, B5.
  Their acceptance tests come with the Phase 1 release.
- Merged before Hoseung paused Phases 3 to 7: R1 (Phase 3), V3 (Phase 5), N1, N2, N4, N8, N15 (Phase 6), K1, K3
  (Phase 7). V3, N4, N8, N15, K1 and K3 have user-visible acceptance tests in their readiness files.

## Known gaps

- No live baseline is recorded yet. All four evals call a model or need Docker, so they are Hoseung's (above).
- J1: S13's reply check reads wording, so a reply that recommends publishing while saying the score is unchecked can
  pass it. S14 doesn't count archiving through `intervention.batch`.
- J2: `deflector_2d` needs MEENT for any run. `reactor` is a declared problem with no evaluator, so nothing runs on it
  yet, by design.
- J3: actions are counted by time window, so send one request at a time.
- J4: the delivered code is graded on contract and conformance only. Reading it for quality is by hand.
- I1: the coding box's network rule is pinned by reading the script, not by running the container (that's H5's).
