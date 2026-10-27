# Pi campaign runtime

Campaigns activated with `agent.activate` use the installed Pi SDK (pinned at
1.0.4 in `agent-harness/package.json`). No provider is selected by default: a dev
profile supplies its default model, or a locked-mode server names its one provider
with the launcher's `pi_provider` (`GRATING_PI_PROVIDER`). Activation without either,
and without an explicit model, is refused. The optional development container image
(`deploy/implementation-workspace`) installs the Pi CLI 1.3.0. With `openai-codex`
as the locked provider, the PI uses `gpt-6-astra`; specialists use `gpt-6-sol`;
proposal and implementation reviewers use Astra.
All sessions currently use `xhigh` reasoning. Models are pinned for each session;
historical chat/discovery model settings do not alter a Pi session. No paid API
fallback is configured.

The [full Pi implementation workspace](pi-implementation-workspace-plan.md)
documents the browser IDE, native Pi CLI sessions, developer and PI interaction,
development accounting, and the active H12 pilot. Its independent protected
validation still requires a submitted implementation and an authorized grant.
The coding agent runs on the campaign's model: the workspace gets that provider's
sign-in from `auth.json` and, for a custom provider (a LiteLLM router), its endpoint
from the Pi `models.json`, and refuses a provider on a private address, which the
container cannot reach. Workspaces are off unless `GRATING_DEVELOPMENT_ENABLED=true`;
while they are off, the refusal tells the agents to commission the implementation
and the researcher how to turn workspaces on. Either way the test designer, builders
and reviewer see the specification alone, so a specification whose name, mechanism
or acceptance criteria name a campaign record instead of stating it is refused
before any model call (`ImplementationBridge.check_self_contained`); provenance may
cite records.

## Deployment and sign-in

Run `npm ci && npm run build` in `agent-harness` and build `frontend`. A launcher
configuration with `pi_port: 8768` starts Pi, the implementation library, and the
workspace. Pi listens on loopback only, authenticates callbacks with a private
generated token, and stores sessions under `<directory>/pi`. The existing
TailNet proxy exposes the workspace UI.

Open **Research notebook → Get browser sign-in link**. Open the displayed OpenAI
URL and enter the code within 15 minutes. Pi polls for completion and stores
credentials in `~/.pi/agent/auth.json`; the browser receives no access or refresh
token. If OpenAI requires device authentication to be enabled, follow its
account instructions. `pi /login` through the interactive CLI is also supported.
Codes are not reusable after expiry; the UI can request a new one.

The session begins only after Pi reports configured credentials. Model catalog
availability alone is not proof that a live model request has succeeded.

## Ownership and recovery

Python owns campaign records, current guidance, grants, typed commands, jobs and
publication. Pi owns persistent inference sessions and automatic context
compaction. Tools retrieve bounded pages of the existing archive; the old 170 KiB
discovery working-context limit and per-task tool/source quotas are not on this
path. Campaign compute allocations and protected validation reserves still apply.

`agent.activate` records a migration manifest, archives legacy sessions, preserves
their artifacts/costs/unfinished states, pins existing H labels, and creates the lead
agent. It starts no turn: the lead agent waits for the researcher (see the next section).
One workspace lease and one Pi session serialize each campaign's manager. The
PI delegates focused assignments; independent implementation roles are created
by the library under a frozen grant, with separate sessions and private workspaces.
Builders cannot read protected fixtures or reviewer sessions. Generated code is
executed inside bubblewrap; protected validation and publication stay in Python.

Exact run IDs, tool intents and receipts reconcile retries after a lost reply.
Local mutations and their receipts commit together. A Pi restart marks in-flight
turns interrupted; the controller resumes from the exact session file and saved
receipts. Pausing/stopping retains historical work. A resumed assignment gets an
explicit continuation. The UI preserves unsent messages on network failure.

New PI proposals require independent conceptual review before experimentation.
Conceptual approval, executable validation, and empirical effectiveness remain
separate. Each model event records subscription calls and token usage; catalog
API prices are not reported as charges. The implementation library projects the
same child usage without reserving an additional paid API allowance.

## The lead agent acts on requests

The lead agent designs and carries out experiments as the researcher asks through the interface.
It does not work through a campaign by itself, and there is no setting that makes it do so. A
scripted run, such as a reproduction used as a test, is driven the same way: by sending it requests.

- **Starting the team starts no work.** No model call is made until the researcher's first message.
  A request the researcher left unanswered before the team existed is handed over as that first message.
