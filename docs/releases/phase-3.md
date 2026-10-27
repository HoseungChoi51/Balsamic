# Phase 3: a mandate for every request, release phase-3

Phase 3 completed on 27 October 2026, when R7 merged (`3c42487`). This release is the commit on `main` that adds these
notes. It holds everything merged by then (listed below). What a request allows is now a record the command bus checks,
not a line of the prompt. Each researcher request has a mandate (Answer, Explore, Screen or Run the campaign): the lead
proposes one, small ones start at once, larger ones are one Inbox card, and the researcher can grant one with their own
message from a dial in the chat, see it above the chat and close it. The bus refuses an agent's work outside its request's
mandate: a kind of work it does not allow, a proposal a Screen does not name, work past Explore's envelope, and new work once
its deadline has passed, its envelope is spent or it is closed. Model spend is counted per request. Autopilot is a standing
mandate instead of a special case, and outcomes of work the researcher started directly no longer wake the lead.

## How to run it

```bash
git fetch origin && git checkout phase-3    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

For the real lead on the dev profile's default model, put `CENTINELS_BASE_URL` and `CENTINELS_API_KEY` in
`~/.config/balsamic/secrets.env` first ([#70](https://github.com/HoseungChoi51/Balsamic/issues/70), included; see
`agent-harness/profiles/dev/README.md`). Without them the chat says "Model unavailable: centinels/gpt-6.1-sol" and names
the two variables. No migration is needed: compute go-aheads given before this release read as Screen mandates, and an
autopilot that is on gets its mandate at its next round.

## Tags to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a phase-3 <this release's commit> -m "Phase 3: a mandate for every request"
git push origin phase-3
```

## Acceptance tests

Start with the end-to-end check; the per-part checks below it isolate one change each, and each links to its part's full
steps. Use a campaign with a problem, two proposals with an installed method, and the lead agent switched on.

### End to end

- [ ] **A request's mandate, from the dial to the refusal.**
  1. In the chat, turn the dial beside Send to Screen, write "Screen H01 with two seeds, ten minutes each", press Send,
     set 40 minutes of worker time in the small form, and press "Grant and send".
  2. Expect no Inbox card; the lead starts the runs; above the chat: "Screen · This request · left: 40.0 min of worker
     time · deadline …", going down as runs start.
  3. Press Close on that line. Expect "closed by you: new work is refused"; runs already going keep going, the others do
     not start, and the lead says the mandate was closed when it reports.
  4. Send a new message with the dial at Explore asking for a 20-minute run. The lead does not start it: it sends one
     Inbox card for a Screen mandate. The go-ahead you granted for the first request does not pay for this one.

### The parts

