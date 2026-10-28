# The strategy library

Strategies that won earlier campaigns of the same problem, carried forward with their evidence (UI plan, M4), and
methods another campaign assessed fairly and stopped (roadmap K4).

## Entries

`library.publish {hypothesis_id, notes}` is the researcher's. It takes a finalist, or a strategy whose confirmation was
promising, and writes an immutable `library_entry`: the strategy (title, mechanism, rationale, algorithm and its
configuration, the implementation version), the campaign's problem signature at the time (problem id, evaluator
version, objective name and direction and units, representation, dimensions, a digest of the constraints and of the
instance, the charter), the evidence (the confirmation protocol, the race, the finalist selection, the best measured
score and its basis, seeds won, worker seconds, the runs) and where it sat in the graph (round, stage, parent links).
The hypothesis records `library_entry_id`. Publishing twice returns the same entry.

`library.publish {hypothesis_id, kind: "negative"}` (K4) writes a negative entry, "assessed and stopped". It takes a
stopped strategy whose typed stop (V1) judges the method: `configuration_unpromising` or
`adequately_assessed_deprioritized` with an adequate assessment (V2) or the researcher's tuning waiver, or
`implementation_invalid` or `assumptions_incompatible` with the stop's evidence ids. `under_evaluated`,
`unaffordable_within_allocation`, a stop without an outcome (`researcher_decision`) and one from before outcomes
(`unspecified`) are refused with the reason: they say nothing about the method. The entry records the stop (outcome,
words, reason, evidence ids, who), the assessment (`basis` adequate, waiver or not required, the words, and each
configuration run with its seeds), the best score as measured, and the signature that says where it applies. The
fidelity check of a positive entry does not apply: the score is not offered for reuse. An entry with no `kind` (written
before K4) reads as positive.

## Search

`GET /api/v1/library?campaign_id&problem_id&q` ranks entries against a campaign's signature (built from its first
development task's problem instance): same problem +3, same objective name and direction +2, same representation +1,
same constraints +1, and +1 for a word match in the title, mechanism, algorithm or notes; every score comes with its
reasons. Each row carries `kind`, and a negative one `label` "assessed and stopped: <outcome>"; the stop's reason is
searched with the words. The lead's `library_search` tool returns the same ranking with the kind and stop outcome, and when a campaign starts with matches of score 3
or more, the lead's turn state names them (`balsamic/lead/state.py` `library_line()`), the negative ones on a line of
their own.

## Apply

`library.apply {entry_id, note, title?}` (delegable) records a new root strategy in the campaign, inspired by the entry:
the entry's mechanism and algorithm, a rationale that names the entry, its origin campaign, its best score and how well
its signature fits here, and a typed `inspired_by` parent link, which the lineage draws as a long-dashed edge from
outside the campaign. Applying a negative entry is allowed; the rationale then says how and where the method was stopped:
the outcome and its reason, the assessment, the origin campaign and its signature, and the evidence ids. It is reviewed
and screened like any other proposal; the library grants nothing.

## Pages

The Library page lists entries for the current campaign with their fit and reasons, the winners and the "Assessed and
stopped" ones in two sections, searches by words, applies an entry (then opens the new strategy's card) and publishes
this campaign's eligible finalists, and its strategies stopped with an outcome that judges the method. Ctrl+K opens the search
palette over pages, threads and messages (`GET /campaigns/{id}/threads?q=`); `g` then a letter jumps to a page; a
thread exports as Markdown (`GET /threads/{id}/export`) and the graph as JSON (`GET /campaigns/{id}/evolution/export`).
