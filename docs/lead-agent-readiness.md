# Lead agent readiness: what is implemented and what is proposed

Status on 14 October 2026. This page keeps two things apart: changes that exist in the code, and
changes that are only proposed. An item moves from one part to the other when it is built and
tested, and the date is updated.

The goal is that a researcher and the campaign's lead Pi agent can run a whole campaign on the 2D
deflector problem (choose a preset, generate hypotheses, review and run quick experiments, choose
finalists and run them longer, record what was learned) without an outside coding session, and
that a later campaign can read what an earlier one learned. The longer aim is for the lead agent
to replace that outside session.

| Item | State |
|---|---|
| Lead receives bounded results; comparison report made small | Implemented, live |
| Lead sees installed methods and their parameters | Implemented, live |
| Findings may cite measurements; Lead reads referenced findings | Implemented, live |
| Results carry every objective of the best design | Implemented, live |
| Journals pack long binary designs | Implemented, live |
| Comparison of chosen experiments; a continued run read as one | Implemented, live |
| Journal clean-up on the researcher's approval | Implemented, live |
| Ten findings of the transformer-policy experiment recorded and published | Done |
| Rehearsal: the Lead runs the whole workflow once | Done: passed, after two fixes |
| Finalists may be chosen from runs that ended at their time limit | Implemented, live |
| Convergence test of the old campaign's best designs, recorded and in the report | Done; see Part F |
| Scores re-checked at higher RCWA orders as a step of every campaign | Not in place; see Part F |
| Lead reads files and runs its own analysis | Implemented, live, used once by a Lead |
| Requests that apply themselves on approval | Implemented, live, used once by a Lead |
| Lead changes code through an implementation workspace | Proposed, acceptable in dev mode only |
| Lead acts only on the researcher's requests; starting the team starts no work | Implemented, live, checked with a Lead; see Part G |
| Enter sends a chat message; Shift+Enter starts a new line | Implemented, live; see Part H |
| The Lead's steps and reasoning shown while it works; progress notes folded | Implemented, live, checked with a Lead and a reviewer on a scratch campaign; see Part H |
| The Lead answers briefly and links the page that shows the details | Implemented, live, checked with a Lead; rests partly on the model; see Part H |
| Agent discussions page: rounds, replies, verdicts, the Lead's responses | Implemented, live, checked on a scratch campaign; see Part H |
| Reports asked in the chat, written by the staged writer on the Lead's model | Implemented, live, one report written on a scratch campaign; see Part H |
| Menu in groups; pages merged; no Lead panel above the pages; an Agents page | Implemented, live; see Part I |
| Page agents: discussion moderator, experiment operator, implementation lead | Implemented, live, each checked once on a scratch campaign; see Part I |
| Experiments: short and long runs apart, runs edited or run again, obsolete runs hidden, the operator's rules and presentation | Implemented, live, checked with the operator on a scratch campaign; see Part J |
| The review rounds drawn as a graph | Implemented, tested; see Part K |
| Lead-agent evals that can be run again (scripted and live), a prompt-size ratchet | Implemented, tested with the scripted harness; no live baseline yet; see Part L |
| The campaign's state in every turn (state block); instructions fixed per role; pins reach the model | Implemented, tested; not checked live; see Part M |
| The guidance revision pinned on the server, never taken from the model | Implemented, tested; not checked live; see Part N |
| Pi extensions bound and curated per role; extension tools receipted; dialogs answered by the researcher; a turn without yield_work continued in the turn | Implemented, tested; not checked live; see Part O |
| The pages' operations routed in code: refused from the lead with the agent to ask; the lead reads experiment progress itself | Implemented, tested; not checked live; see Part P |
| Workflow procedures read on demand; the lead's instructions cut from 2,889 to 886 words | Implemented, tested; two domain procedures await review; not checked live; see Part Q |
| Specialists with briefs, tool scopes and output schemas; results submitted before completion | Implemented, tested; not checked live; see Part R |

"Live" means the running services on X670 use the code (last restarted on 14 October 2026).
"Not live" means the code is in the working tree and tested, and the services still run the old
code. "Tested"
alone means the automated tests pass; where a change was also checked on the running service, the
item says so. Parts A to G are committed on branch `lead-readiness`. Parts H to K are in the working
tree and not committed.

## Why this was needed

An audit of campaign `campaign_738bf861-d57f-4667-a797-669fc1bb101f` (transformer policies for
FLRL PPO, 12–13 October 2026) found:

- **The Lead did not drive the campaign.** All 8 hypotheses, the 25 `trial.create` and
  4 `trial.continue` commands, the finalist selection, the runtime profiles and the waiver were
  issued under the researcher's authority, none by the Lead. The Lead ran comparison reports,
  equivalence checks, snapshots and one fixed-mask check, and recorded one finding.
- **A comparison report ended the Lead's session.** `comparison.report` returned its whole result
  to the model: 11, 21, 24 and then 55 MB. After the last, every model request failed with
  HTTP 413 (from 06:22 KST on 13 October). The session file is 113 MB.
- **The Lead could not see what it could run.** The method catalog went only to the browser. The
  Lead asked the researcher for a mode-limit setting that already exists
  (`level_set_modes_x`, `level_set_modes_y`).
- **Nothing recorded reached a later campaign.** Agent reads are confined to their own campaign;
  no finding was published; the Lead's tools did not return findings referenced from another
  campaign; a finding could not cite runtime profiles, equivalence checks or fixed-mask reports
  (the Lead was refused twice).
- **The Lead asked for constraints to be lifted and got no answer.** Two questions have been
  pending since 12 October: one about mode limits, implementation workspaces and reading TE and
  TM of the best designs; one about a higher worker ceiling or a waiver.

## Part A — Implemented and live

Each item is covered by tests; the full suite passed on 13 October (1,278 passed, 1 skipped, plus
the three workspace tests run separately and the new tests listed here).

### A1. Bounded results for the Lead

`src/optimization_framework/agents/tools.py`

- A command receipt above 48 kB is returned as its status plus an index of its outcome; the Lead
  reads the parts it needs with `evidence_read` and the listed pointers. For `comparison.report`
  the receipt also gives each method's summary and one line per experiment.
- No tool returns more than 256 kB; a larger result becomes an error that says the call was
  carried out and how to read its record.
- Tests: `tests/test_pi_agents.py::test_large_command_outcome_returns_as_an_index_the_lead_pages`,
  `::test_no_tool_hands_the_model_more_than_it_can_hold`.

### A2. A small comparison report

`src/optimization_framework/analysis/general.py`

- Curves keep both ends of every run of equal best-so-far values instead of one point per
  evaluation. Values read at any cost are unchanged.
- Runtime-profile probes and equivalence replays are listed under `excluded`; they measure the
  evaluator and are no method's result. This was not in the first plan: 26 of the 55 experiments
  in the saved report were such measurements, and each replay carried about 3.5 MB of designs.
  Because 30-second probes no longer take part, a report's common cost changes.
- Checked on the running service against the saved 61.6 MB report of the same campaign: the
  report is 477 kB, 29 experiments are compared with the same best value and end cost as before,
  26 are left out as measurements, and the Lead's receipt for it would be 14 kB. It still takes
  28 s to compute, because it reads every experiment's metrics journal.
- Tests: `tests/test_framework_comparison.py::test_a_thinned_curve_reads_the_same_at_every_cost`,
  `::test_evaluator_measurements_are_not_reported_as_methods`.

### A3. Methods and referenced findings in the Lead's view

`src/optimization_framework/agents/tools.py`

- `campaign_inspect` returns `methods`: every installed optimizer that can run on a current task,
  with the parameters its `algorithm_config` accepts.
- `campaign_inspect` returns `reference_evidence`: findings of earlier campaigns that the
  researcher referenced for this campaign's study. `evidence_read` with a referenced asset id
  returns the whole finding; nothing else of the earlier campaign is readable.
- The instructions tell the Lead to build experiments from `methods`, to read referenced findings
  before proposing, and to record and publish what the campaign learns.
- For the 2D task the list has 21 methods in 16 kB, among them `flrl_ppo` with
  `level_set_modes_x/y`, `policy_network`, the `transformer_*` settings and
  `stacked_observations` (computed from the registry and the recorded task, not yet read by a Lead).
- Tests: `::test_inspection_lists_the_methods_a_task_can_run_with_their_parameters`,
  `::test_the_lead_reads_a_finding_of_another_campaign_only_once_it_is_referenced`.

### A4. Findings may cite the campaign's measurements

`src/optimization_framework/campaigns/findings.py`

- A finding may cite its own campaign's runtime profiles, equivalence checks, fixed-mask jobs and
  reports, and agents' saved analyses. Evidence of another campaign is still refused.
- Test: `tests/test_framework_manager_context.py::test_findings_cite_the_campaigns_own_measurements_and_saved_analyses`.

### A5. Every objective of the best design

`src/optimization_framework/execution/worker.py`

- A result gives `best_objectives` (for the 2D problem: TE, TM, their minimum and mean). A best
  design found before this change has none.
