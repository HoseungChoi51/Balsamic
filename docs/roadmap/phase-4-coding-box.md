# Phase 4 — The coding box: open inside, strict at the walls

| Item | Detail |
|---|---|
| Part of | [The Balsamic roadmap](README.md). Read its §0 (instructions), §1 (principles) and §2 (decisions) first |
| From | The design review §07 ("a coding-harness architecture") and §01 ("the coding agent is two hops away"). H1–H3 were the optional track H of the first version of this plan; their ids are kept |
| Decisions it needs | 8 (Pi stays the harness), 18 |
| Start after | F3 and F4 (Phase 1) for H4, H6 and H7; H1 and H5 can start at any time |
| Status | Not started |

## Why

The capable coder exists, but the agent the researcher talks to is not it. The implementation lead runs with Pi's
built-in tools off (`agent-harness/src/runtime.ts` L95–99: no shell, no edit, no test runner) and steers a separate Pi TUI
in Docker through a file bridge, so every instruction crosses two models and a file queue. The coder is tied to Pi by its
extension (`agent-harness/extensions/implementation.ts`: `campaign_checkpoint`, `campaign_submit`). Three routes build
code. And what the box delivers is trusted on its own report: the install copies the exact commit but runs none of its
tests (`agents/library_install.py` `prepare()`), and "ready" means the coding agent says conformance passed
(`agents/development.py` L88–89).

The design: the work ticket is the interface, and a small MCP server and CLI in the box replace the Pi extension, so
nothing between Balsamic and the coder depends on Pi's internals. Pi stays the harness (decision 8): a thin adapter runs it
headless or as a TUI, and another harness could use the same seam later. Inside the box the harness is free. The walls are code: an egress allowlist, limits and a deadline charged to the go-ahead, no protected fixtures, and
validation of the exact commit outside the box.

```
Lead / implementation lead                 Coding box (one container per library)
──────────────────────────                 ───────────────────────────────────────
writes the ticket (H4):           ──────▶  worktree: TASK.md, AGENTS.md, CLAUDE.md,
spec, acceptance tests,                    .balsamic/spec.json, libraries/<name>/ (F4)
budget, deadline                           Pi, headless or TUI (H2)
                                           balsamic-workspace MCP server + CLI (H1)
receives events, usage,           ◀──────  checkpoint · ask · evidence · check · submit
questions, submissions
validation outside the box (H6)   ◀──────  the exact commit
installs; runs start (Phase 1)             walls (H5): egress allowlist, limits, deadline
```

## Summary

| ID | Part | What it fixes | Depends on | Size | Wave |
|---|---|---|---|---|---|
| H1 | The workspace bridge as an MCP server and a CLI | Only Pi can talk to Balsamic from the container | — (after F4 is best) | M | 1 |
| H2 | A harness adapter, with Pi as the harness | Nothing runs the coder headless; the box is wired to Pi's TUI and extension | H1 | M | 2 |
| H3 | Bring your own session | The researcher cannot deliver from their own coding agent | H1, F2 | M | 2 |
| H4 | The work ticket | The coder gets a JSON dump; the implementation lead relays chat instead of reviewing work | H1, F4 | M | 2 |
| H5 | Walls in code | The public internet is open from the box; limits are fixed; there is no deadline | B2, decision 18 | M | 1 |
| H6 | Validation outside the box | The install trusts the coding agent's own report of its tests and conformance | F3, D2 | M | 1 |
| H7 | Commissions run as headless boxes | A second route builds code with restricted file tools and a 30-second runner | H4, H6 | L | 3 |
| H8 | One implementation route | Three routes, three logs, three cost paths | H7 | M | 4 |

---

## Parts

### H1 — The workspace bridge as an MCP server and a CLI

**Depends on:** nothing; after F4 is best. **Size:** M.

**Read first:** `agent-harness/extensions/implementation.ts`, `deploy/implementation-workspace/{Dockerfile,start.sh,network.sh}`,
`agents/development.py` (`receive()` L523–557, `_apply_event()` L559–598), `docs/pi-implementation-workspace-plan.md`.

**Today** the coding agent reaches Balsamic only through two Pi tools (`campaign_checkpoint`, `campaign_submit`) defined in
the Pi extension, which write files into `outgoing/events/` and read `incoming/results/`. No other harness can use them.

