# Status

The one current status page, on 2026-10-27. What works, each phase of the [roadmap](roadmap/README.md), and the known
gaps. The logs behind it are [lead-agent-readiness.md](lead-agent-readiness.md) (Parts A–S, before the roadmap) and
[readiness/](readiness/README.md) (one file per roadmap part, each with its State line).

## What works

A researcher sets a problem up as a charter, creates a campaign from it, and works with a team of Pi agents through the
chat ([ui-workspace.md](ui-workspace.md), [problem-setup.md](problem-setup.md)).

| Area | State | Log |
|---|---|---|
| The chat as the main interface: Enter sends, the lead's steps shown live, brief answers that link the page with the details, reports written on request | Live | Part H |
| Pages with one job each, grouped in the menu; page agents: discussion moderator, experiment operator, implementation lead | Live | Part I |
| Experiments: short and long runs apart, runs edited, run again or hidden, the operator's rules | Live | Part J |
| The review rounds drawn as a graph | Tested | Part K |
| The lead acts on the researcher's requests and starts nothing by itself; autopilot works under a standing mandate (R4) | Live | Part G, [ADR 0002](adr/0002-the-lead-acts-on-requests.md) |
| A mandate for every request: Answer, Explore, Screen or Run the campaign, proposed by the lead or granted with the researcher's message from the dial in the chat, shown above the chat with Close; the command bus refuses an agent's work outside it; autopilot is a standing mandate; model spend counted per request | Tested | [R1–R7](releases/phase-3.md) |
| The lead reads bounded results, installed methods, findings and files, and runs its own analysis | Live | Parts A, C |
| Compute is the researcher's: a notice threshold and a go-ahead threshold per campaign | Tested | [ADR 0007](adr/0007-compute-is-the-researchers.md) |
| The campaign's state in every turn, the guidance revision pinned on the server, Pi extensions curated per role, the pages' operations routed in code, procedures read on demand, specialists with briefs and output schemas | Tested, checked live by the evals | Parts M–R |
| Lead-agent evals that can be run again: 36 of 36 runs pass at `f851e9c` | Live evals | Parts L, S |
| Changing code through an implementation workspace | Dev mode only | Part C; roadmap Phase 4 |
| Scores re-checked at higher RCWA orders as a step of every campaign | Not in place | Part F; roadmap V3 |

"Live" means the running services use the code; "tested" means the automated tests pass. Parts from the roadmap on say
their own state in [readiness/](readiness/README.md).

## Phases of the roadmap

| Phase | Goal | State on 2026-10-27, at `phase-3` | Release |
|---|---|---|---|
| 1 | Charter to results | Complete | [`phase-1`](releases/phase-1.md) |
| 2 | Measure first | Complete; the eval baseline is the `baseline` tag (`61538de`) | [`phase-2`](releases/phase-2.md) |
| 3 | A mandate for every request | Complete | [`phase-3`](releases/phase-3.md) |
| 4 | The coding box | Paused by Hoseung: H1 merged; H5 and H6 open | — |
| 5 | Evidence gates | Paused: V3 merged; V1 and V4 open | — |
| 6 | Problem packs | Paused: N1, N2, N4, N8 and N15 merged; N3, N5, N6, N7 and N11 open | — |
| 7 | Fewer standing agents, claims that resolve | Paused: K1 and K3 merged; T2 and K2 open | — |

This table changes when a phase completes: the part that completes it marks it done with its release tag
([releases](releases/README.md)). Between, a phase's parts say how far they got in their own files in
[readiness/](readiness/README.md); other parts do not edit this page.

## Known gaps

The guarantees that rest on the agents' instructions or on nothing, from the [invariant register](invariants.md), with
the roadmap part that closes each:

| Row | Guarantee | State | Closed by |
|---|---|---|---|
| INV-12 | A reviewer does not read the other reviewers' verdicts before giving its own | none | T1 |
| INV-13 | The moderator's synthesis agrees with the reviewers' verdicts | none | T2 |
| INV-14 | A stop carries a typed stop outcome and its evidence | none | V1 |
| INV-15 | A stop for performance follows an adequate assessment or the researcher's waiver | none | V2 |
| INV-18 | Locked confirmation results stay unreadable to the agents until release | none | V4 |
| INV-19 | Numbers in findings and reports appear in the evidence they cite | none | K2 |
| INV-23 | A library's tests and conformance passed before it enters the lab | none | H6 |
| INV-25 | The coding box has a deadline | none | H5 |

The register is the source: when a part closes a row there, this list is out of date until the phase completes, and the
register wins.