- [ ] **R2: `mandate_propose`.** A question gets an answer and no card; small work under your go-ahead threshold starts
  with no card; work beyond it is one card, "Approve a Screen mandate for this request?", with Approve, Approve as Explore
  only, Decline. [R2](../readiness/R2.md#acceptance-test)
- [ ] **R3: the bus refuses work outside the mandate.** Ask the lead to stop a proposal: it asks for a Screen card first.
  Approve a screen naming H01 only: it does not start H02 without a new card. After a deadline, running work goes on and
  nothing new starts; if something was stopped, the Inbox says so once. Several short probes start until they add up to
  your go-ahead threshold, then the next waits for a card. [R3](../readiness/R3.md#acceptance-test)
- [ ] **R4: autopilot is a standing mandate.** Switch autopilot on with a 5-minute cap: "Recently resolved" lists
  "Autopilot on: a compute cap of 5 min"; your own run counts against the cap; raising the cap mid-round lets the round go
  on; once spent, the last round writes the report and starts nothing; switching off refuses what is left.
  [R4](../readiness/R4.md#acceptance-test)
- [ ] **R5: the model-spend envelope.** With a small LLM cap, the agents stop at it with "Agent turns are on hold" as
  before. A Screen granted with a model-spend envelope holds the request's turns when it is spent, with one card to raise
  it. [R5](../readiness/R5.md#acceptance-test)
- [ ] **R6: who is woken.** Allocate 60 s to a proposal yourself and ask "How are the experiments going?": one answer, and
  nothing when the run ends; `/probe` gets no message from the lead; two probes the lead asks for still wake the operator
  and the lead reports once. [R6](../readiness/R6.md#acceptance-test)
- [ ] **R7: the mandate dial.** Monitor › Resources shows the default mandate under the compute thresholds (Screen for a
  delegated campaign until you choose). With the dial at Answer the lead only answers; Screen opens the envelope form and
  grants it with the message, shown above the chat with what is left; Close refuses new work; `/probe` opens no form; in
  the Autopilot thread its mandate shows with "switch autopilot off to end it" instead of Close.
  [R7](../readiness/R7.md#acceptance-test)
- [ ] **#70: the real lead on a fresh checkout.** Without the two Centinels variables the chat names them; with them, the
  lead answers on `gpt-6.1-sol`; providers in your own `~/.pi/agent/models.json` are still offered.

R1 (the mandate record) shows only through R2–R7.

## Live evals (Hoseung)

Phase 3 is judged against the eval baseline at `61538de` (the `baseline` tag). On Centinels, which needs no approval, at
this release's commit:

```bash
(cd agent-harness && npm ci --ignore-scripts && npm run build)
uv run python scripts/run_lead_evals.py --repeats 3 --record-baseline \
  --compare evals/lead/baselines/61538de-<provider>-<model>.json
```

Each of S1–S15 should pass at least as often as at the baseline (S15 fails until V4). R6 expects S8 to take one lead turn
(two if the lead asks the operator) instead of three, and S3 to record exactly two hypotheses and start nothing now that
its instructions no longer say "Read a request narrowly". Watch the number of Inbox cards per request (the phase's risk
of refusing too much): a request for small work should get none.

## In this release

| Part | What changed | PR |
|---|---|---|
| R1 | The mandate record and its four templates; every compute go-ahead reads as a Screen mandate | #33 |
| R2 | `mandate_propose`: Answer and Explore granted at once, Screen and Run the campaign one card | #60 |
| R3 | The bus refuses an agent's work outside its request's mandate; deadlines, spent envelopes and closing end it | #69 |
| R4 | Autopilot is a standing Run-the-campaign mandate; its cap guard is gone | #73 |
| R5 | Model spend counted per request, with a model-spend envelope per mandate | #56 |
| R6 | The researcher's own work wakes nobody; the instructions drop what the mandate enforces | #72 |
| R7 | The mandate dial in the chat, the active mandate above it with Close, the campaign's default template | #74 |

Also included: the fix for [#70](https://github.com/HoseungChoi51/Balsamic/issues/70) (the dev profile defines the
Centinels provider; a failed turn's error shows in the chat), PR #71. From phases not complete yet (paused): H1 (Phase 4),
V3 (Phase 5), N1, N2, N4, N8, N15 (Phase 6), K1, K3 (Phase 7), all merged before Phase 3 started.

## Known gaps

- Experiment rules and hiding runs are `configure` work, which only Run the campaign allows an agent; the experiment
  operator's instructions still say it keeps the rules, so under another mandate it is refused and asks (R3, R6).
- Once a request's Screen ends, it does not fall back to an earlier Explore; new work waits for a new mandate. The lead is
  not woken by a deadline unless approved runs were still to start (R3).
- Autopilot cannot ask for more with a card; once its cap is spent or its report date passes it may only answer, ask and
  record (R4).
- Balsamic's planned runs under a page agent's own mandate still wake the lead, and records no command names still do
  (R6). That a question gets an answer, not actions, still rests on the instructions.
- A report job the researcher starts on the Reports page belongs to no request and counts only against the campaign cap;
  a model-spend card raises the envelope by its own size (R5).
- The dial starts at Screen on most campaigns: it follows `autonomy`, which starting the agent team sets to delegated
  (Hoseung's choice), so every message first asks for an envelope until you set another default on Monitor › Resources.
  The form has no proposal picker and starts at fixed values; closing a mandate does not wake the agent; the dial is in the
  chat's composer only (R7).