- **A request is open from a researcher's message until the lead reports it fulfilled** with
  `yield_work(complete)`, which is refused while experiments, subagents, questions or jobs of the
  campaign are still outstanding. The campaign's agent record carries this as `request_open`. The
  researcher's answer to something the lead filed (an approval, a trial extension) opens it again.
- **Outcomes wake the lead only while a request is open.** These are finished or failed experiments,
  validations, fixed-mask jobs, implementation results and the end of a runtime profile (once, not
  once per probe). Without an open request they wake nobody; the lead reads the current state at
  its next request. A change the researcher makes to the campaign is not an outcome and never wakes it.
- **Turns the platform starts are marked.** Outcome notices, a subagent's result, a resumption and
  the request for a missing checkpoint begin with `[Platform notice. This is not a request from the
  researcher.]`, and tell the lead to carry the open request on and start nothing it did not ask for.
- **A turn's message is everything the agent wrote in it**, in order, not only its last line: an
  answer written before the closing checkpoint call would otherwise be hidden behind the remark that follows.
- **The instructions name the stages** (runtime profile, hypotheses, review, experiments, longer
  runs, validation, comparison, findings, journal clean-up) and allow one only when a request covers
  it. A request may cover several stages or the whole workflow. A question gets an answer, not actions.

Which of these rules the controller enforces and which rest on the lead's instructions is kept in the
[invariant register](invariants.md) (INV-04 to INV-06), with the test or eval scenario that pins each.

## The chat is the researcher's main interface

The researcher asks the lead agent for work in the chat panel; the pages of the application show
what that work produced. Four things follow from this.

- **A reply is short and points to the page.** The lead says what it did and found in a few lines,
  names the open choices, and links the page that shows the details instead of repeating it.
  `campaign_inspect.pages` lists the pages with their link targets (`#experiments`,
  `#experiments/<trial_id>`, `#hypotheses`, `#hypotheses/rounds`, `#implementations`, `#comparison`,
  `#decisions`, `#assets`, `#reports`, `#agents`, a draft at `/reports/<report_id>`), and a command
  receipt names the page of what the
  command created (`page`). A `#…` link in a reply switches the page; other links open beside it.
  `tests/test_agent_discussions.py` checks that every page the lead may link exists in the menu.
- **While an agent works, its steps and its reasoning are shown and not kept.** The harness holds
  one entry per running turn in memory: the tool calls of the turn with short arguments, the text
  being written, and the last 4,000 characters of the model's reasoning. `GET /v1/live?ids=…`
  returns it; the workspace serves it at `GET /api/v1/campaigns/{id}/agents/live` with each tool
  call as one readable line (`step_label` in `agents/tools.py`). The entry is replaced when the
  next turn starts. Reasoning is never written to `events.jsonl`, to the agent log or to the
  database; a model that hides its reasoning shows steps only. (Pi's own session file, which the
  harness already kept, holds whatever the provider returned.)
- **Notes that need not stay are folded.** A reply records the kind of turn it came from
  (`turn`: `request` or `notice`) and how the turn ended (`disposition`). In the chat, a reply of a
  notice turn that ended with work still running is folded once the lead has written again right
  after it; such notes gather into one line that opens on a click. Three kinds of reply therefore
  always stay: the lead's first reply after a researcher's message (a message that arrives during
  a notice turn is answered in it), the note a researcher replied to (it may have asked
  something), and the newest message. The lead is told to write no message in a
  notice turn when nothing new needs the researcher, and to give the status in `yield_work`; the
  chat shows that status as a temporary line together with what the lead waits for.
- **A saved `yield_work` ends the turn.** The harness returns its result with Pi's `terminate`
  flag, so the model is not called again in that turn; a researcher's message that arrives
  meanwhile is still taken. Without it a model may keep writing closing lines and yielding again
  (DeepSeek did, three times in one turn). A refused `yield_work` does not end the turn.
- **The assistants' exchange is shown.** The Review rounds tab of Hypotheses (`#hypotheses/rounds`;
  `#discussions` still leads there; `agents/discussions.py`,
  `GET /api/v1/campaigns/{id}/discussions`) is assembled from saved records, with no model call. A
  round is the assistants that the discussion moderator or the lead created in one turn. For each it
  shows the assignment, the assistant's own closing summary (what it passed to `yield_work`), the
  full reply, its saved documents and its verdicts, and the response of whoever asked. A table
  above the rounds gives, for every proposal and its revisions, the verdicts in order. A Graph view of the
  same records (`#hypotheses/rounds/graph`) draws who asked whom, the verdicts, and how each proposal was
  created (the round whose turn ran its `hypothesis.create`) and revised.
