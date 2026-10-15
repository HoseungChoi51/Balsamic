# Setting up a problem: workflow, design and status

Status on 15 October 2026: **implemented, tested, live, and checked once with a model on the running
service**. The first part states the workflow the researcher asked for. The second part is the
agreed design. The last part says what exists in the code and what does not.

## What is wrong now

- **Fields appear before there is a problem.** The New campaign form opens with the first
  installed example already applied. Its "Problem instances" fields are shown before the
  researcher has chosen or imported a problem.
- **The same value is stated twice.** The research objective text and the fields both state
  values. The installed 2D deflector example says "1050 nm", "75°", "Px ≈ 1087.04 nm",
  "256 × 128" and "325 nm" in its text. The fields hold `wavelength_nm`, `target_angle_deg`,
  `period_x_nm`, `grid_x`, `grid_y` and `thickness_nm` again. When a field is changed, the text
  still states the old value. Nothing compares the two.
- **Dependent values are not linked.** In that example:
  - `period_x_nm` is exactly 1050 / sin 75°, by the grating equation;
  - `silicon_n_1050` is the linear interpolation of the FLRL index table at 1050 nm.

  When the wavelength changes, both stay at their old values. The 1100 nm / 70° ablation had to set
  them by hand.
- **The importer's open questions do not hold anything back.** The importer records assumptions
  and open questions as free lists. A campaign can be created while they are still unanswered, and
  nothing checks the draft beyond the evaluator's schema.

## Principles

1. **Nothing is built for one problem.** The framework's code knows no particular problem.
   Knowledge of a problem lives in three places, all of them data or general guidance:
   - **The formulator's guideline:** a general method, with examples from several fields, that
     any capable model follows to formulate a scientific optimization problem.
   - **The problem charter:** the formulation of one problem, written by the formulator and
     confirmed by the researcher.
   - **Installed problem adapters and their examples:** each adapter is a package of its own.

   Every check, expression, comparison and page works for any charter.
2. **Every value is stated once.** Texts refer to values by name, so a text always shows the
   current value.
3. **Relations are decided by the formulator and computed by code.**
   - **Deciding:** the formulator states which quantity follows from which, with a citation. The
     researcher reviews this like any other part of the problem.
   - **Computing:** code does all the arithmetic, strictly mechanically. The same charter always
     gives the same numbers, and the model never does the arithmetic.
4. **Two ways to change a charter, and no link or unlink controls.**
   - **Type an input.** Everything that follows from it recomputes at once, without a model and
     without cost.
   - **Ask in words for anything else.** The formulator answers with a proposal: one to three
     options, each a list of changes with reasons. Code computes every number in an option and
     checks it, and the researcher accepts one option or rejects them all.
5. **Every value shows where it came from:** the researcher, a source (with its citation), an
   assumption by the formulator, or a computation. An assumption stays marked until the researcher
   accepts it.
6. **Only the researcher confirms.** A blocking issue holds confirmation back unless the
   researcher waives it with a reason.

## Terms

| Term | Meaning |
|---|---|
| Source material | What the researcher supplies: a written problem statement, papers, code, notes. Any one of them is enough. |
| Formulator | The agent that reads the source material and writes the problem charter, following the guideline. Today's problem importer, extended. |
| Guideline | The formulator's general method for formulating a scientific optimization problem. Its examples come from several fields. |
| Problem charter | One JSON document that states the problem. Every value is stated in it once. |
| Quantity | A named value in the charter, with its kind, units and allowed range. |
| Input | A quantity whose value is typed in (wavelength, temperature, layer thickness). The optimizer does not change it. |
| Derived quantity | A quantity computed from other quantities by a stated relation: an expression, possibly using a table of data. It is not typed in. |
| Decision variable | What the optimizer searches over, with its representation (binary, discrete, continuous), size and bounds. |
| Constraint | A condition a design or the setup must meet. It is **hard** (breaking it makes a design invalid) or **soft** (breaking it is penalised or flagged). Its form is a test on quantities, a linear condition on the decision variables, a condition the evaluator enforces, or words only (**qualitative**). |
| Objective | The one number the optimizer improves, with its direction, its units and how it is computed. |
| Recorded metric | Another number measured for every design but not optimized. |
| Evaluator | The code that computes the objective. Either an installed problem adapter, or a declared problem whose evaluator is built later. |
| Fidelity | The evaluator's accuracy settings. They are inputs like any other, and part of the problem: a score belongs to the fidelity it was computed at. |
| Instance | One set of input values for the problem, with its split (development, selection or held-out test). |
| Reference result | A number the sources report, kept as prior literature, never as a measurement. It names the input values it holds at. |
| Provenance mark | Where a value came from: researcher, source, assumed or computed. |
| Finding | Something the checks found, either **blocking** or a **warning**. |
| Question | A choice put to the researcher, with the options the formulator sees. |
| Proposal | The formulator's answer to a request for a change: one to three options of changes. |
| Confirmed charter | A charter revision the researcher has confirmed. It is frozen, and a campaign is created from it. |
| Fork | A copy of a confirmed charter with one or more inputs, the **axis**, changed. It starts a new campaign. |
| Campaign settings | Everything else a campaign needs: its name, its research question, budgets and autonomy. |

