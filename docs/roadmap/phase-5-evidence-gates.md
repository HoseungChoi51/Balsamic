# Phase 5 — Evidence gates: a conclusion needs its evidence

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §08 B ("evidence-gated strategy transitions: restores the deleted layer"), §05 (adequate assessment, fidelity before trust, protected confirmation evidence), §01 finding 2 |
| Decisions it needs | 13, 14, 15, 16 |
| Start after | The Phase 2 baseline (J1's traps measure this phase). Start with V3, since readiness Part F already showed its value |
| Status | Not started |

## Why

The deleted `research/discovery/assessment.py` (removed with the rebuild, `52cbda4`) had an `AssessmentPlan` (minimum
configurations, seeds per configuration, an informative horizon, a tuning waiver required for a one-configuration test)
and an `AssessmentDecision` whose outcome told an under-tuned method from a bad mechanism. Nothing replaced it:
`hypothesis.status` archived takes any `stop_reason` of up to 2,000 characters (`contracts/commands.py` L171), and the
autopilot prompt asks the lead to "stop strategies that are dominated" (`src/balsamic/autopilot/rounds.py` L10–11).

Readiness Part F is the project's most important scientific finding: a design scored 93.75% at RCWA orders (10, 5) and
67.56% at (26, 22). The response was a draft procedure. The mechanism to bind a check to a decision exists (validation
requirements, recipes, results and waivers in `evaluation/policy.py`), but nothing binds it to promotion:
`library.publish` takes any finalist with its best score (`src/balsamic/library/service.py` L56).

And the rule that development reasoning excludes locked test results until release exists in code
(`campaigns/guidance.py` `MemoryService._records()`, and `llm/adapter.py` `_safe_context()` for the report writer), but the
Pi agents' read tools never call it.

The ledger already has stages (proposed, reviewed, screening, extended, finalist, confirmed, stopped; `ledger.py`
`stage_of()` L40–53). This phase attaches typed requirements to the transitions. Agents stay free to propose anything;
they cannot record a conclusion the evidence does not support.

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| V1 | Typed stop outcomes | A stop is free text: an under-tuned method and a bad mechanism look the same | decision 13 | M | 2 |
| V2 | Adequate assessment before a performance stop | A method can be stopped "for performance" after one default configuration | V1, decisions 14, 16 | M | 3 |
| V3 | A fidelity check before finalist and library | A score that collapses at higher fidelity can become a finalist or a library entry | decisions 15, 16 | M | 1 |
| V4 | Locked results stay unreadable to agents until release | The agent read tools return locked confirmation trials, their files and their analyses | — | M | 1 |
| V5 | The gates on the pages; waivers in one click | Nothing shows why a transition is refused or what would unlock it | V1, V2, V3, decision 16 | S–M | 4 |

---

## Parts

### V1 — Typed stop outcomes

**Depends on:** decision 13. **Size:** M.

**Read first:** `contracts/commands.py` `HypothesisStatusInput` L164–171, `campaigns/hypotheses.py` `set_status()` L44–56,
`campaigns/commands.py` L355–366 (the status branch and `_hold_race_configurations`), `src/balsamic/autopilot/rounds.py`
`ROUND_PROMPT` L10, the readers of `stop_reason` (`src/balsamic/evolution/ledger.py` L128, `src/balsamic/evolution/lineage.py`
L55, `src/balsamic/monitor/digest.py` L44 and L51, `frontend/src/evolution/LineageTree.tsx`,
`frontend/src/hypotheses/HypothesisCard.tsx`), and the deleted `research/discovery/assessment.py` (`git show 52cbda4^:src/optimization_framework/research/discovery/assessment.py`).

**Today** `set_status(..., "archived")` stores `stop_reason or "stopped without a stated reason"`.

**Change**
1. `HypothesisStatusInput` gains `outcome` (the six stop outcomes of decision 13) and `evidence_ids` (records the stop rests
   on: trials, comparisons, validation results, reviews). `stop_reason` stays as the free-text explanation.
2. For actors `manager` and `autopilot`, a stop needs an outcome and at least one evidence id, each a visible record of the
   campaign (the same visibility rule as findings, `campaigns/findings.py` L15). The researcher may stop without one; the
   record says `researcher_decision`.
3. The hypothesis record stores `stop: {outcome, evidence_ids, reason, by, at}`; records stopped before this part read as
   outcome `unspecified`.
4. The ledger row, the lineage graph, the digest and the hypothesis card show the outcome in words ("stopped: under-
   evaluated", "stopped: implementation invalid").
5. `ROUND_PROMPT` asks for "a stop outcome and its evidence" instead of "dominated".

**Tests**
- An agent's stop without an outcome, or citing an invisible record, is refused with the text.
- The researcher's stop without one records `researcher_decision`.
- An old stopped record reads as `unspecified`; the race configuration is still held on a stop.

**Done when** the tests pass, and the J1 scenario S14 is re-run.

### V2 — Adequate assessment before a performance stop

**Depends on:** V1, decisions 14 and 16. **Size:** M.

**Read first:** `campaigns/experiment_rules.py` (`ExperimentRulesInput` L56, `current()` L121, `run_kind()` L186,
`classify()` L194), `contracts/requests.py` `TrialInput` (`algorithm_config`, `seed`, `hypothesis_id`),
`src/balsamic/evolution/ledger.py` `rows()`, `evaluation/policy.py` (`ValidationService.require()`, `waive()`),
`contracts/commands.py` `ApprovalRequestInput` (kind `waiver`).

**Today** nothing counts how a proposal was tried before it is stopped as inferior.

**Change**
1. The experiment rules gain `assessment`, per decision 14: `min_configurations` (3), `min_seeds` (2), and the informative
   horizon `min_evaluations` (the deleted plan's `minimum_informative_evaluations`; unset by default). The researcher
   changes them with `experiments.rules`.
2. `campaigns/assessment.py` `adequacy(store, hypothesis)`: from the proposal's trials, the distinct configurations (the
   canonical hash of `algorithm_config`), their seeds, and which runs reached the horizon: completed with
   `scientific_complete`, or ran at least the campaign's `short_run_seconds`, and reached `min_evaluations` when it is set
   (the deleted code's rule, L193 of the file above). It returns `{adequate, configurations, seeds_per_configuration,
   missing}`.
3. A stop with outcome `configuration_unpromising` or `adequately_assessed_deprioritized` by an agent needs `adequate`, or
   a researcher's waiver of a `tuning` requirement on that proposal (a `validation_requirement` the gate creates, waived
   with the existing records; an agent asks with `approval.request` kind `waiver`, decision 16). Otherwise the refusal
   says what is missing and names the honest outcome: `under_evaluated`, or `unaffordable_within_allocation` when the
   budget cannot cover the missing runs.
4. The ledger row carries `assessment` ("2 of 3 configurations, 2 seeds each").

**Tests**
- One default configuration that lost: `configuration_unpromising` is refused with "1 of 3 configurations"; `under_evaluated` is accepted.
- Three configurations × two seeds past the horizon: accepted.
- A researcher's tuning waiver lets the stop through; a waiver by an agent is refused.

**Done when** the tests pass, and S14 passes live (it may still fail on wording; the gate itself must hold).

### V3 — A fidelity check before finalist and library

**Depends on:** decisions 15 and 16. **Size:** M.

**Read first:** `contracts/problems.py` `ProblemDefinition` L85–97 (`validation_recipes`), `evaluation/registered_recipes.py`
(`FidelityComparison`, `fidelity_comparison:v1`), `evaluation/recipes.py`, `evaluation/policy.py` (`DEFAULT_WAIVABLE` L6
includes `solution_fidelity`), `campaigns/hypotheses.py` (`nominate()` L36, `set_status()`), `campaigns/commands.py`
(`finalist.set` L643), `analysis/finalists.py`, `src/balsamic/library/service.py` `publish()` L44–76,
`src/dqn_meent/problem_2d.py` (`ORDER_CONVERGENCE_RECIPE` L18, `validation_recipes` L241),
`src/balsamic/procedures/rcwa-convergence-check/SKILL.md`, readiness Part F.

**Today** a strategy becomes a finalist after an implementation-readiness check only (`nominate()`), and `library.publish`
requires a finalist or a promising confirmation, with its best score as measured.

**Change**
1. `ProblemDefinition` gains `promotion_validation`: the recipes (with parameters) a score must pass before it counts for
   promotion. `Meent2DProblem` declares its order-convergence recipe with the tolerance the procedure states (half a
   point at the two highest orders); a problem without fidelity declares none, and its gate is open.
2. `campaigns/promotion.py` `fidelity_state(workspace, hypothesis)`: for the proposal's best trial (by the objective's
   direction, A2) and each declared recipe, `passed` (a `validation_result` with verdict passed for a requirement on that
   trial), `waived` (a waiver in force), `failed`, `not_checked` or `not_required`.
3. The transitions of decision 15 (`hypothesis.nominate`, `hypothesis.status` finalist, `finalist.set`, `library.publish`)
   require `passed`, `waived` or `not_required`. An agent's refusal names the recipe and how to run it (`validation.run`),
   or how to ask for a waiver (decision 16). The researcher's own choice of a finalist passes with a recorded warning.
   `library.publish` is the researcher's alone (L46) and is what other campaigns reuse: it needs `passed` or
   `not_required`, or a waiver the researcher gives with the publish (V5).
4. The library entry records the fidelity state and the validation result id, and shows it.
5. `rcwa-convergence-check` stays the procedure for how to read the check; its status stays draft until Hoseung reviews it
   (N3 moves it into the MEENT pack).

**Tests**
- A 2D finalist whose score fails the order recipe cannot be nominated by an agent, nor published without the
  researcher's waiver; one that passes can.
- A waiver by the researcher lets it through; an agent's waiver is refused.
- A `bounded_continuous` strategy is not gated.
- Part F's numbers as a fixture (93.75% at (10, 5), 67.56% at (26, 22)) fail the recipe's tolerance.

**Done when** the tests pass, and S13 passes live.

### V4 — Locked results stay unreadable to agents until release

**Depends on:** nothing. **Size:** M.

**Read first:** `campaigns/guidance.py` (`visible_records()` L120, `_records()` L124–200: locked splits, protected cohorts,
transitive references, the `protected_work_status` view), `agents/tools.py` (`record()` L821–827, `evidence_search` L968–977,
`inspect()` from L850), `agents/files.py` (`Files.root()` L58–67, `analysis_run()` L175–184), `agents/experiments.py`
`progress()` L28, `llm/adapter.py` `_safe_context()` L562, `reports/evidence.py` `freeze()`, `evaluation/confirmation.py`
(`release()` L342).

**Today**
- `PiTools.record()` checks only that the record's kind is readable and that it belongs to the campaign. `trial` is a
  readable kind, so a confirmation cell's trial, its result and its metrics are readable before release.
- `evidence_search` lists every readable record of the campaign.
- `Files.root()` opens any trial's experiment directory through `record()`, and `analysis_run()` takes any trial ids.
- `MemoryService._records()` computes exactly what an agent may see (locked splits, protected cohorts, and whatever
  refers to them), and `finding.record` uses it; the read tools do not.

**Change**
1. `MemoryService.protected_ids(campaign_id)`: the ids `_records()` withholds, cached by the campaign's event cursor (as
   `ledger.rows()` caches).
2. `record()` refuses a protected id with "withheld until the confirmation is released", except that a protected trial
   reads as its `protected_work_status` view (status only, as `_records()` builds it).
3. `evidence_search` leaves protected ids out; `Files.root("experiment")` and `analysis_run()` refuse protected trials;
   `experiment_progress` and `campaign_inspect` show protected trials as status only. Check `comparison.report`'s receipt
   and the page agents' reads the same way.
4. A test lists every agent tool that returns records and checks it against `protected_ids()`, so a new read tool cannot
   skip it.

**Tests**
- Before release, each read path (record, search, files, analysis, progress, inspect) returns no result or metric of a
  confirmation cell; after `release()`, all of them do.
- A finding that refers to a protected trial stays withheld (unchanged).
- The list-of-tools test fails for a new tool that is not checked.

**Done when** the tests pass, S15 passes live, and the invariant row is `code` (I1).

### V5 — The gates on the pages; waivers in one click

**Depends on:** V1, V2, V3, decision 16. **Size:** S–M.

**Read first:** `frontend/src/evolution/EvolutionPage.tsx`, `frontend/src/evolution/LineageTree.tsx`,
`frontend/src/hypotheses/HypothesisCard.tsx`, `frontend/src/inbox/InboxPage.tsx`, `src/balsamic/api/evolution.py`.

**Change**
1. Each ledger row shows its gates: the stop outcome (V1), the assessment ("2 of 3 configurations", V2) and the fidelity
   state (V3), each with a link to its evidence.
2. A refused transition shows why and what would unlock it: the missing runs, the recipe to run, or "waive".
3. The researcher waives a tuning or fidelity requirement from the row or from the agent's waiver card, with a rationale;
   the waiver is the existing record.

**Tests** Playwright `evolution.spec.ts`: a gated row shows its state; a waiver from the row unlocks the transition.

**Done when** the tests pass.

---

## Order and shared files

```
Wave 1  V3 · V4
Wave 2  V1
Wave 3  V2 (V1)
Wave 4  V5 (V1, V2, V3)
```

| File | Parts |
|---|---|
| `campaigns/hypotheses.py`, `campaigns/commands.py` | V1, V2, V3 |
| `contracts/commands.py` | V1 |
| `src/balsamic/evolution/ledger.py` | V1, V2, V3 (and A2) |
| `agents/tools.py` | V4 (and B6, B7, R2, R6) |
| `frontend/src/evolution/*` | V5 (and A2) |

## Risks

- **Gates that block the researcher:** the gates bind agents. The researcher's own transitions pass with a recorded
  warning, and waivers are theirs.
- **Old records:** stops before V1 read as `unspecified`; finalists before V3 are not re-checked, but their state shows as
  `not_checked`.
- **Cost of fidelity checks:** a high-order RCWA check is expensive. It is asked for only at promotion, never on screening
  runs, and its compute goes through the go-ahead like any other.
- **Visibility cost** (V4): `_records()` walks the campaign's records; the cache by event cursor keeps it to one walk per
  change.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, Playwright for V5.
- Live (Centinels): S12–S15 against the Phase 2 baseline, in the phase's readiness Part.
