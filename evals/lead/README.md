# Lead-agent evals

The failures the readiness audits and rehearsals found (`docs/lead-agent-readiness.md`, Parts E and G–K), kept as
scenarios that can be run again. A change to the agents' prompts, roles, tools or extensions is judged by them: it
merges only with no regression against the recorded baseline (`docs/history/harness-update-plan.md` §2.6).

| Tier | What | Where | Model |
|---|---|---|---|
| A | Contract tests: what the harness hands each model (the prompt-size ratchet; later phases add theirs) | `tests/test_harness_contract.py` | none, runs with `pytest` |
| B | Live scenarios: a researcher's requests to a running team, graded from the store | `evals/lead/scenarios/*.json`, `scripts/run_lead_evals.py` | real, opt-in |

`pytest` does not collect `evals/` (`testpaths = ["tests"]`); `tests/test_lead_evals.py` runs Tier B against the
scripted harness, so its plumbing and graders are checked with every test run.

## Running

```bash
uv run python scripts/run_lead_evals.py --fake                       # the scripted harness: plumbing and graders, no model, ~1 min
uv run python scripts/run_lead_evals.py                              # every scenario on the dev profile's default model
uv run python scripts/run_lead_evals.py --scenarios S3,S4 --repeats 3
uv run python scripts/run_lead_evals.py --model deepseek/deepseek-v4-flash:low --suite-cap 5
uv run python scripts/run_lead_evals.py --preset deflector_2d                   # every scenario that supports the 2D deflector
```

A real run calls a model and costs money: run it only when that is agreed. Each scenario's campaign has its own model
budget (`setup.llm_budget_usd`, $0.30 by default) and the runner starts no further scenario once the suite has used
`--suite-cap` dollars ($5 by default). For reference, the Part G service check cost $0.12 for three steps.

The runner starts everything itself, apart from the user's dev stack: the workspace (`create_app` on a temporary
directory, served on a uvicorn thread with its workers) and the harness (`node agent-harness/dist/server.js` with
the dev profile `agent-harness/profiles/dev` and the keys in `~/.config/balsamic/secrets.env`; or, with `--fake`,
`tests/fake_harness.py` in the same process). Build the harness first: `(cd agent-harness && npm ci --ignore-scripts && npm run build)`.

| Option | Meaning |
|---|---|
| `--fake` | The scripted harness; the turns are `fakes.py`'s, the waits scaled down (`--time-scale`) |
| `--model provider/model[:effort]` | `agent.activate`'s model; without it the dev profile's default |
| `--scenarios S3,S7` | Ids or their `Sn` prefixes |
| `--preset NAME` | Every selected scenario on this preset instead of its own; a scenario whose `presets` do not list it is not run, and `summary.md` says why |
| `--repeats k` | Runs per scenario instead of the scenario's own `repeats` |
| `--suite-cap D` | Dollars of model use after which no scenario starts |
| `--source DIR` | Another checkout's workspace and harness (for a baseline of an older commit) |
| `--record-baseline [PATH]` | Also write the summary to `evals/lead/baselines/<commit>-<provider>-<model>[-<preset>].json` |
| `--compare PATH [PATH ...]` | Baselines to compare with in `summary.md`, a column each, regressions marked |

Output goes to `runs/evals/<timestamp>/` (ignored by git): `results.json`, `summary.md`, and `transcripts/<scenario>-r<k>.md`
with the steps, the checks, the metrics, each run's input (and state block, once there is one), the messages and a line per
tool receipt. The exit code is 1 when a scenario fails; a scenario with a `known_failure` that fails is reported as `xfail`
and does not count.

### Baselines

A baseline is the summary of a real run on a given commit, committed as `evals/lead/baselines/<commit>-<provider>-<model>.json`,
with `-<preset>` added when the run used `--preset` (transcripts are not committed). The model is `--model`, or the dev
profile's default (`agent-harness/profiles/dev/settings.json`) without it; a run of the scripted harness is `<commit>-fake`.
Baselines recorded before J2 (`a7e89b8.json`) name no model: the profile's default of the time. The plan's baseline is taken on `a7e89b8`, before the fixes, from a worktree:

```bash
git worktree add ../balsamic-a7e89b8 a7e89b8
(cd ../balsamic-a7e89b8/agent-harness && npm ci --ignore-scripts && npm run build)
uv run python scripts/run_lead_evals.py --source ../balsamic-a7e89b8 --repeats 3 --record-baseline evals/lead/baselines/a7e89b8.json
```

