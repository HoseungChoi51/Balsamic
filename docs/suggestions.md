# Suggestions: why the lead reasons worse than Codex or a Claude Project, and what to change

| Item | Detail |
|---|---|
| Target | `kc-ml2/balsamic`, branch `workspace-rebuild` |
| Date | 2026-10-26 |
| Evidence | The two lead sessions in `runs/dev/pi`: `lead_2d-gratnig` (112 turns, 368 model calls) and `lead_token-sharing` (40 turns), with a third, `lead_tk-share` (7 calls), in the per-role figures; every agent's `events.jsonl` for the comparisons (Appendix A). Read on 2026-10-26 while the sessions were still running, so a re-run gives slightly larger counts |
| Status | Suggestions. Reviewed on 2026-10-26 against the code and the records; the corrections are in place below. Q1 is obsolete, Q3 is answered (measured), and S1 is Hoseung's. The researcher's compute thresholds (R6, S6) are implemented, and Balsamic offers the thinking levels Pi offers (S1, 2026-10-27); nothing else here is |

The same model answers better in Codex or in a Claude Project than as Balsamic's lead. The model is not the difference;
the conditions it works in are. In order of impact: the lead does no thinking at all; it forwards work rather than doing
it; its context is mostly snapshots of bookkeeping; bookkeeping wakes it far more often than the researcher does; its rules
and its evals reward doing less; and it cannot compute or check anything by itself.

## Summary

| ID | What | Problem it fixes | Size |
|---|---|---|---|
| S1 | Thinking on for the lead, and a guard against it going off silently | Every lead call runs without reasoning (R1) | S |
| S2 | Coding-workspace checkpoints go to whoever started the workspace, as notices | A third of the lead's turns are checkpoint relays, labelled as requests (R4) | S |
| S3 | A smaller context: slimmer reads, superseded snapshots collapsed, earlier compaction, working notes | 241k tokens per call, three quarters of it stale JSON (R3) | M |
| S4 | The lead reads evidence first-hand; only actions stay routed (D1 unchanged) | The researcher diagnoses failures the lead forwards (R2) | M |
| S5 | Goals instead of style and scope rules in the lead's contract | Literal and narrow readings the researcher corrects (R5) | S–M |
| S6 | One-step Python for the lead | The lead never computes; it estimates or says it cannot know (R6) | S–M |
| S7 | Evals that grade quality, and a comparison with Codex | The suite checks only compliance, so every change pushed toward doing less (R5) | M |

---

## 0. Instructions for Claude Code (read first)

1. Read §2 (principles) and §3 (decisions) before any suggestion; the principles of `docs/harness-update-plan.md` §2 hold too.
2. If a decision (Q1–Q8) the suggestion depends on is still open, ask Hoseung before implementing.
3. Line numbers refer to the working tree on 2026-10-26 (`e931cc2` plus uncommitted changes); later commits moved some, `tools.py` among them, so find code by function name.
4. The lead's instructions are under the prompt-size ratchet (`tests/test_harness_contract.py`, `LEAD_WORDS` + 10%). S5 replaces text rather than adding it.
5. Live evals on the dev profile's default provider (Centinels) need no cost approval; on any other provider, ask first.
6. Judge every suggestion with the eval suite: the existing compliance scenarios must not regress, and the S7 quality scenarios must improve. Record the reasoning tokens and the context size per lead call in each run's summary.
7. When a suggestion is done, add a Part to `docs/lead-agent-readiness.md` in its existing format (What was wrong / What changed / Checked / Not done).

---

## 1. What was measured

### 1.1 Findings

