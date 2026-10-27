# Phase 7 — Fewer standing agents, claims that resolve

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §08 D ("fewer standing agents, more structured calls") and §08 E ("claims resolve to receipts"); §05 (independent reviews, the moderator's synthesis, the model never does arithmetic); §02 (tool-less structured calls, three separate statements, a knowledge library with typed links); §04 (knowledge narrowed to a library of winners); §06 (more agents, more prose boundaries) |
| Decisions it needs | 19 (T1, T3); 13 and 14 through V1 and V2 (K4) |
| Start after | The Phase 2 baseline (J1–J3): each part is kept or reverted by its effect on it. T1 after V4. K1, K2 and K3 can start at any time |
| Status | Not started |

## Why

**Model calls.** The first plan made every reasoning role a tool-less, bounded, structured call whose context the backend
assembled, so each call recorded exactly what it saw and reviewers were independent by construction. Today every role is a
persistent Pi session with tools: 15 roles in `ROLES` (`agents/models.py` L18–20), four of them standing page agents (L12).
Part R's "Not done" (`docs/lead-agent-readiness.md` L1003–1008) names the cost: a reviewer can read the other verdicts on the
same revision before its own, and "the moderator's synthesis of the results rests on its instructions and the notice;
nothing checks it". The report writer already works the first plan's way: `reports/pipeline.py` makes staged, tool-less
calls through the Pi harness's client with a spend guard, and stores each stage's instructions and input.

**Hand-offs.** Routing is in code since the harness plan's Phase 5: the lead cannot run a page's operations and asks its page
agent instead. Each hop is another turn and another set of prose boundaries. In the session behind `docs/suggestions.md` R2,
the lead made 81 `page_agent_message` calls, and 27 of its turns were exactly inspect, `page_agent_message`, `yield_work`.

**Numbers.** The charter is the repository's best guardrail-with-flexibility idea: the formulator decides relations and code
computes every number (`problem_charter/expressions.py`). Agents' claims get no such treatment. In readiness Part J the
operator called a mutation rate of 0.005 "about 1/n" for 32,768 cells, where 1/n is 0.00003. The harness plan's Phase 9
(numeric claim checks, `docs/harness-update-plan.md` L718–725) was never started, and the report writer's rule that
"numbers ... must be traceable to supplied read receipts" (`reports/editorial.py` L133) is prose.

**Knowledge.** A finding carries its sources, scope, limitations and one kind of link (`counterevidence_for`,
`contracts/commands.py` L341–357), but not whether it states a promise, a measurement or a decision, and agreement is counted
by findings, not by evidence. The library holds only winners (`src/balsamic/library/service.py` L56), so a method that was
assessed fairly and lost teaches the next campaign nothing.

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| T1 | Reviews as one-shot calls with assembled context | A reviewer can read the other verdicts on the revision it reviews; what a review saw is spread over a session | V4, decision 19 | M | 2 |
| T2 | The moderator's synthesis is checked | The moderator's report of a round is not compared with the verdicts it reports | — | S–M | 1 |
| T3 | Review specialists as one-shot calls; decide the harness plan's D2 | Read-only specialists keep whole sessions; D2 is open | T1, decision 19 | M | 3 |
| T4 | Do the operator and the moderator still need their own sessions? | Every page request is a hand-off whose cost is not measured | the J1–J3 baseline | M | 4 |
| K1 | A `compute` tool on the charter's expression evaluator | Agents do arithmetic in their heads | — | S–M | 1 |
| K2 | Numeric claim checks | A number in a finding, a reply or a report claim may appear in none of its evidence | K1 (for its receipts) | M | 2 |
| K3 | Findings that say what they state, with typed links | A performance claim can rest on a rationale; three agents restating one trial look like three supports | — | M | 1 |
| K4 | Negative results in the library | A method stopped after a fair assessment leaves no trace another campaign can find | V1, V2 | M | 3 |

---

## Parts

### T1 — Reviews as one-shot calls with assembled context

**Depends on:** V4, decision 19. **Size:** M.

**Read first:** `reports/pipeline.py` (`Pipeline` L53–61: an `LLMAdapter` on `workspace.pi.client` with `spend_guard`;
`afford()` L63; `stage()` L87, which stores each call's instructions and input), `reports/writer.py` L217 (a job in its own
thread), `llm/adapter.py` `call_with_prompt()` L287, `agents/tools.py` (`proposal_review` L1012–1025, `delegate` L1038, the
reviewer's tools L466–467), `campaigns/proposals.py` (`hypothesis_revision()` L14, the unused `ProposalReview` contract L18,
`readiness()` L31), `agents/roles/proposal_reviewer.md`, `agents/controller.py` (`create_agent()` L191, `enqueue()` L405,
`_sync()` L667, `_receive()` L779), `agents/discussions.py` `view()`, `evals/lead/fakes.py` `review_round()`.

**Today**
- A review is a Pi session of role `proposal_reviewer`, created by `delegate`, with `campaign_inspect`, `evidence_search`,
  `evidence_read`, `source_read`, `proposal_review` and `artifact_save`. `proposal_review` pins the exact revision, saves an
  `agent_artifact` of kind `proposal_review`, and appends the verdict to the hypothesis's `reviews`.
- Nothing keeps the reviewer from the other verdicts: the hypothesis it reads carries `reviews`; `campaign_inspect` shows each
  proposal's `concept_review` state ("An independent reviewer requested changes or rejected this revision"); and
  `evidence_search` lists the other reviews' artifacts.
- What a review saw is its session's tool receipts, spread over its turns.

**Change**
1. `agents/calls.py` (new), a one-shot role call:
   - `assemble(workspace, campaign_id, role, objective, evidence_ids, hypothesis_id)` builds the call's input.
   - `run(...)` makes one `LLMAdapter.call_with_prompt` call through `workspace.pi.client`, with the campaign's spend guard
     (as `Pipeline.afford()`), a bound on the prompt's bytes and the role's tier model (`agents/tiers.py`).
   - It saves an `agent_call` record (role, model, instructions, input, output, usage) before acting on the output. A failed
     or refused call is not repeated, as in the report pipeline.
2. For `proposal_reviewer`, the input is:
   - the exact revision (the fields `hypothesis_revision()` hashes, its algorithm and its hash);
   - for a revision, its parents' titles and mechanisms and the changes their reviews asked for (`required_changes` only);
   - the campaign's tasks (objective, representation, constraints, fidelities), the installed methods that run on them
     (`PiTools.methods()`), and the charter's summary;
   - the asker's objective and the records it cited, each read with V4's rule and cut to a bound;
   - never another review of this revision, nor another agent's notes on it.

   The result type is `ProposalReview` without `candidate_id`; the backend adds the hypothesis id and the hash. The
   instructions are the role's brief, without its tool lines.
3. `ONE_SHOT_ROLES` in `agents/calls.py` (the reviewer only, in this part). `delegate` with such a role still creates the
   agent session, so the Review rounds view, usage and costs are unchanged. The controller runs its run in a thread with
   `calls.run` instead of submitting it to Pi, records the verdict exactly as `proposal_review` does, and ends the run the way
   `_receive` does, so the asker's notice is the same. `agent_message` to such an assistant is refused with "it answers once;
   delegate again".
4. The reviewer's brief loses "pinning the hypothesis_hash from campaign_inspect".
5. The fake harness answers one-shot calls with a scripted output (`evals/lead/fakes.py`, the reviewer's branch of
   `review_round()`).

**Tests**
- The input of a third review of a revision holds neither of the first two verdicts nor their artifacts. For a revision, the
  parent's required changes are there.
- A protected trial the asker cites is withheld from the input (V4's rule).
- The verdict is recorded as before: the artifact pins the hash, `readiness()` gives the same state, and the Review rounds
  view lists the reviewer with its verdict.
- The asker gets its notice. A message to the reviewer is refused.
- A call the model budget cannot cover is refused before it is made, and no verdict is recorded.
- The `agent_call` record holds the exact input.
- `--fake`: S12 passes.

**Done when** the tests pass, live S12 passes as at the baseline or better, and the readiness Part gives the cost, the
latency and the share of valid outputs of a review before and after. It closes Part R's "Optional independence".

### T2 — The moderator's synthesis is checked

**Depends on:** nothing (V1 makes the `rejected` check stronger). **Size:** S–M.

**Read first:** `agents/models.py` `PAGE_OBJECTIVES["discussion_moderator"]` L23–25 ("report a short synthesis: which
proposals stand, which were revised or rejected, and why"), `agents/tools.py` (`ROLE_OPERATIONS` L34, the moderator's line
in `manifest()` L523–525, `yield_work` and its refusal of a specialist's `complete` before its result, L1137),
`campaigns/proposals.py` `readiness()` (the latest verdict per reviewer, L41), `agents/discussions.py` `view()` (the
verdicts per revision, L120–141), `execution/service.py` L570 (the concept-review gate on runs),
`frontend/src/hypotheses/HypothesesPage.tsx`.

**Today** the moderator delegates reviewers and specialists, sets statuses with `hypothesis.status`, and ends with a reply in
prose. The verdicts are records. The synthesis is not compared with them, and a status that goes against them is not flagged.
The concept-review gate still keeps a proposal with an objection from running.

**Change**
1. `campaigns/proposals.py` `tally(store, hypothesis)`: for the exact current revision, the latest verdict of each reviewer
   (the rule `readiness()` uses), the counts of test, revise and reject, and the review ids.
2. A `review_synthesis` tool for the moderator. For each proposal of the round it takes
   `{hypothesis_id, standing: stands | revise | rejected | undecided, review_ids, reason}`, plus a summary, and records them
   as an `agent_artifact` of kind `review_synthesis`. The backend compares each standing with the tally:
   - `stands` needs no objection on the current revision;
   - `rejected` needs a reject verdict, or a stop (with its V1 outcome once V1 has landed);
   - `revise` needs a revise or reject verdict, or a linked revision created in the round;
   - `undecided` always holds.

   A standing that goes against the tally is saved with `against_tally` and the reviews it overrides.
3. After a round in which the moderator delegated reviews, its `yield_work(complete)` is refused until the synthesis is
   recorded, as a specialist's is refused before its result (Part R). Its closing reply links the synthesis.
4. The moderator's `hypothesis.status` on a proposal of the round that goes against its tally (`investigating` with an
   objection, `archived` with only test verdicts) is recorded with `against_tally` too.
5. The Review rounds view shows the tally beside the moderator's words, with a badge on each standing against it. The
   lead's notice of the round carries the synthesis's id and its badges.
6. A badge, not a refusal: refusing is for later, once the evals show how often it happens and why. The I1 row is `prompt`,
   with the eval that measures it.
7. The objective's "report a short synthesis" names the tool.

**Tests**
- A synthesis saying a proposal stands while a reviewer rejected it is saved with `against_tally` and that review's id; one
  that matches is saved without it.
- After a round, `yield_work(complete)` without a synthesis is refused, and accepted with one.
- `archived` on a proposal with only test verdicts is flagged.
- `--fake` S12: the moderator records a synthesis matching the reject verdict. A new check, `synthesis_matches_tally`,
  passes.

**Done when** the tests pass, and live S12 records a synthesis with no standing against the tally (or the readiness Part
says why). It closes Part R's last "Not done" item.

### T3 — Review specialists as one-shot calls; decide the harness plan's D2

**Depends on:** T1, decision 19, the J1 baseline. **Size:** M.

**Read first:** `agents/roles.py` (`SPECIALIST_CONTRACT`, `ROLE_BRIEFS` and `ROLE_OUTPUT_SCHEMAS` L60), `agents/roles/*.md`
and `*.schema.json`, `agents/calls.py` (T1), `docs/harness-update-plan.md` (D2 L119; Phase 7's "Compatibility" L678),
`evals/lead/scenarios/S12-flawed-proposal-review.json`, `tests/test_roles.py`.

**Today**
- The seven specialists are Pi sessions with briefs, tool lists and schemas (Part R).
- Two of them only read: `methodology_specialist` and `skeptical_domain_analyst` (the campaign, evidence and run files).
  `literature_specialist` and `cross_domain_explorer` search sources; `empirical_assessor` and `results_analyst` run
  analyses.
- D2 (merge the specialists into one analyst) is open: "revisit merging after evals".

**Change**
1. `methodology_specialist` and `skeptical_domain_analyst` join `ONE_SHOT_ROLES`. Their input is T1's, plus the resource
   summary (`resource_inspect`'s) and, for each cited trial, its status, result and metrics (V4's rule). Their result types
   are their schemas, unchanged.
2. A switch, `GRATING_ONE_SHOT_ROLES` (default: the roles that passed the comparison below), returns a role to a session
   without a code change.
3. A comparison on Centinels, on S12, S14 and the scenarios that delegate these roles, in three arms:
   - (a) sessions, the Phase 2 baseline;
   - (b) one-shot calls;
   - (c) for D2, one one-shot `analyst` whose brief and schema merge the two roles', with the old names loading as aliases
     (harness plan L678).

   It measures scenario passes, the share of valid outputs, cost, latency and the size of each call's input.
4. The result decides one-shot or session per role, and D2. Record it as an ADR in `docs/adr/` (I3) and mark D2 decided in
   the harness plan.
5. Roles that search or run analyses keep their sessions (decision 19).

**Tests**
- Each one-shot role's input holds what its brief needs (the methods, the representation, the cited evidence) and no
  review. Its output is validated against its schema.
- The switch returns a role to a session.
- `tests/test_roles.py` still passes for the session roles.

**Done when** the tests pass, the comparison is in the readiness Part, and the ADR records the choice.

### T4 — Do the operator and the moderator still need their own sessions?

**Depends on:** the J1–J3 baseline; better after T1–T3. **Size:** M. An experiment and an ADR; the change it decides is a
later part.

**Read first:** `agents/models.py` (`PAGE_AGENTS` L12, `PAGE_OBJECTIVES`), `agents/tools.py` (`ROLE_OPERATIONS` L33–40,
`LEAD_EXCLUDED_OPERATIONS` L47, `LEAD_CONTRACT` L79, `page_agent_message`), `agents/controller.py` (`page_agent()` L224,
`ask_page_agent()` L235), `docs/harness-update-plan.md` Phase 5, `docs/suggestions.md` R2 and R3, readiness Part S.

**Today**
- Four standing page agents keep Pi sessions. The lead cannot run their operations (`LEAD_EXCLUDED_OPERATIONS`). It asks with
  `page_agent_message`, and the reply comes back as a notice.
- The hand-offs are frequent and heavy. In the 2D session that `docs/suggestions.md` R2 and R3 measured, the lead made 81
  `page_agent_message` calls, and the operator's median request was 404k tokens.
- S11 (experiments go through the operator) passed at the baseline too (Part S). The routing works; whether each hop is
  worth its cost is not measured.

**Change** (no default changes in this part)
1. A per-campaign switch in the dev profile, `page_agents: standing | lead`, for the moderator and the operator. Under
   `lead`:
   - the lead gets their operations and tools (`ROLE_OPERATIONS`, `experiment_progress`, `config_suggest`, `delegate` to
     the discussion roles);
   - their page instructions become a procedure the lead reads when needed;
   - the researcher's messages on those pages go to the lead, and the page says the lead answers.
2. A comparison on Centinels between the two settings, on the whole suite and the J2 presets. It measures passes, cost,
   turns and latency per request, the lead's context size, and J3's partnership metrics.
3. An ADR in `docs/adr/` records the result per page agent: keep its session, or fold it into the lead. A fold (removing
   the session, the page's routing, open requests) is a new part, added to this file when Hoseung accepts the ADR.
4. Out of scope: the implementation lead (its work changes with Phase 4, reviewing tickets and diffs) and the resource
   planner (it starts nothing).

**Tests**
- Under `lead`, the lead's operations include the folded ones, and a researcher's message on Experiments reaches the lead.
  Under `standing`, the routing tests pass unchanged.
- `--fake` S8 and S11 pass under both settings. S11's check gets an `any_of` naming the lead under `lead`.

**Done when** the tests pass and the comparison and the ADR are written for Hoseung.

### K1 — A `compute` tool on the charter's expression evaluator

**Depends on:** nothing (V4 for reads of protected records; until then the reads go through today's `record()`).
**Size:** S–M.

**Read first:** `problem_charter/expressions.py` (`MAX_LENGTH` and `MAX_NODES` L14–15, `FUNCTIONS` L28, `parse()` L45,
`evaluate()` L111), `agents/tools.py` (`INSTRUCTIONS` L56, `TOOLS` L341, `PiTools.names()` L446, `record()` L821, the
receipt L699–702), `agents/roles.py` `SPECIALIST_CONTRACT`, `agents/roles/*.md` (their tool lists), `docs/suggestions.md`
R6 and S6.

**Today** an agent computes in its head, or writes and runs a script (`analysis_run`: two steps, described only in the
`analysis-scripts` procedure; suggestions R6). The charter's whitelisted evaluator computes the charter's numbers and
nothing else.

**Change**
1. A `compute` tool taking `{expression, values: {name: number | {record_id, pointer}}}`, with at most 50 values. A value is
   a literal or a number read from a visible record at a JSON pointer, through `record()`. The backend evaluates with
   `expressions.evaluate()` and returns `{value, inputs: [{name, value, record_id, pointer}]}`. Errors are the evaluator's.
2. The call's receipt is the computation: the expression, each input with its source, and the value. K2 reads it.
3. Agents that get it: the lead, the page agents, and the specialists whose role files list it (`results_analyst`,
   `empirical_assessor`, `methodology_specialist`, `skeptical_domain_analyst`). Not the grant roles. The one-shot roles
   (T1, T3) have no tools.
4. Instructions: one sentence in `INSTRUCTIONS`, "A number you derive comes from compute or a script, never from mental
   arithmetic", and the same in `SPECIALIST_CONTRACT` in place of its sentence on numbers, under the size ratchet.
5. A label for the chat ("Computing a number").

K1 is arithmetic over recorded values. Suggestion S6 (one-step Python) stays for analyses that need code.

**Tests**
- `compute` with literals, with a pointer into a trial's result, and with both; the receipt names each source.
- A pointer into a record outside the campaign is refused; after V4, a protected one is.
- An expression over the evaluator's bounds is refused with its text, and nothing is passed to `eval`.
- Part J's case: `0.005 / (1 / 32768)` gives 163.84.

**Done when** the tests pass, and the prompt-size ratchet holds.

### K2 — Numeric claim checks

**Depends on:** K1 for its receipts (K2 can land first, recognizing records and receipts only). **Size:** M.

**Read first:** `docs/harness-update-plan.md` Phase 9 (L718–725), `campaigns/findings.py` `record()`, `agents/tools.py`
(`yield_work`, the receipt L699–702), `reports/editorial.py` (`Claim` L63–72: `statement`, `support`), `reports/pipeline.py`,
`frontend/src/files/FilesPage.tsx`, `frontend/src/chat/Turn.tsx`, `scripts/run_lead_evals.py` (the summary).

**Today** nothing compares the numbers an agent writes with the numbers in its evidence.

**Change**
1. `analysis/claims.py` (new):
   - `numbers(text)` extracts decimals, numbers with thousands separators, percentages, scientific notation and signs. It
     skips numbers in record ids, dates, times, versions, links and code spans, and integers below 10 (counts), at first.
   - `unverified(text, evidence)` returns the numbers no evidence matches. A number matches when an evidence number rounds
     to it at the precision written, directly or as a percentage (93.75% matches 0.9375).
2. Checked, with their evidence:
   - `finding.record`'s content: its sources and the recording run's receipts;
   - `yield_work(complete)`'s report: the run's receipts, the records they returned, the records it cites, and the results
     its assistants delivered in the run;
   - each report `Claim.statement`: the receipts in its `support`;
   - T2's synthesis reasons.

   Numbers from K1's receipts count as evidence.
3. The result is `unverified_numbers`, saved on the finding, on the run's receipt, or on the report stage. A badge shows
   them: on the finding (Files), on the reply (chat), on the claim in the report's side panel. No refusal, as Phase 9 and
   the design review ask.
4. Evals:
   - the summary gains `unverified_numbers` per scenario and per suite;
   - **S16 a derived number** (seed: a run with mutation rate 0.005 on a 32,768-cell design): "Is the run's mutation rate
     about 1/n?" It passes when the reply says no and its numbers have no badge.
5. The I1 row ("a number in a claim points at its record or receipt") is `prompt`, measured by the metric. It becomes `code`
   only if a later part refuses.

**Tests**
- Extraction: percentages, separators, scientific notation, signs; ids, dates, versions and code are skipped.
- Matching at the precision written: 93.75% and 0.94 match 0.9375; 0.95 does not; a value from a compute receipt
  matches.
- A finding with a number in none of its sources is saved with `unverified_numbers`; one with all its numbers sourced is
  saved without it.
- A report claim whose number is in no supporting receipt is listed on its stage.
- `--fake` S16 runs.

**Done when** the tests pass, and the live suite reports the metric against the baseline.

### K3 — Findings that say what they state, with typed links

**Depends on:** nothing (V1 for decisions that cite stops). **Size:** M.

**Read first:** `contracts/commands.py` `FindingInput` L341–357, `campaigns/findings.py` `record()` (`MEASUREMENT_KINDS`
L6), the claim levels in the code (`campaigns/hypotheses.py` L23 `rationale_only`, `analysis/general.py` L212 `descriptive`,
`evaluation/confirmation.py` L314, `analysis/finalists.py` L99 `manual_shortlist`), `reports/evidence.py`,
`frontend/src/files/FilesPage.tsx`, `docs/agentic-algorithm-discovery-plan.md` L433 (the first plan's typed links).

**Today**
- A finding has an `interpretation` (observation, interpretation, researcher_endorsed, counterevidence), its sources, scope
  and limitations, and one link: `counterevidence_for`, naming an earlier finding.
- Whether a finding states a promise (why something may work), evidence (what was measured) or a decision (what was chosen,
  and why) is not recorded. A finding can claim a performance difference citing only a rationale or a review.
- Three agents restating one trial look like three supports.

**Change**
1. `FindingInput` gains `statement: promise | evidence | decision`. Agents must give it; the researcher's findings without
   one read as `unspecified`.
   - `evidence` needs at least one measurement among its sources: a trial, a comparison, a confirmation, a validation
     result, or a kind in `MEASUREMENT_KINDS`.
   - `decision` cites the decision record: a stop (V1), a finalist selection, an approval or, after Phase 3, a mandate.
   - `promise` may cite sources, reviews and proposals, and is shown as "not measured".
2. `links: [{id, relation: supports | contradicts | supersedes | qualifies}]`, to earlier findings of the campaign (the
   existing visibility rule). `counterevidence_for` stays as input and is stored as `contradicts` links; `interpretation:
   counterevidence` stays for old records. A superseded finding leaves the default view and stays readable by id.
3. Support is counted by distinct evidence. Files shows, for each finding, the distinct measurements behind it and behind
   its `supports` links (two levels deep), and marks a supporting finding that adds no source as "restates".
4. The report writer's evidence (`reports/evidence.py`) carries `statement` and the links, so a report keeps a promise
   apart from a result.

**Tests**
- An agent's `evidence` finding citing only a proposal and a review is refused with the text; with a trial, accepted.
- A `decision` finding needs a decision record; a `promise` finding is accepted with sources only.
- `counterevidence_for` is stored as `contradicts`, and old findings load.
- A superseded finding leaves the default view and is still readable by id.
- Three findings citing the same trial count as one distinct measurement.

**Done when** the tests pass.

### K4 — Negative results in the library

**Depends on:** V1, V2 (decisions 13 and 14). **Size:** M.

**Read first:** `src/balsamic/library/service.py` (the module docstring; `publish()` L44–76, the researcher only L46, a
finalist or a promising confirmation L56; `search()`; `apply()`), `src/balsamic/library/signature.py`,
`frontend/src/library/LibraryPage.tsx`, `frontend/tests/library.spec.ts`, `src/balsamic/evolution/ledger.py` `rows()`, and
V1's stop record and V2's `adequacy()`.

**Today** the library is "immutable records of a strategy that won". `publish` takes a finalist, or a strategy whose
confirmation was promising. A strategy stopped after a fair assessment leaves nothing another campaign can find.

**Change**
1. `PublishInput` gains `kind: positive | negative`. The default, `positive`, keeps today's rule.
2. A negative entry needs a stopped strategy whose V1 outcome is a judgement of the method:
   - `configuration_unpromising` or `adequately_assessed_deprioritized`, with V2's `adequate` or the researcher's tuning
     waiver (the entry records which);
   - or `implementation_invalid` or `assumptions_incompatible`, with their evidence.

   `under_evaluated`, `unaffordable_within_allocation`, `unspecified` and a stop without an outcome are refused with the
   reason: they say nothing about the method.
3. The entry records the outcome, its evidence ids, the assessment (configurations and seeds), the best score as measured,
   and the problem signature that says where it applies.
4. `search()` returns negative entries labelled "assessed and stopped", with their outcome. `apply()` of one is allowed, and
   the new proposal's rationale says why the method was stopped and where.
5. Publishing stays the researcher's. The Library page shows the two kinds apart.

**Tests**
- A stop with `configuration_unpromising` after an adequate assessment publishes as negative; `under_evaluated` is refused
  with the reason.
- Search returns a negative entry, with its label, for a matching signature.
- Applying a negative entry writes its outcome into the new proposal's rationale.
- Old entries read as positive.
- Playwright `library.spec.ts`: the two kinds show apart.

**Done when** the tests pass.

---

## Order and shared files

```
Wave 1  T2 · K1 · K3
Wave 2  T1 (V4) · K2 (K1)
Wave 3  T3 (T1) · K4 (V1, V2)
Wave 4  T4 (the baseline, after T1–T3)
```

| File | Parts |
|---|---|
| `agents/tools.py` | T1, T2, T4, K1, K2 (and V4, R2, R6, B6, B7) |
| `agents/calls.py` (new) | T1, T3 |
| `agents/roles/*.md` | T1, T3, K1 |
| `campaigns/proposals.py` | T1, T2 |
| `contracts/commands.py`, `campaigns/findings.py` | K2, K3 (and V1) |
| `src/balsamic/library/service.py` | K4 (and V3) |
| `frontend/src/files/FilesPage.tsx` | K2, K3 |
| `evals/lead/fakes.py`, `scripts/run_lead_evals.py` | T1, T2, K2 (and J1) |

## Risks

- **Less context for a one-shot role:** a reviewer can no longer read on demand. The assembled input must hold what its brief
  needs, T3's comparison measures it, and the switch returns a role to its session.
- **Independence versus revision:** a revision's reviewer sees the changes asked of its parent, not the verdicts on its own
  revision. That is the line between checking a revision and copying a verdict.
- **False badges** (K2): rounding, units and counts will produce some. Badges come first, the metric shows the rate, and a
  refusal comes only after the evals.
- **Folding page agents** (T4) moves context into the lead, whose context is already the heaviest (suggestions R3). The
  comparison measures it before anything changes.
- **Negative entries read as verdicts on a method everywhere:** each one carries its signature, and the search says where it
  was assessed.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, `scripts/run_lead_evals.py --fake`, Playwright for K3 and K4.
- Live (Centinels): S12, S14 and S16 for T1–T3 and K2, against the Phase 2 baseline; the whole suite and the J2 presets for
  T4. The comparisons go in the phase's readiness Parts, and T3's and T4's results in ADRs.
