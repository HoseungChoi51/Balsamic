# Balsamic roadmap: from charter to results, then guardrails in code

| Item | Detail |
|---|---|
| Target | `kc-ml2/balsamic`, branch `workspace-rebuild`. The parts are built on Hoseung's fork, `HoseungChoi51/Balsamic`, whose `main` holds that branch: on the fork, read `workspace-rebuild` in this roadmap as `main` |
| Date | 2026-10-27 |
| Sources | `docs/charter-to-results-plan.md` (`cc0e693`), which Phase 1 replaces; the design-drift review of 2026-10-27, every suggestion and every lost idea it lists (§4 maps each one to its parts); and the algorithm-family review of 2026-10-27 (§4.1) |
| Checked against | The code at `cc0e693`. Each part's "Today" says what the code does now |
| Status | Plan, not started. A1 fixes a live bug. Decisions 1–24 are settled (§2): 1–3 before this roadmap, 4–21 in Hoseung's review on 2026-10-27 (8 and 14 with changes), 22–24 after the algorithm-family review the same day (22 with a change) |
| How to work | One part = one branch = one PR into `workspace-rebuild`. Each phase file lists its parts, what each depends on and which can run in parallel |

The diagnosis behind Phases 2 to 7, in one paragraph: Balsamic enforces in code what agents may *do* (commands, compute,
approvals), but what counts as *evidence* (enough tuning before rejecting a method, a fidelity check before trusting a
score, independent reviews, locked test results) lived in the discovery layer the 19 October rebuild deleted, and now
survives mostly as prose. The workflow also became open chat, so each new rule is bolted onto one command after an
incident. The remedy is to be flexible at the edges (the problem, the methods, the ideas, the coding tools) and strict in
the middle: a typed mandate for each request, evidence gates on strategy transitions, validation outside the coding box,
and domain knowledge moved out of the core into problem packs.

## The phases

| Phase | Goal | Parts | Start after | File |
|---|---|---|---|---|
| 1 | **Charter to results.** After the charter, Balsamic is no harder than a script and a local coding agent | 28: A1–A4, B1–B7, C1–C3, D1–D3, E1–E5, F1–F4, G1–G2 | — | [phase-1-charter-to-results.md](phase-1-charter-to-results.md) |
| 2 | **Measure first.** An invariant register, trap evals of scientific judgement, docs that are small and dated | 7: I1–I3, J1–J4 | — (runs beside Phase 1) | [phase-2-measure-first.md](phase-2-measure-first.md) |
| 3 | **A mandate for every request.** What a request allows is a record the command bus checks, not a line of the prompt | 7: R1–R7 | B2; the J1 baseline | [phase-3-mandates.md](phase-3-mandates.md) |
| 4 | **The coding box.** Pi inside, behind an interface that does not depend on Pi; open inside, strict at the walls, validated outside | 8: H1–H8 | F3, F4 for most parts | [phase-4-coding-box.md](phase-4-coding-box.md) |
| 5 | **Evidence gates.** A stop, a promotion or a read of a locked result needs its evidence or the researcher's waiver | 5: V1–V5 | the J1 baseline | [phase-5-evidence-gates.md](phase-5-evidence-gates.md) |
| 6 | **Problem packs.** Domain knowledge out of the core; problem-agnostic constraints (M5); every algorithm family on fair terms | 15: N1–N15 | — (N9, N10 after G1 and decision 20; N11 after N2) | [phase-6-problem-packs.md](phase-6-problem-packs.md) |
| 7 | **Fewer standing agents, claims that resolve.** Roles as calls with assembled context; numbers that point at receipts; findings that say what they state | 8: T1–T4, K1–K4 | the Phase 2 baseline; V4 for T1; V1, V2 for K4 | [phase-7-agents-and-claims.md](phase-7-agents-and-claims.md) |

78 parts. Size: S is under about 200 changed lines including tests, M about 200–600, L more.