**Change**
1. A small CLI and stdio MCP server in the image, `balsamic-workspace`: `checkpoint`, `ask`, `submit <commit>`, `check`
   (runs the library's tests and `test_contract.py` and returns the counts for the report), `evidence` (only what
   `.campaign/evidence.json` names).
2. They write the same event files the extension writes; the file bridge stays the transport and the host side does not
   change.
3. The Pi extension keeps working; a parity test pins that both write the same events for the same inputs.

**Tests**
- The CLI and the extension write identical events for the same inputs; `receive()` accepts them.
- The MCP server lists the five tools.

**Done when** the tests pass.

### H2 — A harness adapter, with Pi as the harness

**Depends on:** H1, decision 8. **Size:** M.

**Change**
1. A thin adapter between the workspace and its harness: start it, map its event stream to the existing event kinds
   (`agent_start`, `agent_settled`, `message` with usage), stop it, and configure H1's MCP server for it.
2. Pi's adapter, in two modes: headless (`--mode json`) for agent-driven work, which H7 uses, and the tmux TUI for the
   researcher to attach to.
3. A harness setting per workspace, read by `start.sh`. It accepts only `pi` for now.
4. The seam is a placeholder for another harness (decision 8). Claude Code is not expected to replace Pi. If an adapter is
   ever added, it is opt-in per workspace, on the researcher's own credentials mounted read-only, and the egress allowlist
   (H5) adds only its model endpoint.

**Tests**
- A fake harness binary's stream maps to the workspace record, in both modes.
- A recorded Pi `--mode json` stream maps to the workspace record: its events and its usage.
- A harness setting other than `pi` is refused with the text.
- Host and private networks stay blocked.

**Done when** the tests pass, and J4 runs on Pi's headless mode with its result recorded beside the Phase 2 baseline.

### H3 — Bring your own session

**Depends on:** H1, F2. **Size:** M.

**Change**
1. The researcher works in their own coding agent on the exported project (F2) or on the workspace's branch, and runs
   `balsamic-workspace submit` from their machine.
2. It sends the commit as a git bundle to a new endpoint for that workspace, authenticated with a per-workspace token shown
   on the workspace card.
3. The host takes the same path as `capture_submission()`: the exact commit, never loose files. Validation (H6), install,
   binding and runs do not care who wrote it.

**Tests**
- A bundle submitted from outside the container installs and binds like one from inside.
- A wrong token, or a bundle without the commit, is refused.

**Done when** the tests pass.

### H4 — The work ticket

**Depends on:** H1, F4. **Size:** M.

**Read first:** `agents/development.py` (`create()` L268–326, `_sync_one()` L449–470, `DEVELOPMENT_INSTRUCTIONS` L726–779),
`agents/development_runtime.py` `prepare()` L119–175, `implementations/bridge.py` `check_self_contained()` L334, the
`implementation_workspace_*` tools in `agents/tools.py` (schemas from L360, handlers near L955), `agents/models.py`
(`PAGE_OBJECTIVES["implementation_lead"]`).

**Today**
- The coder's brief is generated from the proposals and generic instructions (F4 makes it the generated library and a
  shorter brief).
- The implementation lead has no shell, edit or test tools. It steers the coder with chat messages
  (`implementation_workspace_message`) and reads checkpoints; `implementation_workspace_inspect` shows state, progress,
  questions and submissions, but no diff.

**Change**
1. A ticket record, `development_ticket`: the served proposals (title, mechanism, the `METHODS` key), the charter revision,
   acceptance criteria as runnable tests (F1's and F3's generated tests, plus any the implementation lead adds), protected
   acceptance tests (kept on the host, H6), the compute and model budget, the deadline (H5), and the house rules.
   `check_self_contained()` checks it, as it checks a commission's spec today.
2. `prepare()` writes it into the worktree beside F4's library: `TASK.md` (the ticket, readable), `AGENTS.md` and
   `CLAUDE.md` (the same house rules for any harness: what to build, how to run the tests, how to submit, what not to
   touch), and `.balsamic/spec.json` (machine-readable). Protected tests are never written there.
3. The implementation lead writes the ticket (`implementation_workspace_create` gains `ticket`) and reviews the result:
   `implementation_workspace_inspect` gains the submission's diff summary against the generated base (files and lines
   changed, generated files touched) and H6's results.
