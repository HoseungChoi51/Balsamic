---
name: rcwa-convergence-check
description: Checking that an RCWA score holds at higher orders before reporting or ranking it.
metadata:
  roles: lead, experiment_operator, results_analyst, empirical_assessor
  status: draft from docs/lead-agent-readiness.md Part F and docs/paper-mapping.md; to be reviewed by the researcher
---

# RCWA convergence check

A score is computed at the evaluator's fidelity, and the Fourier truncation order is part of it: a score found at the searched
orders may not hold at higher orders. Energy conservation alone does not establish convergence of the target order.

What the record shows (`docs/lead-agent-readiness.md`, Part F, the 2D deflector):

- Designs searched at orders (10, 8) lost 6 to 15 points of mean efficiency by (26, 22); the TE part fell by 23 to 38 points
  while TM moved by at most half a point. The ranking of three designs did not survive.
- The orders that were short were those along the shorter period (y); raising only x changed little.
- A search can gain from the truncation: a design found at (10, 5) scored 93.75% there and 67.56% at (26, 22).
- The campaign's convergence recipe compares its two highest orders with a tolerance of half a point.

Before you report a best score, rank designs, or record a finding on an efficiency:

1. Re-evaluate the candidates at a ladder of increasing orders, raising each direction separately, with the campaign's
   convergence recipe or a validation; mind its memory at high orders (a ladder with (22, 18) and (26, 22) ran out of GPU memory).
2. Report the score at the searched orders together with the higher-order scores, per polarization when the objective
   combines them.
3. State in the finding the orders a score holds at, and do not compare scores computed at different orders.

For the 1D deflector of the 2022 paper (`docs/paper-mapping.md`): Fourier order 40 means 81 harmonics; the starter
configuration uses order 15, so a winning candidate must be re-evaluated across increasing orders before its efficiency is
interpreted.
