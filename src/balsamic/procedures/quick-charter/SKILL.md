---
name: quick-charter
description: Writing the charter of a simple problem yourself, for the researcher to confirm in one step.
metadata:
  roles: lead
---

# The quick path: the charter of a simple problem

On the full path (procedure problem-formulation) you write the problem note, the researcher adopts it, the formulator writes
the charter and the researcher confirms it. For a simple problem you write the charter yourself with `charter_write`, the note
is read from it, and the researcher's one action is to confirm it: confirming accepts the assumptions it lists and installs its
tasks.

## When

Take the quick path when the researcher's words state the problem: what is chosen, what is measured and in which direction, and
every value or the data it comes from; no documents or code to read first; the objective is computed by the campaign's installed
problem or in a few lines from the given data; and at most two decisions are left open. Otherwise take the full path.

The code checks every `charter_write` (its result's `quick_path`): the problem was given in the conversation; the evaluator is
installed, or declared with notes saying what it computes, white box and with no fidelity fields; it is deterministic; at most 3
decision variables and 10 inputs; no blocking finding of yours left after 3 writes; at most two questions, in one round. When one
fails, the quick path ends: your charter is kept, the note goes to the full path with its sections written from it, and after
Adopt the formulator revises it. Tell the researcher in one line why, then go on with procedure problem-formulation. The
researcher can choose the full path too. Once the quick path ended or the note is adopted, `charter_write` is refused.

## Writing the charter

Write a whole charter in one `charter_write` call; it returns the computed values and the findings, so do not check first.

- **Every value once, from the researcher.** Each value is a quantity: an input with its `value`, `units` (`"1"` for a pure
  number) and `origin`. A value the researcher gave has origin `source` and a `citation`: list it in `citations` as
  `{id, source: "the researcher's message", quote}` with their words. A value you chose has origin `assumed` and a `note` saying
  why. Never invent a value the problem turns on: ask, or assume a conventional one with a note.
- **No arithmetic.** A value that follows from others is `role: "derived"` with an `expression` over their names. Quote
  numbers only from what `charter_write` or `charter_read` returned.
- **Data as given.** A list of numbers (durations, due times, weights) is one quantity of kind `data` whose value is the list,
  in the researcher's order.
- **Decision variables.** An order of items is a `permutation` whose shape is the count of items (a quantity, such as
  `["n_jobs"]`), and whose `meaning` says what an entry indexes. A number to choose is `continuous` with `lower` and `upper`; a
  choice from a list is `discrete` with its `values`; a yes or no per element is `binary`. A variable's bounds belong on the
  variable, not in constraints.
- **Objective.** `name`, `direction`, `units`, and a `definition` that says exactly what is computed and how it is aggregated.
  Other numbers worth recording are `metrics`.
- **Constraints.** `quantities` (a test on the values), `linear`, `design` (an expression over the decision variables, checked on
  every candidate), `outcome` (an expression over the objective and metrics), `evaluator`, or `qualitative` (words only).
- **Evaluator.** When the campaign's tasks run on an installed problem that computes exactly this, bind it (`kind:
  "installed"`, its `problem_id`, every field of its configuration and fidelity mapped to a quantity). Otherwise declare one:
  `kind: "declared"`, a new lowercase `problem_id`, every input it needs mapped in `configuration`, and `notes` saying what it
  computes from them. `deterministic` is false only when evaluations of one design differ. Leave `access` unset.
- **Instances.** At least one: `{name, split: "development"}`.
- **Texts.** `text` states the problem in a few sentences and `summary` in one, every value as `{name}` (or `{name:.0f}`),
  never typed.
- **Confounders.** Give the note's confounders with `confounders` (`{text, items}`): what besides the design could move the
  score (fidelity, seeds, the instance), or "None" with the reason.

Resolve each blocking finding from the researcher's words and write again; never silence one by inventing a value. Do not write
the note's sections on this path: the note is read from the charter.

## Questions and assumptions

Ask only what changes what is optimized, which designs are allowed or under which conditions, and the words leave open: at
most two questions, together, in `charter_write`'s `questions` (two to four options each, the one you recommend first). Decide
everything else as an assumption with a note. The researcher answers on the Charter tab; their answers start your next turn.
Read the charter then (`charter_read`: they may have changed values) and write it again from the answers. A question they
left unanswered you decide yourself: record it as an assumption naming the question and drop the question. A second round of
questions, or a third question, ends the quick path.

## Your reply

In a few lines: what the charter states (what is chosen, the objective, the evaluator), one line per assumption (confirming
accepts it), your questions if you asked any, and the link to confirm it: [Charter](#note/charter). Nothing is adopted on
this path. Once the researcher confirms, the gate opens; from then on the charter changes only through them, on the Charter tab.
