---
name: meent-problem-setup
description: The installed MEENT grating problems, and what to check when one is set up or varied.
metadata:
  roles: lead, discussion_moderator, experiment_operator, results_analyst
  status: draft from docs/paper-mapping.md and docs/problem-setup.md; to be reviewed by the researcher
---

# MEENT problem setup

Every value is stated once, in the problem charter; texts refer to values by name. Relations between quantities are decided by
the formulator, with a citation, and computed by code. Only the researcher confirms a charter (`docs/problem-setup.md`).

## The 1D metagrating deflector (Seo et al., ACS Photonics 2022)

From `docs/paper-mapping.md`:

- Normal-incidence TM light enters through silica (n = 1.45), passes a 325 nm patterned Si/air layer of 64 equal binary cells
  per period, and leaves into air. The objective is the absolute transmission efficiency in order +1, as a fraction of incident
  power; efficiency relative to the total transmitted power is not the objective.
- The period follows the grating equation: `wavelength_nm / (n_exit * sin(deflection_angle))`, 1435.95 nm at 1100 nm and 50°.
- Silicon: the default constant index 3.551726470588235 is the linear interpolation at 1100 nm of the authors' table, without
  extinction. Changing the wavelength while keeping it is a constant-index experiment, not the original dispersive material:
  set the index for the new wavelength (900 nm: 3.6349961538461537; 1000 nm: 3.5859457271364317) or choose another material
  model and record it as a separate assumption.
- The paper's 98.4% after two million evaluations at 1100 nm / 50° is a literature result, not a measurement of this platform.
- The reference design `tests/fixtures/wl1100_ang50_eff98.4.npy` checks the order sign and the forward formulation at order 40;
  it is not a trained result.

## The 2D dual-polarization deflector

The installed example states 1050 nm, 75°, a 256 × 128 grid and 325 nm thickness; its x period is 1050 / sin 75° by the grating
equation, and its silicon index is interpolated at 1050 nm (`docs/problem-setup.md`). When an input changes, the derived values
(period, index) must follow it; the charter computes them.

## Before comparing results

- A score belongs to the fidelity it was computed at: read `rcwa-convergence-check` before reporting or ranking.
- Compare methods with repeated seeds and matched evaluation budgets; one good design shows a successful search, not that a
  method is better.