- **No agent panel above the pages.** The lead is in the chat. Pausing, stopping, sign-in and the
  list of agents are on the Agents page (`#agents`), with the models, the guidance, the usage and the
  log as its tabs. The lead's questions are kept above the chat's message box, to answer or dismiss
  (`agent.question_dismiss`, which wakes no agent).

## Agents in charge of pages

Three agents each own the work of one page and stay for the whole campaign, like the lead
(`PAGE_AGENTS` in `agents/models.py`). Each is created, as an assistant of the lead, the first time
the researcher or the lead writes to it, and acts on nothing else.

| Agent | Page | Commands (`ROLE_OPERATIONS`) | Also |
|---|---|---|---|
| Discussion moderator | Hypotheses | `hypothesis.create`, `.review`, `.status`; `approval.request` | `delegate` to specialists and reviewers only; their results come back to it |
| Experiment operator | Experiments | `draft.save`, `draft.launch`, `trial.create`, `trial.control`, `trial.extension_request`, `trial.continue`, `runtime.profile`, `fixed_mask.run`, `comparison.report`; `approval.request` | |
| Implementation lead | Implementations | `implementation.commission`, `.attach`, `.revalidate`, `.bind_builtin`, `.resolve_runtime`; `evaluator.commission`, `.attach`, `.equivalence`; `approval.request` | the `implementation_workspace_*` tools |

All three read like the other agents (campaign and resources, evidence, files, analyses) and may ask
the researcher (`researcher_ask`). The tool schemas each one is given list only its own commands and,
for the moderator, only the roles it may ask; anything else is refused before it runs.

Who hears what:

- **The researcher asks on the page** (`agent.message` with `page_agent`). The request is the page
  agent's own: the lead's request is not opened, the reply is shown on the page, and its end wakes no
  one. The lead sees each page agent's last summary in `campaign_inspect.page_agents` at its next
  request.
- **The lead asks** (`page_agent_message`). The request is kept on the page as the lead's message;
  when the page agent ends it, the result comes back to the lead as an assistant's result does. The
  lead cannot call its own request complete while that one is open.
- **Outcomes go to whoever started the work.** An experiment's or an implementation job's outcome
  wakes the agent whose command started it (read from its tool receipts, `PiController.starter`)
  while that agent's request is open; an outcome with no such agent goes to the lead as before. The
  lead's "still running" check counts only what page agents did not start.
- Page agents do not count toward the limit on assistants at work (`max_subagents`).

The lead's commands leave out the pages' own operations (`LEAD_PAGE_WORK` in `agents/tools.py`, harness plan D1): drafts,
runs, continuations, extension requests, experiment rules, hiding runs, runtime profiles and fixed-design checks are the
experiment operator's; implementations and evaluators (commissions, attachments, equivalence checks) the implementation
lead's. They are not in the lead's `campaign_command` enum, and a call that names one is refused with the agent to ask
(`page_agent_message`). The lead keeps `trial.control` (pausing and stopping, never enlarging), `comparison.report`, the
proposals, findings, validations, studies and its workspace operations, and reads `experiment_progress` itself: a status
question is a read, not work for the operator. The researcher's own commands are not affected.

A page agent can ask the lead (`lead_ask`): the question starts a lead turn whatever the researcher's request,
the lead's reply goes back to the agent that asked, and that turn neither opens nor closes the researcher's
request. The chat shows both, marked as an exchange between agents.

The experiment operator keeps the campaign's experiment rules (`campaigns/experiment_rules.py`): naming, the
threshold between short and long runs, how many of the campaign's runs may go at once (the scheduler enforces
it), how runs are chosen and ordered, and how runs are presented on the Experiments page. It is given them in
every turn's state block (below), and has `experiment_progress` and `config_suggest` (`agents/experiments.py`).

## Reports

Asked for a report, the lead starts the staged report writer of the Reports page with
`report_write` and answers in a line with a link; the job's end wakes it (`report.writer_completed`,
`report.writer_failed`, or `report.writer_question` when the writer asks about the focus, which
the lead answers with `report_answer` or passes on). `yield_work(complete)` is refused while a
report the lead started is still being written. The writer freezes the campaign's own records
(runs, hypotheses, decisions, sources, studies) by itself; what the agents wrote, such as reviewers'
verdicts and saved analyses (`agent_artifact`) or assistants' replies (`agent_run`), reaches it
only when the lead names those records in `reference_ids`, each under its own id and kind.

