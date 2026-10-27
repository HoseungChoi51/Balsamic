---
name: runtime-profiling
description: Runtime profiles, flags, waivers, worker ceilings; optimizing a slow evaluator.
metadata:
  roles: lead, experiment_operator, resource_planner, implementation_lead
---

# Runtime profiling

Speed is measured, not assumed. `resource_inspect` shows each task's runtime profile: evaluations per second at 1, 2, 4...
workers, device load, the platform's share of each step, storage and solver executions per evaluation, with flags for waste.

- Runs at or above the gate length are refused until the evaluator's current source has a profile on this host with every
  flag fixed or waived.
- Notes (`note_flags`, such as `unsaturated`: speed still rising at the worker ceiling) hold nothing and need no waiver: go on
  with the work and mention the note in your reply.
- `runtime.profile` measures this on an idle workspace and takes a few minutes of compute: run it when the researcher asks for
  it or for runs that need it, and plan budgets from its measured evaluations per hour. (The lead asks the experiment operator.)
- How many runs go at once is planned by the resource planner within the researcher's resource level and worker maximum; the
  scheduler starts a queued run only when its expected memory fits. Queue the runs a request needs and ask the planner, not the
  researcher, why they wait or how many can go at once.

## A flag

1. Delegate one bounded optimization assignment in an implementation workspace (the implementation lead).
2. A change must reproduce recorded results before it is used: `evaluator.equivalence` replays a finished experiment's
   candidates under the new source; after it passes, `trial.continue` carries a finished run's saved state on as a new
   experiment.
3. Stop when the last attempt gained less than it cost, or the optimization allowance is spent. Then file `approval.request` for
   a waiver or another worker ceiling, or use `researcher_ask` for a fix to a built-in evaluator: only the researcher grants these.