Today "charter" means the campaign's objective text together with its settings and instances. In
this design the problem charter becomes the problem part of that. A campaign then records the
confirmed problem charter revision it was made from, plus its settings.

## The workflow

1. **The researcher supplies the source material:**
   - a written problem statement, papers, code or notes;
   - or an installed example;
   - or a fork of a confirmed charter.

   No problem fields exist before this step.
2. **The formulator reads the material and formulates the problem, following the guideline.**
   1. It separates inputs, decision variables and constraints.
   2. It defines the objective: what is optimized, its direction, its units and how it is
      computed. Other measured numbers become recorded metrics.
   3. It defines the evaluator: the installed adapter that computes the objective, or a declared
      problem whose evaluator must be built.
   4. It also records:
      - **Units and ranges** of every quantity.
      - **Relations:** which quantities follow from which, and by what expression.
      - **Fidelity:** the evaluator settings the scores are computed at.
      - **Instances and splits:** which conditions are for development and which, if the sources
        define any, are held out.
      - **Reference results:** numbers the sources report, with the conditions they hold at.
      - **Provenance:** where each value came from, or that it is an assumption.
3. **The formulator writes the problem charter (JSON).**
   - Every value is stated in it once, and the texts refer to values by name.
   - Checks run on every revision. The formulator resolves each finding from the sources, or asks
     the researcher.
   - **Forking:** a confirmed charter can be copied with inputs changed, to start a campaign along
     a new axis.
     - The derived quantities follow the change.
     - Reference results that no longer hold are marked.
     - The copy records which charter it came from and what changed.
4. **The researcher reviews the charter, adjusts it and confirms.**
   - Typing an input recomputes everything that follows from it, and the text.
   - Anything else is asked for in words. A derived value is read-only; its "Change…" link opens
     the request box.
   - The formulator answers a request with a proposal. The researcher accepts an option or
     rejects them all.
   - Confirming freezes that revision, and the campaign is created from it.

## Problems to expect, and how each is handled

The checks are code. They run on every revision and on every edit, without a model. The formulator
finds what code cannot, from reading the sources. A blocking finding must be resolved, or waived by
the researcher with a reason, before confirming.