In a campaign with a started team, and on a server whose earlier research provider is not set up,
every stage of the writer runs on the lead agent's model: one call each through the harness
(`POST /v1/complete/<job id>`, `completeOnce` in `agent-harness/src/runtime.ts`), which holds the
sign-in and the price catalogue. Each call is capped at 64,000 output tokens, reasoning included
(or the model's own limit if lower), and reserved at that cap and its prompt before it is made;
it is refused when the campaign's model budget cannot cover it; afterwards the harness's measured cost
replaces the reservation, and the call is written to the campaign's usage ledger under the role
`report_writer`. A failed call is not repeated. The reasoning of the running call shows on the
job's card on the Reports page, under the stage it belongs to, through the same live view.

## What the lead agent is given

[Lead agent readiness](lead-agent-readiness.md) keeps apart what of this is implemented and what is only proposed.

### Instructions and the state block

An agent's instructions and tools (the manifest, `POST /api/internal/pi/manifest`) are fetched once, when the harness
makes the agent's runtime, and serve every later turn of that runtime. They are the same for a role whatever the
campaign's state (`tests/test_turn_state.py`, `tests/test_harness_contract.py`): a change to the system prompt or the
tool set would alter the start of every request and cost the provider's prompt cache for the whole session (Pi folds
system-prompt changes into the leading system message for these providers).

