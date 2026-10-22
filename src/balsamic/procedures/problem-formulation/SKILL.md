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

- every section of the problem note written with substance: objective; knobs with ranges; observables; noise; constraints;
  confounders; open questions, which reads "none remaining" once settled;
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
   allowed), one section at a time when the researcher must answer first, and revise it as they answer.
2. Answer questions about the note as proposed edits (`problem_note_propose`), never a silent rewrite.
3. When every section is written, say so and ask the researcher to adopt the note (Adopt on [the note](#note)). The formulator
   then writes the charter and the researcher confirms it on `#note/charter`.
4. The moment the gate opens, say so once and ask how they want to proceed: by hand (you act on their requests) or with
   autopilot, which only they can switch on in the top bar.
