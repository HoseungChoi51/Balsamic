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
| `--repeats k` | Runs per scenario instead of the scenario's own `repeats` |
| `--suite-cap D` | Dollars of model use after which no scenario starts |
| `--source DIR` | Another checkout's workspace and harness (for a baseline of an older commit) |
| `--record-baseline [PATH]` | Also write the summary to `evals/lead/baselines/<commit>.json` |
| `--compare PATH` | Mark regressions against a baseline in `summary.md` |

Output goes to `runs/evals/<timestamp>/` (ignored by git): `results.json`, `summary.md`, and `transcripts/<scenario>-r<k>.md`
with the steps, the checks, the metrics, each run's input (and state block, once there is one), the messages and a line per
tool receipt. The exit code is 1 when a scenario fails; a scenario with a `known_failure` that fails is reported as `xfail`
and does not count.

### Baselines

A baseline is the summary of a real run on a given commit, committed as `evals/lead/baselines/<commit>.json` (transcripts
are not committed). The plan's baseline is taken on `a7e89b8`, before the fixes, from a worktree:

```bash
git worktree add ../balsamic-a7e89b8 a7e89b8
(cd ../balsamic-a7e89b8/agent-harness && npm ci --ignore-scripts && npm run build)
uv run python scripts/run_lead_evals.py --source ../balsamic-a7e89b8 --repeats 3 --record-baseline evals/lead/baselines/a7e89b8.json
```

Later runs compare with it: `--compare evals/lead/baselines/a7e89b8.json`. Record `pi_continue` turns per scenario
(the summary's column): Phase 4 is measured against them.

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

- `setup.preset`: `quadratic` (a task installed, so the problem-definition gate is open) or `formulating` (no task, gate closed).
  `setup.seeds` run before the team starts. `setup.extensions` names an extension allowlist (relative to the checkout) for
  the scenario's sessions instead of `agent-harness/extensions/allowlist.json` (S9 uses `evals/lead/extensions/allowlist.json`). Optional `scoring`: `all` (default: pass^k, every repeat passes) or `any`.
  Optional `known_failure`: why the scenario is expected to fail on the current code; remove it with the fix.
- Steps: `say` (a researcher message in the main thread; `{key}` takes a value a seed returned), `wait`
  (`request_closed`: the lead closed the request and no agent run is active; `idle`; `trials_settled`; `seconds`, with
  `timeout_s` or `seconds`), `seed` (a function of `seeds.py`), `approve_latest_decision`, `answer_latest_question`, `pin` (a record id).
- Checks, each read from the store at the end: `commands_exactly`, `commands_at_least` (an operation or a list, optionally
  `role` for one role's agents), `no_commands`, `max_commands` (agents' accepted commands), `max_lead_turns`, `max_continue_turns` (`pi_continue_*` runs), `no_model_calls`,
  `cost_usd_max`, `no_refusal_containing` (any refused tool call of the campaign's agents), `max_tool_result_bytes`,
  `reply_contains_any`, `reply_contains_none`, `reply_links_page`, `reply_matches` (a regular expression; all of the lead's
  replies to the last request, so a positive check passes on any and a negative one fails on any), `last_state_contains` (the state block the lead's last turn was given), `external_receipts_at_least` and
  `no_external_receipts` (receipts of extension tools), `outputs_at_least` and `structured_outputs_valid` (results specialists
  submitted), `verdicts_in` (a proposal's review verdicts), `no_researcher_question`, `request_closed`, `no_failed_runs`,
  `records_at_least`, `records_at_most`.

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
| S12 | A flawed proposal (an algorithm not installed, a binary mechanism on a continuous task) sent to a review round | F4, Phase 7 | The skeptical analyst submits a result, every result matches its schema, the verdicts are revise or reject |

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