What changes comes in the state block instead. Right before each prompt the harness asks the workspace for it
(`POST /api/internal/pi/turn_state`) and sends `[Assignment <run>]`, the block, a blank line, and the run's text; the
run's identity stays its text alone, so a run submitted again is the same run. The workspace builds the block from its
records at that moment (`agents/turn_state.py`, and `balsamic/lead/state.py` for the lead's part), in a fixed order,
at most 3,000 characters, with no wall-clock time, and saves it on the run (`agent_run.turn_state`):

| Who | Items |
|---|---|
| Every standing agent | Whether the turn is a request or a platform notice; its thread; the researcher's open questions it answers for (up to five) |
| Lead | The problem-definition gate (open, or the next step, its page and the unwritten sections); autopilot (on with its cap and what is left, chosen at setup and waiting, or off); up to three library strategies that match; up to ten records pinned in this thread and the ones set aside; the page agents with an open request |
| Experiment operator | Who asked; the experiment rules (naming, short/long threshold, runs at once, how runs are chosen, how they are presented) |
| Resource planner | Who asked; the researcher's resource level and the launcher's maximum |
| Other assistants, import agents, implementation roles | Nothing |

A workspace without the route answers 404 and the harness sends the prompt as before; any other error fails the run, as
a manifest error does. Steering messages go to the turn in progress unchanged.

`campaign_inspect` returns, besides the campaign, its tasks and hypotheses:

- `methods`: every installed optimizer that can run on a current task, with the parameters its
  `algorithm_config` accepts (type, allowed values, default). An experiment is built from this list.
- `reference_evidence`: findings of earlier campaigns that the researcher referenced for this
  campaign's study (Evidence view, "reference" for "manager evidence"). Each is a scoped claim
  with limitations; `evidence_read` with its asset id returns it whole. Nothing else of the
  earlier campaign becomes readable.

Every tool result joins the model's context for the rest of its session, and a provider refuses a
request above its size limit. A command receipt above 48 kB therefore comes back as an index of
its outcome, to be read in pages with `evidence_read` and the listed pointers; a
`comparison.report` also gives each method's summary and one line per experiment. No tool returns
more than 256 kB. `comparison.report` itself keeps both ends of every run of equal best-so-far
values instead of one point per evaluation, and leaves out runtime-profile probes and equivalence
replays, which measure the evaluator and are no method's result. With `trial_ids` it compares
only the named experiments, and a run continued with `trial.continue` is one row.

The lead agent files `journal.compaction_request` when the researcher asks for the clean-up, after
results are analysed and recorded; the researcher approves it in the decision inbox, and only then are evaluated designs removed from
the finished experiments' journals.

### The contract and the procedures

The system prompt is a short contract: what every agent but an implementation grant's is told (`INSTRUCTIONS` in
`agents/tools.py`, at most 350 words: the researcher decides, requests and notices, the narrow reading with three short
examples, the `yield_work` protocol, replies and links, evidence ids, the researcher's limits), the role and assignment
lines, the lead's contract (`LEAD_CONTRACT`: the page agents and delegation), the workspace briefing
(`balsamic/lead/instructions.py`: links, threads, the state block, the gate in two lines, proposals, names) and the role's
procedure catalog. The lead's comes to under 900 words (2,889 at `a7e89b8`); a test pins both limits and a ratchet
(`tests/test_harness_contract.py`). An implementation grant's roles keep the instructions they had before (`GRANT_INSTRUCTIONS`).

Workflow procedures are files in the Agent Skills format, `src/balsamic/procedures/<name>/SKILL.md` (frontmatter `name`,
`description`, `metadata.roles`; bundled files under `references/`), usable from the Pi CLI or Claude Code too. The service
layer scans them at start-up (`workspace.procedures`); each role's catalog (name and description, sorted) is in its static
instructions, and `procedure_read(name, file?)` returns a body (at most 24 kB) and its bundled files, refused for a procedure
outside the agent's roles; its receipt records which run read which. When a workflow starts without its procedure having been
read in the run (`report_write`, `problem_note_draft`, `hypothesis.create` and `hypothesis.edit`, `journal.compaction_request`,
`finding.record`, `runtime.profile`, `implementation_workspace_create`, `panel_render`), the result carries
`"procedure": "<name>"`, once per run (`workspace.procedure_hint`).

| Procedure | For |
|---|---|
| `report-brief` | Starting the report writer and waiting for it |
| `problem-formulation` | The problem note and the problem-definition gate |
| `proposal-fields` | What each field of a proposal says; correcting one |
| `journal-cleanup` | Asking for journal compaction after findings are recorded |
| `recording-findings` | Earlier campaigns' findings; `finding.record` and publishing |
| `runtime-profiling` | Profiles, flags, waivers, worker ceilings; optimizing a slow evaluator |
| `implementation-supervision` | A method as a library: coding workspace, tests and contract checks, install, binding; commissions |
| `panels` | `panel_render` |
| `analysis-scripts` | Repository and experiment files; `analysis_run` |
| `rcwa-convergence-check` | A score at the searched RCWA orders checked at higher orders (draft from Part F) |
| `meent-problem-setup` | The installed MEENT grating problems (draft from `paper-mapping.md` and `problem-setup.md`) |

### Specialists

The assistants the lead or the moderator asks for one assignment (the literature specialist, methodology specialist,
cross-domain explorer, skeptical domain analyst, empirical assessor, results analyst and proposal reviewer) differ by brief,
tools, output schema and their own context, not by name only. Each has a file in Pi's agent-definition format,
`src/optimization_framework/agents/roles/<role>.md` (frontmatter `name`, `description`, `tools`, `model` as a tier hint; the
brief as the body, at most 200 words), and a `<role>.schema.json` (`agents/roles.py`, `ROLE_BRIEFS`, `ROLE_OUTPUT_SCHEMAS`).

- A specialist is told `SPECIALIST_CONTRACT` instead of the shared instructions: it reports to the agent that asked it,
  starts no work of its own, cites record ids, has 40 tool calls for an assignment (enforced: past them only
  `submit_output`, `proposal_review` and `yield_work` run), and records its result before it completes.
- Its tools are those its file names; `delegate` gives it its role's schema, `submit_output` validates against it, and
  `yield_work(complete)` is refused until it has submitted. The proposal reviewer's structured output stays its
  `proposal_review`.
- The asking agent's notice says where the result is (`/output` on the run); the Review rounds view shows it.
- Specialists saved before the schemas keep working without one.

### Files and the agents' own analysis

Agents other than the protected implementation roles can read two places outside the database:

- `file_list`, `file_read` and `file_search` with root `repository` reach this server's checkout,
  limited to the files git tracks. Credentials, run data and Pi's runtime state are never tracked,
  so they are never listed, read or searched.
- With root `experiment` and a `trial_id` they reach that experiment's directory, for experiments
  of the agent's own campaign, without its saved states.

`analysis_run` runs a Python script that the agent wrote into its work directory
(`workspace_write`) in a bubblewrap sandbox: the named experiments are mounted read-only at
`/data/<trial_id>`, the interpreter and the framework's source are read-only, the work directory
is the only writable place, and there is no network, no GPU, and nothing else of the host (not
the workspace database, not the user's configuration or keys). A script runs for at most 300 s
and a campaign's agents for 7,200 s in all; the last 12 kB of its output is returned.

`compute` does arithmetic for the lead, the page agents and the specialists whose role files list
it (roadmap K1): an expression of the charter's evaluator (`problem_charter/expressions.py`, parsed
and walked node by node, never passed to `eval`) over at most 50 values, each a number or a number
read from a record of the agent's own campaign at a JSON pointer. The result, which is also the
call's receipt, holds the expression, each input with its record and pointer (none for a literal),
and the value. The protected implementation roles do not have it.

Whatever an agent reads is sent to its model provider. The repository root therefore exposes the
committed code and documents of this checkout to that provider; nothing outside the two roots is
reachable.

### What only the researcher grants

Campaign limits (compute, model spending, the per-experiment limit, the validation reserve),
waivers and the worker ceiling are the researcher's. An agent files `approval.request` with one
of them and its reason; it appears in the decision inbox, and approval applies it as the
researcher's own command (`campaign.update`, `validation.waive` or `workers.set`). Declining
changes nothing. A changed worker ceiling holds until the services restart, when the launcher
configuration's `workers` applies again. The per-experiment limit may be set up to 86,400 s.

So is compute, at every step (`campaigns/compute_consent.py`), under two thresholds the researcher
sets per campaign on Monitor, Resources (`campaign.update`: `compute_notice_seconds`, by default a
minute, and `compute_gate_seconds`, by default five minutes; the notice threshold is at most the
go-ahead threshold). They count the worker time of each thing an agent starts: a run, an allocation, a
runtime profile, a validation, an implementation job, a race, an analysis script.

- Up to the notice threshold, it starts freely.
- Up to the go-ahead threshold, it starts and a `compute_notice` goes to the inbox ("The experiment
  operator started a run, about 4 min of compute"). It stays in front of the researcher until they
  acknowledge it, and listed in the inbox after. Work an approved plan covers is charged to that plan
  instead, without a notice.
- Longer, and any coding workspace, waits for the researcher's go-ahead, even when a request implies
  the work. The agent proposes the request's mandate with `mandate_propose` (template `screen` or
  `run_campaign`; `approval.request` kind `mandate`, which replaces kind `compute` for agents): the plan
  (what runs and why), how long until results, the worker time, any coding workspaces, a model-spend
  envelope, a deadline, a stop condition and what the researcher can do meanwhile. The inbox card has
  three choices. Approve records the mandate with a consent for that worker time (and those
  workspaces), which the work it starts is charged against, for at most an hour or three times the
  stated wall time; Approve as Explore only records Explore; Decline changes nothing. An Answer or
  Explore mandate within the thresholds is granted at once, and a request with none has Explore from
  its first work-starting command. The state block names the request's mandate and what is left of it.
  Decisions filed as kind `compute` before mandates stay readable and are resolved as before.

The command bus refuses an agent's work-starting command over the go-ahead threshold that no consent
covers and names what is left; coding workspaces, their validations and analysis scripts are checked
where they start. Every standing agent's state block states the two thresholds. The researcher's own
commands are never checked, and autopilot runs within the compute cap the researcher set when
switching it on. The per-experiment limit still applies. An agent may ask for other thresholds with
`approval.request` kind `campaign_limits`; it cannot set them.

For experiments, the request lists its `runs`: per run, the task, the hypothesis or method, seeds, wall
time, evaluation cap and device. The workspace computes their plan from the records
(`campaigns/experiment_plan.py`), and the inbox shows it on the approval as a plan card. The plan gives
each run's design and its speed, measured on the nearest earlier run of the same problem (same method
and device first). It gives the evaluations the wall time allows and what ends the run (the wall time or
the cap). It gives the disk use of each output file, scaled from that run's journals, and warnings: a run
writing more than 2 GB, a cap that ends runs early, a problem nothing has measured yet. What was not
measured says so. A draft is one run: the Experiments page's Drafts open as the same plan, with what
blocks the draft from starting.

