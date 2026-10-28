# Single-machine total tardiness — 0.2.1

Reusable numeric scheduling library with three separate optimizer plugins. No problem
adapter or campaign evaluator is provided or registered. No campaign runs are authorized
by this delivery. The immutable generated `data.py` and `charter.json` remain untouched
for installation integrity; none of the algorithms or tests imports campaign data.

## Numeric API

```python
from single_oven_total_tardiness import subset_dp, due_date_insertion, swap_search, recalculate
r = subset_dp([2, 0, 3], [1, -1, 4])  # tiny artificial fixture
assert recalculate([2, 0, 3], [1, -1, 4], r.order) == r
```

Every `solve(p,d)` returns immutable `Result(order, total_tardiness, completion, wait)`.
`order` holds original zero-based job indices. `completion[j]` and `wait[j]` are indexed
by original job, NOT sequence position. Wait means customer tardiness, not queue time:
`max(0, completion[j]-d[j])`. All jobs are available at elapsed start zero; processing
is continuous, with no idle/setup/preemption. Due values are ALREADY elapsed minutes;
no clock-origin subtraction occurs. There is no early reward.

Inputs are copied to finite binary64 floats. Processing must be nonnegative, including
zero; due values may be negative. Length mismatch, nonfinite values and bad permutations
raise ValueError. Overflow of cumulative time/objective raises OverflowError. Empty input
returns empty vectors and zero; a singleton has completion p[0] and wait max(0,p[0]-d[0]).
Integer job indices are required (not bool or float); numpy integer indices are accepted.

* `subset_dp(p,d)`: O(n 2**n) arithmetic, O(2**n) state, hard cap 20 jobs (three packed
  arrays of subset sums, values and last-job pointers). Exact equal computed values choose
  the smallest original LAST index, recursively; all-zero tardiness therefore returns
  descending indices, not lexicographically smallest order. Independent final sequential
  recalculation must agree within 1e-10 absolute/relative or ArithmeticError is raised.
  Mathematical recurrence is exact, but binary64 arithmetic is not exact real arithmetic:
  near ties, very large magnitudes and loss of small increments can change choices.
  Exact integer arithmetic is reliable only while intermediate integer sums fit binary64's
  exact range (2**53); no formal floating-point optimality certificate is claimed.
* `due_date_insertion(p,d)`: increasing (due,processing,index), every position scored on
  ALL placed jobs, exact computed ties earliest position. Old relative order is preserved.
  O(n**3) arithmetic in this implementation. No later local search, no global guarantee.
* `swap_search(p,d,seed=0,evaluations=100)`: positive finite observation budget, random
  initialization only; returns best observed full order, not necessarily final current.
  No global guarantee. Neighborhood storage O(n**2); no unbounded-scale promise.

`swap_search.SwapSearch` (module import) exposes ask/tell, diagnostics, state_dict and
load_state_dict. Utilities are maximized; use **minus tardiness**. Core is a byte-identical
vendored copy of `src/optimization_framework/optimizers/swap_search.py`, SHA256
`fbfac29f9a740c71ba3112f0fe457543dcddba41ad2b21378cb35cfaffaf39ee`.
NumPy default_rng, moves, shuffled-pop and restart behavior are unchanged; source parity
is tested separately with NumPy 2.4.2 and 2.5.3. Package metadata permits
`numpy>=2.4.2,<3` to coexist with the host's 2.5.3 pin without changing host dependencies.
Only those two versions were tested; this does not guarantee cross-version RNG bitstream
or checkpoint portability, or behavior on every permitted future NumPy release. Raw core assumes sequential valid ask/tell; the optimizer_v1 wrapper
validates permutation/observation matching and prohibits multiple outstanding proposals.
Core checkpoint includes current/best, RNG, remaining moves and restart counters. Wrapper
checkpoints are JSON bytes with problem identity and an outstanding proposal if present.
Checkpoints are trusted same-version data, not a hardened untrusted-input format.

## Plugin binding

Entry point `single_oven_total_tardiness.plugin:Plugin` in group
`optimization_framework.optimizers`, permutation representation:

| Method ID | Proposal ID |
|---|---|
| subset_dp_exact_scheduling | hypothesis_pi_command_476837ad6603990c15d2240c6558dca2 |
| due_date_insertion | hypothesis_pi_command_7a87a57e21b6a87453d4dad3a5f5d325 |
| swap_insert_restarts | hypothesis_pi_command_f8872b4f838364d5f119c6cb0c790113 |

optimizer_v1 context uses dimensions, seed and a permutation problem descriptor with
primary_objective.direction=minimize. Constructive methods require public.processing and
public.due aligned to dimensions. No campaign-specific field translation is inferred:
the eventual trusted adapter must provide that generic descriptor. Host schemas currently
require n>=1; standalone numeric APIs support n=0. No parameters are exposed; especially
no restart override. Constructive methods expose exactly one FULL permutation and finish.
Swap plugin only proposes/observes: external trusted objective execution, caching and
wall/CPU timeout enforcement remain the host's responsibility. Non-ok or nonfinite
observations are rejected and leave the proposal outstanding; caller may supply a corrected
observation or stop. Inspection is bounded counters only; no artifact exports.

## Executed synthetic checks

Install locally with `python -m pip install --no-deps --no-build-isolation -e
libraries/single_oven_total_tardiness` (build tooling installed separately). Actual final
commands and outputs for v0.2.1 are in `reports/numpy-2.4.2.txt` and
`reports/numpy-2.5.3.txt` and implementation-manifest.json. On NumPy 2.4.2 the full suite
passed 70 tests in 0.33s and the separate contract rerun passed 7 in 0.24s; on NumPy 2.5.3
these passed 70 in 0.25s and 7 in 0.26s. Contract tests include installed entry-point
version/discovery checks. v0.2.1 wheel build also passed (`reports/packaging.txt`).
`reports/tests.txt` and `reports/contract.txt` are historical v0.2.0 receipts. All fixtures
have at most six jobs. tests/test_contract.py invokes the REAL host conformance checker
with synthetic ProblemInstance/CandidateSchema and no registered evaluator. Also checks
minimizing sign, outstanding checkpoint restoration, sequential lifecycle and installed
entry-point discovery. Exhaustive oracle tests are bounded correctness tests, not scientific
experiments, performance studies, a general proof or campaign optimality evidence.

Initial development run: 68 passed, 2 failed (uninstalled entry point and incorrect hand
fixture expectation). Installation needed editables; both issues were fixed before the
recorded final passing run. Missing campaign evaluator blocks end-to-end campaign use;
no such integration check was attempted or reported as passing. Adapter-dependent
protected validation is unavailable and was NOT invoked. v0.2.0 automatic host install
failed on its overly strict NumPy pin before adding methods; v0.2.1 repairs only package
metadata compatibility, without changing the host project's dependency files.
