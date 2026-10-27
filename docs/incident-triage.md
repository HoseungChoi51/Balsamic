# Incident triage: fix a failure at the lowest layer that fits

When an agent does something it should not have, the quickest fix is usually a sentence in the instructions of the
command it happened on. Done every time, that leaves the visible failures with code and the silent ones with prose
(design review §06): the instructions grow, the model may or may not follow them, and nothing fails when it does not.
This page sets the order to ask in before fixing, so that a failure is fixed by code wherever code can hold it. The
[invariant register](invariants.md) records the result: which guarantees code holds, which rest on the instructions,
and which nothing holds yet.

## The five layers

Before fixing a failure, ask these questions in order, and fix it at the first layer that fits.

| Layer | Ask | Fix it in | Today | Later |
|---|---|---|---|---|
| `mandate` | Was it outside what the request allowed? | The guard that decides what a request may start | The compute consent (`campaigns/compute_consent.py`), the controller's request rules (`agents/controller.py` `_request`) and the routing of operations to the agent whose page they belong to (`agents/tools.py` `LEAD_PAGE_WORK`) | The mandate guard (Phase 3, R1–R3) |
| `budget` | Was it over a budget? | That budget's guard | The compute go-ahead and notice thresholds, the campaign's model cap (`agents/controller.py` `_within_llm_budget()`), autopilot's cap (`src/balsamic/autopilot/rounds.py` `cap_guard()`) | The mandate's envelope and deadline (R3) |
| `evidence` | Was it an unsupported claim or transition: a stop, a promotion, a published number without the evidence for it? | An evidence gate or a claim check | The concept review of an agent's own proposal (`campaigns/proposals.py` `readiness()`), the cited-evidence check of findings (`campaigns/findings.py` `record()`) | The evidence gates (Phase 5, V1–V5), the claim check (K2) |
| `prompt` | Was it the agent's judgement, with nothing above to hold it? | The instructions or a procedure, and an eval scenario that reproduces the failure | `agents/tools.py` `INSTRUCTIONS`, `src/balsamic/procedures/`, `evals/lead/scenarios/` | |
| `UI` | Was it what the researcher saw or could do? | The page | `frontend/src/` | |

A failure can touch more than one layer: a lead that started a run nobody asked for was both outside the request and
over a budget nobody approved. Fix it at the first layer in the table, and add a lower one only if the first cannot hold
it alone. A fix at the `prompt` layer while a code layer fits is a stopgap: say so, and name the part that moves it.

The order follows the roadmap's principle 9 ("fix at the lowest code layer"): what a request allows and what it costs
are checked by code before anything runs; what counts as evidence is checked when it is recorded; the instructions are
for what remains a matter of judgement; the page shows the state, it holds no rule of its own.

A failure that is a defect in code that already holds the behaviour (the code meant to refuse did not, or parsed a line
wrongly) is fixed where it is. The layers decide where a missing guarantee goes, not where a bug is.

## What every fix adds

1. **An invariant row.** Add a row to the [register](invariants.md) for the guarantee the fix holds, or update the row
   that already states it, with the test that now pins it (`code`) or the scenario (`prompt`). A guarantee left unheld
   gets a `none` row with the part that will close it.
2. **An eval scenario**, in `evals/lead/scenarios/`, that reproduces the failure and passes after the fix. A fix at a code
   layer adds one when the failure came from an agent's turn, so that the eval shows whether the agent still trips over
   the guard. A fix at the `UI` layer adds a Playwright test instead.
3. Or a sentence saying why none fits: a fix with no agent behaviour to reproduce (a parsing bug, a race between two
   writes) needs no scenario; a guarantee already in the register with the right state needs no new row.

The part's readiness file ([format](readiness/README.md)) names what was chosen in two lines after "What was wrong":
`Layer:` and `Invariant:`. `tests/test_readiness.py` checks them wherever they appear.

## Examples from the readiness log

| Failure | Layer | What the fix was |
|---|---|---|
| Started as a real campaign, the lead worked for 8 turns and 86 model calls before anyone asked (Part G) | `mandate` | Starting the team starts no turn, and outcomes wake the lead only while a request is open: code in the controller (INV-04, INV-05). The instruction "act on requests" stayed as the `prompt` layer for what happens inside a turn (INV-06, S3) |
| The lead held the pages' operations, and only the instructions told it to hand them over (Part P) | `mandate` | The operations left the lead's tools; a call is refused with the agent to ask (INV-07, S11) |
| Finalists' scores collapsed at higher RCWA orders (Part F) | `evidence` | A draft procedure only, so the row stays `none` until the fidelity gate (INV-16, V3) |
| The notice example said "wait" without its condition, and a request stayed open with nothing left to wake the lead (Part S) | `prompt` | The example waits only while the other run is still going, pinned by S8 |
| The Start panel told the researcher that the lead "begins working at once", after it no longer did (Part G) | `UI` | The panel and the lead's status say that it waits for a request |
| A housekeeping job wrote back a stale thread revision, so the researcher's next commands were refused (Part S) | none: a race in code that already owned the write | Fixed where it was, with a test; S4 reproduces its effect |
