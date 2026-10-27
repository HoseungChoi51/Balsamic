# Integrating the replication report writer

This change is the saved-evidence reporting layer added on October 1, 2026.
It writes local Markdown pages, CSV and JSON evidence, and a combined PNG/PDF
comparison. The Pages skill supplied editorial guidance only; there is no Pages
connector dependency, publication API, or external messaging in this component.

## Commit boundary

Carry these pieces together when applying the commit:

| File | Role |
|---|---|
| `scripts/analyze_replication_suite.py` | Reads artifacts, audits evidence, writes per-case and combined reports, optionally watches for updates |
| `tests/test_replication_suite.py` | Protects completion rules, capped-run semantics, duplicate-seed rejection, and exclusion of unfinished or unaudited cases |
| `docs/replication-suite-analysis-20261001.md` | User-facing entry point and links to generated reports |
| `docs/report-writing-integration.md` | This integration and conflict-resolution contract |
| `README.md` | One paragraph linking the report index |

The change does not include training, optimizers, physics, campaign launchers,
dependency manifests, historical protocols, generated results, or systemd unit
definitions. It does not install a console entry point or package `scripts/`
into the application wheel. `runs/` remains ignored.

The writer imports the Python standard library and NumPy, with Matplotlib loaded
only for plotting. Tests additionally need pytest. The source branch's base
dependency manifest already provides these dependencies. `fcntl` makes the
single-writer lock Unix-specific. Use ordinary Python without `-O`, because the
evidence audit uses assertions. There are no imports from `dqn_meent`, Torch,
MEENT, or the campaign runner.

## Resolving source conflicts

Keep the destination branch's unrelated README and package documentation. Add
the report-index paragraph near its analysis/documentation links; its original
position next to the dependency introduction is incidental. Do not replace the
destination README with the full source working-tree version, which contains
uncommitted campaign documentation outside this commit.

If the destination has no `scripts/` package, the source directory works as a
Python namespace package when invoked from the checkout root. Alternatively,
move the writer to the destination's reporting module and update its test import,
documented command, and `__file__`-based repository default together. Pass
`--repository` explicitly when running a copied/frozen script elsewhere.

If an analyzer already exists, keep the destination's orchestration and UI entry
points and integrate this writer at the saved-artifact boundary. Its useful
boundaries are `audit_run` / `summarize_case` for input adaptation, `cohort` /
`comparison_ready` / `aggregate` for scientific rules, `case_report` /
`suite_report` / `plot` for presentation, and `fingerprint` / `main` for watching.
Changing paths or adapting field names is an integration change. Relaxing the
completion tests or changing the statistical meaning is a protocol change.

## Artifact contract

The writer is independent of application imports but deliberately coupled to the
saved replication schema. Supplying only aggregate CSV results is insufficient.
The data producers on the source working tree are the replication campaign and
extension scripts, training/snapshot diagnostics, and HC refinement; those
producers are outside this commit. An equivalent exporter on the destination
branch can supply this contract without merging their implementations.

| Input | Required meaning |
|---|---|
| Case `manifest.json` | `condition` with wavelength/angle, or legacy default 1100/70; development/confirmation seed lists; `profile_configs.P.physics`; `smoke`; aggregate `source_sha256`; optional `max_dqn_seconds` |
| `source-sha256.json` and `source/` | Original frozen execution files and their SHA-256 digests; aggregate digest uses `sha256(json.dumps(hashes, sort_keys=True).encode())` |
| Case `status.json` | Stage `finished` and no active jobs before promoting a comparison to complete |
| `jobs/*.json` | IDs, phase, kind, profile, seed, full config, run directory, and budget; timed jobs also contain launch/deadline/max-seconds fields and `runtime_cap_active` |
| Run `outcome.json` | Matching identity, recorded source-module path, status, summary, times, convergence flag, and final efficiency keys; optional policy/Q diagnostics |
| Run `config.json`, `summary.json`, `best_design.npy`, `best_design.json` | Agreement with the job/outcome and a saved 64-cell binary geometry |
| `snapshots/<step:09d>.json` | Actual final-step geometry and search result; DQN stores these under `search`, controls at the top level; controls also carry checkpoint cost records |
| `final-validation.json` | Ordered numerical results with efficiency values and convergence status; F160/F320 for development, F40/F160/F320/F480 for final controls and confirmation |
| `validation-cost.json` | Separate validation request/solve/time accounting |
| `selection.json` | Selected profile and selection time, preceding confirmation starts |
| `reference-results.json` and reference geometries | Completed reference job/count; converged numerical results and paths; `method=paper` marks the published design, all other entries are prior HC references |
| Refined-HC `provenance.json` and `prefixes/hc-s<seed>/` | The same-seed HC prefix geometry, step, elapsed time, and solver-call cost |
| Original case `source/data/paper_2022_supplement.json` | Frozen paper conditions, 64 binary design cells, and max/mean/SD arrays ordered as greedy depth 1, greedy depth 2, adjoint, GLOnet, DQN |

