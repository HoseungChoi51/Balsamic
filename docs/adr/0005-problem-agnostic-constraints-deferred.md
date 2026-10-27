# 0005 Problem-agnostic constraints (M5) deferred until the narrower framework is confirmed

| Date | Status | Commit |
|---|---|---|
| 2026-10-21 | Accepted; restated as roadmap decision 20 on 2026-10-27 | `dec4713` |

## Context

The charter's checks are generic in vocabulary but narrow: the framework checks only a true/false test on quantities and
a linear condition on the decision variables. A non-linear design constraint, or a constraint on an outcome, has no
checkable form and becomes words.

## Decision

Add two forms when the time comes: a design constraint as an expression over the candidate's variables, and an outcome
constraint on the metrics the evaluator reports (M5, [problem-setup.md](../problem-setup.md), "Next step"). Start it only
after the present, narrower framework is confirmed to work correctly end to end, so there is a reference point to compare
against.

## Consequences

- Until then a qualitative finding is kept as a recorded criterion, or the formulator is asked for a checkable form.
- In the roadmap, M5 is parts N9 and N10, which start after G1 passes and Hoseung confirms the framework (decision 20).