4. `implementation_workspace_message` stays for answers to the coder's questions; relaying progress stops (A4 routes
   checkpoints as notices).
5. `DEVELOPMENT_INSTRUCTIONS` keeps only what `AGENTS.md` does not say.

**Tests**
- `prepare()` writes the four files for a ticket; a second `prepare()` keeps the coder's edits.
- A ticket without acceptance tests is refused by `check_self_contained()`.
- `implementation_workspace_inspect` returns the diff summary.

**Done when** the tests pass, and J4 re-run on the ticket route is recorded beside its Phase 2 baseline.

### H5 — Walls in code

**Depends on:** B2 (the deadline is charged to the consent; to the mandate after R3), decision 18. **Size:** M.

**Read first:** `deploy/implementation-workspace/network.sh`, `start.sh`, `Dockerfile`, `agents/development_runtime.py`
(`start()` L183–206, the credential copy L111–116), `agents/development.py` (`create()`: the consent at L298 and L320;
`DEVELOPMENT_INSTRUCTIONS` L776: "This session has no programming wall-clock deadline").

**Today**
- Egress: `network.sh` rejects private, link-local and CGNAT ranges and new IPv6 connections; the rest of the internet is
  open.
- Limits are fixed: `--cpus 4 --memory 8g --pids-limit 1024`, a read-only root, a 2 GB `/tmp`.
- No deadline: a workspace runs until it is stopped.
- The host copies one provider's entry of its Pi `auth.json` into the box.

**Change**
1. An egress allowlist (decision 18): `network.sh` resolves the allowed hosts at start (the harness's model endpoint, the
   package index or its mirror) and accepts only those and DNS. The list is on the workspace record and its card. A
   ticket may name more hosts; they are part of what the researcher approves.
2. A wall-clock deadline per workspace, from the ticket (default: the consent's `wall_seconds`). At the deadline the
   container is paused, not removed, the coder's last state is recorded, and the lead and the researcher are told once.
   Going on is a new go-ahead. Wall time is charged to the consent (the mandate after R3).
3. Limits come from the ticket, within ceilings the researcher sets (CPUs, memory); no GPU unless the ticket names one.
4. The one-provider credential stays the only secret in the box, and is documented as such; a harness added later under
   decision 8 follows the same rule. Protected fixtures are never mounted (H6 keeps them outside).

**Tests**
- The rule generator allows the listed hosts and rejects another public host (a unit test of the generated rules; a
  network-namespace test where the CI allows it).
- A workspace past its deadline is paused and the lead is told once.
- Limits above the researcher's ceiling are refused.

**Done when** the tests pass, and Hoseung checks on a live workspace that it can install from the package index and reach
its model, and cannot reach another host.

### H6 — Validation outside the box

**Depends on:** F3, D2 (the generated contract tests and `check_function`). **Size:** M.

**Read first:** `agents/library_install.py` (`prepare()` L80–118, `automatic()` L121, `install()` L171), `agents/development.py`
(the report model near L62 and its check at L88–89; `validate()` L636–670, the protected validation of commissions),
`optimizers/conformance.py`, `execution/isolation.py`, `implementations/runtime.py` (the bwrap sandbox).

**Today**
- The install copies the exact commit's files and checks them against what was submitted, but runs none of the
  library's tests. "Ready" requires every method's conformance "passed" as the coding agent reports it.
- Protected validation exists for commissions (`implementation_workspace_validate`), not on the library route.

**Change**
1. Before an install counts (Balsamic's or the researcher's), the host runs on the exact commit's files, in the worker
   sandbox with no network: the library's own tests, the generated contract tests (F3), conformance (`check` for
   optimizer_v1 methods, `check_function` for function methods) and the ticket's protected acceptance tests, which the
   box never saw.
2. The install record carries the host's results beside the coder's report. A method reported as passing that fails on
   the host is not installed; the install names the failing test, and the coder gets it as a result file (one notice).
3. Methods that pass are installed when another fails, and the install lists both, as "ready_with_limits" does today.
4. Protected acceptance tests live with the ticket on the host. The coder sees their names and outcomes, never their
   content.
5. Validation compute is charged to the consent (the mandate after R3).

