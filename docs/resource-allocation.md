# Resource allocation: one level from the researcher, the rest decided for them

Status, 2026-10-15:
- **Implemented and live on X670:** everything under "Implemented".
  - The level, measurement, memory admission and the implementation pool went live at the 13:25 UTC restart.
  - The resource planner and the rest went live at the 13:47 UTC restart.
- **Not done:** the items under "Not done".
- **Open:** the level numbers, which are proposed defaults.

## The request

The researcher should not have to decide what runs in parallel or how much: how many
experiments at once, whether two implementation jobs can share the machine, when a profile can
run. They choose how hard the machine may be used, and an agent decides the rest from the
system's resources and the usage expected of each job.

## Before this work

Concurrency was decided in four places, and none of them looked at what the others used.

| What | Who set it | Rule |
|---|---|---|
| Experiments at once, server-wide | Researcher: launcher `workers` (4 on X670); `workers.set` until restart | A fixed count of slots, with no memory or GPU check |
| Experiments at once, per campaign | Experiment operator: experiment rules `max_concurrent` | A count inside the server's slots |
| Race stages | The race profile | Its own worker count, plus a check that host memory stays 4 GiB above forecast use |
| Implementation jobs | Code | Exactly one at a time on the server, in queue order |

What was measured:
- **Live readings:** each worker's memory and the host's CPU, memory and GPU. Nothing was kept per run once it ended.
- **Runtime profiles:** evaluations per second at 1, 2, 4… workers.

On Oct 13, 8 workers ran out of GPU memory because another process held about 12 GiB. A fixed
slot count cannot foresee that.

## Decisions

Decided by the researcher on 2026-10-15:

1. **The Lead with a dedicated context, not a separate server-wide agent.**
   - **Built as:** the campaign's **resource planner**, a page agent on the Resources page. Like
     the experiment operator, it is an assistant of the Lead with its own conversation and its own
     narrow tools.
   - **Who reaches it:** the researcher writes to it on the Resources page. The Lead asks it with
     `page_agent_message`, which serves as the `resource_ask` this design first named.
   - **What it saw by default:** I had recommended a separate agent for the whole server, which
     could weigh one campaign's work against another's.
   - **What follows: code shares the machine between campaigns.** When several campaigns have
     runs waiting, each gets an even share of the runs at once, and each campaign's planner plans
     within it. (I chose this rule; it was not discussed.)
2. **The worker count moves to the planner, under a maximum.** The launcher's `workers` stays
   the researcher's hard maximum. The planner sets its campaign's working number at or below it.
3. **Code first.** The code-only part was built first and went live before the planner.
4. **GPU memory under CUDA MPS** (the researcher, after the code-only part): the planner reads
   `nvidia-smi` and the process list to infer what the live runs hold on the GPU, and records it
   as an estimate.

## How it works

### Who decides what

| Who | Decides | When |
|---|---|---|
| Researcher | One level for the server; the launcher's `workers` as a hard maximum | Whenever they like, on the Resources page |
| Code (admission) | Whether the next queued run fits now, within the level, the maximum, the planner's plan and the campaign's share | Every scheduler pass (0.4 s). No model is involved. |
| Resource planner | Estimates for kinds never measured; how many of the campaign's runs and of each kind go at once; when to re-profile; explaining a wait or an out-of-memory failure | When asked, and on resource events |

The planner starts and stops no runs. It cannot change the level, `workers`, budgets or
campaign limits. When the maximum is what holds the campaign back, it asks the researcher with
`approval.request` (`worker_ceiling`).

### Levels

| Level | Memory target (RAM and GPU) | Kept free | Implementation jobs at once | A run of a kind never measured | Planner's estimate counts as | After running out of memory |
|---|---|---|---|---|---|---|
| Cautious | 60% | 8 GiB | 1 | Starts only when nothing else runs | × 1.5 | Not run again |
| Balanced (default) | 80% | 4 GiB | 2 | Starts while no other such run is still starting | × 1.5 | Queued again once |
| Aggressive | 92% | 2 GiB | 4 | Starts while no other such run is still starting | × 1.0 | Queued again once |

On the GPU, the memory kept free is the smaller of this amount and 10% of the card. The level is
kept across restarts; `workers.set` is not.

A run is "still starting" until it has made 3 evaluations or run for a minute, whichever comes
first. From then on, its own live use, plus the margin, counts as its expectation. With the
planner's estimate, a kind never measured no longer waits for another to settle, except at
Cautious.

### Measurement

- **Memory:** every second, the scheduler reads the resident memory of each running run's whole process tree.
- **GPU memory:** the worker reports, when it ends, the most GPU memory its process held, where its array library keeps count (PyTorch or JAX, only if already loaded). The driver's own context, a few hundred MB per process, is not counted, and neither is an evaluator running in a separate process.
- **The usage record:** when a run ends, it is written as a `job_usage` record with:
  - the memory peak;
  - the GPU memory peak;
  - the run's status;
  - whether it ran out of memory, recognised from its failure reason.
- **What the planner reads:** `resource_inspect` adds, under `admission`, each running run's memory now and at its peak, and the GPU's processes from `nvidia-smi`. Under CUDA MPS the platform's runs share one MPS server process, so the planner infers a run's GPU memory: the card's total, minus other processes, divided among the runs alive.

A run's **kind** is what its use depends on: the problem as configured, and the algorithm or
implementation version with its settings and threads. A seed is not part of the kind. A kind
is expected to use the most any of its runs used, plus 25%. Until a run is measured, it uses
the planner's estimate (`resources.estimate`), shown as "Estimated by the resource planner". A
GPU estimate stands until a run reports its own GPU use.