| Problem | Example | Found by | Handling |
|---|---|---|---|
| The statement as a whole is unclear | "Optimize the reactor" with no feed, temperature range or measure of success | Formulator | It asks before writing a charter, with what it would assume. |
| Conflicting constraints | Fill fraction at most 30% and at least 40%; a pressure input outside its own stated range | Checks: tests on quantities, and linear conditions on the decision variables (a feasibility test); formulator for the rest | A blocking finding. The formulator asks which one to relax. |
| Unclear objective | "Maximize efficiency for both polarizations": the mean, the minimum, or both kept apart? "Best yield at low cost": which weighting? | Formulator | A question with the options; the other numbers become recorded metrics. |
| Qualitative constraint | "Must be manufacturable", "thin enough", "safe operating conditions" | Checks (a constraint without a test) and formulator | Blocking until it gets a test, or the researcher waives it as a criterion that is recorded and not enforced. |
| The same quantity defined twice | A text states 1050 nm while the input holds 1100 nm; `Px` and `period_x_nm` both present | Checks: numbers in the texts with a quantity's units; two inputs with the same units and value; one evaluator field mapped twice | One definition is kept, and the texts use references. |
| One quantity depends on another | A period from the wavelength and angle; a material property from a table at the operating temperature; a total from its parts | Formulator states the relation; code computes it | A derived quantity. It follows its inputs, and changes only through a proposal. |
| Missing constraint or under-defined problem | No grid size, no incidence angle, no fidelity, no bounds on a continuous variable | Checks against the evaluator's required fields, and for inputs without a value or variables without bounds; formulator for the rest | Blocking: the formulator asks, or records an assumption that the researcher accepts. |
| The sources disagree | A paper and its code state different training budgets | Formulator | A question. Both are kept as reference settings until the researcher chooses. |
| Units differ or are missing | nm in the paper, µm in the code; degrees passed to a sine | Checks: every number has units; a trigonometric function applied directly to a quantity in degrees | The formulator states one unit per quantity, and relations convert explicitly. |
| No installed evaluator computes it | A new device or process | Formulator, from the catalog | A declared problem. The campaign can be created, and the evaluator is built afterwards, as today. |
| The installed evaluator optimizes something else | The researcher wants the worse polarization scored; the adapter scores the mean | Checks: the charter's objective against the evaluator's primary objective | Blocking: choose the evaluator's objective, or declare a problem whose evaluator computes the wanted one. |

## Design

### Artifacts

1. **Source material.** Today's import folder (`documents/`, `code/`, notes). A written statement
   alone is enough to start.
2. **The guideline.** `src/optimization_framework/problem_import/guideline.md`. It is the
   formulator's instructions, written for any capable model and for any field. It covers:
   - how to read the sources;
   - each element of a formulation, with how to recognise it and examples from several fields;
   - relations and tables;
   - what to ask and what to assume;
   - how to write texts with references;
   - how to answer a request with a proposal.
3. **The problem charter.** A contract, `contracts/problem_charter.py`. It holds:
   - title, summary and text;
   - quantities (inputs and derived) and tables;
   - decision variables and constraints;
   - objective and recorded metrics;
   - evaluator binding (which evaluator field takes which quantity);
   - instances and reference results;
   - citations and assumptions;
   - questions and waivers;
   - its origin, when it is a fork.

   Expressions use arithmetic, comparisons, `min`, `max`, `abs`, `sqrt`, `exp`, `log`, the
   trigonometric functions, `rad`, `deg`, `pi`, and `table(name, x)` (linear interpolation, with
   no extrapolation). A small whitelisted evaluator computes them, never Python's `eval`.
4. **Findings.** Computed from a charter, or from unsaved edits, without a model.
5. **Proposals.** Each holds the request, its options, and for each option the changes, the
   computed differences, the findings and the reasons. Its status is open, accepted or rejected.
   - A change can set an input to a number, or to an expression evaluated once.
   - A change can **solve** an input so that a derived quantity takes a wanted value. Code finds
     the root, so "set the period to 1100 nm" gives an exact angle without the model computing it.
6. **Compiled instances.** On confirmation, the charter compiles into today's campaign task input.
   Experiments, studies, problem identity, evaluator building and charter versions are unchanged.
   The installed deflector example compiles to the same problem identity as before.

### Agents

- **Formulator.** Today's `problem_importer`, extended. It has:
  - its own Pi identity, read-only access to its material, its model tier and its spending cap;
  - the guideline as its instructions;
  - the tools `charter_check`, `charter_submit`, `charter_propose` and `question_ask`.

  It works only when the researcher starts it, answers it or asks it for a change. It never
  confirms. It cannot:
  - change a value the researcher set, except through a proposal;
  - waive a finding;
  - accept an assumption;
  - answer a question.
- **Checks.** Code, not an agent.
- **Charter reviewer.** Not built. Filling in a researcher's partial intent is formulation work,
  and it belongs to the formulator, which holds the sources. A reviewer is valuable because it
  reads the charter fresh, and that is lost if it also fills things in. It will be added only if
  live checks show misreadings.
