# 0003 Problems are set up as charters: relations decided by the model, numbers computed by code

| Date | Status | Commit |
|---|---|---|
| 2026-10-15 | Accepted; widened by M5 when it starts ([0005](0005-problem-agnostic-constraints-deferred.md)) | `5f6f61f` |

## Context

Problems were described in prose and hand-written adapters. A model reading a statement could get the relations right
and the arithmetic wrong, and nothing showed which numbers had been typed in and which computed.

## Decision

A problem charter states a problem once: inputs, derived quantities (whitelisted expressions and tables), decision
variables, constraints, objective, evaluator binding, instances, reference results and sources. The formulator agent
decides the relations; code computes every value. Findings report conflicts, gaps, untested constraints, numbers typed
into texts and unused quantities. A campaign is created from a confirmed revision of the charter, on the New campaign
page. Framework code stays problem-agnostic; a domain's relations are data in its own package.

## Consequences

- The formulator cannot waive, accept or answer for the researcher.
- The framework checks only two constraint forms (a test on quantities, a linear condition on the variables); anything
  else lives in the evaluator or stays words. See [problem-setup.md](../problem-setup.md).