### Admission

A queued run starts when the existing rules allow it (the `workers` maximum, the campaign's
`max_concurrent`, runtime-profile holds, execution grants) and all of these hold:
- **The planner's plan:** at most its number of the campaign's runs at once, and of each kind.
- **The campaign's share:** when other campaigns have runs waiting, each campaign gets an even share of `workers`.
- **New kinds:** the level's rule for a kind never measured (above).
- **Planned memory:** what running runs and this one are expected to use fits under the level's target of host memory.
- **Free memory now:** host memory free now, minus what running runs may still grow into, minus this run's expectation, stays above the memory kept free.
- **GPU:** where this run's kind has a GPU figure (measured or estimated), the same two checks hold for the GPU.

Runs admitted in the same scheduler pass count against each other. Race runs keep their own
memory admission. Each queued run's reason for waiting is shown on the Resources page.

### Running out of memory

When a run fails with an out-of-memory error, three things follow:
- **Its usage record raises its kind's expectation** to at least what the run reached.
- **At Balanced and Aggressive, an ordinary run is queued again once**, with the same request, a note in its question and `oom_retry_of` on the new run. A retry, or a run of a protocol, race or check, is not queued again.
- **The planner is told**, and lowers that kind's runs at once if the machine cannot hold them.

### What wakes the planner

These events are routed to the campaign's resource planner (created on first use; left alone
while paused or stopped). They do not wake the Lead:
- `resources.unmeasured_kind`: a run of a kind with neither a measurement nor an estimate is queued.
- `resources.out_of_memory`: a run ran out of memory.
- `resources.level_changed`: the researcher changed the level. Campaigns that already have a planner hear of it.
- `resources.long_wait`: a queued run has waited 10 minutes.

Each event is raised once per kind or run while the services run. Events from one pass arrive
together as one notice.

## Implemented

| What | Where | Live |
|---|---|---|
| The level: three settings, kept in the store, `PUT /api/v1/resources/level` (HTTP only, so only the researcher) | `execution/admission.py`, `api/app.py` | Yes |
| Memory of each running run's process tree; a `job_usage` record when it ends | `execution/admission.py` (`observe`, `_record`) | Yes |
| The worker's GPU memory peak in `result.json` (`device_peak_bytes`) | `execution/worker.py` (`device_peak`) | Yes |
| Kinds and expected use from records | `execution/admission.py` (`kind`, `expected`) | Yes |
| Admission against planned and free memory, and the GPU, in the scheduler pass | `execution/service.py` (`_loop`), `execution/admission.py` (`fits`) | Yes |
| A pool of implementation jobs sized by the level; the workspace sends the count to the implementation service | `implementations/service.py`, `implementations/api.py`, `implementations/client.py` | Yes |
| The resource planner: role, standing assignment, instructions with the current level, its tools (`resource_inspect`, `experiment_progress`, `campaign_command` limited to `resources.plan`, `resources.estimate`, `runtime.profile`, `approval.request`) | `agents/models.py`, `agents/tools.py` | Yes |
| `resources.plan` and `resources.estimate` commands; plans and estimates in admission | `campaigns/commands.py`, `contracts/commands.py`, `execution/admission.py` | Yes |
| The split between campaigns | `execution/admission.py`, `execution/service.py` | Yes |
| One retry after running out of memory, by level | `execution/admission.py` (`_retry`) | Yes |
| Events that wake the planner, routed by the controller | `execution/admission.py` (`_signal`), `agents/controller.py` (`_resource_events`) | Yes |
| What the planner reads: each running run's memory, the GPU's processes | `execution/admission.py` (`view(detail=True)`, `gpu_processes`), `agents/tools.py` (`resource_inspect`) | Yes |
| The Lead's guidance: ask the planner, not the researcher, why runs wait | `agents/tools.py` | Yes |
| Resources page: the level, the planner's desk, its plan, why queued runs wait, expected use per kind marked measured, estimated or not measured | `frontend/src/resourceDashboard.tsx`, `frontend/src/App.tsx`, `frontend/src/agentDesk.tsx`, `frontend/src/agentLive.tsx` | Yes |
| Tests | `tests/test_resource_admission.py` (11), `tests/test_pi_agents.py` (the planner's routing, tools and commands), `frontend/tests/resource-dashboard.spec.ts` | — |

The workspace sends the implementation count only to a service the deployment names
(`GRATING_IMPLEMENTATIONS_URL`), or to one passed in explicitly. An unconfigured client would
reach port 8766, which on X670 belongs to another checkout.

## Not done

- **Implementation jobs and analysis runs are not measured one by one.** Implementation jobs run as threads inside the implementation service, with check processes started from it. Analysis runs are short sandboxed scripts. Both are seen only in the host's free memory, which admission checks, not in expected use. Implementation jobs are limited by the level's count. Measuring them would need each check process to report its own peak when it exits.
- **The level numbers** are proposed defaults.

## Risks

- **GPU numbers.** Runs whose array library does not count GPU memory leave a gap the planner has to fill by inference. A kind with no GPU figure, measured or estimated, is checked against host memory only.
- **Processes outside Balsamic**, such as another GPU job on the same card, are seen only in live free memory and in what the planner reads, never in expected use. The memory kept free is what protects against them.
- **A large run can wait behind smaller ones.** When the run first in line does not fit, the scheduler moves on to the next. The planner can hold small kinds back with a per-kind limit.
- **Wall-clock allocations.** Implementation grants are charged in wall-clock time, so two jobs running their checks at once make each other slower.
- **Model spending.** Each batch of resource events is one planner turn on the economy tier, charged to the campaign's model budget.