- Test: `tests/test_framework_worker.py::test_result_gives_every_objective_of_the_best_design`.

### A6. Packed designs in the journals

`src/optimization_framework/execution/metrics.py`, `worker.py`, `evaluation/jobs.py`, `execution/racing.py`

- A binary design of 128 cells or more is written to `requests.jsonl` and `observations.jsonl` as
  packed bits: 5.5 kB instead of 65.5 kB for 32,768 cells. Readers return the list as before, and
  journals written earlier still read.
- Expected for a 500,000-sample run: about 7 GB of journals instead of 66 GB (14 kB per
  evaluation instead of 133 kB). This is computed from the row sizes of the 12-hour runs, not
  measured on a run.
- Tests: `tests/test_framework_worker.py::test_journals_pack_a_long_binary_design_and_read_either_form`,
  `tests/test_framework_overhead.py::test_a_long_binary_design_costs_a_fraction_of_its_list_in_the_journals`.

### A7. Comparison of chosen experiments, a continued run read as one

`src/optimization_framework/analysis/general.py`, `contracts/commands.py`, `api/app.py`

- `comparison.report` takes `trial_ids`: only those experiments are compared, at the largest cost
  all of them reached. Without it one short run sets that cost for a whole study.
- A run continued with `trial.continue` is one row, named by its last experiment, with the earlier
  experiments' curves in front and their costs added; its method is the one it began as. An
  earlier experiment named on its own is the run as it stood then.
- Checked on the running service: the three 12-hour runs of campaign `738bf861` compare at 87,630
  evaluations (frame tokens 88.25%, coefficient tokens 84.12%, reference CNN 81.72%); the report
  is 66 kB and the Lead's receipt 2 kB. Each of those runs shows its last two experiments only:
  their first three hours were joined by the earlier warm-start workaround, which leaves no link.
- The report still takes about 26 s. Not addressed.
- Test: `tests/test_trial_continuation.py::test_a_comparison_reads_a_continued_run_as_one_and_compares_the_runs_it_is_given`.

### A8. Journal clean-up on the researcher's approval

`src/optimization_framework/execution/compaction.py`, `campaigns/commands.py`, `campaigns/research_commands.py`

The journals of every evaluated design are working data: a few gigabytes per long run are fine
while a campaign is analysed, and are removed afterwards, when the researcher confirms.

- The Lead files `journal.compaction_request` once results are analysed and recorded; it cannot
  run a compaction itself. The request appears in the decision inbox with the number of
  experiments, the gigabytes held, what stays, what is lost, and which of the experiments no
  recorded finding cites yet (it recommends keeping the journals while any is uncited).
- Approval runs `journal.compact` under the researcher's authority, one job at a time off the
  scheduler. The researcher can also issue `journal.compact` directly.
- What stays: every row and every number of both journals; the designs of each experiment's
  archive, of its 32 best evaluations and of 32 spread over the run; results, metrics, costs and
  saved states. What goes, for good: the other evaluated designs. They can no longer be
  snapshotted; an equivalence check replays the designs that stayed, and `trial.continue` is
  unaffected.
- A journal is replaced only after its copy reads back as the original without those designs.
  Only finished experiments are compacted, and compacting twice changes nothing.
- Tests: `tests/test_journal_compaction.py` (both), `tests/test_pi_agents.py::test_the_lead_may_ask_for_a_journal_compaction_but_not_run_one`.
- Not yet used on real data. The 72 GB of campaign `738bf861` is untouched.

## Part B — Agreed, not yet done

### B1. Record the transformer-policy experiment as findings — done

Ten published findings and one note superseding the stale finding
(`finding_pi_command_a2e616b9…`) were recorded on 13 October after the researcher's review
(ids in `runs/transformer-screen-20261012/journal/findings-recorded.json`; wording in
`findings-draft.md`, payloads in `findings-draft.json`).
Four are about the problem (efficiencies reached, comparison with the manuscript, evaluation
cost, what is unverified) and six about practice (a 1,024-design screen does not rank policies,
rankings change with budget, mid-run collapses, the CNN's plateau, measuring speed first, what was
not tested). Recording them exposed a fault in A4, fixed the same day: an equivalence record
names its problem by digest, which the publisher did not expect.

### B2. Rehearsal — done, see Part E

A scratch campaign from the preset at RCWA orders (10, 5) with a small budget. The researcher's
part is limited to what the interface offers (approve, choose finalists, waive); the Lead does the
rest: runtime profile, three hypotheses built from the method list and the referenced findings,
review, quick runs, finalist runs, `trial.continue`, a comparison of the finalists, a published
finding, and a request to compact the journals. It is
the acceptance test for "the Lead can run the workflow", and its profile gives the measured speed
at (10, 5) from which the new campaign's compute budget is set. Needs Part A live and B1 done.

### B3. Settings for the new campaign (the researcher's, at creation; no code)

- RCWA orders (10, 5): the preset default.
- 500,000 samples and 3 seeds per method, one environment: `max_steps: 500000`, continued with
  `trial.continue` when 24 hours is not enough.
- Compute budget: at the measured 20.6 evaluations per second for four concurrent runs, a
  500,000-sample run takes about 27 hours, so three methods with three seeds need about 250
  worker-hours (preset 69 h). This assumes a learner adds little to the probe's time, as in the
  earlier campaign, and it is for orders (10, 5), which Part F puts in question. Model budget
  about $25 (preset $5): the rehearsal used $1.02 in 52 minutes.
- Per-experiment limit for the Lead: at most 3,600 s. The contract caps it there, so an earlier
  version of this page was wrong to suggest 86,400 s. A run longer than an hour therefore goes one
  of three ways: the Lead starts it and files `trial.extension_request`, which the researcher
  approves once per run; the Lead carries it on an hour at a time with `trial.continue`; or the
  researcher launches it. Raising the cap is a code change, proposed in Part D.
- Reference the ten findings in the new campaign's Evidence view before activating the Lead.
- Worker ceiling: stay at 4 and waive the `unsaturated` flag, unless a higher ceiling is tried.

## Part C — Widening the Lead's access

The researcher approved points 1 and 2 on 13 October after the rehearsal; point 3 stays proposed.

### C1. Read access and its own analysis — implemented

`src/optimization_framework/agents/files.py`, `agents/tools.py`

- `file_list`, `file_read`, `file_search`: the repository, limited to the files git tracks, and
  the directories of the campaign's own experiments without their saved states.
- `analysis_run`: the agent's own Python script in a sandbox, with the experiments it names
  mounted read-only at `/data/<trial_id>`, numpy and the framework's journal readers importable,
  no network, no GPU, at most 300 s a run and 7,200 s per campaign.
- What the agent reads goes to its model provider. Outside the repository's tracked files and
  the campaign's experiments nothing is reachable: the private MEENT source and the manuscript lie
  outside the checkout, and credentials are untracked.
- Tests: `tests/test_pi_agents.py::test_agents_read_committed_repository_files_and_their_own_experiments_only`,
  `::test_an_agent_analyses_its_experiments_with_its_own_script_in_a_sandbox`.

### C2. Requests that apply themselves on approval — implemented

`campaigns/commands.py`, `campaigns/research_commands.py`, `contracts/commands.py`

- `approval.request` with kind `campaign_limits`, `waiver` or `worker_ceiling` puts a decision in
  the inbox; approval issues `campaign.update`, `validation.waive` or `workers.set` under the
  researcher's authority. Run extensions and journal compaction already worked this way.
- The per-experiment limit may now be set up to 86,400 s (it was capped at 3,600 s), in the
  campaign form as well. This goes with the request and was not separately confirmed.
- `workers.set` changes the ceiling of the running services at once and until they restart; the
  launcher configuration is not rewritten.
- Not covered: switching features on, and anything that needs a restart.
- Test: `tests/test_pi_agents.py::test_what_only_the_researcher_grants_is_asked_for_and_applied_on_approval`.

### Checked with a Lead on the running service

On 13 October the rehearsal campaign's Lead was asked to use the new tools. It found and read the
compaction rules in the repository's documents and stated them correctly; wrote a script and ran
it in the sandbox over four experiments (0.5 s, the evaluation counts and window medians it
printed match the records); and filed a request to raise the per-experiment limit from 1,200 s to
7,200 s, which was applied on approval as a budget amendment.

That check found a fault, now fixed (`agents/controller.py`): a researcher's message that arrived
while the Lead's last turn was calling the campaign complete was never delivered, because the
campaign was closed with the message still waiting. Test:
`tests/test_pi_agents.py::test_a_message_that_arrives_as_the_lead_finishes_is_still_delivered`.

### C3. Code changes, in dev mode only — proposed

Switch on the implementation workspace (a coding session in a container with a copy of the
repository) and add a path from an accepted commit to the running services. Dev mode is a server
started with a Pi profile (`pi_profile` in the launcher configuration, as on X670); a locked-mode
server would not offer this. Untested on this host, and the largest piece. Not built.

## Part D — Found on the running service

