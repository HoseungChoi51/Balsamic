# Releases

Each phase of the [roadmap](../roadmap/README.md) ends in a release that Hoseung checks by using the app: a user
acceptance test, not a code review. A phase is complete when all its parts have merged. Phases may finish out of order;
a release holds everything merged by then and its notes say which parts of unfinished phases it already contains.

| Tag | What it marks |
|---|---|
| `phase-<n>` | The release that completes phase n, on the commit that adds its notes, `docs/releases/phase-<n>.md` |
| `track-l` | The release that completes track L (code libraries), on the commit that adds `docs/releases/track-l.md` |
| `baseline` | The code the eval baseline is measured on: `main` once J1–J4 have merged, before any part of Phases 3, 4, 5 or 7 (except K1–K3) merges. Those phases are compared with the evals run at this tag |

Tags are annotated (`git tag -a phase-1 -m "Phase 1: charter to results"`). A GitHub release page can be drafted from the
tag with the notes pasted in.

## The notes: `phase-<n>.md`

```markdown
# Phase <n>: <goal>, release phase-<n>

Tagged <date> on `main` at <commit>. <What a user can now do that they could not before, in one paragraph.>

## How to run it

The quick start of the root README at this tag, plus anything this release needs (a migration, a setting, a library to
install).

## Acceptance tests

- [ ] <part id>: <what to check>
  1. <step>
  2. <step>
  Expect: <what you should see>

## Live evals

<The eval runs this phase asks for, the command, the tag to run them at, and what to compare.>

## In this release

| Part | What changed | PR |
|---|---|---|

Also included, from phases not complete yet: <parts>.

## Known gaps

<The parts' "Not done" lists, condensed.>
```

The acceptance tests come from the "Acceptance test" section of each part's file in [readiness/](../readiness/README.md)
and from the phase file's Verification section. They are written for someone using the app: where to go, what to do,
what should happen, and no code.