**Names.** A part is a letter and a number (A1); the letter is its track, and a phase holds one or two tracks. A line
number is written L123. Decisions are numbered 1–24 and written "decision 7" (the first version of this plan called 4–9
"D4–D9"). Other series keep their own names, and the roadmap names their file when it cites them: the harness plan's
D1–D9, `docs/suggestions.md`'s findings R1–R6, suggestions S1–S7 and questions Q1–Q8, and the eval scenarios S1–S16.
Entries of `docs/lead-agent-readiness.md` are "Part T", "Part U" and so on: a separate series, which names the roadmap
part it closes.

---

## 0. Instructions for coding agents (read first)

1. Work on one part at a time. One part = one branch (`roadmap/<id>-<short-name>`, e.g. `roadmap/a1-install-reparse`) =
   one PR into `workspace-rebuild`.
2. Before a part, read §1 (principles) and §2 (decisions) here, the introduction of its phase file, and the part itself.
   Then read its "Read first" files (plan mode recommended).
3. Line numbers refer to `cc0e693`. Code moves; find it by function name. A path such as `agents/development.py` is under
   `src/optimization_framework/`; paths that start with `src/`, `frontend/`, `tests/`, `docs/`, `evals/`, `scripts/`,
   `deploy/`, `libraries/` or `agent-harness/` are from the repository root.
4. The decisions in §2 are settled. If a part needs a choice §2 does not cover, ask Hoseung before implementing it.
5. Write or update the tests first, then implement. A part closes only when every "Done when" item holds.
6. Live evals follow `docs/suggestions.md` §0.5: the dev profile's default provider (Centinels) needs no approval; any other
   provider needs Hoseung's.
7. The core (`src/optimization_framework`) never imports the service layer (`src/balsamic`); see
   `tests/balsamic/test_layering.py`. For Balsamic-specific behaviour the service layer registers a hook on `workspace`.
   Once N1 has landed, the core also gains no new domain names (its ratchet).
8. Prompt text is under the size ratchet in `tests/test_harness_contract.py` (`LEAD_WORDS` and `SPECIALIST_WORDS` + 10%).
   A part that adds instruction text removes as much elsewhere. When code takes over a step, the prose for it goes.
9. Never ask the researcher to run commands, and never change the live lab by hand. The live checks named in the parts are
   Hoseung's.
10. Before opening the PR, rebase on the latest `workspace-rebuild`. Parts that share a file (each phase file lists them)
    are merged one after another.
11. When closing a part:
    - add a Part to `docs/lead-agent-readiness.md` in its format (What was wrong / What changed / Checked / Not done), with
      the roadmap id in its title, e.g. "Part T — Install without a false confirmation (roadmap A1)". The last Part at
      `cc0e693` is Part S. Parts built in parallel take the next free letter when they merge: on a rebase, keep the other
      Parts and renumber yours after them;
    - once I1 has landed, update the rows of `docs/invariants.md` the part changes, with the test that now pins each one;
    - once I3 has landed, update the part's line in `docs/status.md`.
12. Commit messages follow the log: `feat(scope): …`, `fix(scope): …`, `docs(scope): …`, `test(scope): …`.
13. Do not edit the roadmap files in a part's PR, except to correct a mistake in them; say so in the PR.

Test commands:

```bash
GRATING_LLM_DISABLED=true uv run pytest -q          # tests/test_tracking.py is known to be flaky: rerun it alone
(cd agent-harness && npm test)
(cd frontend && npx tsc -b && npx playwright test)   # when the UI changes
uv run python scripts/run_lead_evals.py --fake       # the eval plumbing, no model calls
```

In a fresh container, such as a cloud session: install bubblewrap (`apt-get install -y bubblewrap`; without it the isolated
package tests fail with `SandboxUnavailable`), then `uv sync --extra dev` and
`uv pip install scipy==1.18.1 "matplotlib>=3.10,<4"`. Some tests outside the `meent` marker need scipy and matplotlib,
which come with the `meent` extra, and that extra installs `meent` from a private repository. Install them into the
environment rather than with `uv run --with`, which a sandboxed test's Python does not see. As root,
`tests/test_server_launcher.py` fails by design (the launcher refuses to run as root): run it as a normal user.

