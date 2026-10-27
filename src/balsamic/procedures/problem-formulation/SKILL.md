---
name: problem-formulation
description: Writing the problem note and taking it through the problem-definition gate.
metadata:
  roles: lead
---

# Problem formulation

## The gate

No proposals (`research.generate`, `hypothesis.create`), allocations, interventions, runs or autopilot until the problem is
fully defined:

- every section of the problem note written with substance (objective; knobs with ranges; observables; noise; constraints;
  confounders; open questions, which reads "none remaining" once settled) or skipped with the researcher's agreement;
- the note adopted at its current revision;
- the charter confirmed;
- the tasks installed.

The bus refuses gated commands until then. `campaign_inspect.definition` says what is missing (`ready`, `step`, `missing`), and
the state block at the top of each turn says where the gate stands. Check it before you suggest adopting, before you act on a
request for proposals, and before you mention autopilot.

When the researcher asks for proposals or autopilot while the gate is closed, do not start: name the missing sections or step
with its page, and offer to write what is missing now. Never pad a section to pass the gate; a section you cannot write from
what you know becomes a question to the researcher.

## Writing the note

1. Write it with `problem_note_draft` (objective, knobs, observables, noise, constraints, confounders, open questions; LaTeX
   allowed), one section at a time when the researcher must answer first, and revise it as they answer. An order or a ranking
   is a permutation knob (each item once, no range); do not encode it as discrete values.
2. Answer questions about the note as proposed edits (`problem_note_propose`), never a silent rewrite.
3. When every section is written or skipped by agreement, say so and ask the researcher to adopt the note (Adopt on [the note](#note)). The formulator
   then writes the charter and the researcher confirms it on `#note/charter`.
4. The moment the gate opens, say so once and ask how they want to proceed: by hand (you act on their requests) or with
   autopilot, which only they can switch on in the top bar.

## An installed problem

When the campaign's tasks run on an installed problem (campaign_inspect.tasks; the setup's request names its package and example),
the package states the problem, and the researcher is not the source of what it states. Write every section yourself from it, in
one `problem_note_draft`: the objective as the package computes it, the decision variables and the fixed inputs with their values,
the objective and recorded metrics, noise (deterministic or not, and the fidelity a score belongs to), the constraints, the
confounders you see, and open questions. Then decide whether anything needs the researcher: only what their own question leaves
open and the package does not state. Each such question is an item of open questions, with the answer you suggest; when there is
none, open questions reads "None remaining" with no items, and you say in one line that nothing is missing and the note is ready
to adopt. Do not propose skips and do not ask the researcher to confirm what the package states. At Adopt the formulator is
handed the installed problem with the note and builds the charter on it.

## Skipping a section

A section other than the objective need not be written when the confirmed charter already states it or it does not apply to
this problem. The researcher should not have to work that out alone: you make the case, briefly, and they agree. Sort each
unwritten section:

- Stated by the confirmed charter: propose basis `charter` with the paths that state it (knobs: variables and the input
  quantities; observables: objective and metrics; constraints: constraints; noise: `evaluator.deterministic`; open questions:
  every charter question answered).
- Does not apply here: propose basis `not_applicable` and say why.
- Matters and the records do not settle it: ask, at most two short questions each with the answer you would suggest, and write
  the section from the answer.

Confounders are seldom settled by a charter: name the ones you see (solver fidelity, seeds, budgets, the instance split) and
write them unless the researcher says none matter. Before the note is adopted, writing a short section costs nothing, so write
it; after adoption a new revision reopens the note for adoption and the charter for confirmation, so skip what the confirmed
charter already says instead of copying it into the note.

Propose all the skips in one `problem_note_skip` call, then reply with one line per section (why it need not be written, and
what agreeing confirms) and your questions, if any. The researcher agrees on the card; a declined skip means you write that
section with them. Never propose a skip to get past the gate. The state block lists the sections skipped and the skips that
wait for the researcher.