1. **A comparison had no common cost when one experiment was very short.** In campaign `738bf861`
   a 2.5-second rehearsal run emptied every method's summary; before that run existed the common
   cost was 473 s, the length of the quick screens, which is where the stale finding came from.
   Addressed by A7.
2. **The comparison report takes 26 to 28 s** on that campaign, whatever is compared. Not addressed.
3. **Recording a finding takes 13 to 29 s** on that campaign. Not addressed.
4. **The Lead cannot start a run longer than an hour.** `delegated_trial_seconds` is capped at
   3,600 s in the campaign contracts, while a 500,000-sample run takes many hours. Proposed: let
   the researcher set it up to 86,400 s, the limit a single experiment already has. Undecided.

## Part E — The rehearsal (13 October 2026, 14:32 to 15:24 KST)

Campaign `campaign_rehearsal-20261013-a`, created from the 2D preset at RCWA orders (10, 5) with the
ten findings referenced. It passed: the Lead carried out every step, and the researcher's part
was limited to what the interface offers.

| Who | What |
|---|---|
| Lead (24 commands) | Runtime profile; three hypotheses built from the method list, each citing referenced findings; a reviewer agent for them; six quick runs; two finalist runs of 900 s; two continuations of 300 s; a comparison of the two finalists by name; three findings (one published); a request to compact the journals |
| Researcher | Created the campaign, referenced the findings, activated the Lead; waived the `unsaturated` flag; approved the hypotheses; chose the finalists; approved the compaction |

- Cost: 52 minutes, 3,333 s of compute in 17 experiments, $1.02 of model use (97 calls). The
  Lead's session file ended at 0.7 MB and its largest tool result was 49 kB; the session that died
  in the earlier campaign had reached 113 MB.
- Measured speed at (10, 5): 8.1, 13.9 and 20.6 evaluations per second with 1, 2 and 4 workers.
- Journals: 193 MB for about 14,000 evaluations, 44 MB after the approved compaction.

Broken and fixed during the rehearsal:

1. A run that ended at its time limit could not be chosen as a finalist; only a run that completed
   its step count could. Fixed in `analysis/finalists.py` (test:
   `tests/test_framework_finalists.py::test_a_run_that_used_its_whole_time_allocation_can_become_a_finalist`).
2. The Lead could not read the result of the runtime check, a waiver or the shortlist. They are
   now readable (`agents/tools.py`). Not exercised again after the fix.

Seen and left as it is:

- After each answer from the researcher the Lead's next commands were refused once for an outdated
  guidance revision (four refusals); it re-read the revision and repeated them.
- Reading a result field of a run that is still going returns "The JSON pointer continues beyond a
  scalar value" (14 times), which does not say that the run has no result yet.

Not exercised: a failing run or a rejected hypothesis; implementing a new method; a run longer
than the Lead's limit; PPO at (10, 5); more than one reviewer or other agent roles.

## Part F — Scores at the searched RCWA orders do not hold at higher orders

First seen on 13 October while checking the rehearsal's best result, then tested on the three best
designs of campaign `738bf861`.

### What was run

- **Campaign records.** The campaign's convergence recipe (`meent_2d_order_convergence:v1`) on
  each long run's best design at orders (10, 8), (12, 10), (14, 12) and (18, 14): experiments
  `trial_3403da5762864d63` (frame-token), `trial_62c85acd1a8f4bca` (coefficient-token) and
  `trial_0a6c551f476149e0` (reference CNN). Its verdict compares the two highest orders with a
  tolerance of half a point.
- **Direct calls of the same evaluator**, not campaign records: orders (10, 5) to (26, 22), x and
  y raised separately, and y raised to 36 with x held at 14, for those three designs and for the
  rehearsal's evolution-strategy design. Kept in
  `runs/transformer-screen-20261012/journal/convergence-study-20261013.json`.
- Every score recorded at (10, 8) was reproduced to within 1e-13, and energy is conserved to
  2e-11 at every order.

### What it shows

Mean efficiency, with TE / TM in brackets (%):

| Design, and where it was found | (10, 5) | (10, 8) | (12, 10) | (18, 14) | (26, 22) | (14, 36) |
|---|---|---|---|---|---|---|
| Frame-token PPO, (10, 8) | 81.81 | **88.25** (81.8 / 94.7) | 86.48 | 77.33 (60.2 / 94.4) | 69.05 (43.8 / 94.3) | 70.41 |
| Coefficient-token PPO, (10, 8) | 79.42 | **84.12** (69.9 / 98.3) | 70.01 | 68.30 (37.9 / 98.7) | 67.48 (36.3 / 98.6) | 63.98 |
| Reference CNN PPO, (10, 8) | 76.36 | **81.72** (71.8 / 91.6) | 65.71 | 70.24 (48.4 / 92.1) | 70.50 (49.2 / 91.8) | 70.79 |
| Evolution strategy, rehearsal, (10, 5) | **93.75** (90.8 / 96.7) | 85.19 | 72.56 | 70.59 (44.5 / 96.7) | 67.56 (38.7 / 96.4) | 62.48 |

- **TM holds, TE does not.** From (10, 8) upwards TM moves by at most half a point; TE of the
  three campaign designs falls by 23 to 38 points by (26, 22).
- **The campaign's check fails two designs of three**: frame-token (5.3 points between its two
  highest orders) and reference (1.4). It passes the coefficient-token design (0.15), which had
  already fallen from 84.12% to 70.01% one step above the searched orders.
- **The ranking does not survive.** The designs are 6.5 points apart at (10, 8) and 3.0 at
  (26, 22), where the reference CNN's is highest.
- **Only the reference CNN's design settles**: 70.1 to 70.8% at all eight settings with 14 or
  more orders in each direction. The two transformer designs were still falling at (14, 36).
- **The orders that were short are those in y**, the direction of the 525 nm period. Raising
  only x from 10 to 26 moves the frame-token design from 88.25% to 86.19%; raising only y from 8
  to 22 moves it to 77.40%.
- **A search can gain from the truncation.** The evolution strategy reached 93.75% in 15
  minutes at (10, 5); that design scores 67.56% at (26, 22).
- **What it does not show**: the true efficiency of the transformer designs (still changing, and
  no second solver was used), or anything about designs this project has not evaluated, the
  manuscript's included.

### Where it is recorded

- Campaign `738bf861`: published finding `finding_finding-transformer-policies-convergence-20261013`,
  recorded as qualifying the findings on the efficiencies reached, the comparison with the
  manuscript and what was unverified. A new campaign should reference it with the other ten.
- The HTML report (`scripts/transformer_policy_report.py`): a section with a chart and both
  tables; the findings and the results table now lead with it.

### Consequence for the next campaign, undecided

RCWA orders (10, 5) match the manuscript's released code, and at those orders a score is cheap to
raise and does not transfer. One evaluation takes about 0.1 s at (10, 5), 0.2 s at (10, 8), 1.4 s at
(18, 14), 6 to 14 s at (22, 18) and 13 to 15 s at (26, 22), so a search of 500,000 samples cannot
run at orders where TE is stable. No step of the campaign workflow re-checks best designs at
higher orders unless someone asks for it.

### Faults found while running it, not fixed

1. The convergence recipe holds every order's solver in one job. With (22, 18) and (26, 22) in
   the ladder it ran out of GPU memory (15 to 22 GB), twice, while another job used part of the
   GPU. The recorded ladder therefore stops at (18, 14).
2. `validation.run` on a continued run did not answer within the request time (four attempts)
   when the run's best design had been observed in an earlier experiment of the chain: the
   service searches the whole journal for it. It answered at once for the experiment that found
   the design.
3. The evaluator loads the solver from a working checkout (`meent_2d_source`). That checkout was
   edited on 13 October at 16:29 KST while the services ran; later experiments record its source
   as modified. The scores reproduced, but nothing pins the solver for the length of a campaign.

## Part G — The Lead acts on requests (13 October 2026)

### What went wrong

A campaign created from the preset as a real campaign (`campaign_7cc90a3b`) had its agent team
started at 20:02 KST. The Lead began at once: it launched a runtime profile 29 seconds later, and
each probe that finished woke it again. Before the researcher's "stop" reached it, it had taken
8 turns and 86 model calls ($0.57) for work nobody asked for.

This was the design, not a slip of the model. Starting the team queued a first turn that said
"continue the campaign", the Lead's instructions said the researcher had "authorized end-to-end
work", every outcome in the campaign woke it with "inspect the records and continue", and the
Start panel announced that the lead agent "begins working at once". The rehearsal in Part E
showed that the Lead can carry out each stage. It is not how a campaign is meant to run: the
Lead designs and carries out experiments as the researcher asks, and does not run a programme.

### What changed

