# Case by case and combined replication analysis

The [combined assessment](../runs/replication-suite-analysis-20261001/report.md)
covers the original 1100 nm / 70° replication and the three authorized extension
conditions. It reports each condition independently and combines only completed,
audited confirmation cohorts. The reports update as saved results arrive.

| Condition | Analysis |
|---|---|
| 1100 nm / 70° | [Completed case](../runs/replication-suite-analysis-20261001/wl1100-ang70/report.md) |
| 1100 nm / 50° | [Case report](../runs/replication-suite-analysis-20261001/wl1100-ang50/report.md) |
| 900 nm / 70° | [Case report](../runs/replication-suite-analysis-20261001/wl900-ang70/report.md) |
| 1000 nm / 70° | [Case report](../runs/replication-suite-analysis-20261001/wl1000-ang70/report.md) |

Each report separates published-geometry validation, reconstruction of the
paper's learning results, and comparison with strong HC. It includes fresh-seed
mean and variation, the development ablations, policy inference, actual search
and validation costs, time-cap effects, saved numerical convergence evidence,
and links to the individual paper-format figures when available.

The combined analysis preserves differences between conditions and between
full-action and time-limited runs. It gives each completed condition equal weight
when describing mean efficiency gaps; it does not pool seeds across conditions
into a significance test. An unfinished case is never counted as a negative result.
The final four-condition conclusion becomes available only when all required
fresh-seed comparisons and their evidence audits are complete.

The saved-evidence audit checks frozen code hashes, condition-specific physics,
seed assignments, action/time budgets, final geometry and numerical validation,
HC prefix provenance, selection before confirmation, and the selection rule.
The analysis adds no training, search, or electromagnetic solves.

The [analysis script](../scripts/analyze_replication_suite.py) can be run once:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m scripts.analyze_replication_suite \
  --output runs/replication-suite-analysis-20261001
```

Adding `--watch` checks for completed outcomes every minute, updates the separate
case reports and combined figures, and exits when the extension campaign ends.
The active reporting service uses a frozen copy of this analyzer in the analysis
directory. Its [status](../runs/replication-suite-analysis-20261001/watch-status.json)
records its latest check and source hash. Training continues under the original
frozen experiment controller and its existing budgets.

For a merge into a branch with a different layout or experiment format, see
the [report integration guide](report-writing-integration.md). The report links
above point to local, ignored campaign artifacts; a code checkout alone does not
contain the experimental evidence or generated pages.