---

## 1. Principles

1. **Flexible at the edges, strict in the middle.** The problem, the methods, the ideas and the coding tools are open. What a
   request allows, what counts as evidence and what enters the lab are checked by code.
2. **Three researcher actions after the charter.** Confirm, ask, approve. Everything after the go-ahead is Balsamic's, until
   the comparison (Phase 1).
3. **Free inside, strict at the walls.** The coding agent and the methods may do anything inside their sandbox. What enters
   the lab is checked outside it: the exact commit, the manifest, the tests, conformance, and the comparison of the
   library's problem with the charter.
4. **Every automatic step is a receipted action within an approval.** Installing, binding and starting runs are done by a
   named system actor (`balsamic`), each with a receipt naming the install, the consent or the mandate it acts under, and
   never more than was approved.
5. **A conclusion needs its evidence.** A stop, a promotion and a published claim are recorded only with the evidence their
   gate asks for, or with the researcher's waiver. Agents may propose anything.
6. **One meaning per number.** "Best" follows the objective's direction everywhere. A method that finished holds its final
   value. A number in a claim points at the record or receipt it came from.
7. **No domain in the generic path.** No grating names, defaults or references in what a new problem goes through. A
   problem brings its own tools, procedures and validation in its pack.
8. **Measure first, judge by the evals.** Phase 2 records a baseline; every later phase records its effect on it.
9. **Fix at the lowest code layer.** Triage a failure in order (outside the mandate, over a budget, an unsupported claim or
   transition, the prompt, the UI) and fix it at the first layer that fits, with an eval scenario (I2).
10. **Prompts shrink as code takes over.** When code does a step, the prose that told the agent to do it goes.

---

## 2. Decisions

### 2.1 Settled before this roadmap, and changed in its review (Hoseung, 2026-10-27)

1. **Where the evaluator comes from:** from the library. The coding agent writes the scoring function into the same library
   as the algorithms. Balsamic generates the boilerplate and the tests from the charter, and once the library is installed
   the task uses it like any installed problem. No separate evaluator commissioning on the default path.
2. **Concept review:** it does not gate runs of proposals the researcher asked for or approved. Review happens on request
   and is shown when done; proposals agents create on their own still need it.
3. **Approvals:** one go-ahead per request, covering the coding workspace, the evaluator and the runs, with their minutes.
   Implementation compute counts against it, with no separate allocation to raise. The go-ahead threshold still holds; work
   beyond what was approved asks again.

Changed in the review of this roadmap:

- **8. Other coding harnesses:** Pi stays the coding harness; Claude Code is not expected to replace it. The box keeps a
  seam for another harness (H2's adapter) as a placeholder. If one is ever added, it runs on the researcher's own
  credentials mounted read-only, opted into per workspace.
- **14. The assessment minimums** (the deleted `AssessmentPlan`'s): before an agent stops a method as inferior, 3
  configurations, each run to the informative horizon (completed, or at least the campaign's short-run threshold, plus a
  minimum number of evaluations when the researcher sets one). Seeds matter only for stochastic methods: a stochastic
  method needs 2 seeds per configuration, and a deterministic one needs one run per configuration, since another seed
  gives the same run. A method counts as deterministic when it declares so and conformance confirms it; an undeclared one
  counts as stochastic. A stochastic evaluator makes every method's runs vary, so the seed minimum applies again. Fewer
  needs the researcher's waiver. Set per campaign in the experiment rules.

### 2.2 Settled at their recommended defaults (Hoseung, 2026-10-27)

| No. | Question | Decision | Needed by |
|---|---|---|---|
| 4 | What a consent covers | Only work for the proposals and workspaces its plan names. A plan that names none stays campaign-wide (today's behaviour, and every consent recorded before this change) | B2 |
| 5 | Where unknown fields are tolerated | Agent paths only: the coding agent's manifest and the top level of agent command payloads. The researcher's HTTP API and nested objects stay strict, and a near-miss is always refused | B6 |
| 6 | The system actor | `balsamic`, allowed exactly two operations: `implementation.bind_builtin` after an install, and `trial.create` for a run an approved plan lists, under that consent. Every use has a receipt | B4, B5 |
| 7 | What "asked for" means | A proposal created in a lead turn whose request root (`controller.request_root`) is a researcher message. Not autopilot turns, not notices without such a root | B1 |
| 9 | Which generated files the coding agent may change | `charter.json` and `data.py` are fixed (the install refuses edits). Everything else is the agent's; the install lists the generated files it changed | F4 |
| 10 | The mandate templates | Four, after the design review: **Answer** (reads and answers; starts nothing), **Explore** (work up to the researcher's go-ahead threshold in total, no coding workspace; the default when nothing else is chosen), **Screen** (the proposals, workspaces and runs a plan names, with their minutes: today's compute go-ahead, B2), **Run the campaign** (every stage within a compute and model envelope and a deadline; what autopilot uses) | R1 |
| 11 | What happens when a mandate's deadline passes or its envelope is spent | New work is refused, and the lead and the researcher are told. Work already running continues to its own limits; nothing is stopped automatically | R3 |
| 12 | Whose mandate a page agent works under | The lead's, when the lead asked it. Its own, proposed with the same tool, when the researcher wrote on its page | R3 |
| 13 | The stop outcomes | The six stop outcomes of the deleted `AssessmentDecision`: `implementation_invalid`, `assumptions_incompatible`, `configuration_unpromising`, `under_evaluated`, `unaffordable_within_allocation`, `adequately_assessed_deprioritized`. An agent gives one, with evidence ids; the researcher may stop without one (recorded as `researcher_decision`) | V1, K4 |
| 15 | What the fidelity gate guards | Choosing finalists (`hypothesis.nominate`, `hypothesis.status` finalist, `finalist.set`) and `library.publish`. Not screening or extended runs | V3 |
| 16 | Who may waive a gate | Only the researcher. An agent asks with `approval.request` kind `waiver`, which exists | V2, V3, V5 |
| 17 | Where a problem pack lives | In the problem plug-in's own package (`src/dqn_meent` for MEENT), declared by its adapter; no separate distribution | N2 |
| 18 | The coding box's egress | The harness's model endpoint and the package index (pypi.org and files.pythonhosted.org, or a configured mirror). Anything else is named in the ticket and approved with it | H5 |
| 19 | Which roles become one-shot calls, and the harness plan's D2 (merge the specialists) | `proposal_reviewer` and the review specialists first; roles that search or run analyses keep sessions. D2 is decided by T3's eval comparison | T1, T3 |
| 20 | When M5 (problem-agnostic constraints) starts | After G1 passes and Hoseung confirms the narrower framework end to end, as decided on 21 October | N9, N10 |
| 21 | What moves to `docs/history/` | The 14 docs that open with a "Superseded" banner at `cc0e693`, plus `docs/charter-to-results-plan.md` and `docs/agentic-algorithm-discovery-plan.md` (the first plan, superseded by the redesign that is itself superseded); `docs/harness-update-plan.md` once its D1–D9 are marked. Links in the repository are updated; no stubs are left | I3 |

### 2.3 Settled after the algorithm-family review (Hoseung, 2026-10-27)

The review asked whether Balsamic favours MILP-style methods. It does not run MILP solvers; its bias is toward black-box
search (Phase 6 "Why"). Balsamic's goal is to solve the researcher's practical problem as efficiently as possible, not to
run a benchmark or teach, and the decisions follow from that.

| # | Decision | Settled | Parts |
|---|---|---|---|
| 22 | May a method use the objective's code, not only call the evaluator? | Yes, by default: every problem is `white_box` unless it declares `oracle` (an expensive evaluator such as MEENT, or a black-box comparison the researcher wants). Changed in the review: the recommendation was `oracle` by default | N11, D1, F1 |
| 23 | The default cost axis on a white-box problem | `worker_seconds` on a fixed worker class; `core_seconds` (threads × wall time) when a method uses more than one thread. Evaluations stay as a diagnostic | N11, F1 |
| 24 | A general problem-owned representation, or one named type at a time | `structured`, owned by the problem's library. A named type enters the core only once two problems need it (the rule of two, `docs/optimizer-plugins.md`) | N12 |

---

## 3. Order across phases

Phases are an order of priority, not a strict sequence: parts state their real dependencies.

```
Now     Phase 1 (A1 first; critical path A3 → D1 → D2 → F3 → F4 → G1)
        Phase 2 beside it (I1, I2, I3, J1–J4: other files)          N1 (the domain-names ratchet: one test), N15 (prompts)
Next    Phase 3 (after B2)                                          Phase 5 (V3 first, then V4, V1, V2, V5)
Then    Phase 4 (after F3, F4)                                      Phase 6 (N2–N8, N11, N13, N14; N9, N10, N12 after G1
                                                                    and decision 20)
Last    Phase 7: T1–T4 judged against the Phase 2 baseline (K1–K3 may start any time; K4 after V1, V2)
```

This follows the design review's order (measure, mandates, coding box, gates and packs, topology and claims), with Phase 1
first because it is the work in progress and it holds a live bug.

### 3.1 Dependencies between phases

| Part | Needs | Why |
|---|---|---|
| R1 | B2 | A mandate generalizes B2's scoped consent; a consent becomes a mandate's compute part |
| R3 | B5 | The `balsamic` launches act under the consent their origin names; after R3, under its mandate |
| R4 | R3 | Autopilot's cap guard becomes the mandate guard |
| H2, H3, H4 | H1 | They use the harness-independent bridge |
| H4 | F4 | The ticket starts from the generated library |
| H5 | B2 | The wall-clock deadline is charged to the consent (to the mandate after R3) |
| H6 | F3, D2 | It runs the generated contract tests and `check_function` outside the box |
| H7 | H4, H6 | A commission is a ticket in a headless box, validated outside |
| V5 | V1, V2, V3 | The page shows the gates |
| T1 | V4 | The assembled context uses the same visibility rule as the read tools |
| K4 | V1, V2 | A negative library entry needs a typed stop and, for a performance stop, an adequate assessment |
| N9, N10 | G1, decision 20 | M5 waits for the narrower framework to be confirmed end to end |
| N12 | N9 | A problem-owned candidate is admitted through N9's design-constraint path |
| N13 | A3 | The bound travels in a finished method's final inspection |
| N14 | N5 | The size ladder sits in the pack's `racing` section beside the fidelity ladder |
| J1 (S17) | — | It measures the bias N11 and N15 address: expected to fail before them |
| J1 (S15) | — | It measures the gap V4 closes: expected to fail before V4 |
| Phase 7 | J1–J3 | Its parts are kept or reverted by their effect on the baseline |

---

## 4. Traceability: every item of the design review

The review's sections: 01 findings, 02 the original plan, 04 what drifted, 05 good ideas not implemented, 06 why
flexibility and guardrails fought, 07 a coding-harness architecture, 08 architecture suggestions, 09 workflow suggestions,
10 a suggested order. Section 03 is the timeline; it asks for nothing.

| § | Item | Parts |
|---|---|---|
| 01 | Autonomy swung (graded delegation, autonomous iteration, "acts on requests", per-action consent) and ended as two thresholds: graded delegation in a narrower form | R1, R2, R7 (graded delegation as named templates) |
| 01 | The epistemic guardrails were deleted with the discovery layer | V1–V5, K3, K4 |
| 01 | Rules follow incidents | I1, I2; R3 is the layer new rules attach to |
| 01 | The core still knows MEENT | N1–N8 |
| 01 | The coding agent is two hops away | H1–H8 |
| 02 | A researcher–system partnership; system-only operation is an ablation | J3 |
| 02 | Three separate statements: scientific promise, empirical evidence, research decisions | K3 |
| 02 | Code enforces budgets, allowed actions, job lifecycle and evaluator integrity | Kept; extended to a request's scope (R3) and model spend (R5) |
| 02 | Tool-less, bounded, structured calls; the backend assembles each call's context | T1, T3 |
| 02 | Guided and delegated modes | R1, R7 |
| 02 | Fair assessment before rejection | V1, V2 |
| 02 | Re-evaluate at higher fidelity before strong conclusions | V3 |
| 02 | Protected confirmation evidence with exposure provenance | V4 |
| 02 | A knowledge library with counterevidence, applicability and typed links | K3, K4 |
| 02 | A general harness, specific optimizers | Phase 1 (C, D, E, F); N1–N10 |
| 04 | Who acts | R1–R4 |
| 04 | Staying within a request rests on the prompt (`docs/pi-agent-harness.md` L102–103) | R3, R6 |
| 04 | Model calls: tool-using sessions, caps re-added after incidents | T1, T3 |
| 04 | Agent topology grew (15 roles in `ROLES` plus the formulator, the housekeeper and the report writer; 4 standing page agents) | T3, T4 |
| 04 | Rejecting a method: a free-text `stop_reason` | V1, V2 |
| 04 | Fidelity before conclusions: a draft procedure only (readiness Part F) | V3; N3 moves the procedure into the pack |
| 04 | Knowledge narrowed to a library of winners | K4 (negative results); K3 |
| 04 | Problem generality partial; M5 deferred | N1–N10 |
| 04 | Evaluation of the product narrowed to compliance on one model | J1–J3 |
| 04 | Docs as the plan drifted: 1.08 MB, superseded plans in place, the harness plan's D1–D9 still "Open" | I3 |
| 05 | Adequate assessment before rejecting a method | V1, V2 |
| 05 | Fidelity validation before trust; `library.publish` takes any finalist | V3 |
| 05 | Protected confirmation evidence. The review left it unverified; at `cc0e693` it holds: the agent read tools never call `MemoryService.visible_records()` | V4 |
| 05 | Independent reviews; the moderator's synthesis is unchecked | T1, T2 |
| 05 | The model never does arithmetic: claims get no such treatment (harness plan Phase 9 not started) | K1, K2 |
| 05 | Domain knowledge out of the core | N1–N8 |
| 05 | Evaluating the partnership: compliance scenarios only, one model, one problem | J1–J3 |
| 06 | With no typed workflow, rules attach per command and per incident | R1–R3 |
| 06 | Visible failures got code, silent ones got prose | J1 (traps make silent failures visible); I1 |
| 06 | Tool-using agents removed the choke point; independence and protection must be re-imposed on every read tool | V4, T1 |
| 06 | More agents, more prose boundaries; some hops add cost more than safety | T4 |
| 07 | The work ticket is the interface; the implementation lead reviews diffs and checks instead of relaying chat | H4 |
| 07 | An MCP server and a CLI replace the Pi extension's two tools | H1 |
| 07 | A thin adapter per harness, headless and interactive | H2 (Pi's adapter; the seam is a placeholder for others, decision 8) |
| 07 | Guardrails at the walls: egress allowlist, cgroup limits, a deadline charged to the consent, no protected fixtures | H5 |
| 07 | Independent validation of the exact commit outside the box | H6 |
| 07 | Bring your own session | H3 |
| 07 | One implementation route: the service route becomes the box's headless mode | H7, H8 |
| 07 | Pi first, Claude Code second, judged by an eval that builds a method from its specification | J4. Pi stays the harness (decision 8) |
| 08 A | A mandate for every request: `mandate_propose`, small ones start at once, larger ones are one inbox card, the bus refuses what is outside, autopilot is a standing mandate, the thresholds are the default template | R1–R7 |
| 08 B | Evidence-gated strategy transitions: typed stops with evidence, minimum configurations and seeds, fidelity before finalist or library, locked confirmation trials | V1–V5 |
| 08 C | Problem packs: tools, procedures, validation recipes, a resource estimator, presentation defaults, references; a test that the core holds no domain names; M5 in the charter contract and the pack's evaluator | N1–N10 |
| 08 D | Fewer standing agents, more structured calls; decide D2; reconsider the operator's and the moderator's sessions | T1–T4 |
| 08 E | Claims resolve to receipts: Phase 9, and a compute tool on the charter's expression evaluator | K1, K2 |
| 09 | An invariant register (code and test, prompt and eval, nothing) that fails CI when a "code" row has no test | I1 |
| 09 | Triage each incident by layer before fixing it | I2 |
| 09 | Evals of scientific judgement: planted traps, a second problem, two models | J1, J2 |
| 09 | Docs smaller and dated: `docs/history/`, short ADRs, one status page | I3 |
| 09 | Close Part S's open decision: should outcomes of runs the researcher started wake the lead | R6 |
| 10 | The suggested order | §3 |

### 4.1 The algorithm-family review (2026-10-27)

[Is Balsamic biased toward MILP?](https://claude.ai/artifact/LwiujDQ7GTZqyoqDJK7mtV) (a private doc of the project).

| Gap | Parts |
|---|---|
| An order has no form; a method cannot finish; a method is heavy to write; methods do not see the data | C1, C2, A3, D1, D3 (Phase 1, unchanged) |
| The problem does not say whether the objective is an oracle or known code; evaluations are the cost; a threaded solver cannot be compared | N11 (decisions 22, 23); F1 and D1 amended for time budgets and the objective |
| No place for a proven bound or optimality; nothing exact as a baseline | N13 (with `enumerate`); A3 amended to keep the bound |
| Instance size is not an axis | N14 |
| Representations stop at vectors and orders; scheduling constraints have no form | N12 (decision 24), with N9 |
| Prompts ask for a search method; nobody classifies the problem or looks up known algorithms | N15 |
| Nothing measures the bias | J1 S17 |
| The UI assumes anytime runs (evaluations axis, "Extend" as more budget, no proof or gap badges) | N11 (axis), N13 (badges), N14 ("Extend" as the next size) |

---

## 5. Relation to other plans

| Plan | Here |
|---|---|
| `docs/charter-to-results-plan.md` | Replaced by Phase 1, which splits it into parts; it gets a banner pointing here |
| `docs/harness-update-plan.md` | Phases 1–7 are done (readiness Parts L–S). Phase 8 (MCP at the edges) is not in this roadmap. Phase 9 is K2. I3 marks D1–D4 and D6–D9 as decided (D2 at its default, revisited by T3); D5 stays open with Phase 8 |
| `docs/suggestions.md` | S2 is A4. S6 (one-step Python) is close to K1: K1 is the whitelisted calculator whose receipts K2 recognizes, and S6 may still give the lead Python. S7's scenario format is used by G2 and J1, and its judge (Q8) grades J1 when settled. S1 and S3–S5 stay there |
| `docs/pi-implementation-workspace-plan.md` | Phase 4 extends it |
| `docs/problem-setup.md`, "Next step: problem-agnostic constraints" (M5) | N9, N10 |

## 6. Verification

- **Per part:** its tests; then the full commands of §0, and Playwright when the UI changed.
- **Per phase after Phase 2:** the eval summary before and after the phase (`--compare` with the Phase 2 baseline), in the
  phase's last readiness Part.
- **Live checks** are Hoseung's and are named in the parts: A1 (the baking-order install), wave 5 of Phase 1 (charter to
  ranked results with three researcher actions), J2 (another provider, with approval).