- **The Lead.** After the campaign exists, the Lead reads the confirmed charter. It may suggest a
  revision as a request for the researcher, and never edits the charter.

### Decisions (taken 15 October 2026)

1. **Naming:** "Problem charter" for the problem, "campaign settings" for the rest.
2. **Forks:** a fork makes a new campaign. Adding a fork as an instance of the same campaign may
   come later.
3. **Charter reviewer:** not built, for the reason above.
4. **Relations:** decided by the formulator and computed by code. There are no link or unlink
   controls; anything other than typing an input is asked for in words.
5. **Blocking findings** can be waived by the researcher, with a recorded reason.

## Status

| Item | State |
|---|---|
| Workflow and design written | Done (this page) |
| New campaign starts with no problem fields | Implemented, tested |
| Problem charter, expressions, findings, compilation | Implemented, tested |
| The guideline and the formulator's tools | Implemented, tested with a stand-in harness |
| New campaign page: Start, Formulate, Review, Confirm | Implemented, tested in the browser |
| Campaigns created and revised from a charter | Implemented, tested |
| Forks | Implemented, tested |
| Removing unused drafts and imports | Implemented, tested |
| Live check with a model | Done once; see below |

"Tested" means the automated tests pass. "Live" means the services on X670 run the code (restarted
on 15 October 2026). Nothing here is committed.

## Implemented (15 October 2026)

### Where it is

| Part | Files |
|---|---|
| Contract | `src/optimization_framework/contracts/problem_charter.py` |
| Expressions (whitelisted, no `eval`) | `src/optimization_framework/problem_charter/expressions.py` |
| Values, texts, findings, differences, changes, solving, compilation, conversion | `src/optimization_framework/problem_charter/charter.py` |
| Revisions, edits, answers, waivers, proposals, confirmation, forks, removal | `src/optimization_framework/problem_charter/service.py` |
| HTTP routes, under `/api/v1/problem-charters` | `src/optimization_framework/problem_charter/api.py` |
| The guideline | `src/optimization_framework/problem_import/guideline.md` |
| The formulator's tools and instructions | `src/optimization_framework/problem_import/service.py` |
| Campaigns from a charter (`charter`, `research_question`) | `contracts/requests.py`, `execution/service.py` (`_from_charter`) |
| The deflector's example charter (data in its own package) | `src/dqn_meent/problem_2d.py` (`flrl_charter`), `src/dqn_meent/data/flrl_si_index_800_1600nm.csv` |
| New campaign page, and the charter on the Problem page | `frontend/src/problemSetup.tsx`, `problemSetup.css`, `problemViews.tsx` |
| Tests | `tests/test_problem_charter.py`, `tests/test_problem_import.py`, `frontend/tests/problem-setup.spec.ts`, `frontend/tests/campaign-setup.spec.ts` |
| Browser fixtures, written by the real service | `scripts/charter_test_fixtures.py` → `frontend/tests/fixtures/reactor-charter.json` |

### What it does

- **New campaign** opens a page, not a form. Its Start step offers:
  - a written statement, with optional documents and code, for the formulator;
  - the installed and saved examples;
  - any installed evaluator, from the defaults its schemas declare, with no model involved. This is
    how `bounded_continuous`, which has no example, is started;
  - unconfirmed drafts to continue or remove;
  - confirmed charters to fork.

  The old form remains only for campaign settings and for drafts from the old importer.
- **The deflector example as a charter:**
  - The example is a charter whose period is the grating equation and whose silicon index is
    `table(silicon_index, wavelength_nm)`.
  - Both reproduce today's values exactly (1087.0399894305872 nm and 3.567390909090909), and the
    example compiles to its old problem identity.
  - The one assumption, normal incidence, waits for the researcher's acceptance.
- **Examples without a charter,** and campaigns made before charters, get one made from their
  instances.
  - Every scalar field becomes an input, without relations or units.
  - A structured field (a list or an object) is left to the evaluator when the evaluator would
    derive the same value. Otherwise it becomes a `data` input.
  - The decision variable's size is linked to the integer input, or the pair of inputs, whose
    value matches the size (`n_cells`; `grid_y × grid_x`).