| Change | Where | Enforced by |
|---|---|---|
| Starting the team starts no turn; the Lead waits for the first message | `agents/controller.py` `activate` | The controller |
| A request is open from a researcher's message until the Lead reports it fulfilled; outcomes wake the Lead only while one is open | `controller.py` `_request`, `_campaign_events`, `_receive` | The controller |
| A runtime profile wakes the Lead once, at its end, not once per probe; a change the researcher makes to the campaign wakes nobody | `controller.py` `_campaign_events` | The controller |
| Resuming a paused team starts a Lead turn only if a request was in progress | `controller.py` `control` | The controller |
| Turns the platform starts are marked as notices, not requests | `agents/models.py` `NOTICE` | The Lead's instructions |
| The Lead's instructions: act on requests, one stage only when a request covers it, a question gets an answer | `agents/tools.py` `INSTRUCTIONS` | The model following them |
| The standing assignment replaces "continue the campaign"; saved teams are migrated at start-up | `agents/models.py`, `controller.py` `_migrate_records` | The controller |
| A turn returns everything the Lead wrote, not only its last line | `agent-harness/src/supervisor.ts` | The harness |
| The Start panel and the Lead's status say that it waits for a request | `frontend/src/models.tsx`, `piAgents.tsx` | — |

There is no setting that restores the old behaviour. A scripted run, such as a reproduction used
as a test, sends the Lead requests like a researcher would.

### Checked

- Automated: 1,296 tests pass (the full suite, before the harness change); the 49 agent tests and
  the 12 harness tests pass with it. New tests are in `tests/test_pi_agents.py`
  (`test_starting_the_team_starts_no_work_until_the_researcher_asks`,
  `test_outcomes_wake_the_lead_only_for_an_open_request_and_a_profile_reports_once`,
  `test_a_silent_turn_is_asked_for_its_checkpoint_not_told_to_continue`,
  `test_instructions_make_the_lead_act_on_requests_and_saved_assignments_follow`) and in
  `agent-harness/test/supervisor.test.mjs`.
- On the running service, after the restart: no campaign's Lead took a turn and no model call was made.
- With a Lead on DeepSeek V4 Pro, in a scratch campaign from the same preset and charter text
  (`campaign_service-check-20261013-a`, team stopped afterwards, $0.12 in all):

  | Step | What the Lead did |
  |---|---|
  | Team started, no message for 150 s | Nothing: no turn, no command, no model call |
  | "What can you do for me in this campaign, and what would you suggest as the first step?" | One turn, read the campaign and the host, answered, started nothing, closed the request ($0.03) |
  | "Create two hypotheses ..., each runnable with an installed method. Nothing else for now." | One turn, two `hypothesis.create` commands, no experiment, no profile, closed the request |

Not checked with a Lead: a request that starts experiments and is woken by their outcomes; a
request covering several stages; a subagent's result; an approval answered while no request is
open. The first of these is covered by the automated tests only.

### Seen during the check

- The first question's answer was 3,280 characters, written before the Lead's last tool call; the
  conversation showed only the 624-character closing line that followed. Fixed by the harness
  change above. A turn's message now also carries the short remarks the Lead makes between tool calls.
- After each researcher message the Lead's first commands are still refused once for an outdated
  guidance revision (Part E). Not addressed.

## Part H — The chat as the main interface (14 October 2026)

### What was missing

The researcher now runs a campaign by talking to the Lead. In the first campaign run that way
(`campaign_d6bcb1be`, 13 and 14 October):

- Enter did not send a message.
- While the Lead worked the chat showed nothing, and afterwards it kept every "still waiting" note:
  17 of the Lead's 62 messages were such notes.
- The Lead answered everything in the chat, including tables that a page already shows, and never
  pointed to a page. Asked for a report, it pasted the table and saved a record that no page opens.
  The writer on the Reports page could not run on this machine, which has no subscription model.
- Three specialists and eight reviewers had been asked, had answered and had given 31 verdicts.
  All of it was saved and no page showed it. The Notebook listed their replies as "Campaign manager".

### What changed