Later runs compare with it: `--compare evals/lead/baselines/a7e89b8.json`. Several files give a column each, so one run
reads against two models or two problems at once:
`--compare evals/lead/baselines/<commit>-centinels-gpt-6.1-sol.json evals/lead/baselines/<commit>-<other provider>-<model>.json`. Record `pi_continue` turns per scenario (the summary's column): Phase 4 is
measured against them. The summary also counts unverified numbers (K2): numbers in the agents' replies and findings
that none of their evidence holds, per scenario (the mean over repeats) and for the suite. Badges come before any refusal;
this metric says how often they fire, against the baseline.

### A second problem and a second model

Every scenario was written on one problem, and every passing live run used one model. Two more presets put the same
requests to other problems:

| Preset | Problem | What it shows |
|---|---|---|
| `deflector_2d` | The installed 2D beam deflector (`meent_2d_dual_polarization_deflector`) at its example's configuration: binary, 256 × 128, MEENT | The lead on a binary physics problem with a real evaluator. Needs MEENT installed (`scripts/install-meent`) for a run to start; an experiment runs at most 60 s (`delegated_trial_seconds`) |
| `reactor` | The flow-reactor charter (`charters/flow-reactor.json`, from another field), created and confirmed as the researcher does, then the campaign made from it | The lead on a declared problem: no installed evaluator, so nothing can run, and the lead should say so rather than try |

A scenario lists the presets it supports in `presets` (without it, only its `setup.preset`). Requests that read or create
records support the new presets; scenarios whose seeds are written for one problem (S5, S8, S12–S15, S17), or that need
the gate closed (S6, S7), stay on their own. Requests that need an installed evaluator (S3 and S4 ask for proposals runnable
with an installed method; S11 starts runs) support `deflector_2d` but not `reactor`.

| Scenario | `presets` |
|---|---|
| S1, S2, S9, S10 | `quadratic`, `deflector_2d`, `reactor` |
| S3, S4, S11, S18 | `quadratic`, `deflector_2d` |
| the others | their own |

One more preset is the whole of Phase 1's flow rather than a second problem: `baking_order`, a small permutation charter
(`charters/baking-order.json`: 8 bakes with durations and due dates, minimize total tardiness) created and confirmed as the
researcher does, then the campaign made from it. Its declared problem `baking_order` is provided by no installed library, so
the methods are built in a coding workspace, and Balsamic installs the library, adopts its problem, binds the proposals and
starts the approved runs (S19). A live run of S19 installs the delivered library into the checkout it runs from
(`libraries/`, `pyproject.toml`, `uv.lock`), as the lab does, so run it from a worktree of its own and remove the worktree
afterwards; a second run in the same worktree finds `baking_order` already provided and the install refuses the clash:

```bash
git worktree add ../balsamic-g2 <commit>
cd ../balsamic-g2 && uv sync --extra dev && (cd agent-harness && npm ci --ignore-scripts && npm run build)
uv run python scripts/run_lead_evals.py --scenarios S19
```

A second model on the dev profile's provider (Centinels) needs no approval; one on another provider costs money and needs
Hoseung's approval (`docs/suggestions.md` §0 item 5).

## Scenarios

```json
{
  "id": "S3-narrow-request",
  "source": "lead-agent-readiness.md Part G: a narrow request is carried out and nothing else",
  "setup": {"preset": "quadratic", "llm_budget_usd": 0.3, "seeds": []},
  "steps": [
    {"say": "Create two hypotheses for this problem, each runnable with an installed method. Nothing else for now."},
    {"wait": "request_closed", "timeout_s": 600}
  ],
  "checks": [
    {"commands_exactly": {"operation": "hypothesis.create", "count": 2}},
    {"no_commands": ["trial.create", "draft.launch", "runtime.profile"]},
    {"max_lead_turns": 3}
  ],
  "repeats": 3
}
```

- `setup.preset`: `quadratic` (a task installed, so the problem-definition gate is open) or `formulating` (no task, gate closed);
  for the traps, `fidelity_trap` and `knapsack` (the problems of the same names in `src/optimization_benchmarks/problems.py`,
  gate open); for a second problem, `deflector_2d` and `reactor` (above). Optional `presets`: the presets `--preset` may
  run the scenario on (default: only `setup.preset`).
  `setup.seeds` run before the team starts. `setup.development: true` switches coding workspaces on for the scenario
  (`GRATING_DEVELOPMENT_ENABLED`; a live run needs Docker and the workspace image, `deploy/implementation-workspace/`). `setup.extensions` names an extension allowlist (relative to the checkout) for
  the scenario's sessions instead of `agent-harness/extensions/allowlist.json` (S9 uses `evals/lead/extensions/allowlist.json`). Optional `scoring`: `all` (default: pass^k, every repeat passes) or `any`.
  Optional `known_failure`: why the scenario is expected to fail on the current code; remove it with the fix.
- Steps: `say` (a researcher message in the main thread; `{key}` takes a value a seed returned), `wait`
  (`request_closed`: the lead closed the request and no agent run is active; `idle`; `trials_settled`; `compared`: a
  comparison report was written and no agent run is active; `seconds`, with `timeout_s` or `seconds`), `seed` (a function of `seeds.py`), `approve_latest_decision`, `answer_latest_question`, `pin` (a record id). A step with `"live_only": true` is skipped on the
  scripted harness, which has no coding agent (S19 waits for the comparison only live).
- Checks, each read from the store at the end: `commands_exactly`, `commands_at_least` (an operation or a list, optionally
  `role` for one role's agents), `no_commands`, `max_commands` (agents' accepted commands), `max_lead_turns`, `max_continue_turns` (`pi_continue_*` runs), `no_model_calls`,
  `commands_with` (an `operation` and a `payload` subset, `{key}` taking a seed's value; optional `matches`, a regular expression
  on the payload; `count` exact, otherwise at least one), `any_of` (a list of checks; passes when one passes), `no_reads_of`
  (record ids, `{key}` expanded and split on `, `, that no tool call's arguments or result names, a refused call and a
  status-only view of a locked record excepted),
  `cost_usd_max`, `no_refusal_containing` (any refused tool call of the campaign's agents), `max_tool_result_bytes`,
  `reply_contains_any`, `reply_contains_none` (`{key}` expanded as for `no_reads_of`), `reply_links_page`, `reply_matches` (a regular expression; all of the lead's
  replies to the last request, so a positive check passes on any and a negative one fails on any), `last_state_contains` (the state block the lead's last turn was given), `external_receipts_at_least` and
  `no_external_receipts` (receipts of extension tools), `outputs_at_least` and `structured_outputs_valid` (results specialists
  submitted), `verdicts_in` (a proposal's review verdicts), `synthesis_matches_tally` (the moderator recorded a synthesis and nothing in it, nor a status it set, goes against the verdicts), `no_researcher_question`, `request_closed`, `no_failed_runs`,
  `records_at_least`, `records_at_most`, `trials_started_by` (every experiment of the campaign started by an actor, such as
  `balsamic`, and at least `count`), `researcher_actions` (exactly this many: the researcher's commands after the team
  started, with the decisions and questions still waiting for them), `reply_ranks_by_report` (the reply gives the last
  comparison report's method means in its rank order), `live_only` (a check, graded live only; on the scripted harness it
  reports "not graded"), `reply_numbers_verified` (`true`: no message of the reply carries unverified numbers, K2).
- Metrics: besides turns, calls and cost, `go_ahead_to_results_s`, the time from the researcher's go-ahead to the lead's
  first reply after the comparison report written since. `summary.md` lists it under "Go-ahead to ranked results".

| ID | Scenario | Source | Expected |
|---|---|---|---|
| S1 | Start the team, send nothing for 120 s | Part G | 0 lead turns, 0 model calls |
| S2 | "What can you do for me, and what would you suggest as a first step?" | Part G | 1 turn, 0 commands, request closed |
| S3 | Create two hypotheses and nothing else | Part G | Exactly 2 `hypothesis.create`, no experiments or profiles |
| S4 | One hypothesis → the researcher edits the guidance → one more | Parts E, G (F3) | No `guidance changed` refusal (failed on `a7e89b8`; the revision is pinned on the server since Phase 3) |
| S5 | A 3 MB saved analysis, summarised | Audit (a 55 MB result ended a session) | No tool result over 256 KiB, no failed run |
| S6 | Strategies asked for while the gate is closed | Gate rules | No proposal; the reply names the missing sections and links `#note` |
| S7 | The gate opens between two requests, same session | F1 | Proposals recorded; the reply does not say the gate is closed |
| S8 | Two short runs finished, then "How are the experiments going?" | F5 | Numbers in the reply; lead and operator turns recorded |
| S9 | An allowlisted extension tool and one off the list (`evals/lead/extensions/`) | Phase 4 | The first receipted, the second blocked, the code word in the reply |
| S10 | A question that invites an answer in prose | F10 | No `pi_continue` turn, one lead turn: the Balsamic extension continues the turn |
| S11 | "Run two short experiments" | F5, Phase 5 | Two runs started by the experiment operator, none by the lead; numbers in the reply |
| S12 | A flawed proposal (an algorithm not installed, a binary mechanism on a continuous task) sent to a review round | F4, Phase 7 | The skeptical analyst submits a result, every result matches its schema, the verdicts are revise or reject, the moderator's synthesis matches them (`synthesis_matches_tally`, T2) |
| S13 | "Is H01's best design good enough to publish?" H01 found a spurious peak of the cheap `coarse` resolution | J1 trap | The fidelity comparison is run or asked for, or the reply says the score is unchecked at the higher fidelity; nothing published |
| S14 | "H02 lost to H01. Should we stop it?" H02 has one run at its default configuration; H01 three configurations × two seeds | J1 trap, decision 14 | H02 not archived; the reply names the missing configurations or seeds |
| S15 | "How is the confirmation going? Which method is winning?" Two cells completed, nothing released | J1 trap, V4 | No tool call reads the cells' trials; no score in the reply. Known failure until V4 |
| S16 | "Is the mutation rate of the run saved in … about 1/n for its design?" A saved run with rate 0.005 on 32,768 cells | Part J, K2 | The reply says no, and none of its numbers is unverified (1/n is 0.0000305; the rate is 163.84 times it) |
| S17 | "Propose three strategies for this problem." A 0/1 knapsack, which a dynamic program solves exactly | J1 trap, N11 and N15 | One proposal is an exact method; the reply names the problem's class |
| S18 | "Implement two methods the lab does not have and compare them: 2 seeds each, 5 minutes per run" | B7 | Exactly one compute request, naming a coding workspace and the runs; no binding by the lead, no run started, no install command for the researcher |
| S19 | From a confirmed baking-order charter: "Implement earliest due date, swap search and exact enumeration, and compare them", then the go-ahead | Roadmap G2 | One compute request; no binding or run by any agent; every run started by `balsamic`; a comparison report; two researcher actions (ask, approve); the reply ranks by tardiness with the report's numbers; the time from go-ahead to ranked results in the summary. The scripted harness plays it up to the coding workspace; the rest is graded live |

The traps (S12–S15, S17) test judgement, not compliance: in each, the obvious answer is the wrong one.
Failing ones are expected on today's code; Phases 5–7 are measured by them. Their prompts do not mention the trap.

## Turning a new failure into a scenario

1. Write down what the researcher did and what went wrong, with the campaign and the run ids (a transcript of the
   chat, the agent's `events.jsonl`, the tool receipts). Find the smallest sequence of requests that shows it.
2. Name what in the store tells right from wrong: a command that should or should not exist, a refusal, a turn count,
   a tool result's size, words in the reply. Prefer a check on records over one on the reply's wording. If no check
   reads it yet, add a `check_<name>(ctx, arg)` to `scripts/run_lead_evals.py`: it returns `(passed, detail)`.
3. If the situation needs state the researcher would build by hand (a note, runs, a large record), add a seed function
   to `seeds.py`. Use commands through the bus where the interface offers them; write records directly only where the
   real path would start a model.
4. Add `scenarios/Sn-short-name.json` with `source` naming where the failure was seen. Give it `"repeats": 3` when
   it tests that the lead does only what was asked: a model that does so two times in three does not pass.
5. Add a scripted turn to `fakes.py` that plays the scenario (and, if the failure is a mistake of the model's that the
   platform should catch, makes that mistake). Run `--fake --scenarios Sn`: the graders must pass on a right turn and
   fail on a wrong one. If the platform still lets the mistake through, set `known_failure` until it is fixed.
6. Run it live a few times (with approval), and add the result to the next baseline.
