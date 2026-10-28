# Track L — Code libraries that last: versioned, kept and reused

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The review of how Balsamic builds, installs and records libraries (28 October 2026), which Hoseung accepted with all three of its recommendations (decisions 25–27) |
| Decisions it needs | 1 (the evaluator comes from the library), 9 (fixed generated files), 24 (the rule of two), 25–27 |
| Start after | Phase 4 (the coding box, H6's validation outside the box) and Phase 7 are released; L1 first |
| Status | Not started |

## Why

A coding workspace writes its library to `libraries/<problem id>/` (`agents/development.py` `generated_library()`), so
every campaign on the same problem writes to the same library. Each new workspace starts from the blank library generated
from the charter: the lab never commits what it installs, so the coding agent does not see the methods earlier campaigns
built, and writes them again. An install replaces the whole folder, and replacing the same library is not a change that
needs the researcher's confirmation (`agents/library_install.py` `install()`, `changed_packages()`). If campaign B delivers
a library without campaign A's methods, they disappear from the lab; if B's library changes the scoring function, A's
problem changes underneath it. Nothing ties a campaign to a version: a proposal records the method's name and settings
(`implementations/builtin.py`), runs record package versions, and nothing keeps the old version. The strategy library
carries ideas, not code: `library.apply` brings over a winner's mechanism and settings, and brought the code only through
the implementation service H8 retired. `docs/optimizer-plugins.md` already says reusable code lives in its own versioned
package, pinned by whoever uses it; the coding box does not follow it.

The design: each library is a long-lived product with its own history, and each campaign is one user of it. A campaign
builds on the library's latest version and leaves a new version behind. Nothing another campaign relies on is changed in
place.

```
                       library repository (one per library, L2)
                       v0.1.0 ── v0.2.0 ── v0.3.0 ──▶ tags; each with its methods, problems, tests
                          ▲          ▲          │
campaign A ── workspace ──┘          │          │ checkout of one version = the lab's libraries/<name>/
campaign B ── workspace (starts from v0.2.0, L3)┘
                                                ▼
install of v0.3.0:  keeps every method and problem a campaign uses (L1)
                    passes every earlier version's tests for what it keeps (L4)
                    reproduces the recorded runs of what it keeps (L4)
```

## Decisions (Hoseung, 28 October 2026)

| # | Decision | Settled | Parts |
|---|---|---|---|
| 25 | When a method's behaviour changes | It gets a new method name (`foo_v2`), and the lab keeps one installed version of each library. A change to a scoring function is a new problem id; the old problem stays. Installing several versions side by side, each in its own environment, was not chosen | L1, L4 |
| 26 | When method libraries split from problem libraries | When a second problem needs a method (the rule of two, decision 24). Until then one library per problem holds its scoring function and its methods, as decision 1 has it | L6 |
| 27 | Reusing an existing method under Explore | Needs no card: binding an installed method to a proposal (`implementation.bind_builtin`) and applying a strategy whose code is installed (`library.apply`) are reuse, which Explore allows. They take no coding time | L5 |

**The name on screen.** "Library" in the app is the strategy library of winning ideas (the Library page). A code library
is called a **package** on screen: the Packages page, "Builds on package bakery-search 0.2.0 (4 methods)". In code and in
this roadmap it stays a library.

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| L1 | An install keeps what campaigns use; every version is archived | An install can drop a method or problem another campaign uses; the replaced version is lost | — | S | 1 |
| L2 | One repository per library, with versions | A library has no history: the lab's copy is a folder each delivery overwrites | L1 | M | 2 |
| L3 | Workspaces build on the latest version | Each workspace starts from a blank library, so methods are written again | L2 | M | 3 |
| L4 | Tests accumulate; kept methods reproduce their recorded runs | A new version may break what it keeps: its tests are its own only | L2 | M | 3 |
| L5 | Reuse first | The lead opens coding work for a method the lab has; strategy entries carry no code | L2 | M | 3 |
| L6 | Method libraries split off when a second problem needs them | A method another problem uses stays governed by the first problem's library | L3, L4, L5 | L | 4 |

"A campaign uses" a method when a run of any campaign ran it or a proposal of any campaign is bound to it; it uses a
problem when a task of any campaign is on it. Usage is lab-wide, not the installing campaign's.

---

## Parts

### L1 — An install keeps what campaigns use; every version is archived

**Depends on:** nothing. **Size:** S.

**Read first:** `agents/library_install.py` (`Installer.prepare()`, `install()`, `_validate()`), `agents/library_validation.py`
(`verdict()`), `optimizers/plugins.py` (`origin()`).

**Today** an install of a library already in the lab moves the old folder aside and deletes it once the new one is in.
Nothing compares the new version's methods and problems with the old one's. A method the new version leaves out, or one
that now fails validation outside the box, is gone from the lab or refused for every campaign, even one whose runs and
proposals use it.

**Change**
1. Before anything is installed, the install compares the version it replaces (the methods and problems the installed
   package provides now) with the new one (the methods the validation outside the box listed and passed, and the problems
   its entry points name). A method or problem the new version drops, or a method it keeps that fails validation, which
   any campaign uses, refuses the install, naming each one and the campaigns that use it, and saying what to do instead:
   keep it, and give a changed method a new name (decision 25). Unused ones may go; the install records them as removed.
2. Every installed version is archived on the host with its files, its methods and problems, the install and the commit it
   came from (`<workspace>/library_archive/<name>/<version>/`). The version an install replaces is archived first when it
   is not yet (a library installed before L1, or the lab's own committed one).
3. The install record says what the version adds, keeps and removes (`methods_kept`, `methods_removed`,
   `problems_kept`, `problems_removed`, `archive`), and the notice and the install card say it in a line.

**Tests**
- An install that drops a method a run of another campaign used is refused before uv runs, naming the method and the
  campaign; the lab's copy is unchanged.
- The same for a problem a task uses, and for a used method the new version keeps but that fails validation.
- An install that drops an unused method installs, and records it as removed.
- Every install archives its version; the replaced version is archived before it is replaced.

**Done when** the tests pass.

### L2 — One repository per library, with versions

**Depends on:** L1. **Size:** M.

**Read first:** L1, `agents/own_session.py` (how the researcher's own session reaches a commit), `docs/optimizer-plugins.md`.

**Today** the lab's `libraries/<name>/` is a folder each install overwrites. L1's archive keeps copies, but nothing records
a library's history as one line of versions or lets a campaign name the version it used.

**Change**
1. Balsamic keeps one Git repository per library on the host (`<workspace>/library_repositories/<name>.git`, bare). Each
   install commits the version's files onto it, as Balsamic's own commit, with the source commit, workspace and campaign
   in its message, and tags it `v<version>`. L1's archived versions and a library the lab already has are imported as its
   first versions.
2. The lab's copy is a checkout of one tagged version: the install exports the tag into `libraries/<name>/` and checks
   the exported files against the tag before uv runs.
3. Each version is a `library_version` record: library, package, version, tag and commit, parent version, the source
   (campaign, workspace, submission, install), its methods and problems, and what it added and removed.
4. `GET /api/libraries` and `GET /api/libraries/<name>` list each library with its versions, its methods and problems,
   and which campaigns use each method (runs and bound proposals). The Packages page (a new page in the rail) shows them;
   it is a page of the lab, the same in every campaign.
5. The researcher's own coding agent (H3) clones the library from this repository (the workspace's own-session URL
   names it).

**Tests**
- Two installs of a library make two tagged commits in its repository, each a `library_version` with its parent; the lab's
  copy equals the tag's tree.
- A library installed before L2 and L1's archive are imported as versions once.
- The API lists versions, methods and the campaigns using each method.
- The Packages page shows a library's versions and methods (Playwright).

**Done when** the tests pass.

### L3 — Workspaces build on the latest version

**Depends on:** L2. **Size:** M.

**Read first:** `agents/development.py` (`generated_library()`, `_sync_one()`, `diff()`), `agents/development_runtime.py`
(`write_library()`), `agents/development_ticket.py` (`build()`), `agents/library_install.py` (`generated_changes()`).

**Today** a workspace's `libraries/<name>/` is generated from the charter, blank but for the problem, and the delivery is
reviewed against that.

**Change**
1. When a library of the generated library's name has an installed version, the workspace starts from its latest
   version's files instead (the tag's tree), and its record names the base: library, version, commit and methods.
   Decision 9 holds against the base: its `charter.json` and data are fixed; the base's other files are the agent's to
   extend.
2. The ticket lists the existing methods (id, name, what it fits) and the rule: keep every method; add new ones; a changed
   behaviour is a new method name; a changed scoring function is a new problem id; raise the version.
3. The delivery is reviewed as a change against the base version: the diff, and the install, name the base.
4. The workspace card says "Builds on package <name> <version> (<n> methods)".

**Tests**
- A second workspace on a problem whose library is installed starts from its latest version, the ticket lists its methods
  and the rule, and the diff is against the base.
- A workspace on a problem with no library starts from the generated library, as before.
- An edit of the base's fixed files is refused at install.

**Done when** the tests pass.

### L4 — Tests accumulate; kept methods reproduce their recorded runs

**Depends on:** L2. **Size:** M.

**Read first:** `agents/library_validation.py`, `optimizers/conformance.py` (`check()`), `execution/worker.py` (the
observation journal).

**Today** validation outside the box runs the new version's own tests and protected tests only. An earlier version's tests
can be deleted with the method they pinned, and nothing checks that a method the new version keeps still behaves the same.

**Change**
1. Validation runs, beside the new version's tests, every earlier version's tests the new version does not hold
   unchanged, and the protected tests of every earlier workspace of the library. A failure owned by a method the new
   version keeps refuses that method (so, under L1, the install when a campaign uses it); one owned by a removed method is
   ignored; one no method owns is the library's.
2. Kept methods reproduce their recorded runs: for each kept method a campaign ran, the validation replays the first
   evaluations of up to three of its recorded runs (the run's seed, settings and problem instance), feeding back the
   recorded results, and compares each proposal with the recorded one. A kept problem of the library evaluates the same
   recorded candidates to the same results. A difference refuses the method or the problem, naming the run and the
   evaluation where it diverged; under decision 25 the change belongs under a new name.
3. The install record and card say "the 6 kept methods reproduce their recorded runs", or name what did not.

**Tests**
- A new version that deletes an earlier test of a kept method and breaks the method is refused by that test.
- A kept method whose proposals changed for a recorded seed is refused, naming the run and the step; the same method
  unchanged passes.
- A kept problem whose objective changed is refused.

**Done when** the tests pass.

### L5 — Reuse first

**Depends on:** L2. **Size:** M.

**Read first:** `campaigns/method_catalog.py` (`catalog()`), `campaigns/mandates.py` (`CLASSES`), `agents/development.py`
(`create()`), the strategy library's `library.publish` and `library.apply`.

**Today** the method list shows every installed method, without the library or version it comes from. An agent can open a
coding workspace for a proposal whose method the lab already has. Binding an installed method is `implement` work, which
Explore refuses. A strategy entry records the idea and settings, not the code.

**Change**
1. The method list (`campaign_inspect` methods and the Algorithms list) names each method's package and version.
2. When an agent opens a coding workspace for proposals whose named method is installed and runs on a current task, it is
   refused with what to do instead: bind it (`implementation.bind_builtin`); reuse needs no coding time.
3. Binding an installed method and applying a strategy whose code is installed are reuse (a class of their own, `reuse`),
   which Explore allows without a card (decision 27).
4. `library.publish` records the winner's code: package, version and method. `library.apply` of an entry whose method is
   installed gives a proposal bound to it, ready to run; one whose method is not installed says so.

**Tests**
- The catalog names each library method's package and version.
- Opening a workspace for a proposal whose installed method fits is refused with the binding to make instead.
- Under Explore, binding an installed method is allowed; opening a workspace is still refused.
- A published entry records the code; applying it gives a bound proposal.

**Done when** the tests pass.

### L6 — Method libraries split off when a second problem needs them

**Depends on:** L3, L4, L5. **Size:** L.

**Read first:** L1–L5, `agents/development.py` (`submission_manifest()`), `agents/library_install.py`.

**Today** (after L5) a general method of one problem's library can be bound in a campaign on another problem; it stays in
the first problem's library, whose versions now decide a method another problem relies on.

**Change**
1. When a method of a problem library is bound or run on a task whose problem that library does not provide, Balsamic
   records that a second problem needs it (a `library_split` record: the method, its library, the problems using it) and
   tells the lead, whose method list shows the split as the next step.
2. The lead opens a split workspace (`implementation_workspace_create` with `split`), which needs a coding mandate like any
   workspace. Its ticket asks for a method library `libraries/<name>-methods/` providing the methods, with no problem, and
   a new version of the problem library without them that depends on it.
3. A split delivers two libraries in one commit. Their install is one step: both are validated outside the box, the
   method library takes over the methods the split names (and no others) from the problem library, L1 counts a method
   moved to the method library as kept, and L4's reproduction runs against every problem's recorded runs.
4. The Packages page shows a method library and the problem libraries that depend on it.

**Tests**
- Binding a method of library A on a problem A does not provide records a split need and tells the lead.
- A split delivery installs both libraries at once, the method moves, every recorded run reproduces, and both problems'
  campaigns keep running it.
- A delivery that takes over a method the split does not name is refused.

**Done when** the tests pass.

---

## Order and shared files

```
Wave 1  L1
Wave 2  L2 (L1)
Wave 3  L3 (L2) · L4 (L2) · L5 (L2)
Wave 4  L6 (L3, L4, L5)
```

| File | Parts |
|---|---|
| `agents/library_install.py` | L1, L2, L4, L6 |
| `agents/library_validation.py` | L4, L6 |
| `agents/development.py`, `agents/development_ticket.py` | L3, L5, L6 |
| `campaigns/method_catalog.py` | L5, L6 |
| `frontend/src/hypotheses/Implementations.tsx` | L1, L3, L4 |

## Risks

- **Usage is lab-wide.** A method one old campaign ran once is kept forever. That is the price of reproducibility
  (decision 25); an unused method can still be removed.
- **Replays cost compute.** L4 replays at most three runs per kept method and only their first evaluations; the time is
  charged to the workspace's go-ahead with the rest of the validation.
- **A method that reads the clock or the machine** cannot reproduce its runs. It is refused as changed; the coding agent
  is told to make it depend only on its seed.

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, Playwright for L2 and L3.
- Live: the release's UAT, two campaigns on the same problem, the second building on the first's package.