| Change | Where |
|---|---|
| Enter sends, Shift+Enter starts a new line; Enter that confirms composed (Korean) text does neither | `frontend/src/ui.tsx` `sendOnEnter`, `piAgents.tsx`, `research.tsx` |
| The harness keeps, in memory only, the steps and the end of the reasoning of each running turn | `agent-harness/src/supervisor.ts` `begin`, `observe`, `liveView`; `GET /v1/live` |
| The workspace serves it with each tool call as one readable line; an agent's activity uses the same lines | `agents/tools.py` `step_label`; `controller.py` `live`; `GET /api/v1/campaigns/{id}/agents/live` |
| The chat shows it while the Lead works, and what the Lead waits for while it waits | `frontend/src/agentLive.tsx`, `piAgents.tsx` |
| A reply records the kind of turn it came from and how the turn ended; progress notes the Lead has superseded fold into one line | `controller.py` `turn_marks`, `_migrate_records`; `piAgents.tsx` `chatEntries` |
| The Lead's instructions: short replies that link pages, no narration, no message in a notice turn with nothing new | `agents/tools.py` `INSTRUCTIONS`, `PAGES`, `command_page` |
| Agent discussions page, built from saved records | `agents/discussions.py`; `frontend/src/discussions.tsx` |
| Single model calls through the harness, with its sign-in and prices | `agent-harness/src/runtime.ts` `completeOnce`; `POST /v1/complete/<id>` |
| The report writer runs its stages on the Lead's model and charges the campaign, with a stop at the budget | `research/engine.py` `_call_pi`; `reports/writer.py` `start`; `reports/pipeline.py` `afford`; `controller.py` `report_model`, `model_allowance` |
| The Lead starts the writer and is woken at its end | `agents/tools.py` `report_write`, `report_answer`; `controller.py` `_campaign_events` |
| The Reports page lists the stages, the model, the cost so far and the reasoning of the running call | `frontend/src/reports.tsx` |
| A saved `yield_work` ends the turn (Pi's `terminate`), so a model cannot keep writing closing lines and yielding again; its summary is the status line, in plain words | `agent-harness/src/supervisor.ts`; `agents/tools.py` `INSTRUCTIONS`, `yield_work` |
| Verdicts, assistants' replies and saved analyses the Lead names reach the writer under their own ids and kinds | `agents/tools.py` `report_write`, `AGENT_RECORD_KINDS`; `reports/evidence.py` `freeze` |
| A report call is capped at 64,000 output tokens, reasoning included, and reserved at that cap instead of the model's own limit; the page shows spent and held amounts apart | `controller.py` `REPORT_CALL_OUTPUT_TOKENS`; `research/engine.py` `_call_pi`; `frontend/src/reports.tsx` |
| A Lead turn keeps its separate texts; the chat shows the closing one and folds lines written beside earlier tool calls ("1 earlier note from this turn"), unless an earlier text is much longer | `agent-harness/src/supervisor.ts`; `controller.py` `_receive`; `frontend/src/piAgents.tsx` `turnParts` |
| A claim's passage in a draft is found across a subheading and despite typographic quotes and dashes; the writer is asked for one sentence per claim | `reports/pipeline.py` `located`; `reports/editorial.py` |
| The page is sent with `Cache-Control: no-cache`, so a browser shows a new build on its next load instead of the cached one | `api/app.py` (frontend route) |

What is enforced by the code: reasoning reaches no saved record; a billed report call the budget
cannot cover is not made; a failed call is not repeated; the Lead cannot call a request fulfilled
while a report it started is being written; a turn ends when its `yield_work` is saved. What rests on the Lead following its instructions:
that its replies are short, that they link pages, and that it stays silent in a notice turn with
nothing new.

### Live check (14 October)

After the final round ended, both services were restarted and a scratch campaign (removed afterwards,
nothing kept) was run with DeepSeek V4 Pro at maximum effort. Total model spend: $0.93.

- Asked for one hypothesis and one review, the Lead recorded the hypothesis, asked a proposal
  reviewer and answered with links to Hypotheses and Agent discussions. The chat showed its steps and
  reasoning while it worked and what it waited for while the reviewer worked; the discussions page
  showed the round, the reply, the "revise" verdict and the Lead's response.
- Asked for a report, the Lead started the writer with one short reply and a link to Reports; the
  page showed the stages, the model and the reasoning of the running call. The Lead linked the draft
  when it was done. The report took 9 calls, 16 minutes and $0.36.
- Problems found and fixed during the check (rows added to the table above): the Lead called
  `yield_work` three times in one turn and repeated itself; it wrote lines beside intermediate tool
  calls that duplicated its closing message; a report could not see the reviewer's verdict it was
  about; each report call was reserved at the model's 384,000-token limit (about $1.57), so the
  writer stopped at a $2 budget; one job ($0.34) failed because the editor's passage for a claim ran
  across a subheading; a browser kept showing the previous build after an update.
- The Lead filed a request to raise the scratch campaign's model budget when the writer stopped. That
  was the right move under its rules; it was left unanswered and the campaign was removed.

### Not done

- Revising a draft through the Lead. The draft's own "request a revision" uses the same writer.
- Separate models per report stage; all stages use the Lead's model.
- Folding rests on the kind of turn and on what follows a note, not on what the note says: once
  the Lead has written again, a long interim note is folded like a short one, and opens with a click.
  A note you replied to and the newest note are never folded.
- The status line the Lead gives when it ends a turn is told to avoid record ids; DeepSeek still
  included one once after the change. Nothing removes them.

## Part I — Pages with one job each, and an agent in charge where one helps (14 October 2026)

### What was wrong

- Every page except four opened with the Lead's panel: its status, pause and stop, a message box,
  the whole agent team and the implementation workspaces. The Lead's chat already sits beside every
  page, so on most pages the panel only repeated it.
- The menu listed 19 pages in one column. Some were parts of others: Agent discussions belongs to
  Hypotheses, Experiment drafts to Experiments, Models, LLM usage and Campaign memory to the agents.
- The only agent the researcher could talk to was the Lead, which needs the whole campaign in view.
  The review rounds, the running of experiments and the building of implementations each need less,
  and no agent owned them: the Lead created a one-off assistant per assignment and moderated the
  review rounds itself.

### What changed

| Change | Where |
|---|---|
| Menu in groups: Overview and Decision inbox; Research (Problem, Hypotheses, Implementations, Experiments, Results, Studies, Reports); Evidence (Validation, Research assets, Notebook); Operations (Agents, Resources). 14 entries instead of 19 | `frontend/src/App.tsx` `menu` |
| Running work is marked on its page's entry: experiments running, a review round, an implementation being built, a report being written, decisions waiting | `frontend/src/activity.ts`, `App.tsx` |
| Merged pages keep their addresses: `#discussions` opens `#hypotheses/rounds`, `#drafts` `#experiments`, `#models`, `#llm-usage` and `#memory` the Agents tabs, `#notebook/agent-log` `#agents/log` | `frontend/src/routes.ts` |
| No Lead panel above the pages. Pause, stop, sign-in and the team go to Agents › Team; the Lead's questions to the chat, where they can be answered or dismissed; the implementation workspaces to Implementations | `App.tsx`; `frontend/src/agentsPage.tsx`; `piAgents.tsx` `AgentConversation` |
| Agents page with tabs Team, Models, Guidance (was Campaign memory), Usage (was LLM usage), Log | `frontend/src/agentsPage.tsx` |
| Hypotheses with tabs Proposals and Review rounds (was Agent discussions) | `frontend/src/hypothesesPage.tsx` |
| Problem (was Problem workbench): the charter, its revisions, the problem instances and their evaluators; the study list it repeated is on Studies only | `frontend/src/problemViews.tsx` |
| Drafts not yet started appear on Experiments, and only when there are any; the Experiment drafts page is gone | `frontend/src/experimentForm.tsx` `DraftsPanel` |
| Overview: a "Now" panel with what runs and what waits, linked to its page, and both budgets; the open campaign-manager issues folded into one line | `frontend/src/problemViews.tsx` |
| The Notebook's Agent runs and Discovery tabs only for campaigns of the older campaign manager; Problem importer reached from New campaign | `frontend/src/research.tsx`, `App.tsx` |
| Three page agents, one each per campaign, created when first written to: the discussion moderator (Hypotheses), the experiment operator (Experiments), the implementation lead (Implementations) | `agents/models.py` `PAGE_AGENTS`, `PAGE_OBJECTIVES`; `controller.py` `page_agent` |
| Each sees the commands of its page only. The moderator asks specialists and reviewers, whose results come back to it. The operator starts, pauses, extends and stops runs within the campaign's allocations. The implementation lead commissions implementations and uses coding workspaces | `agents/tools.py` `ROLE_OPERATIONS`, `PiTools.names`, `schema` |
| On its page, one line with its state and last word, opening into its conversation | `frontend/src/agentDesk.tsx` |
| Who hears what: a request on a page is that agent's own, and its outcome does not wake the Lead; the Lead's request (`page_agent_message`) comes back to the Lead. An experiment's or a job's outcome wakes the agent that started it, read from its tool receipts. The Lead's "still running" check ignores what page agents do for the researcher directly | `controller.py` `ask_page_agent`, `starter`, `_campaign_events`, `_receive`; `tools.py` `outstanding` |
| Page agents do not count toward the limit on assistants at work | `controller.py` `_sync` |
| Review rounds run by the moderator: what set the round off (your message, the Lead's request, an earlier round) and who ran it | `agents/discussions.py`; `frontend/src/discussions.tsx` |
| The researcher can set an agent's question aside without answering it (`agent.question_dismiss`); no agent is woken | `controller.py` `dismiss_question` |
| The model spend in the workspace state includes the agents' and the report writer's calls (it showed $0.00 for a campaign that had spent $9.99) | `api/app.py` |
| An agent's closing message carries the answer and its numbers, not only a pointer to them; the moderator reports verdicts in the reviewer's word and does not record them twice | `agents/tools.py` `INSTRUCTIONS`, `manifest` |

What is enforced by the code: a page agent's commands are limited to its page; the moderator asks
only specialists and reviewers; a request to a page agent does not open the Lead's request; the
Lead cannot complete while a page agent works on its request. What rests on the Lead following its
instructions: that it hands page work to the page agents instead of doing it itself. It keeps all
its tools, so nothing it did before stops working.

### Checked

- Python: 9 tests in `tests/test_page_agents.py` (tools per role, who hears what, the moderator's
  rounds, the limit on assistants, a stopped page agent taking the next request, dismissing a
  question), one in `tests/test_workspace_api.py` (model spend), the updated discussions and page
  tests.
- Browser: `frontend/tests/page-layout.spec.ts` (menu and markers, old addresses, no Lead panel on
  pages, the operator's bar, the moderator's bar, Agents › Team, a question shortened and dismissed);
  about 20 older specs moved to the new places.
- Screenshots of the new pages with this campaign's saved data, read-only, at 1440 and 390 pixels.

### Live check of the page agents (14 October)

Both services were restarted with this part, and a scratch campaign (removed afterwards, nothing
kept) was run with DeepSeek V4 Pro at maximum effort. Total model spend: $0.18 in 35 calls.

- **Experiment operator, asked on its page** to start one short run and stop it: it started the run,
  stopped it within a few seconds, read the run's files and reported 10 evaluations and the best
  score ($0.06). The Lead was not woken and its request stayed closed.
- **The Lead, asked in the chat** to have a proposal reviewed through the moderator: it handed the
  round to the moderator (`page_agent_message`) and linked Review rounds; the moderator asked one
  proposal reviewer, whose answer went to the moderator; the moderator reported back and the Lead
  gave the verdict in one line with links. Review rounds showed the round as the moderator's,
  started by the Lead's request, with the reviewer's "test" verdict.
- **Implementation lead, asked on its page** what a simple genetic algorithm would take: it read the
  installed methods and the code, answered that one is installed (`population`), named the experiment
  operator for running it, and started nothing.
- Seen and changed: the operator's closing message said it had the measurements without giving them
  (they were only in its status line); the moderator and the Lead called the "test" verdict "stand",
  and the moderator saved the reviewer's text again as a free-text review. The instructions now ask
  for the answer in the closing message and for verdicts in the reviewer's word, recorded once.
- Seen and left: an outcome that arrives while an agent is still at work is delivered as a short
  extra turn after it finishes (here, $0.002, "nothing further to do"). The Lead has always been
  handled the same way, so that a researcher's message arriving meanwhile is not lost.
- The page agents ran on the campaign's model: model tiers are not used on this machine.

### Not done

- The Lead may still do page work itself; the instructions ask it not to.
- Campaigns of the older campaign manager show their progress panel on Overview only.

## Part J — Experiments run by rules the operator keeps (14 October 2026)

### What was wrong

- A run the agents started could not be edited or run again with changes; only "Design an experiment" offered the form.
- Obsolete runs (failed out of memory, superseded) stayed in the list for good.
- Screening runs of 5 minutes and final runs of 4 hours were listed together, with speed probes among them.
- Nothing said how runs are named, how many may run at once, or in what order; each agent decided anew.
- Opening a run of the 2D problem listed its 32,768-cell design as a table, one row per cell.
- Time was entered in seconds everywhere, including campaign budgets of days.

### What changed

| Change | Where |
|---|---|
| Experiments has tabs: short runs, long runs, checks (validation, recipes, diagnostics, speed probes) and rules. Short and long are split at the rules' threshold, by default the runtime gate (10 minutes); the parts of a continued run are listed together | `campaigns/experiment_rules.py` `classify`; `api/app.py` (each run's `run_kind`); `frontend/src/experimentsPage.tsx` |
| A queued run is edited in the experiment form and the edited run replaces it; any run can be run again with changes, its settings filling the form. A run that started stays as it is | `frontend/src/experimentForm.tsx` (`template`, `replaces`) |
| Finished runs are hidden from the page, with a reason and who hid them, and shown again on request (`trial.hide`). Their records stay; findings and reports may still cite them | `experiment_rules.py` `hide` |
| Experiment rules per campaign, with revisions: how runs are named, the short/long threshold, how many of the campaign's runs may go at once, how runs are chosen and ordered (screening by successive halving across strategies, model-based sampling within one) | `experiment_rules.py`; `experiments.rules` |
| The scheduler holds back a campaign's runs above its limit; checks, speed probes and race runs are not held | `execution/service.py` `_over_campaign_limit` |
| The experiment operator keeps the rules and is told them every turn; the lead reads them in `campaign_inspect` and asks the operator how runs are going | `agents/tools.py` `manifest`, `INSTRUCTIONS` |
| `experiment_progress`: runs at work in queue order and the latest finished, with time and evaluations used and allotted, the best score, and whether a running run still improves | `agents/experiments.py` `progress` |
| `config_suggest`: the next settings to try, a space-filling spread at first, then expected improvement under a Gaussian process fitted to the scores | `agents/experiments.py` `suggest` |
| `lead_ask`: a page agent asks the lead about a proposal's reasoning or the researcher's intent; the answer comes back to it, and that lead turn neither opens nor closes the researcher's request | `controller.py` `ask_lead`, `_receive` |
| What the list and a run's entry show is part of the rules (presentation), chosen by the operator after asking the lead, from what the page can draw: the design as a mask image, a strip or a short table; the learning curve; the objectives; counts and time; settings; files; the question. Until chosen, a default drawn from the problem: a grid design is an image, and a design of hundreds of values is never listed | `experiment_rules.py` `Presentation`, `default_presentation`; `frontend/src/runViews.tsx` |
| A run's curve is read as a few hundred points of the columns it needs, not its whole journal | `api/app.py` metrics (`fields`, `points`) |
| Long time entries in minutes (campaign budgets in hours), with a unit beside the number | `frontend/src/duration.tsx` |
| An agent that calls a request complete gives its reply in `yield_work`'s `report`, which the chat shows as its message; without it the call is refused. DeepSeek had written "Now I can report" and ended the turn with the numbers only in its status line | `agents/tools.py` `yield_work`; `controller.py` `_receive` |
| A question the operator asks the lead, and the lead's answer, show in both conversations as an exchange between them | `frontend/src/piAgents.tsx` |

### Live check (14 October)

A scratch campaign (removed afterwards, nothing kept) on the 2D problem, with DeepSeek V4 Pro at maximum
effort; model spend $0.22.

- Asked to decide the presentation, the operator asked the lead (`lead_ask`); the lead answered with what
  matters for this problem (the grating drawn in 2D, TE, TM and the minimum beside the mean); the operator
  recorded it with its reason.
- Asked for a tiny screen, it started random and coordinate search for 30 evaluations each, named by the
  rule ("Screen · random floor · random · seed 1"), listed as short runs.
- Found and fixed: its closing message said it would report and the turn ended with the numbers only in
  its status line (twice), which led to the required `report`; it described a curve with TE and TM lines
  that the page cannot draw, which led to the schema saying exactly what each section draws.
- After the fix, asked again, its reply gave both scores with their TE/TM split, said one seed each cannot
  rank them, and suggested three population-search settings with reasons. It chose them itself rather than
  with `config_suggest`, and called a mutation rate of 0.005 "about 1/n" for 32,768 cells (1/n is 0.00003).

What is enforced by the code: the limit on runs at once; hiding only finished runs; a presentation that
fits the design (rows × columns equal to its size, no table of hundreds of values); the operator's
commands limited to its page. What rests on the operator following its instructions: naming runs by
the rule, the order of runs, and asking the lead before choosing the presentation.

### Not done

- The learning curve draws the primary objective only. The journals keep the other objectives (TE, TM, the
  minimum) inside a nested record per row, so a curve of them would read a long run's whole journal
  (over 100 MB) at every refresh. Asked for by the lead in the live check; it needs a scalar column per objective.
- The per-run allocations of a confirmation study (a dense table on Studies) are still entered in seconds.
- Results does not leave hidden runs out of its comparisons.

## Part K — The review rounds as a graph (15 October 2026)

The researcher asked to see the agents' discussion during hypothesis generation as a DAG, as ThoughtDAG
draws conversations. ThoughtDAG is an app (web, desktop, CLI, MCP; MIT), not a component that can be
embedded; its Session Atlas reads our Pi session files but draws each agent's session apart, without the
links between the lead, the moderator and the reviewers. The graph is drawn in our own page instead, from
the records the Review rounds list already reads.

| Change | Where |
|---|---|
| Review rounds has a List / Graph switch (`#hypotheses/rounds/graph`). The graph runs left to right: what set a round off, the round, each assistant asked, its response, the verdicts on proposals (labelled and coloured), the proposals each round created, and each revision | `frontend/src/discussionGraph.tsx`, `discussions.tsx` |
| A card opens its full text beside the graph (over it on a phone); a proposal can be followed, dimming the rest; an assistant at work pulses with its current step | same |
| Each proposal revision names the round whose turn created it and the role that did, read from its `hypothesis.create` receipt; unreviewed proposals are listed too (the table keeps to reviewed ones) | `agents/discussions.py` |
| Drawn with `@xyflow/react` 12.12.0 and `@dagrejs/dagre` 3.1.1 (MIT, pinned), in a chunk loaded only when the graph opens (243 kB; the main bundle grew 2 kB) | `frontend/package.json` |

The layout is computed again only when nodes appear or go, so a live update does not move the picture.
Nothing is written and no model is called: the graph reads what the list reads.

## Part L — Evals that can be run again (22 October 2026; harness plan, Phase 1)

### What was wrong

Parts E and G–K were checked by hand: a rehearsal, a service check, a scratch campaign. None of it could be
repeated, so a change to the instructions or the tools could not be compared with what came before
(`docs/harness-update-plan.md`, F8).

### What changed

| Change | Where |
|---|---|
| A runner that starts a workspace and a harness of its own (the real one, or the scripted one with `--fake`), plays a scenario's requests through the bus, grades from the store, and writes `results.json`, `summary.md` and a transcript per run; repeats with pass^k, a per-campaign model budget and a suite cap, baselines and comparison | `scripts/run_lead_evals.py` |
| Eight scenarios from the audits and the plan's findings (S1–S8), with seeds that build their state and scripted turns for `--fake` | `evals/lead/scenarios/`, `seeds.py`, `fakes.py` |
| How to run them, what each step and check means, how to record a baseline of an older commit, and how a new failure becomes a scenario | `evals/lead/README.md` |
| A prompt-size ratchet: the lead's instructions (2,889 words) and a specialist's (1,993) may not grow more than 10% | `tests/test_harness_contract.py` |
| The scripted suite runs with the tests | `tests/test_lead_evals.py` |

### Checked

- `--fake`: every scenario runs and is graded; S1–S3 and S5–S8 pass. S4 fails as expected: its scripted lead states the
  guidance revision it read in its first turn, as the models did in Parts E and G, and the handler refuses it (F3). It is
  marked as a known failure until the fix (Part N, which removed the mark).
- Python tests: 879 pass; the 16 that fail and the 3 files that do not load need `torch` or `gymnasium`, which this
  environment does not have, and fail the same way without these changes. Harness tests: 21 pass.

### Seen while writing the scenarios

- A status question cannot be closed while a run the researcher started is still going: `outstanding()` counts every
  run no page agent started as the lead's, so `yield_work(complete)` is refused and the lead must wait for the runs to end.
  S8 lets its runs finish before it asks. Not changed.

### Not done

- No real-model baseline yet: real runs cost money and were not approved in this session. The command to record it on
  `a7e89b8` is in `evals/lead/README.md`; until then the later Parts are checked with `--fake` and the tests only.
- No LLM rubric; every check reads records or the reply's text.

## Part M — The state of the campaign in every turn, the instructions fixed (22 October 2026; harness plan, Phase 2)

### What was wrong

- The harness fetched an agent's instructions only when it made the agent's runtime, and kept them for every later
  turn. The parts that described the campaign were therefore a snapshot of the first turn after a harness restart: the
  lead's "Gate now" line, its library matches and autopilot paragraphs, the experiment operator's rules (which the docs
  said it got every turn) and the resource planner's level (F1).
- `thread_pin` saved a record id on the thread, and the context drawer showed pins as "what the lead sees", but nothing
  put them into a turn (F2).
- The scripted harness fetched the manifest on every run, so no test could have caught this (F7).

Making the instructions follow the campaign would not have helped: for the providers in use, Pi folds a change of the
system prompt into the leading system message, so every change costs the prompt cache of the whole session.

### What changed

| Change | Where |
|---|---|
| Each turn starts with a state block built from the records at that moment and put before the message: the kind of turn, the thread, the researcher's open questions; for the lead the gate, autopilot, up to three library matches, up to ten pins of the thread and what it sets aside, the page agents at work; for the operator its rules; for the planner the level. Fixed order, at most 3,000 characters, no wall-clock time; saved on the run | `agents/turn_state.py`, `balsamic/lead/state.py` (`workspace.lead_state`), `PiTools.turn_state` |
| `POST /api/internal/pi/turn_state`; the harness calls it right before `prompt()`. The run's identity stays its text; a 404 (an older workspace) leaves the prompt as it was, any other error fails the run | `balsamic/api/internal_pi.py`, `agent-harness/src/supervisor.ts`, `server.ts` |
| The instructions no longer describe the campaign: the lead's briefing says where to read the state, the problem-note paragraph is always there, the operator's and the planner's instructions keep only their standing rules | `balsamic/lead/instructions.py`, `agents/tools.py` (`manifest`, `planner_instructions`) |
| The scripted harness fetches the manifest once per runtime (`restart()` forgets them) and puts the state block in the user entry | `tests/fake_harness.py` |
| The context drawer shows the state block the thread's last turn was given; the live layer says pins go into the next turn's block | `balsamic/threads/context.py`, `frontend/src/chat/ContextDrawer.tsx` |
| S7 checks the block its last turn was given (`last_state_contains`) | `evals/lead/scenarios/S7-gate-opens-mid-session.json` |

### Checked

- `tests/test_turn_state.py`: the lead's, operator's and planner's instructions and tools are byte-identical before and
  after the gate opens, autopilot is switched on, a library entry is added, the experiment rules change and the resource
  level changes; each change shows in the next state block; a pin reaches the next turn of its thread only; the block is
  saved on the run and capped; the route needs the token. `tests/test_harness_contract.py`: every role's manifest is the
  same in two campaigns in different states. The end-to-end test over the scripted harness: the gate changes between two
  turns of one runtime and the second turn's prompt says so; the manifest is fetched once, and again after `restart()`.
- Harness: `turn_state` is called on every run and the manifest once per runtime; the prompt carries the block; a 404 is
  tolerated; the same run submitted again while the state differs is the same run.
- The lead's instructions are 3,105 words (the problem-note paragraph is no longer conditional), inside the ratchet.
- `--fake`: S7 passes, with the gate closed in its first turn's block and open in its second.

### Not done

- Live S7 and the `cacheRead` comparison over a five-turn conversation: they need real model calls, not approved in this
  session.
- Steering messages carry no state block; they reach a turn whose block is minutes old at most.
- The state block accumulates in the transcript, one per turn; the cap and the ten-pin limit bound it.

## Part N — The guidance revision pinned on the server (22 October 2026; harness plan, Phase 3)

### What was wrong

After each answer from the researcher, the lead's first command was refused once for an outdated guidance revision
(Parts E and G). Three places disagreed: the shared instructions told the model to send "the exact current guidance
revision", the tool description said the revision was pinned, and the handler preferred the model's value. A model that
stated the revision it had read in an earlier turn was refused (F3).

### What changed

| Change | Where |
|---|---|
| A command is prepared against the larger of the revision its turn started from and the newest one a `campaign_inspect` of the same turn returned; a revision the model states is ignored | `agents/tools.py` `PiTools.guidance_pin`, `campaign_command` |
| `guidance_revision` stays in the schema, described as ignored; it goes in the next release (D7, a TODO beside it) | `agents/tools.py` `TOOLS["campaign_command"]` |
| The shared instructions no longer ask for the revision | `agents/tools.py` `INSTRUCTIONS` |
| A refusal because the researcher acted during the turn says so and what to do: read `campaign_inspect`, check the change, retry only if it still applies. The bus's message is unchanged | `agents/tools.py` `GUIDANCE_RECOVERY` |
| S4 is no longer a known failure | `evals/lead/scenarios/S4-guidance-after-page-command.json` |

### Checked

- A model-stated revision of 99 is ignored and the run's is used
  (`tests/balsamic/test_threads.py::test_lead_commands_pin_guidance_from_their_run_and_ignore_a_stated_revision`).
- A command after the researcher answered, without reading the campaign again, is still refused
  (`test_specialists_cannot_grant_authority_and_answers_invalidate_stale_commands`); after `campaign_inspect` in the same
  turn it is accepted; in a notice turn, a command stating the revision read in an earlier turn is accepted (the Part E
  pattern) (`tests/test_pi_agents.py`).
- `--fake`: S4 passes. Its scripted lead still states the revision of its first turn, as the models did, and is no longer refused.
- One test resolved several approvals (each changes the guidance) inside a single turn and stated the new revision itself;
  it now reads `campaign_inspect` before each command, which is what an agent does after a change within its turn
  (`test_what_only_the_researcher_grants_is_asked_for_and_applied_on_approval`).

### Not done

- Live S4 with k=3: needs real model calls.
- Removing `guidance_revision` from the schema: next release.

## Part O — Pi extensions inside Balsamic (22 October 2026; harness plan, Phase 4)

### What was wrong

- Pi extensions could not be used safely (F9): locked mode loaded none; dev mode gave every role, implementation grants
  included, the profile's extensions; the harness never called `bindExtensions`, so `session_start` never fired (nothing an
  extension starts there, such as an MCP connection, ever started), `ctx.ui` had nothing behind it and extension errors
  went unreported; and an extension's tool would have run without a receipt, an authority check or a size limit.
