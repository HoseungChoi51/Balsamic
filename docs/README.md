# Balsamic documentation

In reading order. Read the design first, then the current state and the plan, then the logs. Documents that no longer
describe Balsamic are in [history/](history/README.md).

## 1. Design

| Document | What it covers |
|---|---|
| [README](../README.md) | What Balsamic is, how to install and run it |
| [ui-workspace.md](ui-workspace.md) | The chat-centred workspace and its service, milestone by milestone: the reference for the rebuilt service and frontend |
| [pi-agent-harness.md](pi-agent-harness.md) | The Pi agents: the lead, page agents, specialists, their tools and the gateway |
| [problem-setup.md](problem-setup.md) | Setting a problem up as a charter, and the next step (problem-agnostic constraints, M5) |
| [optimizer-plugins.md](optimizer-plugins.md) | Optimizer libraries and plug-ins: what a method must declare to be installed |
| [validation.md](validation.md) | The validation of the delivered DQN–MEENT setup |

## 2. Where things stand, and the plan

| Document | What it covers |
|---|---|
| [status.md](status.md) | The one current status page: what works, each roadmap phase's state, the known gaps |
| [roadmap/](roadmap/README.md) | The roadmap in seven phases, its principles and its settled decisions |
| [invariants.md](invariants.md) | The invariant register: which guarantees code holds, which rest on the prompt, which nothing holds |
| [incident-triage.md](incident-triage.md) | Triage by layer: where to fix a failure, from the mandate down to the UI |
| [adr/](adr/README.md) | Short dated decision records |
| [releases/](releases/README.md) | One release per roadmap phase, checked by acceptance tests |

## 3. Logs

| Document | What it covers |
|---|---|
| [lead-agent-readiness.md](lead-agent-readiness.md) | What was built and checked for the lead agent before the roadmap, Parts A–S |
| [readiness/](readiness/README.md) | One file per roadmap part: what was wrong, what changed, how it was checked, the acceptance test |

## 4. Reference for parts of the system

| Document | What it covers |
|---|---|
| [accounting.md](accounting.md) | Recorded expenditure and later receipts |
| [adaptive-algorithm-testing.md](adaptive-algorithm-testing.md) | The adaptive algorithm-testing protocol |
| [comparison-finalists.md](comparison-finalists.md) | Comparing methods and choosing finalists |
| [decision-inbox.md](decision-inbox.md) | The decision inbox |
| [diagnostic-extensions.md](diagnostic-extensions.md) | Registered diagnostic and inference extensions |
| [evaluator-commissioning.md](evaluator-commissioning.md) | Commissioning an optimizer and its problem evaluator |
| [evidence-bundles.md](evidence-bundles.md) | Portable research evidence |
| [flrl-implementations.md](flrl-implementations.md) | Fourier optimizers for the 2D MEENT campaign |
| [implementation-service.md](implementation-service.md) | The implementation service |
| [imported-reproduction.md](imported-reproduction.md) | Imported-source reproduction |
| [panels.md](panels.md) | Panels: pages the agents compose |
| [paper-mapping.md](paper-mapping.md) | Mapping the 2022 paper to this implementation |
| [pi-implementation-workspace-plan.md](pi-implementation-workspace-plan.md) | The Pi implementation workspace (extended by roadmap Phase 4) |
| [report-review.md](report-review.md) | Report review and the technical writer |
| [report-writing-integration.md](report-writing-integration.md) | The replication report writer |
| [resource-allocation.md](resource-allocation.md) | Resource allocation |
| [resource-observability.md](resource-observability.md) | Resource observability and RCWA memory planning |
| [runtime-efficiency.md](runtime-efficiency.md) | Runtime efficiency: measured, gated and owned |
| [server-control.md](server-control.md) | Starting and stopping the review servers |
| [strategy-library.md](strategy-library.md) | The strategy library |
| [study-monitoring.md](study-monitoring.md) | Monitoring a confirmation study |
| [suggestions.md](suggestions.md) | Why the lead reasons worse than a coding agent, and what to change |

## 5. Dated reports and assessments

| Document | What it covers |
|---|---|
| [application-command-inventory.md](application-command-inventory.md) | The application's commands, 2026-09-28 |
| [implementation-status.md](implementation-status.md) | Implementation evidence against the first plan |
| [paper2agent-assessment.md](paper2agent-assessment.md) | The Paper2Agent trial, 2026-09-18 |
| [grating-luna-review.md](grating-luna-review.md) | The first assisted 1D grating discovery run, 2026-09-28 |
| [grating-hybrid-review.md](grating-hybrid-review.md) | A recorded grating hybrid review, 2026-09-28 |
| [publication-checkpoint.md](publication-checkpoint.md) | The public development checkpoint, 2026-09-28 |
| [replication-suite-analysis-20261001.md](replication-suite-analysis-20261001.md) | The replication suite analysis, 2026-10-01 |
| [report-writing-discussion.md](report-writing-discussion.md) | Scientific report writing: discussion and tentative plan, 2026-09-30 |
| `exploratory-workflow-log.txt` | A raw exploratory workflow log |

Links into `runs/` in these documents point at local evidence on the lab machine; `runs/` is not in the repository.

## 6. History

[history/](history/README.md): superseded plans and the documents of the service before the 2026-10-19 rebuild, each
with its date and what replaced it.
