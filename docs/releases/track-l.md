# Track L: code libraries that last, release track-l

Track L completed on 28 October 2026, when L6 merged (`88b8513`). This release is the commit on `main` that adds these
notes. It holds everything merged by then, all seven phases included.

What changes for the researcher: each code library a coding workspace builds is now a long-lived package with its own
history. An install can no longer take away a method or problem any campaign uses (L1). Each library has its own Git
repository on the host, every install is a tagged version, and the new **Packages** page lists them (L2; "Library" stays the
strategy library). A new coding workspace starts from the latest installed version instead of a blank library (L3). A new
version is checked against every earlier version's tests, and each method it keeps must reproduce its recorded runs, so a
changed behaviour has to take a new name (L4, decision 25). Reusing an installed method comes before writing a new one, and
needs no go-ahead under Explore (L5, decision 27). When a second problem needs a problem's method, Balsamic proposes
splitting it into a method package of its own (L6, decision 26).

## How to run it

```bash
git fetch origin && git checkout track-l    # or the commit named above, until the tag exists
uv sync --extra dev
(cd agent-harness && npm ci && npm run build)
(cd frontend && npm ci && npm run build)
scripts/start          # or scripts/start --fake for a scripted lead, no model
```

Nothing to migrate. The first time the lab lists packages or installs a library it already had, it imports what it had
(the lab's copy, and any L1 archive) as that library's first version. Coding workspaces need `development_enabled`, and
validation outside the box needs bubblewrap, as in Phase 4.

## Tag to create (Hoseung)

The cloud sessions cannot push tags. Please create:

```bash
git tag -a track-l <this release's commit> -m "Track L: code libraries that last"
git push origin track-l
```

## Acceptance tests

Use a lab with coding workspaces on and two campaigns on the same problem (A and B), plus a third campaign on another
problem for L6. Each item links to its part's full steps.

### End to end

- [ ] **A package that grows instead of starting over.**
  1. In campaign A, let a coding workspace deliver a package with two methods, and run one of them.
  2. In campaign B, approve a coding workspace. Its card says "Builds on: package <name> <version> (2 methods)", and its
     TASK.md says what it builds on and what to keep.
  3. Have it deliver a version that changes how A's method searches but keeps its name. The install is refused, naming the
     recorded run and the evaluation where it differs.
  4. Have it deliver the change under a new name. It installs; the card says the kept methods reproduce their recorded runs.
  5. On the Packages page the package shows both versions, each method with the campaigns that use it.

### The parts

- [ ] **L1: an install keeps what campaigns use.** A version without a method another campaign ran is refused, naming the
  method and the campaign; one that keeps it installs and says how many methods it keeps. [L1](../readiness/L1.md#acceptance-test)
- [ ] **L2: one repository per library, with versions.** The Packages page lists each package with its versions newest
  first (commit, what changed, where it came from) and the campaigns using each method, the same from any campaign; a
  package committed with the lab is imported. [L2](../readiness/L2.md#acceptance-test)
- [ ] **L3: workspaces build on the latest version.** A second campaign's workspace builds on the installed version, its
  TASK.md lists the existing methods, and the review's diff is against that version. [L3](../readiness/L3.md#acceptance-test)
- [ ] **L4: tests accumulate; kept methods reproduce their runs.** A changed method under a kept name is refused with the
  run and evaluation; under a new name it installs. [L4](../readiness/L4.md#acceptance-test)
- [ ] **L5: reuse first.** The Algorithms list names each method's package and version; under Explore the lead binds an
  installed method without a card; a published winner applied in another campaign comes back bound to its method.
  [L5](../readiness/L5.md#acceptance-test)
- [ ] **L6: method packages split off.** Binding A's method in the campaign on another problem tells the lead and shows the
  split on the method list; the approved split workspace delivers a method package, and A's package's new version depends
  on it, with runs in both campaigns still using the method. [L6](../readiness/L6.md#acceptance-test)

## In this release

| Part | What changed | PR |
|---|---|---|
| — | Track L added to the roadmap with decisions 25–27 and a readiness file per part | #102 |
| L1 | An install keeps every method and problem any campaign uses; what it keeps and removes is on the install card | #103 |
| L2 | One Git repository per library, each install a tagged `library_version`; the Packages page | #104 |
| L3 | A workspace starts from the latest installed version; the ticket says what to keep; the review diffs against it | #105 |
| L4 | Earlier versions' and workspaces' tests run on a new version; kept methods and problems replay their recorded runs | #106 |
| L5 | Package and version on the method list; a workspace for an installed method is refused with the binding to make; binding and applying are reuse, allowed under Explore; library entries record their code and apply bound | #107 |
| L6 | A second problem's need records a split and tells the lead; a split workspace; the two libraries install as one step; dependencies on the Packages page | #108 |

New invariants: INV-L1-1, INV-L1-2, INV-L2-1, INV-L2-2, INV-L3-1, INV-L4-1, INV-L4-2, INV-L5-1 to INV-L5-3, INV-L6-1 to
INV-L6-3 (`docs/invariants/L<n>.md`).

## Known gaps

- Usage is lab-wide: a method one old campaign ran once is kept for good. An unused method can still be removed (L1).
- Replays cover the first 8 evaluations of up to 3 recorded runs per kept method; a change that shows only later is caught
  by tests, not replay. A method that reads the clock or the machine cannot reproduce and needs a new name for any change (L4).
- A proposal an agent applies from the library still needs its concept review before it runs (L5).
- A split's code is written by the coding agent; Balsamic checks and installs it but does not move code itself. uv's
  handling of the problem package's path dependency is checked by the real `uv lock` at install, not by the tests (L6).