- A turn that ended without `yield_work` cost a whole extra controller turn (`pi_continue_*`) (F10).

### What changed

| Change | Where |
|---|---|
| The harness binds extensions after creating a session (mode `rpc`); extension errors go to the journal as `extension.error`; ending a runtime emits `session_shutdown` | `agent-harness/src/runtime.ts`, `supervisor.ts` |
| A UI bridge like RPC mode's: dialogs become questions to the researcher, answered with `agent.ui_respond` without a turn; 15-minute default, the extension's timeout if it gives one, cancelled at once under autopilot; notices become the activity line | `agent-harness/src/ui-bridge.ts`; `PiTools.ui_request`, `ui_state`; `controller.ui_respond`; `frontend/src/chat/ExtensionDialog.tsx` (chat, inbox, desks) |
| A curated set per role in both modes, from a versioned allowlist in the manifest; locked mode discovers nothing; grant roles load nothing; empty for now (D8) | `agent-harness/extensions/allowlist.json`, `agents/extensions.py`, `PiTools.manifest` |
| The Balsamic extension, loaded first: blocks tools off the allowlist, receipts the others (`external_receipt`, same identity scheme as gateway calls, immutable, readable in the campaign), cuts results over 256 kB, continues a run once in the same turn when it would end without `yield_work`, journals context usage | `agent-harness/src/gateway-extension.ts`; `PiTools.external_receipt` |
| The scripted harness plays the extension's rules: allowlisted calls receipted, others blocked, dialogs through the workspace, the one continuation | `tests/fake_harness.py` |
| S9 (an allowlisted extension tool receipted, another blocked) and S10 (an answer in prose, without `yield_work`) | `evals/lead/scenarios/`, `evals/lead/extensions/` |

