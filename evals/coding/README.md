# Coding evals

How well, how fast and at what cost the coding path builds a method from its proposal (roadmap J4,
`docs/roadmap/phase-2-measure-first.md`). Phase 4 changes that path (the coding box), and is judged against the baseline
recorded here.

`pytest` does not collect `evals/`; `tests/test_coding_evals.py` runs the runner with `--fake`, so its plumbing and its
checks are tested with every test run.

## What a scenario does

Each scenario is one method of `libraries/grating-mask-search`, whose own module, tests and specification are withheld.

1. **The source.** The runner exports the checkout's `HEAD` (committed files only), deletes the scenario's `withhold`
   files, drops the method from the library's `plugin.py`, and commits the result as the only commit of a new repository:
   the workspace clones that, so no history holds the method. The library's `tests/test_contract.py` stays: it is the
   input, with the proposal.
2. **The lab.** As the lead evals do (`scripts/run_lead_evals.py`'s `Stack`): the workspace on a temporary directory, and
   the harness (the real one, or `tests/fake_harness.py` with `--fake`). Coding workspaces are on; installing delivered
   libraries is off (`GRATING_AUTO_INSTALL=false`), since the checks run on the delivery itself.
3. **The request, through the normal path.** A scratch campaign on the deflector example, the proposal recorded as the
   researcher's (`hypothesis.create`), the team activated, and the researcher's message to the implementation lead
   (`say`). The runner plays the researcher while it waits: it approves each go-ahead asked for (`approval.request`, which
   opening a coding workspace needs) and answers each question, the lead's or the coding agent's, with the scenario's
   `answer`.
4. **The checks, outside the box.** Once the workspace submits, the delivered files are written under
   `delivered/<scenario>/` and checked there, in a subprocess on this checkout's Python: the library's
   `tests/test_contract.py` (it must pass and name the method), its whole `tests/` (recorded, not graded), and
   `conformance.check()` of the method on the example's instance, through the library's own entry point. A scenario passes
   when the contract test and conformance pass. The delivered code runs on this machine, as it would once installed in the lab.

| Recorded | From |
|---|---|
| `seconds_to_workspace`, `seconds_to_submission` | the researcher's message to the workspace's creation, and to its first submission |
| `cost_usd`, `model_calls`, tokens | the campaign's model use: the lead and the implementation lead |
| `coding_agent` | the workspace's own use: the coding agent's model calls and tokens, `api_cost_usd` when billed by the API, container CPU seconds |
| `lead_turns` | turns of the lead and the implementation lead |
| `messages_to_coding_agent`, `notices_from_workspace` | the relayed messages: what the agents wrote to the coding agent after its assignment, and the workspace's notices to the agents (since A4, to the one that opened it) |
| `researcher_approvals`, `researcher_answers` | what the runner did as the researcher |
| `contract`, `tests`, `conformance` | the checks outside the box; the coding agent's own verdict is kept beside them |

## Running

```bash
uv run python scripts/run_coding_evals.py --fake                       # scripted agents, a prepared library: no model, no Docker, ~1 min
uv run python scripts/run_coding_evals.py --scenarios C1               # Pi in Docker on the dev profile's model
uv run python scripts/run_coding_evals.py --scenarios C1 --record-baseline
uv run python scripts/run_coding_evals.py --scenarios C1 --compare evals/coding/baselines/<commit>.json
```

A real run needs what a coding workspace needs (Docker, the image `docker build -t grating-implementation-workspace:pi-1.3.0
deploy/implementation-workspace`, the model provider's sign-in) and the harness built
(`(cd agent-harness && npm ci --ignore-scripts && npm run build)`). It calls a model and costs money: on the dev profile's
default provider (Centinels) it needs no approval (`docs/suggestions.md` §0.5). It waits up to the scenario's `timeout_s`
(4 hours) for a submission; `--timeout` sets another.

| Option | Meaning |
|---|---|
| `--fake` | The scripted turns of `fakes.py` and its `PreparedWorkspace`, which submits the original library |
| `--model provider/model[:effort]` | `agent.activate`'s model, which the coding agent runs on too; without it the dev profile's default |
| `--scenarios C1,C3` | Ids or their `Cn` prefixes |
| `--timeout S` | Seconds to wait for a submission, instead of the scenario's own |
| `--source DIR` | Another checkout's lab, harness and `HEAD` (for a baseline of an older commit) |
| `--record-baseline [PATH]` | Also write the summary to `evals/coding/baselines/<commit>.json` |
| `--compare PATH` | Mark regressions against a baseline in `summary.md` |

Output goes to `runs/coding-evals/<timestamp>/` (ignored by git): `results.json` (with the check outputs and the coding
agent's delivery report), `summary.md`, `delivered/<scenario>/` (the library as delivered: read one diff against the
original for quality) and, on a real run, `harness.log`.

## Scenarios

| ID | Method | Proposal | Withheld |
|---|---|---|---|
| C1 | `cyclic_geometric_vnd` | H12 (R4-A): its verbatim common contract, coarse draw and mechanism | module, tests, `docs/cyclic_geometric_vnd.md` |
| C2 | `conditional_mirror_search` | H13 (R4-B): its verbatim common contract, mechanism and the researcher's rescope | module, tests, `docs/conditional_mirror_search.txt` |
| C3 | `elite_spread_relinking` | H14 (R4-C), written from the module: its original mechanism is not in the repository | module, tests, `docs/elite_spread_relinking.md` |

A scenario file holds `method_id`, `library`, `example` (the problem example its instance comes from), `withhold`,
`proposal` (`hypothesis.create`'s payload), `say` (with `{hypothesis_id}`, `{title}` and `{method_id}`), `answer` and
`timeout_s`.

## Baselines

A baseline is the summary of a real run, committed as `evals/coding/baselines/<commit>.json`. The roadmap asks for one
method's baseline on the current route (Pi in the workspace, steered by the implementation lead) before Phase 4, and again
after H2, H4 and H7 (`docs/roadmap/phase-4-coding-box.md`).
