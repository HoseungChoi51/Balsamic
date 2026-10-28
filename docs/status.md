# Status

The one current status page, on 2026-10-28. What works, each phase of the [roadmap](roadmap/README.md), and the known
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
| The coding box: a coding agent works in a workspace from a written ticket, behind an egress allowlist, limits and a deadline; what it delivers is validated outside the box before it installs; commissions run as headless boxes, the one route that builds code; the researcher can deliver from their own coding agent | Tested; on with `development_enabled` | [H1–H8](releases/phase-4.md) |
| Evidence gates: every stop names a typed outcome and its evidence; an agent's stop as inferior needs an adequate assessment, and a finalist or library entry a score that holds at higher fidelity (where the problem declares a check), or the researcher's waiver; locked confirmation results stay unreadable to the agents until release; the gates and waivers on the Evolution page | Tested | [V1–V5](releases/phase-5.md) |
| Claims that resolve: agents compute numbers with a receipt; findings say what they state and count their measurements; numbers their evidence does not hold are badged; methods assessed and stopped are published as negative library entries. Review roles answer in one call from an assembled context; the moderator's synthesis is checked against the verdicts | Tested; the one-call roles wait for their live comparison | [T1–T4, K1–K4](releases/phase-7.md) |
| Problem packs: a problem declares what it brings (procedures, tools, fidelity ladder, references, methods, cost model), and the core names no new domain; whole-number variables, design and outcome constraints and problem-owned structured candidates in any problem; white box by default, judged by time; `enumerate` with proved optimality, size ladders, and proposals that name their family | Tested | [N1–N15](releases/phase-6.md) |
| Code libraries that last: each library a package with its own repository and tagged versions (the Packages page); an install keeps what any campaign uses, runs earlier versions' tests and replays kept methods' recorded runs; workspaces build on the latest version; reuse of an installed method comes first; a method a second problem needs splits into a method package | Tested | [L1–L6](releases/track-l.md) |
| Problem set-up in one pass: for a simple problem the lead writes the charter in the conversation and the note is read from it; one call reads the researcher's words against the charter and they settle each difference; a card in the chat confirms it in one click; code criteria send a problem that is not simple to the formulator with the lead's draft; the set-up measured from words to a confirmed charter | Tested; the live comparison with the baseline is Hoseung's | [P1–P6](releases/track-p.md) |

"Live" means the running services use the code; "tested" means the automated tests pass. Parts from the roadmap on say
their own state in [readiness/](readiness/README.md).

## Phases of the roadmap

| Phase | Goal | State on 2026-10-28, at `phase-6` (all phases released) | Release |
|---|---|---|---|
| 1 | Charter to results | Complete | [`phase-1`](releases/phase-1.md) |
| 2 | Measure first | Complete; the eval baseline is the `baseline` tag (`61538de`) | [`phase-2`](releases/phase-2.md) |
| 3 | A mandate for every request | Complete | [`phase-3`](releases/phase-3.md) |
| 4 | The coding box | Complete | [`phase-4`](releases/phase-4.md) |
| 5 | Evidence gates | Complete | [`phase-5`](releases/phase-5.md) |
| 6 | Problem packs | Complete | [`phase-6`](releases/phase-6.md) |
| 7 | Fewer standing agents, claims that resolve | Complete; T1, T3 and T4 wait for their live comparisons (ADR 0009, 0010) | [`phase-7`](releases/phase-7.md) |
| L | Code libraries that last | Complete | [`track-l`](releases/track-l.md) |
| P | Problem set-up in one pass | Complete; S20 and S21 wait for their live comparison with P1's baseline | [`track-p`](releases/track-p.md) |

This table changes when a phase completes: the part that completes it marks it done with its release tag
([releases](releases/README.md)). Between, a phase's parts say how far they got in their own files in
[readiness/](readiness/README.md); other parts do not edit this page.

## Known gaps

The guarantees that rest on the agents' instructions or on nothing, from the [invariant register](invariants.md), with
the roadmap part that closes each:

| Row | Guarantee | State | Closed by |
|---|---|---|---|
| INV-13 | The moderator's synthesis agrees with the reviewers' verdicts | prompt; code badges a disagreement (T2), nothing refuses it | no part planned |
| INV-19 | Numbers in findings and reports appear in the evidence they cite | prompt; code badges unsourced numbers (K2) and the evals measure them | no part planned |

The register is the source: when a part closes a row there, this list is out of date until the phase completes, and the
register wins.
