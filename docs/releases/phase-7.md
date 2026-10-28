# Phase 7: fewer standing agents, claims that resolve, release phase-7

Phase 7 completed on 28 October 2026, when T4 merged (`37c33bc`). This release is the commit on `main` that adds these
notes. It holds everything merged by then (listed below), Phase 5 included (`phase-5`). Phase 6 is not complete yet (N9,
N10 and N12 are being built), so this release comes before it.

What changes for the researcher: review roles answer in one call from an assembled context, rather than as a session that
reads on demand. The proposal reviewer does this first (T1), then the review specialists (T3). The moderator's synthesis of
a round is checked against the verdicts and badged when it goes against them (T2). The page agents can be folded into the
lead behind a switch, so the two can be compared (T4). On the claims side, agents compute numbers instead of estimating them
(K1). A finding says what it states and how many distinct measurements it rests on (K3). Numbers that the cited evidence
does not hold are badged (K2). Methods that were properly assessed and stopped are published to the library as negative
entries (K4).

T1, T3 and T4 change how the agent team works. Each one is judged by a live comparison against the Phase 2 baseline, and
those comparisons are Hoseung's (below). Until they run, the proposal reviewer and both specialists are one call each, and
the page agents stay standing (the default). ADR 0009 (T3) and ADR 0010 (T4) are Proposed.

## How to run it

```bash
git fetch origin && git checkout phase-7    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

Folding the page agents into the lead (T4) is opt-in. Set `GRATING_PAGE_AGENTS=lead` before the agent team starts, or use
`agent.configure` with `page_agents` in the dev profile. Without it, the page agents stand as before.

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a phase-7 <this release's commit> -m "Phase 7: fewer standing agents, claims that resolve"
git push origin phase-7
```

`phase-3` (`077473f`), `phase-4` (`a0085b3`) and `phase-5` (`3d27d46`) wait for their tags too, if they are not created yet.

## Acceptance tests

Use the Centinels provider and a campaign with an installed problem, the agent team started and at least one finished
experiment. Each item links to its part's full steps.

### End to end

- [ ] **A review and a finding you can trust.**
  1. On Hypotheses, add a proposal whose algorithm is not installed. In the chat, ask: "Have the discussion moderator
     review that proposal with a skeptical domain analyst, a methodology specialist and a proposal reviewer, and tell me
     the verdict."
  2. Expect each reviewer and specialist to finish without tool steps, in one call each. Review rounds should show
     each one's result and a synthesis box that gives the standing with the tally. The lead's answer should agree
     with it.
  3. Ask: "Record a finding that the last experiment reached its best score, and that a longer run would reach 0.99."
     On Files → Assets, the finding shows **evidence** with "1 distinct measurement behind it" and a badge "1 unverified
     number: 0.99".

### The parts