- **Solving** finds the input that gives a wanted derived value by bracketing and root-finding,
  and stores the shortest decimal that still gives it. On the deflector, "period 1100 nm" gives
  72.66° or 1062.52 nm; on the flow reactor, "residence time 200 s" gives a flow of 3 mL/min.
- **Proposals:**
  - An option that leaves a new blocking finding is refused unless it says why it is offered.
  - Accepting an option applies its changes to the current charter, so answers and waivers given
    meanwhile are kept.
  - A proposal goes stale when anything but the questions and waivers has changed since it was
    made.
- **Values the researcher set** cannot be changed by the formulator's drafts; only a proposal the
  researcher accepts changes them.
- **A campaign made from a charter** records the confirmed revision and the research question. Its
  objective text is the research question followed by the charter's text with its values. Its
  instances are compiled from the charter. Changing only the research question or the budgets
  keeps the instances.

### Live check (15 October 2026)

Two scratch checks ran on the running service. The formulator was DeepSeek V4 Pro at maximum
effort. The checks cost $0.23 in all ($0.155 and $0.079). Both scratch charters were then removed,
with their formulators, folders and sessions; nothing was kept.

1. **A written statement from another field.** The statement described a plate-fin heat sink for a
   40 mm chip at 25 W. It had planted problems: conflicting height limits, "thick enough to be
   manufacturable", a fin pitch that follows from other values, "as good as possible", and no
   cooling conditions. The formulator:
   - read the statement and the catalog, and declared a new problem, since no installed evaluator
     computes heat sinks;
   - asked four questions, each with concrete options and their consequences: which height limit
     applies, what to optimize, what test defines "manufacturable", and whether the fin height is
     chosen or fixed. The question on the objective named the missing cooling conditions;
   - marked its own readings (the heights read as 25–30 mm, and others) as assumptions waiting for
     acceptance;
   - kept the fin pitch out of the charter's relations, because it depends on the number of fins,
     which is a design variable; it described the pitch for the evaluator instead.
2. **A request on the deflector example: "Set the period to 1100 nm."** The formulator read the
   charter, checked three candidates and proposed them. Every number was computed by the service:
   - keep 1050 nm, and the angle becomes 72.6586°;
   - keep 75°, and the wavelength becomes 1062.52 nm, with the silicon index following the table
     to 3.56319;
   - make the period a typed input, with a reason saying that the period then no longer matches
     75°.

**Found, and fixed the same day:**
- **The formulator waived a finding in its own draft.** It had marked the "manufacturable"
  constraint waived. Waivers, acceptances of assumptions and answers to questions are now
  stripped from anything the formulator writes; only the researcher gives them.
- **The declared heat-sink evaluator received no inputs.** Its binding was empty, and nothing
  flagged it. A new warning reports any quantity that reaches nothing: no evaluator field takes it,
  and no relation, bound, shape or test uses it. The guideline now says to pass every needed input
  to a declared evaluator, and that relations within the design belong to the evaluator.
- **The page:**
  - proposal options were clipped by a long expression, and are now a wrapping list;
  - long answer options in the question cards now wrap;
  - an option now lists only the blocking findings it adds, not those the charter already had.

### Not done
- **Browser specs that need a live server have not been rewritten.** Six of them create campaigns
  through the old form: `live`, `campaign-controls`, `experiment-controls`, `generated-recipes`,
  `commissioning` and `consolidation`. They are skipped unless their fixture servers run, and they
  will fail until they use the new page.
- **Relations run one way, and units are labels.** Units are not converted or checked
  dimensionally beyond the degree check.
- **A declared problem takes one kind of variable.** Its candidate has one representation, so the
  heat sink's whole-number fin count had to be written as a continuous variable that the evaluator
  rounds or rejects. This is a limit of the framework's candidate schema, not of the charter.
- **One browser test is flaky.** `study-progress` "manual refresh…" expects exactly two reads, and
  under the full parallel run an automatic refresh sometimes makes three. It passes alone. That
  page was not changed by this work.
