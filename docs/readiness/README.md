# Readiness log of the roadmap's parts

Each part of the [roadmap](../roadmap/README.md) records what it did in a file of its own, `docs/readiness/<id>.md` (for
example `A1.md`), written in the part's PR. No page lists them, so parts built in parallel never edit the same file:
this directory is the list. The log from before the roadmap, Parts A to S, stays in
[lead-agent-readiness.md](../lead-agent-readiness.md).

A file follows the format of those Parts, under the part's id and its name in the roadmap:

```markdown
# A1 — Install without a false "needs confirmation"

State: implemented and tested (PR #3, 2026-10-27); the live check is Hoseung's.

## What was wrong

Layer: mandate. The lead started a run the request did not cover.
Invariant: INV-01 (updated).

## What changed

| Change | Where |
|---|---|

## Checked

## Not done

## Acceptance test
```

The State line says how far the part got: implemented and tested, live, or checked live, with its PR and date. A later part
that changes what an earlier one did says so in its own file and leaves the earlier file as it is.

The two lines after "What was wrong" come from [incident triage](../incident-triage.md). `Layer:` names the first layer
that fits the failure, one of `mandate`, `budget`, `evidence`, `prompt` and `UI`, then the reason in a sentence.
`Invariant:` names the register rows ([invariants](../invariants.md)) the part adds or updates, such as `INV-07` or
`INV-07, INV-11`. When none fits, either line says `none` and why: a part that fixes no failure, or a defect in code
that already held the guarantee. Files written before triage (A1, A3, I1) have no such lines; `tests/test_readiness.py`
checks the lines wherever they appear.

The acceptance test is written for someone using the app, not reading the code: where to go, what to do, and what should
happen, with no commands beyond starting the app. Each phase's release checklist ([releases](../releases/README.md)) is
built from these sections. A part that changes nothing a user can see writes "None:" and the reason, and says how the
change shows instead. Live evals go here too, with the command and what to compare.