### Checked

- Harness (`agent-harness/test/extensions.test.mjs`, real Pi sessions with test extensions): `session_start` runs once per
  runtime, the Balsamic extension's first; nothing in `~/.pi` or the working directory loads in locked mode; a grant's
  runtime loads nothing; `session_shutdown` runs on release; an extension error is reported. The extension blocks a tool off
  the list with a reason, receipts an allowlisted one with the active run, cuts a large result, withholds a result it
  cannot receipt, continues at most once and never after a saved `yield_work`. The UI bridge: an answer resolves a dialog,
  a timeout gives the default, a cancellation resolves as RPC mode does. 30 harness tests pass.
- Python (`tests/test_extensions.py`): the manifest names the role's extensions and a grant has none; an allowlist path
  outside its folder is refused; receipts are idempotent, immutable, refused for a tool off the list, for a gateway tool,
  for another agent's run and for a finished run, and readable only in their campaign; a dialog is answered without a
  run or a request and without a guidance change, dismissed or expired, refused when answered by message, cancelled at
  once in an autopilot round; the controller's `pi_continue_*` fallback still counts stalls and asks the researcher after
  three. The manifest's extension set is the same for a role across campaigns (`tests/test_harness_contract.py`). End to
  end over the scripted harness: a receipted call, a blocked call and a dialog answered from the chat in one turn, which
  the in-turn continuation closes without a notice turn.
- `--fake`: S9 and S10 pass.

### Not done

- No live run: the suite against the baseline, `pi_continue_*` counts dropping to about zero, and the cost of the extra
  continuation need real model calls. Until then F10 is fixed only as far as the scripted harness shows.
- No third-party extension is promoted; the allowlist is empty (D8). Codemode, tool search and MCP are Phase 8's.
- The dialog UI is type-checked; the browser tests were not extended for it.

## Part P — Who does what, enforced by the tools (22 October 2026; harness plan, Phase 5)

### What was wrong

The lead held all the pages' operations while its instructions told it to hand that work to the page agents, so the split
rested on the model reading the prose. And it had no `experiment_progress`: asked how the experiments were going, it was
told to ask the operator, so one read cost three model turns (the lead, the operator, the lead again) (F5).

### What changed