## Extensions

Pi extensions run inside the harness process with its permissions, and can see prompts, tool calls, credentials and
session history. In Balsamic they may change how an agent thinks; anything that acts goes through the gateway or reports
to it (harness plan, §2.5).

**Binding.** After `createAgentSession` the harness calls `session.bindExtensions` (mode `rpc`), as Pi's own RPC and
interactive modes do: `session_start` fires (extensions start connections and rebuild their state there), the UI context
below is attached, and extension errors are written to the agent's journal as `extension.error` (extension, event, error).
Ending a runtime (`forget`, shutdown) emits `session_shutdown` before the session is disposed (`runtime.ts` `shutdown`).

**The curated set.** The manifest names each role's extensions (`extensions: [{name, path, tools}]`) from the versioned
allowlist `agent-harness/extensions/allowlist.json` (`GRATING_PI_EXTENSIONS` names another, as the evals do;
`agents/extensions.py`). Being part of the manifest, the set is fixed for a runtime's life. Locked mode discovers nothing:
an empty agent directory of the session's own, no `~/.pi`, no working-directory resources, no skills, prompts or context
files; only the allowlisted paths load. Dev mode keeps loading the profile's extensions for experiments. In both modes the
Balsamic extension loads first, and an implementation grant's roles (builder, test designer, validator) load nothing
(`extension_host: false`). The allowlist is empty for now (D8): every session loads the Balsamic extension only.

