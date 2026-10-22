---
name: implementation-supervision
description: Delegating programming to a coding workspace and supervising it up to a validation.
metadata:
  roles: lead, implementation_lead
---

# Implementation supervision

For substantial programming, use `implementation_workspace_create` to delegate to a full native Pi coding session with a browser
IDE and normal shell and Git tools.

1. Give it an objective, the hypothesis and the evidence ids; no numerical grant is reserved by creating it.
2. Supervise with `implementation_workspace_inspect` (progress, questions, submissions, the event cursor) and steer or answer
   with `implementation_workspace_message`.
3. Commission an independent check of one committed submission with `implementation_workspace_validate`, within the campaign's
   implementation allocation; prefer a frozen envelope id when there is one.

Do not assume that creating a workspace or a submitted commit establishes correctness. Implementation builders, test designers
and reviewers work independently under frozen service specifications; existing working evaluators and bundled implementations
are reused when compatible. The old short-script implementation path remains for historical grants and light compatibility work.