| Change | Where |
|---|---|
| The pages' operations (D1) leave the lead's `campaign_command` and `command_schema` enums: drafts, runs, continuations, extension requests, experiment rules, hiding runs, runtime profiles, fixed-design checks (the experiment operator's); implementations and evaluators (the implementation lead's) | `agents/tools.py` `LEAD_PAGE_WORK`, `schema` |
| A call that names one is refused with the agent to ask and how (`page_agent_message`), before validation and again at execution | `PiTools.page_work`, `_call`, `_execute` |
| The lead reads `experiment_progress`; its instructions say it reads status itself and asks the operator only for a decision about runs; extension requests are the operator's | `PiTools.names`, `INSTRUCTIONS` |
| `campaign_inspect.capabilities` tells the lead which agent does experiments, fixed-design checks and implementations | `PiTools.capabilities` |
| S11: "Run two short experiments" goes through the operator; S8's scripted lead reads progress itself | `evals/lead/scenarios/S11-experiments-through-the-operator.json`, `fakes.py` |

Kept by the lead, as the D1 table has it: `trial.control` (pause, stop, resume; never enlarge), `comparison.report`, the
proposals, findings, validations, studies, `journal.compaction_request`, `approval.request` and the workspace's operations
(`hypothesis.allocate`, `intervention.batch`, `research.generate`, ...), on which autopilot and generation depend; neither
`ROUND_PROMPT` nor the generation prompt asks for a moved operation. The lead also keeps its `implementation_workspace_*`
tools (the table left that open). `hypothesis.allocate` starts experiments in the service layer, not through the lead's enum.

### Checked

- `tests/test_page_agents.py`: the lead's enum holds none of the moved operations and the same set as `command_schema`; a
  direct call is refused naming the experiment operator or the implementation lead and `page_agent_message`; the lead has
  `experiment_progress`. `tests/test_experiment_rules.py`: the lead reads progress, and `config_suggest` stays the operator's.
- Tests that had the lead start runs now have the researcher or the operator start them; the extension-request test files
  the request as the operator and checks that the researcher's answer wakes the operator, and that the lead still cannot
  enlarge a run. Autopilot and evolution tests pass unchanged.
- The lead's instructions are 3,138 words, inside the ratchet.
- `--fake`: S8 (two lead turns, where the scripted operator path took three) and S11 pass.

### Not done

- Live S3, S8 and S11 against the baseline (fewer lead turns on S8 expected): real model calls needed.
- Whether the lead should keep `fixed_mask.run` for diagnostics, and its `implementation_workspace_*` tools, is still open
  (D1's notes); both follow the table's default for now (the first moved, the second kept).

## Part Q — Procedures read when needed, a short contract (22 October 2026; harness plan, Phase 6)

### What was wrong

The procedures of particular workflows (writing a report, cleaning journals, supervising a coding workspace, runtime
profiles and waivers, proposal fields, panels, writing the problem note) were in the system prompt of every turn of every
agent: the lead's instructions were 2,889 words at `a7e89b8`, a specialist's 1,993, most of it the lead's workflows (F6).

### What changed

| Change | Where |
|---|---|
| Eleven procedures in the Agent Skills format, from the instructions they replace, plus two domain procedures | `src/balsamic/procedures/*/SKILL.md` |
| A loader that gives each role its catalog in its static instructions; `procedure_read` (role-scoped, 24 kB, receipted); a hint in the result of a workflow-starting call without its procedure, once per run | `balsamic/procedures/__init__.py` (`workspace.procedures`, `workspace.procedure_hint`); `PiTools.manifest`, `_call` |
| The shared core rewritten: 349 words, with three short examples instead of rule lists (a question gets an answer; a notice with nothing new gets no message; the narrow reading in one line) | `agents/tools.py` `INSTRUCTIONS` |
| The lead's own contract (the page agents and delegation, 119 words) and a briefing cut to links, threads, the state block, the gate in two lines, proposals and names | `LEAD_CONTRACT`; `balsamic/lead/instructions.py` |
| An implementation grant's roles keep the instructions they had (§2.8) | `GRANT_INSTRUCTIONS` |
| The ratchet reset to the new sizes; limits of 900 words for the lead and 350 for the core | `tests/test_harness_contract.py` |

Sizes: the lead 886 words (−69% from `a7e89b8`), a specialist 389 (−80%).

The two domain procedures were drafted from the repository's documents only and are marked as drafts in their
frontmatter: `rcwa-convergence-check` from Part F and `docs/paper-mapping.md`, `meent-problem-setup` from
`docs/paper-mapping.md` and `docs/problem-setup.md`. **They need the researcher's review before they are relied on.**

### Checked

- `tests/test_procedures.py`: every procedure parses, names its folder, serves real roles, and every hint names one; the
  lead's manifest carries its catalog and none of the moved texts; a grant's instructions are byte-identical to the branch
  base (pinned by hash) and carry no catalog or `procedure_read`; a procedure is refused to a role it does not serve, an
  unknown file is refused, a long body is cut, a bundled file is read, the read is receipted with its run; a hint comes once
  per run, not after a failed call or after the procedure was read, and again in a new run.
- The catalog is the same for a role across campaigns (`tests/test_harness_contract.py`, which compares whole manifests).
- Tests that checked moved sentences check them in the procedure (`test_housekeeping.py`); the sentences other tests pin
  stayed in the core ("at the researcher's request", "start one only when a request covers it", `campaign_inspect.pages`,
  "link the page instead").

### Not done

- No live run: the plan judges this phase by the suite against the baseline (no regression, instruction tokens down by at
  least half, cost and turns per scenario). The word counts above are the only measurement so far.
- Option B of D3 (an extension-provided `read` so Pi lists the procedures as native skills) was not tried.
- The domain procedures await review; running a procedure's scripts is out of scope.

## Part R — Specialists with briefs, tools and output schemas (22 October 2026; harness plan, Phase 7)

### What was wrong

The discussion roles were names only: each got the lead's instructions, one `Role:` line, whatever objective the delegator
wrote, and the same tools. Only the proposal reviewer's `proposal_review` was structured; `submit_output` existed for
implementation grants alone, so no other role could be held to a result format (F4).

### What changed

| Change | Where |
|---|---|
| A brief (at most 200 words: purpose, a good result, what not to do), a tool list and a model tier hint for each of the seven roles, in Pi's agent-definition format; an output schema for each but the reviewer | `src/optimization_framework/agents/roles/*.md`, `*.schema.json`, `agents/roles.py` |
| `SPECIALIST_CONTRACT` (217 words) instead of the shared instructions: report to whoever asked, start nothing, cite ids, 40 tool calls, record the result, then complete | `agents/roles.py`; `PiTools.manifest` |
| A specialist's tools are its file's; `delegate` sets the role's schema; `submit_output` for any agent with a schema; `yield_work(complete)` refused before the result; the tool-call budget enforced | `PiTools.names`, `delegate`, `yield_work`, `over_budget` |
| The asking agent's notice points at the result (`/output`); the Review rounds view shows it | `controller._receive`; `agents/discussions.py`; `frontend/src/hypotheses/HypothesesPage.tsx` |
| S12: a flawed proposal sent to a review round | `evals/lead/scenarios/S12-flawed-proposal-review.json`, `seeds.py`, `fakes.py` |

D2 stays at its default: the roles are kept, with briefs and schemas; merging them into one analyst is for after the live evals.

### Checked

- `tests/test_roles.py`: every discussion role has a brief within its length and a valid schema (the reviewer its
  `proposal_review`); a specialist's manifest is the contract, its brief and its schema, not the shared instructions, and its
  tools are its file's (no literature search for the skeptical analyst, no `campaign_command`); `complete` before a result is
  refused, an invalid result is refused, a valid one is saved on the agent and the run; past its tool calls a specialist can
  only record and end; the result shows in the discussion view and the notice says where it is; a specialist saved before
  the schemas still loads and completes.
- `--fake`: S12 passes: the scripted analyst submits two high-severity failure modes, the reviewer rejects.
- A specialist's instructions are 405 words (1,993 at `a7e89b8`).

### Not done

- Live S12 and the share of valid structured outputs from real models: real calls needed.
- Optional independence (a reviewer not reading other reviewers' verdicts on the same revision before its own): not done; the
  hypothesis record carries the reviews, so it needs filtering there as well as in `evidence_read`.
- The moderator's synthesis of the results rests on its instructions and the notice; nothing checks it.

## Not planned

- Several parallel environments, Stable-Baselines3 PPO, and parity with MEENT 0.9.5 for the new
  campaign.
- An HTML report command of the Lead's own. Since Part H a report is written by the staged writer, which the Lead starts.
- Reviving the old campaign's Lead session.

## Autopilot: the exception to "acts on requests"

The lead acts on the researcher's requests and starts nothing by itself. Autopilot is the one explicit exception, and
only the researcher turns it on (`autopilot.set`, with a compute cap and an optional report date). While on, the
workspace gives the lead rounds in a system thread: review the frontier, stop, promote, allocate and generate within the
cap, a rationale on every command, `yield_work(complete)` at the end. Researcher messages still come first (no round
starts while a request is open), limits stay the researcher's (the cap guard refuses what would exceed it; raising
limits still goes through approval), and every record the lead touches under autopilot says so (actor `autopilot`, the
badge on the pages, the away digest). See [ui-workspace.md](ui-workspace.md#m3-merge-monitor-autopilot).
