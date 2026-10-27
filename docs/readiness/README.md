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

## What changed

| Change | Where |
|---|---|

## Checked

## Not done
```

The State line says how far the part got: implemented and tested, live, or checked live, with its PR and date. A later part
that changes what an earlier one did says so in its own file and leaves the earlier file as it is.