| ID | Problem | Evidence |
|---|---|---|
| R1 | **The lead does almost no thinking.** All 485 lead calls in both sessions ran at thinking level `off`: on average 2 reasoning tokens and 173 output tokens per call. Every other role on `gpt-6.1-sol` is off too. The DeepSeek roles at `max` reason 546 (experiment operator) to 3,800 (cross-domain explorer) tokens per call. `off` is a label: Pi then sends no effort, and `gpt-6.1-sol` cannot be switched off (Centinels refuses `none` and `minimal`), so it runs at the server's default effort and decides how much to reason. On a hard prompt it reasoned 1,309 tokens with no effort sent and 2,249 at `high`; on the lead's steps it chose about none. | The `centinels` models in `~/.pi/agent/models.json` have no `"reasoning": true`. Pi then sends no `reasoning_effort` (`pi-ai/dist/api/openai-completions.js` L714; Centinels' URL does support it, L1265) and offers only `off` (`agent-harness/src/runtime.ts` `levels()`), so the Models page refuses any other level (`agents/controller.py` L271). Started with the move of the dev default to Centinels on 2026-10-20 (`864f31c`); before, the lead ran at `xhigh` (`LEGACY_MODELS`, `controller.py` L40). |
| R1b | Even with reasoning on, chat completions drops the reasoning between tool calls; each step of a turn starts its thinking again. Codex uses the Responses API, which carries reasoning across a tool loop. | Pi's Responses provider asks for `reasoning.encrypted_content` and sends it back (`pi-ai/dist/api/openai-responses.js` L276, `openai-responses-shared.js` L414–430); the dev profile uses `openai-completions`. Centinels serves `/v1/responses` and the carry-over works (Q3, measured). |
| R2 | **The lead forwards work instead of doing it.** 81 `page_agent_message` calls; a median of 3 tool calls per turn; 27 turns were exactly `implementation_workspace_inspect` → `page_agent_message` → `yield_work`. The lead never ran `analysis_run` (one call by any agent, the experiment operator) and no agent ever ran `source_search`. Each hand-off loses context: the researcher had to diagnose the failures ("The builder cannot read campaign records such as artifact_pi_tool_ab23…"; "write each mechanism out in full ... up to 20,000 characters") after the lead had forwarded "try again" three times without looking for a cause. | `STANDING_OBJECTIVE` (`agents/models.py`): "Carry out what the researcher ... asks for, report the result, and wait"; `LEAD_CONTRACT` (`agents/tools.py` L79): "Hand page work to them"; `LEAD_EXCLUDED_OPERATIONS` (`tools.py` L43–47, decision D1). |
| R3 | **The context is mostly snapshots of bookkeeping.** In `lead_2d-gratnig` the median request carried 241k tokens (max 471k of a 500k window). `campaign_inspect` results are 39.5% of the session (22 calls) and `implementation_workspace_inspect` results 35.0% (35 calls); each new snapshot supersedes the last, and the old ones stay. The last `campaign_inspect` was 95,520 characters: 58,270 of them the agent team (coding workspaces 36,620, agents 12,022, aliases 4,158); the problem, the proposals and the methods about 31,000; no results. The lead's own words outside its replies: 829 characters in 112 turns, so it keeps no working notes. The lead is not the only heavy one: the experiment operator's median request is 404k tokens (DeepSeek, 170 calls) and the implementation lead's 222k. | `PiTools.inspect()` (`tools.py` L843); compaction starts only at window − `reserveTokens` = 483,616 tokens (`pi-coding-agent/dist/core/compaction/compaction.js` L176; `OVERRIDES` in `runtime.ts` L17, one setting for every role); one compaction in the session. |
| R4 | **Bookkeeping wakes the lead, not the researcher.** Of 112 turns in `lead_2d-gratnig`, 20 carried the researcher's words (plus 2 buttons and 1 steering); 54 were platform notices and 35 coding-workspace checkpoints. In `lead_token-sharing`, 14 of 40. A checkpoint goes to the lead even when the implementation lead runs the workspace, and it is not marked as a notice, so the state block calls it "Turn: a request" while the contract says a request is carried out in full. | `DevelopmentWorkspaces.notify()` (`agents/development.py` L222–229) enqueues to `config["lead_id"]` with text that does not start with `NOTICE`; `turn_state.common()` (`agents/turn_state.py` L28). A workspace does not record who opened it: `create()` sets `parent_agent_id` to the lead (L133) although the implementation lead opened all 9 in `2d-gratnig`. Since `decceff` a checkpoint continues the current request's thread instead of opening one. |
| R5 | **The rules and the evals reward doing less.** The contract asks for the narrow reading ("Read a request narrowly", "A question gets an answer, not actions", "in a few lines", "start nothing it did not ask for", "Answer the one asked"). All 12 eval scenarios check turn counts, command counts, forbidden commands and whether the request closed. Five also match the reply against patterns (S6–S9, S11), and S12 checks that a flawed proposal gets revise or reject; none judges the reasoning. Without thinking, this gives the misreadings the researcher corrected: a wall-clock window read as worker-hours ("Wasn't I clear?"); an availability question answered by testing ("Why are you testing the implementation ...?"); a scheduler setting reported as a hardware limit. Screening scores of 0.22282 and 0.17001 against the researcher's 0.85 got "reaching it is an experimental outcome", with no analysis of why they were low. | `INSTRUCTIONS` and `LEAD_CONTRACT` (`tools.py` L56–88); `evals/lead/scenarios/*.json`. |
| R6 | **The lead cannot compute or check by itself.** `analysis_run` takes two steps (`workspace_write`, then run the file) and is described only in the `analysis-scripts` procedure, not in the lead's contract. Its sandbox runs the lab's environment read-only: numpy always, scipy, matplotlib and torch once MEENT is installed, no pandas. Asked why PyTorch was missing, the lead said "No evidence establishes why it is absent"; a two-line script in that sandbox would have shown it. The sandbox mounts only the runs it is given (`/data/<trial_id>`), so coding-workspace logs and validation reports cannot be read through it. All agents share 7,200 s of analysis time per campaign. Until 2026-10-26 a script could run 300 s without the researcher's go-ahead; it is now under their compute thresholds (S6). | `analysis_run()` (`agents/files.py` L175); `src/balsamic/procedures/analysis-scripts/SKILL.md`; `pyproject.toml`. |

### 1.2 The same model elsewhere

| | Codex | Claude Project | Balsamic's lead |
|---|---|---|---|
| Thinking | High by default, carried across tool calls | Extended thinking on hard turns | Off (R1) |
| Who does the work | The agent itself: reads, runs, fixes | The model itself, with code execution | Page agents, specialists and coding workspaces, through messages (R2) |
| What fills the context | Its own reads, diffs and test output | The conversation: its working notes | Repeated JSON snapshots of the team (R3) |
| What starts a turn | The user's words | The user's words | Mostly notices and checkpoints (R4) |
| Instructions | Keep going until the task is done | Few or none | Do the narrow reading, briefly; start nothing unasked (R5) |
| Computation | A shell | A sandbox, used freely | Two-step `analysis_run`, never used (R6) |

---

## 2. Principles

1. **Authority stays in code and in the rules.** The gate, budgets, compute approval, delegation scope and the outstanding-work check stay as they are. Only rules about style and scope become goals.
2. **The lead sees evidence first-hand; actions stay routed.** D1 stands: the pages' commands go through their agents. Reading, analysing and diagnosing are the lead's own.
3. **The model works on the science, not the bookkeeping.** What wakes the lead and what fills its context should be what the researcher would want it to think about.
4. **Thinking is a setting that shows.** No role runs with reasoning off without the Models page and the eval summary saying so.
5. **Quality is measured as well as compliance.** A change that keeps every compliance scenario green but makes the replies worse is a regression.

---

## 3. Decisions (Hoseung to confirm)

| ID | Question | Recommended default | Needed by | Status |
|---|---|---|---|---|
| Q1 | The lead's thinking level | Obsolete: the strong tier now has eight roles (the builder and the test designer moved to it), so one level for the tier sets all eight, and the test designers no longer run on DeepSeek. The levels are part of S1, which Hoseung handles | S1 | Obsolete |
| Q2 | Where the Centinels model catalog lives | Fix `~/.pi/agent/models.json` now. A versioned `agent-harness/profiles/dev/models.json` would be durable, but in dev mode it replaces the personal file (`modelsFile()`), so other providers would have to move into it too | S1 | Open |
| Q3 | Chat completions or Responses for the OpenAI models on Centinels | Responses. Measured on 2026-10-26 (`gpt-6.1-sol`, one run each): Centinels serves `/v1/responses` and returns reasoning items with `encrypted_content`, streamed too. In a tool loop, sending them back made the step after the tool call take 4.9 s and 0 reasoning tokens; dropping them, as chat completions does, 64 s and 1,505 tokens to reason again. Caveats: no reasoning-summary text is streamed (the harness's live thinking line stays empty), and the proxy reports 0 cached tokens | S1 | Answered |
| Q4 | When the lead's context is compacted | At about 150k tokens, by the Balsamic extension at `turn_end` above a threshold set per role. Lowering the `contextWindow` the model is described with would change every role on that model, and the compaction setting (`OVERRIDES`) is shared too | S3 | Open |
| Q5 | Working notes: where they live, and whether the state block carries them | A record per campaign that the lead rewrites with one tool; its first 1,500 characters in the state block (the block's cap rises accordingly) | S3 | Open |
| Q6 | What the lead reads first-hand | Coding-workspace logs, test output and failures; validation reports; page agents' receipts; run journals through Python | S4 | Open |
| Q7 | How the role is framed | The lead is responsible for the campaign's science: it analyses, explains with numbers and recommends. Verdicts on performance and every authority stay the researcher's | S5 | Open |
| Q8 | Who grades the quality scenarios | An LLM judge on Centinels with a fixed rubric, per criterion pass or fail with a quoted reason; transcripts kept for spot checks | S7 | Open |

---

## 4. Suggestions

### S1 — Thinking on for the lead, and a guard

**Owner**: Hoseung. **Requires**: Q2 (Q1 is obsolete, Q3 is answered).

**Read first**: `agent-harness/src/runtime.ts` (`thinkingFor()`, `createRuntime()`, `applySpec()`, `authStatus()`), `agents/controller.py` (effort validation near L271), `agents/tiers.py`, Pi `docs/models.md`, Pi `dist/core/sdk.js` (how a missing level is filled in).

1. Partly done (2026-10-27): `gpt-6.1-sol` and `gpt-6-astra` have `"reasoning": true` and `{"xhigh": "xhigh", "max": "max"}`, and the harness now lists the levels Pi's `/thinking` offers (`getSupportedThinkingLevels`: off to high unless mapped to `null`, xhigh and max only when mapped). Still open: `"minimal": null`, since Centinels refuses `minimal` for `gpt-6.1-sol` (400); and `off` is not off, since chat completions then sends no effort and the model reasons at the server's default (`"off": null` drops it from the list; on the Responses API it is needed, or `off` sends `effort: "none"`, which fails).
2. Done in Balsamic (2026-10-27): a tier without a level ("default" on the Models page, shown as e.g. "default (medium)") runs at the level Pi gives a new session (the profile's `defaultThinkingLevel`, else `medium`), and the harness sets it on resumed sessions too, so old agents no longer stay at the `off` they recorded.
3. Restart the harness, set the levels on the Models page, and check one lead turn: Monitor → Model usage shows each agent's chosen level and the level its latest call ran at; `usage.reasoning` in `runs/dev/pi/<lead>/events.jsonl` is above zero.
4. Use `"api": "openai-responses"` for the OpenAI models (Q3); check that a multi-step turn in the harness reuses the reasoning items.
5. The guard: when a standing role's calls run at `off`, whether its model offers no levels or its tier sets none, the Models page says so beside the role, and the eval runner prints it in the summary. It reads the level calls ran at (`thinking_level` in `events.jsonl`), not only what the model offers. A test pins both.
6. The eval runner's summary reports reasoning tokens per lead call.

**Done when**
- Lead calls in a live eval run show reasoning tokens above zero at the chosen level.
- A model without thinking levels on a standing role is flagged on the Models page and in the eval summary (test).
- No compliance scenario regresses.

### S2 — Checkpoints to whoever started the workspace, as notices

**Read first**: `agents/development.py` (`notify()`, `create()`), `agents/controller.py` (`enqueue()`, `request_root()`), `agents/turn_state.py` (`common()`).

1. A workspace records the agent that opened it (`create()` now sets `parent_agent_id` to the lead whoever calls it), and `notify()` enqueues to that agent (the implementation lead when it opened it), not always to the lead.
2. The text starts with `NOTICE`, so the state block says "a platform notice".
3. Checkpoints that change nothing the receiver must act on (progress lines) are coalesced: one notice per workspace per state change (submitted, blocked, asks a question, failed, finished).
4. The notice names what changed and says to read `implementation_workspace_inspect` only for that part (see S3 for paging).

**Done when**
- A workspace created by the implementation lead sends its checkpoints there, and the lead's turns count drops accordingly (test with the fake harness).
- A checkpoint turn's state block reads "Turn: a platform notice" (test).
- Replayed on the `lead_2d-gratnig` records, the 35 relay turns become at most a handful of notices to the implementation lead.

### S3 — A smaller context

**Requires**: Q4, Q5.

**Read first**: `agents/tools.py` (`inspect()`), `agents/development.py` (`events()`, `public()`), `agent-harness/src/gateway-extension.ts`, Pi `docs/session-format.md` (`context_edit`) and `docs/extensions.md` (`turn_end`).

1. `campaign_inspect` keeps the problem, the gate, the proposals, the methods by id and one line, the page agents' last summaries and the latest results (best score and status of each recent run). The agent team, coding-workspace details and aliases move to their own read. Target: under 20,000 characters on the `lead_2d-gratnig` records (now 95,520).
2. `implementation_workspace_inspect` pages its events and commands (`after`, `limit`) and by default returns only what changed since the caller's last read.
3. Superseded snapshots are collapsed. At `turn_end`, the Balsamic extension appends `context_edit` entries that replace earlier results of `campaign_inspect`, `implementation_workspace_inspect`, `resource_inspect` and `experiment_progress` with one line naming the read that superseded them and the receipt that keeps them. An edit changes the cached prefix from that entry on, so edits are batched: at most once per turn, and only when they save more than about 20k tokens. Pi 1.0.4 accepts `context_edit` entries from a `turn_end` handler (Pi `docs/extensions.md`), and already writes some itself when it drops a failed recovery attempt.
4. Compaction at about 150k tokens for the lead (Q4), and a threshold of their own for the experiment operator and the implementation lead.
5. Working notes (Q5): one tool (`notes_write`) that replaces the lead's notes on the campaign: its understanding of the problem, assumptions, what the results so far say, open questions. The state block carries their start; the contract says to keep them current.

**Done when**
- The median context per lead call in the eval suite is under 80k tokens, and the S7 scores do not drop.
- The lead's notes exist and change across a multi-turn scenario (test with the fake harness for the plumbing).
- Collapsed snapshots stay readable through their receipts (`evidence_read`).

### S4 — First-hand reads for the lead

**Requires**: Q6. D1 is unchanged: the lead still asks page agents for the pages' commands.

**Read first**: `agents/tools.py` (`names()`, `record()`, `READ_KINDS`), `agents/development.py`, `agents/files.py`, `docs/harness-update-plan.md` Phase 5.

1. The lead may read, without asking anyone: coding-workspace logs, test output and failure reports; validation reports; the tool receipts of its page agents and their assistants; run journals through Python (S6). Only run folders can be mounted in the analysis sandbox, so the logs and reports need read tools (S3's paged `implementation_workspace_inspect`, `evidence_read`).
2. The contract says, as a goal: when work fails, find the cause in the records before asking anyone to try again, and say what it is.
3. `page_agent_message` and `delegate` say in their descriptions what the receiver can and cannot read (builders see only their specification), so the lead writes what they need into the message.

**Done when**
- In the S7 scenario "a failed build whose cause is in its logs", the lead names the cause in its reply, without the researcher's help, in at least two of three runs.
- The compliance scenario S11 (experiments through the operator) still passes.

### S5 — Goals instead of style and scope rules

**Requires**: Q7, and the S7 baseline (so the change can be judged).

**Read first**: `agents/tools.py` (`INSTRUCTIONS`, `LEAD_CONTRACT`), `agents/models.py` (`STANDING_OBJECTIVE`), `balsamic/lead/instructions.py`, `tests/test_harness_contract.py`.

1. The role: the lead is the scientist responsible for the campaign's optimizer. It thinks about the problem, analyses the evidence, explains with numbers and recommends; the researcher decides, and judges performance.
2. Replace the narrowing rules with what they were for:
   - "Read a request narrowly ..." → when a request can be read two ways that lead to different work, say which reading you took and why; ask first when the difference is costly.
   - "in a few lines" → lead with the answer; as long as the answer needs, no longer.
   - Keep "a question gets an answer, not actions" and "start nothing it did not ask for": they protect the researcher's compute, and the evals check them.
3. Add the habits that were missing: compute rather than estimate; when a result disagrees with what was expected, say why, with numbers; check units and readings of the researcher's numbers (wall-clock or worker-seconds).
4. Stay within the ratchet: what is added replaces what is removed.

**Done when**
- Every compliance scenario passes; every S7 criterion improves or holds against the S1 + S2 baseline.
- The lead's instructions stay within `LEAD_WORDS` + 10%.

### S6 — One-step Python

**Read first**: `agents/files.py` (`analysis_run()`), `agents/tools.py` (`TOOLS["analysis_run"]`), `procedures/analysis-scripts/SKILL.md`.

1. `analysis_run` also takes `code` directly (the file stays an option for long scripts); the same sandbox, the same limits. Done on 2026-10-26: a script is compute under the researcher's two thresholds, like any other work (`campaigns/compute_consent.py`). Up to the notice threshold (default 1 min) it runs freely; up to the go-ahead threshold (default 5 min) it runs with a notice in the inbox; longer needs their go-ahead. The researcher sets both per campaign on Monitor, Resources. With the lead computing often, the 7,200 s of analysis time per campaign that all agents share may need a share per role.
2. Its description lists what imports: numpy and the journal readers always; scipy, matplotlib and torch where MEENT is installed. Add pandas to an `analysis` extra that `scripts/install-meent` also installs.
3. The lead's contract says when to use it: a question whose answer is a number, a result to explain, an environment question ("is torch importable here?").

**Done when**
- In the S7 scenarios that ask for a number, the lead computes it with `analysis_run` and the number is right.
- A sandbox test runs inline code and refuses network access.

### S7 — Evals that grade quality, and a comparison

**Requires**: Q8. Record a baseline before S1 (thinking as it is now, which measures R1's effect directly; Centinels is free) and another after S1 and S2, before S3–S6, so each later change is measured.

**Read first**: `evals/lead/README.md`, `scripts/run_lead_evals.py`, `evals/lead/scenarios/*.json`, `evals/lead/seeds.py`.

1. A new check type, `judge`: a model call with the transcript and a rubric; each criterion pass or fail with a quoted reason.
   - Explains why, with numbers from the records or its own computation.
   - Catches a wrong premise or a request that conflicts with an earlier one.
   - Finds a failure's root cause from the records.
   - Says which reading of an ambiguous request it took.
2. Scenarios (seeded records, no long compute):
   - Q-1: a failed build whose cause is in its logs.
   - Q-2: screening results far below a target the researcher states.
   - Q-3: an ambiguous budget (a wall-clock window that could be read as worker-hours).
   - Q-4: a request that contradicts one made two turns earlier.
   - Q-5: a question whose answer must be computed from a run's journal.
3. Per run, record reasoning tokens per lead call and median context tokens per call.
4. The comparison: the same scenarios given to the same model in Codex CLI, with the repository and an export of the seeded records, graded by the same judge. It shows how much of the gap the suggestions closed.

**Done when**
- `run_lead_evals.py --fake` runs the judge check against a scripted transcript (plumbing test).
- A recorded baseline exists for the quality scenarios, and the Codex comparison is written up in `docs/lead-agent-readiness.md`.

---

## 5. Order

1. **S7's judge and a first baseline**, with thinking as it is now.
2. **S1** (Hoseung): a configuration change and the largest effect; everything after is measured with thinking on.
3. **S2**: small, and removes a third of the lead's turns and much of its context.
4. **S7 baseline again**: so S3–S6 are each judged against it.
5. **S3**, then **S5** and **S6** (independent of each other), then **S4**, which depends on S6 for journal reads.

## 6. Out of scope

- Changing D1: the pages' commands stay with their agents.
- Choosing another model or provider: the point is that the same model reasons better elsewhere.
- Merging the page agents or specialists into the lead; S7's comparison can inform that later.

---

## Appendix A. How the numbers were measured

From the repository root, on the records in `runs/dev/pi` (each agent's `state.json` names its session file):

```python
import collections, json, statistics
from pathlib import Path

root = Path("runs/dev/pi")
# Thinking level, reasoning and context per call, by role and model (every agent's events.jsonl).
calls = collections.defaultdict(list)
for events in root.glob("*/events.jsonl"):
    spec = json.loads((events.parent / "state.json").read_text())["spec"]
    for line in events.read_text().splitlines():
        event = json.loads(line)
        if event["type"] == "assistant.message":
            u = event["usage"]
            calls[(spec["role"], spec.get("model"), event.get("thinking_level"))].append(
                (u.get("reasoning", 0), u["output"], u["input"] + u["cacheRead"] + u["cacheWrite"]))
for key, rows in sorted(calls.items(), key=lambda kv: -len(kv[1])):
    print(key, len(rows), "reasoning/call", sum(r for r, _, _ in rows) // len(rows),
          "context median", statistics.median(c for _, _, c in rows))

# What fills a lead's session: tool results by tool, the lead's own text, the turns' inputs.
state = json.loads((root / "lead_2d-gratnig" / "state.json").read_text())
entries = [json.loads(line) for line in open(state["sessionFile"])]
names, size = {}, collections.Counter()
for entry in entries:
    if entry["type"] != "message":
        continue
    message = entry["message"]
    if message["role"] == "assistant":
        for part in message["content"]:
            if part["type"] == "toolCall":
                names[part["id"]] = part["name"]
            elif part["type"] == "text":
                size["assistant text"] += len(part["text"])
    elif message["role"] == "toolResult":
        name = message.get("toolName") or names.get(message.get("toolCallId"))
        size["result: " + str(name)] += sum(len(p.get("text", "")) for p in message["content"])
total = sum(size.values())
for key, value in size.most_common(8):
    print(f"{key:40s} {value:>9d} {value / total:6.1%}")
```

The shares in R3 are of everything in the session, the turns' inputs and the tool calls' arguments included; this script
counts only tool results and the lead's text, so its shares come out higher. Turn origins were read from the same session file: an input containing `[Platform notice` is a notice, one whose body
starts with `Implementation workspace` a coding-workspace checkpoint, `[Researcher steering` a steering message, and the
rest the researcher's words or a button's template text.