**The Balsamic extension** (`agent-harness/src/gateway-extension.ts`, one per session):

| Hook | What it does |
|---|---|
| `tool_call` | The gateway's tools pass; another tool runs only if the role's allowlist names it, else it is blocked with a reason naming the role |
| `tool_result` | Every other tool's result is receipted (`POST /api/internal/pi/external_receipt`): an immutable `agent_tool_receipt` with `external: true`, the same identity as a gateway call's (agent, run, call id), bounded arguments, the first 24 kB of the result, its size and the tool's annotations, readable with `evidence_read` in the campaign. A result over 256 kB is cut for the model. A result the workspace cannot receipt is withheld |
| `agent_before_settle` | A run about to end without a saved `yield_work` gets one continuation in the same turn, with a reminder; the controller's `pi_continue_*` notice stays the fallback when that ends without one too |
| `turn_end` | The session's context usage (tokens, window) goes to the journal as `context.usage` |

A web page an agent wants to cite is still captured with `source_ingest`, so findings cite `source` records; an extension's
result is evidence only through its receipt.

**Dialogs.** `select`, `confirm`, `input` and `editor` become a question to the researcher (`POST
/api/internal/pi/ui_request`, an `agent_question` with `kind: "extension_dialog"`), shown above the chat for the lead and on
the agent's desk for a page agent (`frontend/src/chat/ExtensionDialog.tsx`). The answer (`agent.ui_respond {question_id,
value | cancelled}`) goes back to the waiting extension, which polls `/api/internal/pi/ui_request/{id}`; it opens no
request, queues no turn and changes no guidance. Dismissing the question cancels the dialog. Deadlines (D9): the
extension's own timeout, otherwise 15 minutes; in an autopilot round a dialog is cancelled at once. A cancelled or
expired dialog resolves as in RPC mode (undefined, or false for `confirm`). `notify` and `setStatus` become the agent's
activity line and journal events; widgets, titles, themes and terminal components do nothing. Extension dialogs hold no
request open (`yield_work`'s outstanding check) and are not listed in the state block.

**Codemode, tool search and MCP** are not loaded. When they are (harness plan, Phase 8), they go into
`extensionFactories` (`createCodemodeExtension()`, `createToolSearchExtension()`, `createMcpExtension()`), and the binding
above is what lets MCP connect.

**Trying a third-party extension** (the way onto the allowlist):

1. Try it in the dev profile with `scripts/pi-dev`, then in a scratch campaign on `scripts/dev-stack up --real`.
2. Read its code and list what it touches: files, network, processes, the prompt, messages.
3. If it acts, its tools must be allowlisted per role and receipted by the Balsamic extension. If it spawns processes or
   agents, do not promote it.
4. Add or extend an eval scenario, run the suite and compare with the baseline, `cacheRead` included: `context`
   transforms and prompt changes can cost the cache on every request.
5. Pin its exact version in `agent-harness/package.json` (installed with `npm ci --ignore-scripts`), add a folder under
   `agent-harness/extensions/session/` whose `index.ts` loads it, and list it in the allowlist for the roles that need it.
   A changed list applies to sessions made afterwards and resets running sessions' prompt cache once.

## Numerical diagnostics

`mask_create` makes deterministic full-size masks without putting all cells into
model context. `fixed_mask.run` evaluates immutable masks at specified fidelities
and retains objective values, energy totals, startup/evaluation times, cache flags,
and actual solver counts. Each uncached evaluation is one solve that returns both polarizations.
The implementation contract accepts the campaign's 32,768 cells. Independently
frozen `inspect()` checks can verify unit norm, tangency, PSD, rank and finiteness.
These checks establish declared invariants, not optimizer superiority.

Fixed-mask jobs reserve campaign compute and share worker capacity with trials.
They enforce their wall deadline even during a workspace restart. An uncertain
launch is reconciled or charged as interrupted rather than replayed.

## Host prerequisite found during rollout

On strixhalo, the kernel audit log reports AppArmor denying bubblewrap's
`setpcap` and `net_admin` operations under `unprivileged_userns`. This blocks
generated package execution. Existing MEENT and bundled optimizer evaluation
remain runnable. The PI checks this prerequisite before reserving an
implementation grant.

A scoped profile is prepared in `deploy/grating-bwrap.apparmor` and passes the
AppArmor parser's offline syntax check. An administrator must load it:

```bash
# from the repository root
sudo install -m 0644 deploy/grating-bwrap.apparmor /etc/apparmor.d/grating-bwrap
sudo apparmor_parser -r /etc/apparmor.d/grating-bwrap
```

This follows Ubuntu's documented [per-application user-namespace
permission](https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007).
It grants the namespace permission to `/usr/bin/bwrap`; bubblewrap still supplies
the restricted mounts, empty credential environment and network namespace.
The rollout did not change the global user-namespace restriction. Administrator
credentials were unavailable to this development session.

After loading it, rerun the isolated implementation tests and tell the PI to
continue H12. The saved handoff is
`discovery_task_716baff218c3888fb6e4f123daf4_step_2_artifact_0`; its hypothesis is
`hypothesis_candidate_e7c9dd8fadc32faccbbcc416fe60`.

## Validation and rollback

Harness tests cover persisted login/logout detection, session identity, steering,
restart recovery, idempotent delivery, controls, and filtered telemetry. Python tests cover authority,
cross-campaign evidence boundaries, migration, receipts, budget accounting and
real MEENT fixed masks. Browser tests cover question replies, retries, parent/child
status and revision-checked controls. The full H12 implementation/validation pilot
still requires the administrator sandbox fix above.

Initial rollout verification passed 99 Python tests and 18 browser tests,
plus a real SDK session construction check (only application-approved tools) and
a browser check against the TailNet URL. On September 29, 2026, browser sign-in
completed and a credential-status defect was corrected: Pi's unrefreshed
`hasConfiguredAuth()` snapshot was replaced by a persisted `checkAuth()` lookup.
The live PI resumed the saved campaign using Astra, invoked campaign/evidence
tools, delegated methodology and results analysis to separate Sol sessions, and
completed a native fixed-mask diagnostic (12 evaluations and 24 solver executions).
The authenticated TailNet browser showed
the active team without a sign-in prompt or JavaScript errors. These checks do
not establish H12 implementation correctness or effectiveness.

The live integration follow-up passed 34 focused Python tests and 7 harness tests.
It added campaign-scoped command-receipt citations and pinned GitHub source reads
that preserve code text, separated synchronization errors from authentication,
handled boolean tool-error events, and prevented steering acknowledgments and
late shutdown aborts from being misreported as completed assignments.

The isolated implementation regression tests currently fail at bubblewrap's
namespace setup on this host; those failures are not passing scientific checks.

Before rollout, databases were backed up to
`runs/backups/pi-migration-20260929T054510Z`. To roll back campaign ownership,
pause or stop the agents, wait for acknowledgment, then execute `agent.rollback`
with a reason through `/api/v1/commands`. Evidence is retained. Legacy discovery
sessions remain archived until explicitly resumed. To restore an entire database,
stop the services first and preserve any work recorded after the backup.

## The session tree: one session, many threads

The workspace's conversation threads are branches of the lead's single Pi session (SDK `SessionManager`). The harness
exposes the tree: `GET /v1/agents/{id}/tree`, `GET /v1/agents/{id}/entries?after&leaf` (the path to a leaf), `GET
/v1/agents/{id}/context?leaf` (what the model would see from a leaf, with byte counts), `POST /v1/agents/{id}/leaf
{entry_id, summary?}` (idle agents only; with a summary Pi records a branch summary under the destination) and `GET
/v1/agents/{id}/export?leaf` (one branch as its own session file). A run submitted with `thread_id`, `leaf_entry_id` or
`branch_from_entry_id` (and an optional `summary`) has its leaf positioned before the prompt; its result reports
`entry_ids {parent, last}`, which the workspace records on the thread and on the reply message. Steering reaches the
turn in progress only from its own thread; another thread's message waits as its own run. `agent-harness/test/sessions.test.mjs`
runs this against the pinned SDK; `tests/fake_harness.py` is a scripted stand-in with the same routes.

## Custom providers (a LiteLLM proxy, a local server)

The harness's model runtime loads a Pi `models.json`: the dev profile's own when it has one, otherwise the researcher's
`~/.pi/agent/models.json` (`GRATING_PI_MODELS_FILE` overrides both). Keys stay in `~/.pi/agent/auth.json` or the
environment. So a provider that `pi` itself can use (for example the team's LiteLLM proxy with the ChatGPT models behind
it) is offered to the agents too, and Monitor → Models lists its models once the harness is restarted.