- [ ] **T1: the proposal reviewer as one call.** Its verdict and rationale show on Review rounds and the proposal, with
  no tool steps, and Usage lists its cost. Asking the moderator to have the reviewer "also look at the seeds" leads to
  a new review, not a follow-up. [T1](../readiness/T1.md#acceptance-test)
- [ ] **T2: the synthesis checked.** The newest round shows a synthesis box with each proposal's standing, the
  reviewers' tally and the reason. A standing or status that goes against the verdicts gets an "against the verdicts"
  badge naming the review, and the status still changes. [T2](../readiness/T2.md#acceptance-test)
- [ ] **T3: the specialists as one call.** The skeptical analyst and the methodology specialist each finish without
  tool steps, and Review rounds lists a one-line result for each. The analyst names a high-severity failure mode, and
  the methodology specialist names installed methods only. [T3](../readiness/T3.md#acceptance-test)
- [ ] **T4: page agents folded into the lead (switch).** With `GRATING_PAGE_AGENTS=lead`, the Experiments desk is headed
  "Lead agent", runs are started by the lead, and a review runs with no moderator started. A campaign started without the
  variable keeps the operator and the moderator. [T4](../readiness/T4.md#acceptance-test)
- [ ] **K1: numbers computed.** "0.005 on a grid of 32,768 cells: how many times 1/n?" shows "Computing a number" and
  answers 163.84. A score difference matches the Experiments page. [K1](../readiness/K1.md#acceptance-test)
- [ ] **K2: unverified numbers badged.** A reply quoting the best score has no badge. A finding with an uncited number
  gets a badge naming it, and a report's claims list their "Unverified numbers". [K2](../readiness/K2.md#acceptance-test)
- [ ] **K3: findings that say what they state.** A finding shows evidence and its distinct measurements. An idea cited
  only from a proposal is recorded as **promise · not measured**. Findings that cite the same experiment show
  **restates**, and a superseded finding moves to "Superseded findings" with a link. [K3](../readiness/K3.md#acceptance-test)
- [ ] **K4: negative library entries.** A strategy stopped as "configuration unpromising" after a full assessment can be
  published as "Assessed and stopped". It shows apart from the winners in the second campaign of the same problem, and
  can be applied there with the reason in its rationale. One stopped as "under-evaluated" is refused.
  [K4](../readiness/K4.md#acceptance-test)

## Live evals (Hoseung)

These run on Centinels (no approval needed) at this release's commit. Each one is compared with the same runs at the
`baseline` tag (`61538de`); point `--source` at a checkout of it.

```bash
# T1, T2, K2: the review round and the numbers
uv run python scripts/run_lead_evals.py --scenarios S12,S14,S16 --repeats 3
# T3's three arms (sessions, one call, one merged analyst)
uv run python scripts/run_lead_evals.py --scenarios S12,S14,S16 --repeats 3 --one-shot-roles proposal_reviewer
uv run python scripts/run_lead_evals.py --scenarios S12,S14,S16 --repeats 3 --one-shot-roles proposal_reviewer,analyst
# T4's two arms, on the whole suite, then with --preset deflector_2d and --preset reactor
uv run python scripts/run_lead_evals.py --page-agents standing --repeats 3
uv run python scripts/run_lead_evals.py --page-agents lead --repeats 3
```

- **S12** should pass as at the baseline or better, with T2's new check `synthesis_matches_tally`. Compare the proposal
  reviewer's cost, its time to verdict and the share of valid verdicts (T1).
- **S16** should pass. Record the "Unverified numbers" column as K2's starting rate.
- **T3:** a specialist whose one-call arm passes fewer scenarios, or has fewer valid results, goes back to a session in
  `DEFAULT_ONE_SHOT`. D2 (one analyst) is taken only if its arm does as well at a lower cost. Write the result into
  ADR 0009.
- **T4:** a page agent is folded only if the `lead` arm passes as many scenarios with fewer turns or a lower cost, and
  the lead's largest context stays well within its window. Write the result into ADR 0010; the fold itself is a new part.

## In this release

| Part | What changed | PR |
|---|---|---|
| T1 | The proposal reviewer is one call with an assembled context: the proposal, its record and the evidence it cites | #85 |
| T2 | The moderator records a synthesis per round; code tallies the reviewers' latest verdicts and badges a standing or status against them | #44 |
| T3 | The skeptical analyst and the methodology specialist as one call each; the eval runner's three-arm comparison; ADR 0009 Proposed | #88 |
| T4 | A switch that folds the experiment operator and the discussion moderator into the lead, for comparison; ADR 0010 Proposed | #91 |
| K1 | `compute`: agents derive numbers with a receipt instead of estimating | #34 |
| K2 | Numeric claim checks: numbers in findings, replies and report claims that their evidence does not hold are badged; the evals' unverified-numbers metric | #59 |
| K3 | Findings state what they are (evidence, promise, restates) and count their distinct measurements; superseded findings | #37 |
| K4 | Negative library entries: a method assessed and stopped is published apart from the winners and offered with its reason | #89 |

INV-12 is now held in code (T1). INV-13 (T2) and INV-19 (K2) stay `prompt`: both are badged, and neither is refused.
Phase 5 (V1–V5) is released as `phase-5` (`docs/releases/phase-5.md`). From Phase 6, merged since `phase-4`: N3, N5, N6, N7,
N11, N13 and N14. N9, N10 and N12 are still to come, so Phase 6's own release notes will list them.

## Known gaps

- Only the proposal reviewer and the two review specialists are one call. A one-shot call can't read on demand, run
  `compute` or read a paper. Its input is cut at 8 KiB per record (T1) or 16 KiB (T3), with no index. A call in flight
  can't be cancelled (T1, T3).
- A reviewer is delegated one proposal at a time (T1).
- The synthesis is badged, never refused. `rejected` counts any archived proposal and doesn't read V1's typed outcome
  yet. Nothing checks that the moderator's reply links the synthesis (T2).
- Folding the page agents is a switch for comparison only. It can't be changed from the page, and the fold itself waits
  for ADR 0010 (T4).
- Unverified-number badges will sometimes be false (units, rounding, a number the model derived correctly without
  `compute`). A specialist's structured output and a finding's limitations aren't checked (K2).
- An agent's saved artifact of kind `analysis` counts as a measurement whatever it holds. Any finding can supersede an
  earlier one, including the researcher's. The Notebook tab shows a finding's kind, not its statement (K3).
- A negative library entry carries no fidelity record, and the lead isn't told to look for negative entries before
  proposing (K4).
