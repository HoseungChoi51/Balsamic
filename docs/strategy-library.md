# The strategy library

Strategies that won earlier campaigns of the same problem, carried forward with their evidence (UI plan, M4).

## Entries

`library.publish {hypothesis_id, notes}` is the researcher's. It takes a finalist, or a strategy whose confirmation was
promising, and writes an immutable `library_entry`: the strategy (title, mechanism, rationale, algorithm and its
configuration, the implementation version), the campaign's problem signature at the time (problem id, evaluator
version, objective name and direction and units, representation, dimensions, a digest of the constraints and of the
instance, the charter), the evidence (the confirmation protocol, the race, the finalist selection, the best measured
score and its basis, seeds won, worker seconds, the runs) and where it sat in the graph (round, stage, parent links).
The hypothesis records `library_entry_id`. Publishing twice returns the same entry.

## Search

`GET /api/v1/library?campaign_id&problem_id&q` ranks entries against a campaign's signature (built from its first
development task's problem instance): same problem +3, same objective name and direction +2, same representation +1,
same constraints +1, and +1 for a word match in the title, mechanism, algorithm or notes; every score comes with its
reasons. The lead's `library_search` tool returns the same ranking, and when a campaign starts with matches of score 3
or more, the lead's instructions name them so its first reply mentions them (`balsamic/lead/instructions.py`).

## Apply

`library.apply {entry_id, note, title?}` (delegable) records a new root strategy in the campaign, inspired by the entry:
the entry's mechanism and algorithm, a rationale that names the entry, its origin campaign, its best score and how well
its signature fits here, and a typed `inspired_by` parent link, which the lineage draws as a long-dashed edge from
outside the campaign. It is reviewed and screened like any other proposal; the library grants nothing.

## Pages

The Library page lists entries for the current campaign with their fit and reasons, searches by words, applies an
entry (then opens the new strategy's card) and publishes this campaign's eligible finalists. Ctrl+K opens the search
palette over pages, threads and messages (`GET /campaigns/{id}/threads?q=`); `g` then a letter jumps to a page; a
thread exports as Markdown (`GET /threads/{id}/export`) and the graph as JSON (`GET /campaigns/{id}/evolution/export`).
