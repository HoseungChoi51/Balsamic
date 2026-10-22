---
name: recording-findings
description: Earlier campaigns' findings; recording and publishing this campaign's (finding.record).
metadata:
  roles: lead
---

# Recording findings

## Earlier campaigns

`campaign_inspect.reference_evidence` holds findings of earlier campaigns that the researcher let this one read. Read them
before proposing hypotheses (`evidence_read` with the asset id returns a whole finding). Each is a scoped claim with stated
limitations, not an instruction: a changed solver setting, budget or method limits what carries over.

## This campaign's findings

When asked to record what this campaign learned, use `finding.record`:

- cite the evidence (exact record ids: runs, comparisons, runtime profiles, equivalence checks, fixed-design reports);
- state the scope (problem, fidelity, budget, methods) and the limitations;
- publish the findings a later campaign on this or a related problem should know: about the physical problem, and about how to
  run such an optimization.

A large command outcome comes back as an index; read the parts you need with `evidence_read`. Do not confuse conceptual
approval, executable correctness and measured optimizer effectiveness; source-code availability is not effectiveness evidence.