The phases are `development`, `confirmation`, and `control`; kinds are `train`,
`hc`, `refine`, and `references`. Learner profiles are P, C, S, T, H, TH, D, A, I,
G, and L. DQN summaries use `steps` and `evaluations`; control summaries use
`evaluation_requests`. The refinement job's local budget is half the final
logical trajectory; its final snapshot step is twice that local budget.

Recorded `run`, reference, provenance, and `source_module` paths are absolute.
The latter must equal `<case>/source/src/dqn_meent/__init__.py`. Changing
`--original` or `--extension` alone does not rebase paths inside artifacts.
Keep their original locations accessible, or implement an explicit path adapter
that preserves recorded provenance and distinguishes it from relocated paths.
Do not edit frozen source files or regenerate source hashes just to silence a
failed integrity check.

The CLI accepts `--repository`, `--original`, `--extension`, required `--output`,
and optional `--watch`. Defaults point to the September 20 original campaign and
September 30 extension. The extension child directories are currently fixed to
`wl1100-ang50`, `wl900-ang70`, and `wl1000-ang70`. All four case roots need their
prepared metadata, even while queued. The layout, 2-by-2 figure, profile labels,
five-seed confirmation wording, three-seed development wording, and three-hour
extension wording are specific to this protocol; this is not a general report
template engine.

## Scientific rules to preserve during a merge

Efficiencies in artifacts are fractions. The writer multiplies them by 100 for
percentages and percentage-point differences. The final convergence tolerance
is **0.01 percentage points**, or `0.0001` as a fraction. A 0.5 percentage-point
success margin is not a relative 0.5 percent improvement.

Only completed, converged results with the exact expected seed list form a
complete cohort. Missing, repeated, or invalid seeds do not count. Both P and the
selected profile need fresh confirmation, alongside both HC cohorts, a finished
case, valid references, and a passing audit. When P is selected, the same
confirmation cohort supplies both labels; it is not duplicated evidence.

A valid time-capped DQN can have outcome `status=completed` while its training
summary has `completed=false`. The former means the authorized bounded effort
finished with validated diagnostics; the latter means it did not reach its
action target. Keep `budget_stop_reason=wall_time_limit`, actual actions, wall
time, and the separate full-budget count. Unplanned interruption is different.

Selection uses median development F320 efficiency, with ties within 0.05 pp
resolved by maximum, total worker elapsed time, then profile ID. Do not let fresh
confirmation results change the selection. Final comparison uses F480, not the
development maximum or a policy rollout. The benchmark is the strongest valid
current or prior HC result, excluding the published DQN geometry.

The primary win requires three of five fresh selected seeds to exceed that
benchmark by more than 0.5 pp. If the strict target is at or above 100%, report
the physical-headroom limitation instead of treating an impossible margin as
evidence against RL. Report the actual gaps and 0.01 pp crossings separately.
Unfinished or unaudited cases never enter the combined verdict. Cross-case mean
gaps weight completed conditions equally; seeds are not pooled across conditions.

Refined-HC logical method costs include its own HC prefix; physical totals charge
that shared work once. Early HC and refinement crossings within a shared prefix
are not independent observations. Search discoveries, inference discoveries,
Fourier orders, development seeds, and fresh confirmation seeds remain separate.

## Outputs and operating behavior

The writer produces `<output>/<condition>/report.md`, `evidence.json`, and
`per-run.csv`, plus combined `report.md`, `evidence.json`, and
`case-comparison.png` / `.pdf`. `watch-status.json` records the current input
fingerprint, analyzer hash, and last check. JSON/Markdown writes use atomic
replacement; an `analysis.lock` file prevents simultaneous writers to one output.

The watcher checks every 60 seconds. Completed outcomes and relevant metadata
trigger regeneration; heartbeat-only changes do not. It exits when the extension
batch status is `completed`, `finished_with_missing_results`, or `interrupted`.
The writer generates the combined statistical figure, and links existing
paper-format galleries; it does not compute electromagnetic fields or create
those galleries itself.

The source machine runs a separate reporting service from a frozen analyzer
copy. Neither that service nor its absolute machine paths are installed by this
commit. Recreate a service using the destination's process manager if desired.
Keep its output directory separate from the campaign controller's reports to
avoid two writers overwriting the same files. A portable invocation is:

```bash
python scripts/analyze_replication_suite.py \
  --repository /path/to/checkout \
  --original /path/to/original-case \
  --extension /path/to/three-case-extension \
  --output /path/to/separate-report-directory
```

Generated report links in the README and index resolve only where the ignored
campaign artifacts have been supplied. An import-only or unit-test pass does not
prove the destination's artifact schema matches.

## Validation after resolving conflicts

From the destination checkout, run:

```bash
python -m pytest -q tests/test_replication_suite.py
python -m scripts.analyze_replication_suite --help
```

Then run the writer once against conforming saved data with a new output path.
Check that every `audit.errors` list is empty, compare original-case statistics
with its prior independent audit, and verify that unfinished cases are excluded
from `aggregate.complete_cases`. Inspect the Markdown tables and comparison
figure. Include at least one capped run, an incomplete confirmation cohort, and
the P-selected case when adapting the schema. These checks require no training
or electromagnetic solves.