**Tests**
- A library whose reported conformance passed, with a method that fails `check()` on the host, is not installed, and the
  failure is named.
- Protected tests run outside the box and never appear in the worktree or the coder's result files.
- A library that passes everything installs as before.

**Done when** the tests pass, and the invariant "a delivered library's tests and conformance passed" is `code` (I1).

### H7 — Commissions run as headless boxes

**Depends on:** H4, H6. **Size:** L.

**Read first:** `implementations/bridge.py` (the commission L260–275, the revalidation L315–325), `implementations/service.py`
(the job, `model_call()` L348–357), `agents/implementation.py`, `agents/extensions.py` (`GRANT_ROLES` L16), `agents/tools.py`
(the grant tool set L476, `_files()` from L1170: 256 KiB per file, `workspace_run` at most 30 s), `agents/development.py`
`validate()` L636–670.

**Today** three routes build code:
- the coding workspace: a Pi TUI in Docker, the file bridge, the library contract;
- implementation commissions: builder, test designer and validator roles with restricted file tools, a sandboxed Python
  runner of at most 30 s per call, and protected tests written by the test designer;
- the validation of a workspace's submission through that same service.

**Change**
1. A commission (`implementation.commission`, `evaluator.commission`) opens a box in headless mode: H2's adapter runs the
   harness non-interactively on a ticket (H4), behind the same walls (H5), and its result is a submission like any other,
   validated by H6.
2. The test designer's job survives as the author of the ticket's protected acceptance tests, written outside the box.
3. One log (the workspace timeline), one cost ledger (the consent or mandate), one contract (the library).
4. Old job records stay readable; no history is migrated.

**Tests**
- A commission opens a headless workspace with a ticket and ends with an install through H6.
- A commission's protected tests run outside and are never in the box.
- A commission's compute is charged once.

**Done when** the tests pass, and J4 run headless is recorded.

### H8 — One implementation route

**Depends on:** H7. **Size:** M.

**Change**
1. The builder, test designer and validator grant roles leave `ROLES` (`agents/models.py` L18–20), `GRANT_ROLES`,
   `GRANT_INSTRUCTIONS` (`agents/tools.py` L90) and the grant tool set; the agent loop of `implementations/service.py` is
   removed, and the bridge's commission path calls H7.
2. `docs/implementation-service.md` describes the one route; the open items of `docs/pi-implementation-workspace-plan.md`
   are closed or moved.
3. The method catalog's next actions (`campaigns/method_catalog.py`) name the one route.

**Tests**
- `tests/balsamic/test_layering.py` lists the removed modules in `REMOVED`.
- Tests of the removed route are removed together with the code they test; the behaviours that remain are tested on the
  new route.

**Done when** the tests pass and one route builds code.

---

## Order and shared files

```
Wave 1  H1 · H5 · H6 (after F3, D2)
Wave 2  H2 (H1) · H3 (H1, F2) · H4 (H1, F4)
Wave 3  H7 (H4, H6)
Wave 4  H8 (H7)
```

| File | Parts |
|---|---|
| `agents/development_runtime.py` | H2, H4, H5 |
| `agents/development.py` | H4, H5, H6 (and A1, A4, B3, B5, F4 in Phase 1) |
| `deploy/implementation-workspace/*` | H1, H2, H5 |
| `agents/library_install.py` | H6 (and A1, B4, E2, E5, F4) |
| `agent-harness/extensions/implementation.ts` | H1 |
| `implementations/bridge.py`, `implementations/service.py` | H7, H8 |

## Risks

- **The allowlist breaks installs** when a package pulls from another host; the ticket names extra hosts, and the
  refusal names the host that was blocked.
- **A paused workspace** at its deadline must resume where it stopped; the harness's session lives in `/work/sessions`,
  which a pause keeps.
- **Validation outside costs compute;** it is charged to the go-ahead, and a validation larger than the plan asks again.
- **Retiring a route** (H8) removes the restricted service the protected tests came from; H7 keeps their authoring
  outside the box before H8 removes anything.
- **Credentials:** only the harness's one provider credential enters a box, read-only (decision 8).

## Verification

- `GRATING_LLM_DISABLED=true uv run pytest -q`, `(cd agent-harness && npm test)`.
- Live: J4 before the phase (Phase 2), after H2 (Pi headless), after H4, and after H7.
