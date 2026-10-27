"""Real Pi tools backed by scoped reads and transactional campaign commands."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from optimization_framework.contracts.base import content_hash, lenient
from optimization_framework.contracts.commands import Command
from optimization_framework.storage.sqlite import now
from optimization_framework.campaigns.record_view import view_record
from .models import ROLES, LEAD, PAGE_AGENTS, STANDING, DISCUSSION_ROLES
from .capabilities import implementation_execution
from .roles import ROLE_BRIEFS, ROLE_OUTPUT_SCHEMAS, SPECIALIST_CONTRACT, SPECIALIST_TOOL_CALLS

READ_KINDS = {"campaign", "task", "hypothesis", "source", "source_capture", "source_passage", "source_retrieval", "runtime_profile", "evaluator_equivalence",
    "journal_compaction", "worker_ceiling_change", "campaign_budget_amendment", "validation_requirement", "validation_result", "waiver", "waiver_revocation", "finalist_selection",
    "study", "trial", "decision", "decision_refresh", "action", "manager_note", "manager_command", "manager_issue", "discovery_candidate", "discovery_artifact",
    "discovery_task", "discovery_assessment", "discovery_handoff", "discovery_session", "implementation_reference",
    "implementation_binding", "implementation_grant", "implementation_cache", "reference_correction", "agent_migration", "agent_session",
    "agent_alias", "agent_artifact", "agent_run", "agent_question", "agent_tool_receipt", "fixed_mask_job", "fixed_mask_report",
    "builtin_binding", "manager_state", "message", "methodology_family", "discovery_reference_correction", "discovery_task_resolution", "research_run", "work_command",
    "report_writer_job", "technical_report",
    "adaptive_race", "race_protocol", "race_decision", "race_endpoint", "race_confirmation_roster",
    "race_resource_calibration", "race_fidelity_amendment", "race_execution_lease"}
# What agents wrote, passed to the report writer when the lead names it (the writer freezes the campaign records itself).
AGENT_RECORD_KINDS = {"agent_artifact", "agent_run"}
# The commands of each page agent: the work of its page, and asking the researcher for approval.
ROLE_OPERATIONS = {
    "discussion_moderator": {"hypothesis.create", "hypothesis.edit", "hypothesis.review", "hypothesis.status", "approval.request"},
    "experiment_operator": {"draft.save", "draft.launch", "trial.create", "trial.control", "trial.extension_request", "trial.continue",
                            "runtime.profile", "comparison.report", "approval.request", "experiments.rules", "trial.hide"},
    "implementation_lead": {"implementation.commission", "implementation.attach", "implementation.revalidate", "implementation.bind_builtin",
                            "implementation.resolve_runtime", "evaluator.commission", "evaluator.attach", "evaluator.equivalence", "approval.request"},
    "resource_planner": {"resources.plan", "resources.estimate", "runtime.profile", "approval.request"},
}
# The pages' own work (harness plan, D1): the lead asks the agent in charge (page_agent_message) instead of running it, and
# campaign_command refuses it from the lead with that agent's name. The researcher's own commands are not affected.
LEAD_PAGE_WORK = {**{operation: "experiment_operator" for operation in ("draft.save", "draft.launch", "trial.create", "trial.continue",
                     "trial.extension_request", "experiments.rules", "trial.hide", "runtime.profile")},
                  **{operation: "implementation_lead" for operation in ("implementation.commission", "implementation.attach", "implementation.revalidate",
                     "implementation.bind_builtin", "implementation.resolve_runtime", "evaluator.commission", "evaluator.attach", "evaluator.equivalence")}}
LEAD_EXCLUDED_OPERATIONS = frozenset(LEAD_PAGE_WORK)
OPERATIONS = {"hypothesis.create", "hypothesis.review", "hypothesis.status", "draft.save", "draft.launch", "trial.create",
    "trial.control", "trial.extension_request", "implementation.commission", "implementation.attach", "implementation.revalidate", "implementation.bind_builtin",
    "implementation.resolve_runtime", "evaluator.commission", "evaluator.attach", "finding.record", "comparison.report",
    "validation.run", "validation.execute", "study.create", "study.activate",
    "study.race.control", "study.race.decide", "asset.snapshot", "runtime.profile", "evaluator.equivalence", "trial.continue", "journal.compaction_request", "approval.request",
    "experiments.rules", "trial.hide", "campaign.adopt_problem"}
# What every agent but an implementation grant's is told: role and authority, requests and notices, the turn's end, replies,
# evidence and limits. Workflow procedures are read on demand (procedure_read); the lead's own contract follows below.
INSTRUCTIONS = """You are a persistent Pi agent in a scientific campaign; your role and assignment are below. The researcher
decides what the campaign does next; agents work at the researcher's request. A message from the researcher, or the agent that
asked you, is a request: do what it asks, fully, with real tools, report what was done and found, name the choices now open, and
stop. Stages (a runtime profile, hypotheses, a review, experiments, a validation, a comparison, findings) are separate:
start one only when a request covers it; a request may cover several. Read a request narrowly; say in one line what the broad reading
would add. A question gets an answer, not actions. A turn that begins with [Platform notice ...] is not a request: it reports on
work a request started; carry that request on and start nothing it did not ask for. Examples: told one of two runs finished,
write no message; yield_work(waiting), the status as summary. Asked for two hypotheses: record two; running them is one line of
the report. End every turn with yield_work: waiting while work you started or a question you asked is open (its end wakes
you); complete when it is fulfilled. Your reply is its report: the answer, with the numbers behind it, in a few lines. Do not
repeat what a page shows: link the page instead, as a Markdown link to a target in campaign_inspect.pages, such as
[Experiments](#experiments). The summary is a status line without record ids.
The campaign database is authoritative: read campaign_inspect first and after the researcher acts, read evidence on demand, cite
exact record ids. Only a tool result is a receipt. Derive a number with compute or a script, never mental arithmetic.
Compute is the researcher's to start, at every step: before a coding workspace, or anything longer than their go-ahead threshold
(runs, profiles, validations, jobs, analyses), propose a mandate (mandate_propose) saying what runs, why, how long, and
what they can do meanwhile; start it once approved, never silently. "Implement and compare" is one mandate naming the
coding workspace, any evaluator, the proposals and runs: Balsamic installs, binds and starts the approved runs. Never ask the
researcher to run commands. Limits, budgets, waivers and the worker ceiling are theirs too: file approval.request with the
measurement behind it; ask scientific choices with researcher_ask. Never fabricate validation.
"""
# The lead's own contract: coordination and delegation. The workspace adds its briefing (workspace.lead_instructions).
LEAD_CONTRACT = """You are the lead agent. Three agents are in charge of a page for the whole campaign: the discussion moderator (review rounds
over proposals; #hypotheses), the experiment operator (runs: designing, starting, watching, extending, stopping; #experiments)
and the implementation lead (building and checking implementations; #hypotheses/implementations); the resource planner says how
many runs go at once and why runs wait. Hand page work to them with page_agent_message, link the page, and call
yield_work(waiting). campaign_command refuses you the pages' own operations and names whom to ask.
Reads are yours: experiment_progress, resource_inspect, campaign_inspect.page_agents. Delegate to a specialist only for work that
needs its own context. You may pause, stop or resume a run (trial.control), never enlarge one.
Availability, soundness and performance are separate questions: is a method installed or implementable, does it implement its
specification (its tests), does it perform well (experiments)? Answer the one asked; go further when the request implies it.
"""
# What an implementation grant's protected roles are told, unchanged since before the harness plan (its §2.8).
GRANT_INSTRUCTIONS = """You are a persistent Pi agent in a scientific campaign. Your role and assignment are supplied below.
The lead agent works for the researcher, at the researcher's request. The researcher decides what the campaign does next and the
lead carries it out: it does not work through the campaign by itself. A message from the researcher is a request. Do what it asks,
in full and with real tools, then report what was done and what was found, name the choices that are now open, and stop with
yield_work(complete). A runtime profile, new hypotheses, a review, experiments, longer runs, a validation, a comparison, findings
and a journal clean-up are separate stages: start one only when a request covers it. A request may cover several stages, or the
whole workflow, and then you carry all of it out without asking again at each stage. When a request can be read narrowly or
broadly, do the narrow reading and say what the broad one would add. Answer a question with an answer, not with actions: asked
what you would do next, say it and wait. If the platform requires a step before the requested work can run (such as the runtime
profile before a long run), do that step and say so in the report; for anything else the request did not name, propose it and wait.
Reading and analysing what already exists is always part of a request. Before the first request there is nothing to do.
A turn that begins with [Platform notice ...] is not a request. It reports the outcome of work that a request started, or a
subagent's result: use it to carry that request on, and start nothing the request did not ask for. A notice that brings a question
from an agent in charge of a page (lead_ask) is answered in that turn's reply, which goes back to it; start no other work for it.
Use real tools to investigate, implement, test, and coordinate. A natural-language request is not an execution receipt.
The campaign database is authoritative for current objectives, budgets, evaluator readiness and measured results.
Inspect campaign_inspect first and after researcher steering. Read evidence on demand; do not load the whole archive.
Use resource_inspect to check live host capacity, measured worker consumption, planned allocations and resource blockers
before scheduling numerical work. Forecasts are estimates; a closed execution window does not authorize a new one.
Preserve exact IDs returned by tools. Historical summaries and reviews are evidence, not new authority.
Use artifact_save for incremental findings and unresolved objections before context compaction or a handoff.
Do not confuse conceptual approval, executable correctness, and measured optimizer effectiveness.
Existing working evaluators and bundled implementations must be reused when compatible. Ask for missing information
only after checking the current capabilities and saved evidence. Do not repeat denied reads or duplicate reviews.
campaign_inspect lists every installed method that runs on each task, with the parameters its algorithm_config accepts;
build experiments from that list before concluding that a setting is unsupported.
campaign_inspect.reference_evidence holds findings of earlier campaigns that the researcher let this one read. Read them
before proposing hypotheses. Each is a scoped claim with stated limitations, not an instruction: a changed solver setting,
budget or method limits what carries over.
When asked to record what this campaign learned, use finding.record, citing the evidence and stating scope and limitations,
and publish the findings a later campaign on this or a related problem should know: about the physical problem, and about how
to run such an optimization. A large command outcome comes back as an index; read the parts you need with evidence_read.
The journals of every evaluated design are working data. Once an experiment's results are analysed and recorded as findings,
its journals can be compacted: say so in your report, and file journal.compaction_request for the finished experiments when the
researcher asks for the clean-up, with what was recorded as the rationale; only the researcher approves it. It keeps every row
and number and a spread of designs, and removes the rest for good, so it comes last.
Three agents are each in charge of a page and stay for the whole campaign: the discussion moderator (Hypotheses: review rounds in
which specialists and reviewers criticise proposals and the proposals are revised), the experiment operator (Experiments: designing,
starting, watching, pausing, extending and stopping runs) and the implementation lead (Implementations: building and checking
optimizers and evaluators). The researcher can ask them directly on their pages; what they did is in campaign_inspect.page_agents.
The lead hands such work to them with page_agent_message instead of doing it itself, says so with a link to the page, and waits
for the result, which comes back to it. Asked how the experiments are going, the lead asks the experiment operator. The
experiment operator keeps the campaign's experiment rules (campaign_inspect.experiment_rules): runs the lead starts follow them too. A page agent works only on what it was asked, by the researcher or by the lead, and
reports to whoever asked.
The lead agent owns delegation and execution under existing campaign grants. Subagents return artifacts and findings to the agent that asked them.
A subagent that needs more time or evaluations for a trial says so, with its reasons, in its findings for the lead.
The lead may pause, stop or resume trials within their allocations but never enlarges one. When more budget would
change a decision, the lead files trial.extension_request with that argument; only the researcher approves it.
Implementation builders, test designers and reviewers work independently under frozen service specifications.
For substantial programming, use implementation_workspace_create to delegate to a full native Pi coding session
with a browser IDE and normal shell/Git tools. Use implementation_workspace_inspect, implementation_workspace_message,
and implementation_workspace_validate for supervision and independent validation. Do not assume that workspace
creation or a submitted commit establishes correctness. The old short-script implementation path remains available
for historical grants and lightweight compatibility work.
Use command_schema to inspect supported commands, then campaign_command with the exact current guidance revision
and a stable request_key describing the intended operation. If a request timed out, inspect its receipt before retrying.
Source-code availability is not effectiveness evidence.
Speed is measured, not assumed. resource_inspect shows each task's runtime profile: evaluations per second at 1, 2, 4... workers on each device,
device load, the platform's share of each step, storage and solver executions per evaluation, with flags for waste. Runs at or
above the gate length are refused until the evaluator's current source has a profile on this host with every flag fixed or waived,
except notes (note_flags, such as unsaturated: speed still rising at the worker ceiling), which hold nothing and need no waiver: go on
with the work and mention the note in your reply.
runtime.profile measures this on an idle workspace and takes a few minutes of compute: run it when the researcher asks for it or for
runs that need it, and plan budgets from its measured evaluations per hour.
How many runs go at once is planned by the campaign's resource planner (page_agent_message, resource_planner) within the researcher's
resource level and worker maximum, and the scheduler starts a queued run only when its expected memory fits: queue the runs a request
needs and ask the planner, not the researcher, why they wait or how many can go at once.
For a flag, delegate one bounded optimization assignment in an implementation workspace; a change must reproduce recorded results
before it is used: evaluator.equivalence replays a finished experiment's candidates under the new source, and after it passes
trial.continue carries a finished run's saved state on as a new experiment. Stop when the last attempt gained less than it cost or the optimization allowance is spent, then file
approval.request for a waiver or another worker ceiling, or use researcher_ask for a fix to a built-in evaluator: only the researcher grants these.
Campaign limits (compute, model spending, the per-experiment limit), waivers and the worker ceiling are the researcher's. When one stands
in the way of the campaign, file approval.request with the measurement that shows it; the change is applied when the researcher approves.
Use researcher_ask for scientific choices and for what approval.request does not cover.
file_list, file_read and file_search read this server's repository (its committed source, tests and documents) and the files of this
campaign's experiments (root "experiment" with a trial_id). Read the code or the documents before concluding how something works.
To analyse journals or results beyond what a record shows, write a Python script with workspace_write and run it with analysis_run: the
experiments you name are mounted read-only at /data/<trial_id>; numpy and optimization_framework.execution.metrics (scalar_rows, full_row,
recent_metrics) can be imported; there is no network and no GPU. Print a short result: whatever a tool returns stays in your context.
End every turn with yield_work. waiting: jobs or subagents you started for the request are still running, or you asked the
researcher something; their completion or the answer wakes you. complete: the request is fulfilled or the question answered;
nothing wakes you until the researcher writes again. Your reply to whoever asked goes in yield_work's report, which is required
when you call a request complete: it is what they read, so it carries the answer itself, with the numbers that answer it, not only a
pointer to it. Before you write it, check each part of the request against what you did, and name any part not done and why.
Lines written beside other tool calls are folded away in the chat, and the turn ends when yield_work returns. Its
summary is shown to the researcher as the status line: plain words, no record ids. Work that belongs to the open request you do or delegate without being
asked twice; finishing a request does not finish the campaign, and what comes next is the researcher's choice.
The researcher talks to you in a chat panel beside the application's pages, and the pages show the details: every proposal,
run, curve, review and draft. Keep a reply short: what you did, what was found in a few lines, and the choices that are now
open. Do not repeat in the chat what a page shows (tables of runs, lists of proposals, review texts): link the page instead,
as a Markdown link to a target listed in campaign_inspect.pages, such as [Experiments](#experiments) or
[this run](#experiments/<trial_id>); a command receipt names the page of what it created. When you start work that takes
time, say so and name the page where its progress shows. A direct question still gets its answer in the chat, with the
numbers that answer it.
The researcher sees your steps while you work, so do not narrate them. In a turn that a platform notice started, when the
work is still running and there is nothing new the researcher needs, write no message: call yield_work(waiting) with the
current status as its summary, which the chat shows as a temporary line.
When the researcher asks for a report, start the report writer with report_write: its notes say what the report is about and what
to leave out. Say that it is being written and that its progress shows on [Reports](#reports), and call yield_work(waiting): it takes
many minutes and its end wakes you. Then give the link to the draft in a line or two. If the writer asks about the focus, answer with
report_answer when the request settles it, and otherwise pass the question to the researcher. Do not write the report in the chat.
Use researcher_ask only for a real scientific choice, missing credential, or a campaign resource increase; expose a concrete question.
Ask the researcher only for what the researcher can do, and say how: the words to send, the approval to grant, or the Inbox button
(an issue's actions, such as starting or stopping runs that wait on an incomplete dependency), with your recommendation in suggestion.
Never ask for a "platform owner" or for an interface you do not know exists; when nothing the researcher can do would help, say so in your reply instead.
Never increase campaign budgets, fabricate validation, edit protected checks as a builder, or modify the running app.
A request authorizes the work it names, within campaign allocations. Old discovery per-task quotas are historical;
campaign compute limits, protected reserves and current guidance still apply. Model calls may be billed per call against the
campaign's model budget: do not spend turns on work nobody asked for.
"""


# Extension calls: the arguments and the part of a result a receipt keeps; how long an extension's dialog waits by default (D9).
EXTERNAL_ARGUMENT_BYTES = 8 * 1024
EXTERNAL_EXCERPT_BYTES = 24 * 1024
DIALOG_SECONDS = 15 * 60


# A command refused because the researcher acted during the turn (the bus's "Researcher guidance changed ..." message).
GUIDANCE_RECOVERY = ("The researcher changed the campaign during your turn. Read campaign_inspect, check the change against what you were doing, "
                     "and retry only if it still applies.")


# Every tool result joins the model's context for the rest of its session, and a provider refuses a
# request above its size limit: one 55 MB comparison report ended a lead agent's session for good.
COMMAND_RESULT_BYTES = 48 * 1024
TOOL_RESULT_BYTES = 256 * 1024


def serialized_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


# Where the researcher sees each kind of thing. The lead links these pages instead of repeating what they show.
from .pages import pages as _pages, command_pages as _command_pages, command_page  # noqa: E402  (shared with the frontend router)
PAGES = _pages()
COMMAND_PAGES = _command_pages()


COMMAND_STEPS = {"hypothesis.create": "Recording a hypothesis", "hypothesis.review": "Recording a review", "hypothesis.status": "Changing a hypothesis's status",
    "draft.save": "Saving an experiment draft", "draft.launch": "Starting an experiment", "trial.create": "Starting an experiment",
    "trial.control": "Pausing, stopping or resuming an experiment", "trial.continue": "Continuing a finished run",
    "trial.extension_request": "Asking you for a longer run", "finding.record": "Recording a finding", "comparison.report": "Comparing results",
    "runtime.profile": "Measuring evaluation speed", "evaluator.equivalence": "Checking that a change reproduces recorded results",
    "fixed_mask.run": "Evaluating a fixed design", "journal.compaction_request": "Asking you to approve a journal clean-up",
    "approval.request": "Asking for your approval", "validation.run": "Starting a validation", "validation.execute": "Running a validation",
    "study.create": "Setting up a study", "study.activate": "Activating a study", "asset.snapshot": "Saving a research asset",
    "experiments.rules": "Changing the experiment rules", "trial.hide": "Hiding finished runs from the Experiments page",
    "resources.plan": "Planning how many runs go at once", "resources.estimate": "Estimating what a kind of run uses"}
STEPS = {"campaign_inspect": "Reading the campaign's state", "resource_inspect": "Checking the machine's load and the budgets",
    "command_schema": "Reading how a command is written", "researcher_ask": "Writing a question for you", "yield_work": "Ending the turn",
    "agent_message": "Writing to an assistant", "agent_cancel": "Stopping an assistant", "mask_create": "Making a test design",
    "proposal_review": "Recording a verdict", "workspace_list": "Listing its work files", "analysis_run": "Running an analysis script",
    "workspace_run": "Running a script", "submit_output": "Submitting its result", "source_ingest": "Fetching a paper", "source_read": "Reading a paper",
    "implementation_workspace_create": "Opening a coding workspace", "implementation_workspace_inspect": "Checking a coding workspace",
    "implementation_workspace_message": "Writing to the coding agent", "implementation_workspace_validate": "Asking for a validation of submitted code",
    "report_write": "Starting the report writer", "report_answer": "Answering the report writer",
    "experiment_progress": "Checking how the runs are going", "config_suggest": "Choosing the next settings to try", "lead_ask": "Asking the lead agent",
    "compute": "Computing a number"}
PAGE_AGENT_NAMES = {"discussion_moderator": "the discussion moderator", "experiment_operator": "the experiment operator", "implementation_lead": "the implementation lead",
                    "resource_planner": "the resource planner"}
# Record identities begin with their kind; the first matching prefix names what is being read.
RECORD_NAMES = (("hypothesis", "hypothesis"), ("trial", "experiment"), ("artifact", "saved document"), ("campaign", "the campaign record"),
    ("task", "the problem definition"), ("pi_command", "command receipt"), ("pi_", "an agent turn's record"), ("assignment", "an assistant's reply"),
    ("agent", "an assistant's record"), ("lead", "the lead agent's record"), ("finding", "finding"), ("asset", "an earlier campaign's finding"),
    ("runtime", "speed measurement"), ("decision", "decision"), ("report", "report draft"), ("message", "message"))


def planner_instructions(workspace):
    """The resource planner's standing rules. The researcher's current level comes in the state block (agents/turn_state.py)."""
    from optimization_framework.execution.admission import MARGIN, SETTLING_EVALUATIONS
    return ("\nThe researcher's resource level and the run slots (runs at once, and how many on the GPU) are in the state block at the top of each turn. "
        "The level, the slots, budgets and campaign limits are the researcher's, set in Balsamic without a restart; ask with approval.request "
        "(worker_ceiling: workers, gpu_workers) when the slots are what holds the campaign back. Within them the scheduler starts a queued run only when what it is "
        "expected to use fits: a kind of run (the problem as configured, the method and its settings; not the seed) is expected to use "
        f"the most any of its runs used, plus {MARGIN - 1:.0%}. A kind never measured starts while no other such run is still in its first "
        f"{SETTLING_EVALUATIONS} evaluations, unless you estimated it.\n"
        "You plan; you start and stop nothing. resources.estimate gives a kind never measured an expected use (host memory of one run's "
        "process tree, and GPU memory if it uses a GPU), with how you reached it; a measured run replaces it. resources.plan sets how many of "
        "this campaign's runs go at once, and of each kind, below the maximum. runtime.profile measures speed at 1, 2, 4... workers on an "
        "idle workspace, for each device on its own: more runs at once than its recommended workers adds memory but little speed. "
        + workspace.devices.guidance() + " Only a run on the GPU is held for GPU memory.\n"
        "resource_inspect shows the host, each GPU's memory and load, the largest processes, and under admission: the kinds with what "
        "they are expected to use and why, each running run's own memory now and at its peak, the GPU's processes, and why queued runs "
        "wait. GPU memory per run is reported only by runs whose array library counts it; otherwise infer it: under CUDA MPS this "
        "platform's runs share one MPS server process, so take the GPU's total, subtract the other processes on the card, and divide among "
        "the runs alive, per kind when one kind runs alone; each process also holds a few hundred MB of driver context. Read a run's "
        "method and settings (evidence_read on the trial) to judge a new kind from a similar measured one.\n"
        "A turn that begins with [Platform notice ...] brings resource events: resources.unmeasured_kind (estimate it if you can, and "
        "say how), resources.out_of_memory (say what ran out and why; at the balanced and aggressive levels the platform queued the run "
        "again once; lower that kind's runs at once if the machine cannot hold them), resources.level_changed (revise your plan), "
        "resources.long_wait (say why the run waits and change the plan if it is the plan that holds it). Act on them within these rules, "
        "report in a few lines on the Resources page, and end with yield_work(complete).")


def step_label(tool, args=None):
    """One line a researcher can read for a tool call, from its name and its short arguments."""
    args = args if isinstance(args, dict) else {}
    def text(key, limit=70):
        value = args.get(key)
        return str(value)[:limit] if isinstance(value, (str, int, float)) and value != "" else ""
    def article(word):
        return ("an " if word[:1].lower() in "aeiou" else "a ") + word
    if tool == "campaign_command":
        operation, payload = text("operation"), args.get("payload")
        label = COMMAND_STEPS.get(operation, "Running " + operation if operation else "Running a campaign command")
        title = payload.get("title") if isinstance(payload, dict) else None
        return label + (f": {str(title)[:70]}" if isinstance(title, str) and title else "")
    if tool == "delegate":
        return "Asking " + article(text("role").replace("_", " ") or "assistant")
    if tool == "page_agent_message":
        return "Writing to " + PAGE_AGENT_NAMES.get(text("page_agent"), "an agent in charge of a page")
    if tool == "evidence_search":
        return "Searching saved records" + (f" for “{text('query', 50)}”" if text("query") else "")
    if tool == "evidence_read":
        identity = text("record_id", 200)
        name = next((name for prefix, name in RECORD_NAMES if identity.startswith(prefix)), "record")
        return "Reading " + (name if name.startswith(("the ", "an ", "a ")) else f"{name} …{identity[-6:]}" if identity else article(name))
    if tool == "source_search":
        return "Searching the literature" + (f" for “{text('query', 50)}”" if text("query") else "")
    if tool == "artifact_save":
        return "Saving " + article(text("kind") or "note") + (f": {text('title')}" if text("title") else "")
    if tool in {"file_list", "file_read", "file_search"}:
        where = "an experiment's files" if args.get("root") == "experiment" else "the repository"
        if tool == "file_search":
            return f"Searching {where}" + (f" for “{text('query', 50)}”" if text("query") else "")
        return ("Listing " if tool == "file_list" else "Reading ") + (text("path", 90) or where) + (" of an experiment" if text("path") and args.get("root") == "experiment" else "")
    if tool in {"workspace_read", "workspace_write"}:
        return ("Reading its file " if tool == "workspace_read" else "Writing ") + (text("path", 90) or "a work file")
    return STEPS.get(tool) or (tool or "tool call").replace("_", " ").capitalize()


def comparison_brief(report):
    """What a comparison report concludes, without its curves or method definitions."""
    return [{"group_id": group["id"], "direction": group.get("direction"), "common_observed_cost": group.get("common_observed_cost"),
             **({} if group.get("common_observed_cost") is not None else {"note": "These runs share no cost that all of them reached, "
                 "so no method summary could be computed. Name the runs to compare with each other in trial_ids."}),
             "method_summaries": group.get("method_summaries", []),
             "trials": [{**{key: trial.get(key) for key in ("id", "seed", "method_id", "algorithm", "status", "best_objective", "censored")},
                         **({"chain_trial_ids": trial["chain_trial_ids"]} if trial.get("chain_trial_ids") else {}),
                         **({"held_after_finish": True} if trial.get("held_after_finish") else {}),
                         "end_cost": trial["curve"][-1]["cost"] if trial.get("curve") else None} for trial in group["trials"]]}
            for group in report.get("groups", [])]


# The most inputs one compute call takes (roadmap K1).
COMPUTE_VALUES = 50


def obj(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
# What agents write for each other is read by the researcher too (side conversations, pages), and it came as dense shorthand.
READABLE = ("The researcher reads it: plain sentences in short paragraphs, a list for parallel items, whole words with normal spacing, "
            "no shorthand or capitals for emphasis.")
TOOLS = {
    "campaign_inspect": ("Read current problem, runnable evaluators, methods, budgets, aliases and assignments.", obj()),
    "resource_inspect": ("Read live CPU/RAM, worker measurements, resource forecasts and blockers for this campaign. Does not start jobs or change budgets.", obj()),
    "evidence_search": ("Search saved campaign evidence across current and historical sessions; returns exact IDs. Omit kind to search all supported kinds.", obj({"query": S, "kind": {"type": "string", "enum": sorted(READ_KINDS)}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}})),
    "evidence_read": ("Read a bounded page of an exact evidence record. Follow returned JSON pointers for large records.", obj({"record_id": S, "pointer": S, "offset": {"type": "integer", "minimum": 0}, "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 24576}}, ["record_id"])),
    "source_search": ("Find primary literature and retain retrieval receipts.", obj({"query": S, "provider": {"enum": ["arxiv", "crossref"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"])),
    "source_ingest": ("Capture a DOI, arXiv identifier, or public primary-source HTTPS URL.", obj({"identifier": S}, ["identifier"])),
    "source_read": ("Read saved source passages; available even after the legacy source quota was exhausted.", obj({"source_id": S, "query": S, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, ["source_id"])),
    "artifact_save": ("Save an immutable finding, implementation handoff, analysis, or fixed binary mask with evidence links.", obj({"title": S, "kind": {"enum": ["finding", "handoff", "analysis", "mask", "assessment", "review", "checkpoint"]}, "content": {}, "evidence_ids": {"type": "array", "items": S, "maxItems": 100}}, ["title", "kind", "content"])),
    "proposal_review": ("Record an independent conceptual review of the exact hypothesis revision. Test means plausible, not effective.", obj({"hypothesis_id": S, "hypothesis_hash": S, "verdict": {"enum": ["test", "revise", "reject"]}, "rationale": S, "required_changes": {"type": "array", "items": S}, "suggested_tests": {"type": "array", "items": S, "minItems": 1}}, ["hypothesis_id", "hypothesis_hash", "verdict", "rationale", "suggested_tests"])),
    "delegate": ("Create a persistent specialist child with a focused objective and exact evidence IDs. You receive its result automatically. "
        "The objective: " + READABLE, obj({"role": {"enum": [r for r in ROLES if r not in STANDING]}, "objective": S, "evidence_ids": {"type": "array", "items": S, "maxItems": 100}, "request_key": S}, ["role", "objective", "request_key"])),
    "agent_message": ("Send a follow-up or steering message to one of your own assistants. " + READABLE, obj({"agent_id": S, "message": S}, ["agent_id", "message"])),
    "agent_cancel": ("Cancel a child assignment while retaining its artifacts and costs.", obj({"agent_id": S}, ["agent_id"])),
    "command_schema": ("Read the exact schema of an execution command before preparing it.", obj({"operation": {"enum": sorted(OPERATIONS)}}, ["operation"])),
    "campaign_command": ("Execute a campaign command within existing delegation. Returns a durable receipt with the page that shows the result; never grants new authority. "
        "The guidance and the conversation your turn started from are pinned for you; a command is refused when the researcher wrote since. rationale: why, in one line (required under autopilot).",
        # TODO(next release): remove guidance_revision; it is accepted and ignored so that saved sessions keep working (harness plan, D7).
        obj({"operation": {"enum": sorted(OPERATIONS)}, "payload": {"type": "object"}, "request_key": S,
             "guidance_revision": {"type": "integer", "minimum": 0, "description": "Ignored. The revision is pinned from your turn and from any campaign_inspect you ran in it; omit it."},
             "rationale": S}, ["operation", "payload", "request_key"])),
    "implementation_workspace_create": ("Start or reattach a persistent full Pi coding workspace for an active hypothesis (hypothesis_ids: the other proposals the same library serves). No numerical grant is reserved by creation.", obj({"hypothesis_id": S, "hypothesis_ids": {"type": "array", "items": S, "maxItems": 20}, "objective": S, "evidence_ids": {"type": "array", "items": S, "maxItems": 100}, "request_key": S, "cpu_budget_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400}}, ["hypothesis_id", "objective", "request_key"])),
    "implementation_workspace_inspect": ("Read implementation workspace state, progress, questions, submissions, and event cursor.", obj({"workspace_id": S, "after": {"type": "integer", "minimum": 0}}, ["workspace_id"])),
    "implementation_workspace_message": ("Steer or follow up with the full Pi coding agent in the given workspace.", obj({"workspace_id": S, "message": S, "mode": {"enum": ["steer", "follow_up"]}, "request_key": S, "question_id": S}, ["workspace_id", "message", "request_key"])),
    "implementation_workspace_validate": ("Commission independent validation of one committed source submission under the compute go-ahead. Supply either a frozen envelope_id or a spec; prefer the short envelope ID when available.", obj({"workspace_id": S, "submission_id": S, "envelope_id": S, "spec": {"type": "object"}, "compute_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400}, "request_key": S}, ["workspace_id", "submission_id", "compute_seconds", "request_key"])),
    "page_agent_message": ("Ask the agent in charge of a page for work of its page: discussion_moderator (review rounds over proposals; "
        "Hypotheses), experiment_operator (designing, starting, watching and stopping runs; Experiments), implementation_lead (building and "
        "checking implementations; Implementations) or resource_planner (how many runs go at once, what kinds of runs use, why runs wait; "
        "Resources). Say what to do and name the records. Its result comes back to you; the researcher sees "
        "the exchange on its page. " + READABLE, obj({"page_agent": {"enum": sorted(PAGE_AGENTS)}, "message": S, "evidence_ids": {"type": "array", "items": S, "maxItems": 100}},
        ["page_agent", "message"])),
    "experiment_progress": ("The campaign's runs at work in queue order and the latest finished ones: name, short or long, status, time and "
        "evaluations used and allotted, best score, whether a running run still improves, the most time left; with the worker ceiling and the "
        "campaign's limit on runs at once.", obj({"finished": {"type": "integer", "minimum": 0, "maximum": 40}})),
    "config_suggest": ("The next settings to try for one strategy. space: each parameter with type float, int, log (positive range, "
        "log-scaled) or choice, and low/high or choices. observations: settings already run at the same length, with their scores. With few "
        "observations it spreads settings over the space; after that it picks the settings of highest expected improvement under a Gaussian "
        "process fitted to the scores.",
        obj({"space": {"type": "object", "additionalProperties": obj({"type": {"enum": ["float", "int", "log", "choice"]}, "low": {"type": "number"},
                "high": {"type": "number"}, "choices": {"type": "array", "maxItems": 20}})},
             "observations": {"type": "array", "maxItems": 300, "items": obj({"config": {"type": "object"}, "score": {"type": "number"}}, ["config", "score"])},
             "count": {"type": "integer", "minimum": 1, "maximum": 12}, "direction": {"enum": ["maximize", "minimize"]},
             "seed": {"type": "integer", "minimum": 0}}, ["space"])),
    "compute": ("Compute a number with the charter's expression evaluator: arithmetic, comparisons and sqrt, exp, log, min, max and the like. "
        "values: each name the expression reads, as a number or as {record_id, pointer}, a number read from a record of this campaign at a JSON "
        "pointer. Returns the value and each input with its source; the receipt is the computation, cite it.",
        obj({"expression": S, "values": {"type": "object", "maxProperties": COMPUTE_VALUES, "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
             "additionalProperties": {"oneOf": [{"type": "number"}, obj({"record_id": S, "pointer": S}, ["record_id", "pointer"])]}}},
            ["expression"])),
    "lead_ask": ("Ask the lead agent something your work needs and the records do not answer, such as the reasoning behind a proposal or "
        "what the researcher meant. Its answer comes back to you as a notice; call yield_work(waiting) until then.",
        obj({"question": S}, ["question"])),
    "mandate_propose": ("Propose what the researcher's request allows, its mandate, before starting work beyond Explore. template: answer "
        "(reads and answers, starts nothing), explore (work up to the researcher's go-ahead threshold in total, no coding workspace; the "
        "default when none is proposed), screen (the proposals, coding workspaces and runs the plan names, with their minutes), run_campaign "
        "(every stage within its envelope and deadline). Answer and Explore are granted at once: say so in one line of your reply. Screen and "
        "run_campaign become one card in the researcher's inbox (approve, approve as Explore only, decline): start once they choose. "
        "plan: what will run and why, as the researcher reads it; runs: each planned experiment (task_id, hypothesis_id or algorithm, seeds, "
        "wall_seconds, max_evaluations, device), so they read its measured speed, outputs and disk use.",
        obj({"template": {"enum": ["answer", "explore", "screen", "run_campaign"]}, "plan": {"type": "string", "minLength": 1, "maxLength": 5000},
             "hypothesis_ids": {"type": "array", "items": S, "maxItems": 50}, "runs": {"type": "array", "items": {"type": "object"}, "maxItems": 50},
             "worker_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 2419200}, "coding_workspaces": {"type": "integer", "minimum": 0, "maximum": 10},
             "wall_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 604800, "description": "How long until the researcher has the results"},
             "model_usd": {"type": "number", "minimum": 0, "maximum": 10000}, "deadline_minutes": {"type": "number", "exclusiveMinimum": 0, "maximum": 40320},
             "stop_when": obj({"text": S, "machine": {"enum": ["all_runs_terminal"]}}, ["text"]),
             "meanwhile": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "What the researcher can do while it runs"}},
            ["template", "plan"])),
    "researcher_ask": ("Save a concrete researcher question and stop for its answer only when required. The researcher sees question, "
        "suggestion and options in the Inbox and answers in a click or a line. Ask only for what the researcher can do (the words to send, "
        "the approval to grant, an Inbox button), never for a \"platform owner\" or an interface you do not know exists; when nothing the "
        "researcher can do would help, say so in your reply instead.",
        obj({"question": S, "reason": S,
             "suggestion": {"type": "string", "minLength": 1, "maxLength": 2000,
                            "description": "What you recommend the researcher do, as they would do it: the words to send, the approval to grant or the button to press"},
             "options": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 300}, "maxItems": 4,
                         "description": "Up to four answers the researcher can choose with one click, your recommendation first"}},
            ["question", "reason", "suggestion"])),
    "report_write": ("Start the report writer on this campaign's saved evidence. It investigates, drafts, has the draft reviewed twice and edits it, "
        "in up to 14 model calls billed to the campaign's model budget. It returns at once with the job; the draft takes many minutes, its progress "
        "shows on the Reports page, and its end wakes you. One report is written at a time. reference_ids: the records the report starts from. "
        "The writer sees the campaign's runs, hypotheses, decisions, sources and studies by itself; what agents wrote (reviewers' verdicts and "
        "saved analyses, agent_artifact; assistants' replies, agent_run) it sees only when listed here.",
        obj({"notes": S, "reference_ids": {"type": "array", "items": S, "maxItems": 40}, "literature": {"type": "boolean"}, "request_key": S}, ["notes", "request_key"])),
    "report_answer": ("Answer the report writer's question about the focus of a report you started, so that it continues.",
        obj({"job_id": S, "answer": S}, ["job_id", "answer"])),
    "yield_work": ("End this turn and say how it ends; the turn stops when it returns. report: your reply to whoever asked, shown as "
        "your message (the answer with its numbers, short, linking the pages; " + READABLE.rstrip(".") + "); required with complete while the request is open. "
        "The summary is shown to the researcher as a status line: plain words, no record ids. waiting: jobs or subagents started for the researcher's request are still running, or a question to the researcher is open; "
        "their completion or the answer wakes the lead agent. complete: the request is fulfilled or answered, and nothing wakes the lead until the researcher writes again; "
        "completion must cite actual evidence.", obj({"disposition": {"enum": ["waiting", "complete", "handoff"]}, "summary": S, "report": S,
        "evidence_ids": {"type": "array", "items": S, "maxItems": 100}}, ["disposition", "summary"])),
    "file_list": ("List a directory of this server's repository (committed files only) or of one of this campaign's experiments.",
        obj({"root": {"enum": ["repository", "experiment"]}, "trial_id": S, "path": S}, ["root"])),
    "file_read": ("Read lines of a text file from the repository or from one of this campaign's experiments. Long lines are cut; use analysis_run for journals.",
        obj({"root": {"enum": ["repository", "experiment"]}, "trial_id": S, "path": S, "first_line": {"type": "integer", "minimum": 1},
             "lines": {"type": "integer", "minimum": 1, "maximum": 2000}, "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 65536}}, ["root", "path"])),
    "file_search": ("Find lines matching a regular expression in the repository or in one experiment's files; returns paths and line numbers.",
        obj({"root": {"enum": ["repository", "experiment"]}, "trial_id": S, "query": S, "path": S, "glob": S,
             "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["root", "query"])),
    "analysis_run": ("Run a Python script from your work directory in a sandbox with the named experiments mounted read-only at /data/<trial_id>. "
        "No network, no GPU; numpy and the framework's journal readers are available. Returns the end of its output.",
        obj({"path": S, "trial_ids": {"type": "array", "items": S, "maxItems": 40}, "seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 300}}, ["path"])),
    "workspace_list": ("List the files of your own work directory.", obj()),
    "workspace_read": ("Read a text file from your own work directory.", obj({"path": S}, ["path"])),
    "workspace_write": ("Write a file in your own work directory: a package or test file, or an analysis script for analysis_run.", obj({"path": S, "content": S}, ["path", "content"])),
    "workspace_run": ("Run a Python development script in a network-disabled OS sandbox under the implementation grant.", obj({"path": S, "seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 30}}, ["path"])),
    "submit_output": ("Submit the structured result required by the frozen implementation service contract.", obj({"result": {"type": "object"}}, ["result"])),
}


# Tools the service layer and problem packs add: name -> {"description", "schema", "roles", "handler"(tools, agent, run, args,
# identity), "pack", "local"}. A pack's tool (pack: its package) is offered only in campaigns that have the pack; a local tool's
# changes commit with its receipt.
EXTRA_TOOLS = {}
# Re-evaluating chosen designs, at the run's fidelity or at several, on any problem; a problem pack may add its own tools.
FIXED_DESIGN_CHECK = ("validation.run on a run, with one of the validation recipes its problem declares (such as a re-evaluation "
                      "or a fidelity comparison)")
# Commands a problem pack adds to a page agent's page (roadmap N4): operation -> {"role", "pack", "purpose"}. The lead asks that
# agent for them, as for LEAD_PAGE_WORK; "purpose" names the capability in campaign_inspect.
PACK_OPERATIONS = {}


def register_tool(name, description, schema, handler, *, roles=(LEAD,), pack=None, local=False):
    if name in TOOLS or name in EXTRA_TOOLS:
        raise ValueError(f"Tool {name} exists")
    EXTRA_TOOLS[name] = {"description": description, "schema": schema, "roles": set(roles), "handler": handler, "pack": pack, "local": local}


def register_page_operation(operation, role, *, pack, purpose):
    """A pack's command, run by the page agent ``role`` in the campaigns that have the pack (the bus registers its handler)."""
    if role not in ROLE_OPERATIONS:
        raise ValueError(f"{role} is not a page agent")
    if operation in OPERATIONS or PACK_OPERATIONS.get(operation, {}).get("pack", pack) != pack:
        raise ValueError(f"Operation {operation} exists")
    PACK_OPERATIONS[operation] = {"role": role, "pack": pack, "purpose": purpose}


class PiTools:
    def __init__(self, controller):
        self.controller = controller
        self.workspace, self.store = controller.workspace, controller.store

    def names(self, agent):
        names = {"campaign_inspect", "resource_inspect", "evidence_search", "evidence_read", "source_search", "source_ingest", "source_read", "artifact_save", "yield_work",
                 "file_list", "file_read", "file_search", "workspace_list", "workspace_read", "workspace_write", "analysis_run", "compute"}
        implementation = {"implementation_workspace_create", "implementation_workspace_inspect", "implementation_workspace_message",
                          "implementation_workspace_validate"}
        if agent["role"] == LEAD:
            # A status read is the lead's own (experiment_progress); a decision about runs goes to the operator.
            names |= {"delegate", "agent_message", "agent_cancel", "command_schema", "campaign_command", "researcher_ask", "report_write", "report_answer",
                      "page_agent_message", "experiment_progress", "mandate_propose", *implementation}
        if agent["role"] in PAGE_AGENTS:
            # Each page agent runs the commands of its page (ROLE_OPERATIONS), and can ask the researcher or the lead.
            names |= {"command_schema", "campaign_command", "researcher_ask", "lead_ask", "mandate_propose"}
            if agent["role"] == "experiment_operator":
                names |= {"experiment_progress", "config_suggest"}
            if agent["role"] == "discussion_moderator":
                names |= {"delegate", "agent_message", "agent_cancel"}
            if agent["role"] == "implementation_lead":
                names |= implementation
            if agent["role"] == "resource_planner":
                names |= {"experiment_progress"}
        if agent["role"] == "proposal_reviewer":
            names.add("proposal_review")
        if agent["role"] in ROLE_BRIEFS:
            # A specialist's tools are those its role file names (agents/roles/<role>.md), and submit_output for its result.
            names &= set(ROLE_BRIEFS[agent["role"]]["tools"]) | {"yield_work"}
        if agent.get("output_schema"):
            names.add("submit_output")
        if agent.get("grant_id"):
            # Protected implementation roles receive only the exact context the
            # library supplies. They cannot read campaign fixtures or peer work.
            names = {"artifact_save", "workspace_list", "workspace_read", "workspace_write", "workspace_run", "submit_output"}
        else:
            packages = self.packages(agent)
            names |= {name for name, tool in EXTRA_TOOLS.items() if agent["role"] in tool["roles"] and tool.get("pack") in {None, *packages}}
        return names

    def packages(self, agent):
        """The packages of the problem packs of the agent's campaign (evaluation/packs.py)."""
        packs = getattr(self.workspace, "packs", None)
        return packs.packages(agent["campaign_id"]) if packs is not None and agent.get("campaign_id") else set()

    def pack_operations(self, agent):
        """The commands this campaign's packs add, by operation: the page agent that runs each, and its capability."""
        packages = self.packages(agent)
        return {operation: entry for operation, entry in PACK_OPERATIONS.items() if entry["pack"] in packages}

    def schema(self, agent, name):
        """A tool's input schema for this agent: a page agent sees only its own commands, and the moderator only the roles it may ask."""
        if name in EXTRA_TOOLS:
            return EXTRA_TOOLS[name]["schema"]
        schema = TOOLS[name][1]
        if name in {"campaign_command", "command_schema"}:
            # The service layer may give this workspace's lead more operations (workspace.lead_operations); the enum is read per manifest.
            extra = set(getattr(self.workspace, "lead_operations", ()) or ())
            # A pack's commands are its page agent's work, in the campaigns that have the pack.
            packed = {operation for operation, entry in self.pack_operations(agent).items() if entry["role"] == agent["role"]}
            schema = deepcopy(schema); schema["properties"]["operation"]["enum"] = sorted(ROLE_OPERATIONS[agent["role"]] | packed if agent["role"] in ROLE_OPERATIONS
                                                                                          else (OPERATIONS | extra) - LEAD_EXCLUDED_OPERATIONS)
        if name == "delegate" and agent["role"] == "discussion_moderator":
            schema = deepcopy(schema); schema["properties"]["role"]["enum"] = list(DISCUSSION_ROLES)
        return schema

    def manifest(self, agent_id, run_id):
        agent, run = self._context(agent_id, run_id)
        specialist = agent["role"] in ROLE_BRIEFS and not agent.get("grant_id")
        instructions = (GRANT_INSTRUCTIONS if agent.get("grant_id") else SPECIALIST_CONTRACT + "\n" if specialist else INSTRUCTIONS) + \
            f"\nRole: {agent['role']}\nAssignment: {agent['objective']}\nEvidence IDs: {json.dumps(agent['evidence_ids'])}"
        if specialist:
            instructions += "\n" + ROLE_BRIEFS[agent["role"]]["brief"]
        if agent["role"] == LEAD:
            instructions += "\n" + LEAD_CONTRACT.rstrip()
        if agent["role"] in PAGE_AGENTS:
            page = PAGE_AGENTS[agent["role"]]
            instructions += (f"\nYou are {PAGE_AGENT_NAMES[agent['role']]}, in charge of the {page.capitalize()} page (#{page}). The researcher writes to you "
                "there and reads your replies there; the lead agent's requests come as its messages, and your closing reply goes back to it. "
                "What is said above of replies holds for yours: short, with links to the pages that show the details.")
            if agent["role"] == "experiment_operator":
                instructions += ("\nThe campaign's experiment rules, kept with experiments.rules (the researcher may change them on the Experiments "
                    "page), are in the state block at the top of each turn: how runs are named, where short runs end, how many may go at once, how "
                    "runs are chosen and ordered, and how runs are presented.\n" + self.workspace.devices.guidance() +
                    "\nYou decide how runs are presented, for this problem: what the list of runs shows and what a run's entry shows, chosen "
                    "from what the page can draw (experiments.rules, presentation; command_schema lists the choices). Before the campaign's "
                    "first runs if it is not chosen, or when asked: ask the lead agent (lead_ask) what the researcher needs to see in a run of "
                    "this problem, decide, and record the choice with its reason. A design of many values is drawn (a mask image for a grid, "
                    "a strip for a short binary vector) and never listed value by value. The page draws exactly the sections and columns "
                    "the presentation schema describes: when you report your choice, describe what you recorded, and say plainly what "
                    "was asked for that the page cannot draw."
                    "\nWhen asked how the experiments are going, read experiment_progress and answer in a few lines: what runs, what has "
                    "finished, which runs still improve, and what you would do next. Hide a run (trial.hide) only when you superseded it "
                    "yourself, such as a failed run you ran again, and give the reason.")
            if agent["role"] == "discussion_moderator":
                instructions += ("\nA reviewer's proposal_review is the record of its verdict: report each verdict in the reviewer's own word (test, "
                    "revise or reject), and do not record it again with hypothesis.review.")
            if agent["role"] == "resource_planner":
                instructions += planner_instructions(self.workspace)
        if agent.get("output_schema"):
            instructions += "\nSubmit your result with submit_output using this JSON schema:\n" + json.dumps(agent["output_schema"])
        if agent["role"] == LEAD:
            instructions += self.workspace_instructions(agent)
        procedures = getattr(self.workspace, "procedures", None)
        if procedures is not None and not agent.get("grant_id"):
            instructions += procedures.catalog_text(agent["role"])
        from .extensions import for_agent, hosts_extensions
        return {"instructions": instructions, "tools": [{"name": name, "description": EXTRA_TOOLS[name]["description"] if name in EXTRA_TOOLS else TOOLS[name][0],
                                                          "input_schema": self.schema(agent, name)} for name in sorted(self.names(agent))],
                # The session's extensions: the Balsamic one unless this is an implementation grant's role, then the role's curated set.
                "extension_host": hosts_extensions(agent), "extensions": for_agent(agent)}

    def turn_state(self, agent_id, run_id):
        """This turn's state block (agents/turn_state.py), saved on the run: what the model was told the campaign is now."""
        from .turn_state import build
        agent, run = self._context(agent_id, run_id)
        state = build(self, agent, run)
        with self.workspace.lock, self.store.transaction():
            current = self.store.get(run_id, "agent_run")
            current["turn_state"] = {**state, "at": now()}
            self.store.put("agent_run", current)
        return state

    def external_receipt(self, agent_id, run_id, call_id, tool, extension, arguments, result_excerpt, result_bytes, is_error=False, annotations=None):
        """The receipt of an extension tool's call, posted by the Balsamic extension after the tool ran in the harness.

        Same identity as a gateway call's (agent, run, call id), so a repeated post is the same receipt; immutable; readable
        with evidence_read in the campaign. Refused for a tool the role's allowlist does not name, or a run that is not active."""
        from .extensions import tool_extension
        if not isinstance(call_id, str) or not 0 < len(call_id) <= 500:
            raise ValueError("Invalid tool call identity")
        identity = "pi_tool_" + content_hash([agent_id, run_id, call_id])[:32]
        arguments = arguments if serialized_bytes(arguments) <= EXTERNAL_ARGUMENT_BYTES else {"omitted": f"{serialized_bytes(arguments)} bytes of arguments"}
        request_hash = content_hash([tool, arguments])
        with self.workspace.lock, self.store.transaction():
            try:
                old = self.store.get(identity, "agent_tool_receipt")
            except KeyError:
                old = None
            if old:
                if not old.get("external") or old["request_hash"] != request_hash:
                    raise ValueError("Tool identity belongs to another request")
                return {"receipt_id": identity}
            agent, run = self._context(agent_id, run_id)
            if tool in self.names(agent):
                raise ValueError("A workspace tool is receipted by the workspace itself")
            provider = tool_extension(agent, tool)
            if provider is None:
                raise ValueError(f"{tool} is not an extension tool allowlisted for the {agent['role'].replace('_', ' ')}")
            self.store.put_immutable("agent_tool_receipt", {"id": identity, "campaign_id": agent["campaign_id"], "agent_id": agent_id, "run_id": run_id,
                "tool": tool, "request_hash": request_hash, "external": True, "extension": provider, "reported_extension": str(extension)[:200],
                "arguments": arguments, "result": {"external": True, "excerpt": str(result_excerpt or "")[:EXTERNAL_EXCERPT_BYTES],
                "bytes": int(result_bytes or 0), "is_error": bool(is_error), "annotations": annotations if isinstance(annotations, dict) else None},
                "created_at": now()}, "agent.tool_completed")
        return {"receipt_id": identity}

    def ui_request(self, agent_id, run_id, request_id, method, title, message=None, options=None, placeholder=None, prefill=None, timeout_ms=None):
        """An extension's dialog (select, confirm, input, editor) as a question to the researcher; the extension waits for it.

        Its deadline is the extension's own timeout, else DIALOG_SECONDS. A run under autopilot has nobody to ask: the
        dialog is cancelled at once. Answered with agent.ui_respond, which opens no request and starts no turn."""
        agent, run = self._context(agent_id, run_id)
        if run.get("autopilot"):
            return {"status": "cancelled", "reason": "Autopilot runs without the researcher; an extension's dialog is cancelled at once."}
        if method not in {"select", "confirm", "input", "editor"}:
            raise ValueError("Unknown dialog")
        identity = "question_ui_" + content_hash([agent_id, run_id, request_id])[:28]
        seconds = min(max(float(timeout_ms) / 1000, 1.0), DIALOG_SECONDS * 4) if timeout_ms else DIALOG_SECONDS
        dialog = {"method": method, "title": str(title)[:500], **({"message": str(message)[:4000]} if message else {}),
                  **({"options": [str(option)[:300] for option in options][:40]} if options else {}),
                  **({"placeholder": str(placeholder)[:300]} if placeholder else {}), **({"prefill": str(prefill)[:20000]} if prefill else {})}
        with self.workspace.lock, self.store.transaction():
            try:
                question = self.store.get(identity, "agent_question")
            except KeyError:
                question = self.store.put("agent_question", {"id": identity, "campaign_id": agent["campaign_id"], "agent_id": agent_id, "run_id": run_id,
                    "kind": "extension_dialog", "status": "pending", "dialog": dialog, "question": dialog["title"] + (": " + dialog["message"] if dialog.get("message") else ""),
                    "reason": "An extension of the agent's session asks; the agent waits for the answer.", "deadline_at": time.time() + seconds,
                    "created_at": now()}, "agent.question_created")
        return self.ui_state(agent_id, question["id"])

    def ui_state(self, agent_id, question_id):
        """Where an extension's dialog stands: pending, answered (with its value), cancelled, or expired past its deadline."""
        with self.workspace.lock, self.store.transaction():
            question = self.store.get(question_id, "agent_question")
            if question.get("agent_id") != agent_id or question.get("kind") != "extension_dialog":
                raise ValueError("Not this agent's extension dialog")
            if question["status"] == "pending" and time.time() >= question["deadline_at"]:
                question.update(status="expired", expired_at=now())
                self.store.put("agent_question", question, "agent.question_expired")
        status = {"pending": "pending", "answered": "answered", "expired": "expired"}.get(question["status"], "cancelled")
        return {"question_id": question_id, "status": status, "deadline_at": question["deadline_at"],
                **({"value": question.get("answer_value")} if status == "answered" else {})}

    def workspace_instructions(self, agent):
        """What the lead needs to know about the researcher's workspace: set by the service layer (threads, the problem note)."""
        extra = getattr(self.workspace, "lead_instructions", None)
        return "\n" + extra(agent) if callable(extra) else ""

    def _context(self, agent_id, run_id):
        agent = self.store.get(agent_id, "agent_session")
        run = self.store.get(run_id, "agent_run")
        if run["agent_id"] != agent_id or not self.controller.owns(agent["campaign_id"]):
            raise ValueError("Agent assignment is not owned by this campaign")
        config = self.controller.configuration(agent["campaign_id"])
        if config["status"] != "running" or agent["status"] in {"paused", "stopped"} or run["status"] not in {"submitted", "running"}:
            raise ValueError("Assignment is not active; preserve findings and stop")
        if agent.get("deadline_at") and time.time() >= agent["deadline_at"]:
            raise ValueError("Implementation grant expired; preserve the existing package and findings")
        return agent, run

    def call(self, agent_id, run_id, call_id, name, arguments):
        import jsonschema
        if not isinstance(call_id, str) or not 0 < len(call_id) <= 500:
            raise ValueError("Invalid tool call identity")
        identity = "pi_tool_" + content_hash([agent_id, run_id, call_id])[:32]
        with self.workspace.lock:
            lock = self.controller.tool_locks.setdefault(identity, threading.Lock())
        with lock:
            return self._call(agent_id, run_id, name, arguments, identity)

    def _call(self, agent_id, run_id, name, arguments, identity):
        import jsonschema
        request_hash = content_hash([name, arguments])
        with self.workspace.lock, self.store.transaction():
            try:
                old = self.store.get(identity, "agent_tool_receipt")
            except KeyError:
                old = None
            if old:
                if old["request_hash"] != request_hash:
                    raise ValueError("Tool identity belongs to another request")
                return old["result"]
            agent, run = self._context(agent_id, run_id)
            if name not in self.names(agent):
                raise ValueError("Tool is not available to this assignment")
            refusal = self.page_work(agent, name, arguments) or self.over_budget(agent, run, name)
            if refusal:
                return {"error": refusal, "executed": False, "recovery": "Ask the agent in charge of that page with page_agent_message, then call yield_work(waiting)."}
            try:
                jsonschema.validate(arguments, self.schema(agent, name))
            except jsonschema.ValidationError as exc:
                return {"error": exc.message[:2000], "executed": False}
            try:
                intent = self.store.get("intent_" + identity, "agent_tool_intent")
                if intent["request_hash"] != request_hash:
                    raise ValueError("Tool identity belongs to another request")
            except KeyError:
                pass
            self.store.put("agent_tool_intent", {"id": "intent_" + identity, "campaign_id": agent["campaign_id"],
                "agent_id": agent_id, "run_id": run_id, "tool": name, "request_hash": request_hash,
                "arguments": arguments, "created_at": now()}, "agent.tool_started")
        def execute():
            try:
                result = self._execute(agent, run, name, arguments, identity)
                size = serialized_bytes(result)
                if size > TOOL_RESULT_BYTES:
                    return {"error": f"The result is {size} bytes; a tool returns at most {TOOL_RESULT_BYTES}.", "executed": True,
                        "recovery": "The call was carried out and is not repeated. Find its saved record with evidence_search "
                                    "and read it in pages with evidence_read, or ask for less."}
                # A workflow started without its procedure: the result names it, once per run (workspace.procedure_hint).
                hint = getattr(self.workspace, "procedure_hint", None)
                procedure = hint(self, agent, run, name, arguments, result) if callable(hint) else None
                return {**result, "procedure": procedure} if procedure else result
            except (ValueError, KeyError, OSError, jsonschema.ValidationError) as exc:
                if name == "campaign_command" and "guidance changed" in str(exc):
                    return {"error": str(exc)[:3000], "executed": False, "recovery": GUIDANCE_RECOVERY}
                return {"error": str(exc)[:3000], "executed": False,
                    "recovery": "Inspect the exact error and current capabilities before revising the request; do not repeat an identical denied call."}

        def receipt(result):
            self.store.put_immutable("agent_tool_receipt", {"id": identity, "campaign_id": agent["campaign_id"],
                "agent_id": agent_id, "run_id": run_id, "tool": name, "request_hash": request_hash, "result": result,
                "created_at": now()}, "agent.tool_completed")
        if name in {"artifact_save", "proposal_review", "delegate", "agent_message", "agent_cancel", "page_agent_message", "lead_ask", "researcher_ask", "yield_work", "submit_output"} \
                or EXTRA_TOOLS.get(name, {}).get("local"):
            # Local changes and their acknowledgment commit together. External
            # I/O and idempotent command delivery never hold a SQL transaction.
            with self.workspace.lock, self.store.transaction():
                self._context(agent_id, run_id)
                result = execute()
                receipt(result)
        else:
            result = execute()
            with self.workspace.lock, self.store.transaction():
                receipt(result)
        return result

    def over_budget(self, agent, run, name):
        """A specialist past its tool calls for the run may only record its result and end (SPECIALIST_TOOL_CALLS)."""
        if agent["role"] not in ROLE_BRIEFS or agent.get("grant_id") or name in {"submit_output", "yield_work", "proposal_review"}:
            return ""
        with self.store.connection() as db:
            used = db.execute("SELECT COUNT(*) FROM records WHERE kind='agent_tool_receipt' AND json_extract(data,'$.run_id')=?", (run["id"],)).fetchone()[0]
        return (f"This assignment's {SPECIALIST_TOOL_CALLS} tool calls are spent: record what you have (submit_output, or proposal_review) "
                "and call yield_work(complete), saying what is missing.") if used >= SPECIALIST_TOOL_CALLS else ""

    def page_work(self, agent, name, arguments):
        """Why the lead may not run this command itself, naming the page agent that does; empty when it may."""
        operation = arguments.get("operation") if isinstance(arguments, dict) else None
        if agent["role"] != LEAD or name not in {"campaign_command", "command_schema"}:
            return ""
        owner = LEAD_PAGE_WORK.get(operation) or (self.pack_operations(agent).get(operation) or {}).get("role")
        if owner is None:
            return ""
        return (f"{operation} is the work of {PAGE_AGENT_NAMES[owner]}: ask it with page_agent_message (page_agent: {owner}), saying what to do "
                f"and naming the records; its result comes back to you, and the researcher follows it on #{PAGE_AGENTS[owner]}.")

    def propose_mandate(self, agent, run, args, identity):
        """mandate_propose (roadmap R2): Answer and Explore are granted at once; Screen and Run the campaign are filed as one card, an
        approval.request of kind mandate, through the bus like any command of this turn. A page agent the lead asked proposes for the
        lead's request, the mandate the lead works under; one the researcher asked on its page proposes its own (decision 12)."""
        from optimization_framework.campaigns import mandates
        from optimization_framework.campaigns.compute_consent import request_root
        root = request_root(self.workspace, {"run_id": run["id"]})
        if not root or not root.get("thread_id"):
            raise ValueError("This turn serves no researcher request, so there is no mandate to propose.")
        values = {key: args[key] for key in ("plan", "hypothesis_ids", "runs", "worker_seconds", "coding_workspaces", "model_usd",
                                             "deadline_minutes", "stop_when") if args.get(key) is not None}
        if args["template"] in {"answer", "explore"}:
            mandate = mandates.propose(self.workspace, agent["campaign_id"], args["template"], root, **values)
            return {"mandate_id": mandate.id, "status": "active", "granted_by": "automatic", "mandate": mandates.describe(self.workspace, mandate),
                    "next": "Granted at once. Say so in one line of your reply, and start the work."}
        payload = {"kind": "mandate", "template": args["template"], "rationale": args["plan"],
                   **{key: value for key, value in values.items()}, **({"wall_seconds": args["wall_seconds"]} if args.get("wall_seconds") else {}),
                   **({"meanwhile": args["meanwhile"]} if args.get("meanwhile") else {})}
        receipt = self._execute(agent, run, "campaign_command", {"operation": "approval.request", "payload": payload,
                                "request_key": "mandate_" + identity, "rationale": args["plan"][:500]}, identity)
        return {**receipt, "status": "proposed", "page": "#inbox",
                "next": "One card waits in the researcher's inbox. Tell them in one line and call yield_work(waiting); their choice wakes you."}

    def guidance_pin(self, run):
        """The guidance revision a run's commands are prepared against: the one its turn started from, or the newest that a
        campaign_inspect of this same run returned. A revision remembered from an earlier turn is never used."""
        with self.store.connection() as db:
            inspected = db.execute("SELECT MAX(CAST(json_extract(data,'$.result.guidance_revision') AS INTEGER)) FROM records "
                "WHERE kind='agent_tool_receipt' AND json_extract(data,'$.run_id')=? AND json_extract(data,'$.tool')='campaign_inspect'",
                (run["id"],)).fetchone()[0]
        return max(int(run.get("guidance_revision") or 0), int(inspected or 0))

    def assignment_origin(self, agent, run):
        """The researcher's request an agent's work descends from: the lead's run and thread (for a notice turn, the request it
        continues), inherited by assistants of assistants."""
        if agent["role"] == LEAD:
            return self.controller.request_root(run) if run else None
        return agent.get("assignment_origin") or None

    def ask_page_agent(self, agent, target, message, evidence_ids, identity, run=None):
        """The lead's request to a page agent, kept as a message on that agent's page; the result comes back to the lead."""
        if agent["role"] != LEAD:
            raise ValueError("Only the lead agent writes to the agents in charge of pages")
        for ref in evidence_ids:
            self.record(agent, ref)
        root = self.assignment_origin(agent, run)
        if root:
            # The page agent's work for this request, and what its assistants do, belongs to the request's side conversation.
            target["assignment_origin"] = root
            self.store.put("agent_session", target)
        thread_id = self.controller.message_thread(target, {"origin": root or {}}) if self.controller.message_thread and root else None
        self.store.put("message", {"id": "message_" + identity, "campaign_id": agent["campaign_id"], "role": "lead", "origin": "lead", "agent_role": LEAD, "content": message,
            "created_at": now(), "agent_id": target["id"], "from_agent_id": agent["id"], "to_agent_id": target["id"],
            **({"thread_id": thread_id} if thread_id else {})}, "message.created")
        text = message + (f"\nEvidence IDs: {json.dumps(evidence_ids)}" if evidence_ids else "")
        run = self.controller.ask_page_agent(target, text, "page_request_" + identity[-32:], agent["id"])
        return {"agent_id": target["id"], "run_id": run["id"], "status": run["status"], "page": "#" + PAGE_AGENTS[target["role"]],
                "next": "It works by itself and its result comes back to you. Say where the researcher can follow it, and call yield_work(waiting)."}

    def outstanding(self, agent):
        """Why a standing agent cannot yet call its request complete; empty when nothing holds it.

        A page agent waits for what it started and the questions it asked. The lead waits for everything else in the campaign:
        what a page agent does for the researcher directly does not hold the lead's request open."""
        cid = agent["campaign_id"]
        sessions = {a["id"]: a for a in self.store.list("agent_session", cid)}
        def started_here(record_id):
            starter = self.controller.starter(cid, record_id)
            return not (starter and starter["role"] in PAGE_AGENTS) if agent["role"] == LEAD else bool(starter) and starter["id"] == agent["id"]
        assistants = [a for a in sessions.values() if a["parent_agent_id"] == agent["id"] and (
            a["role"] in PAGE_AGENTS and a.get("request_open") and a.get("requested_by") == agent["id"]
            or a["role"] not in PAGE_AGENTS and a["status"] in {"queued", "running", "paused"})]
        if assistants or any(t["status"] in {"queued", "running", "pausing"} and started_here(t["id"]) for t in self.store.list("trial", cid)):
            return "Outstanding assignments or experiments remain; wait or reconcile them before completing"
        def asked_here(question):
            owner = sessions.get(question.get("agent_id"))
            return question.get("agent_id") == agent["id"] or agent["role"] == LEAD and not (owner and owner["role"] in PAGE_AGENTS)
        if any(g["status"] in {"reserved", "queued", "submitted", "running", "building", "validating", "reviewing", "repairing", "stopping"} and started_here(g["id"])
               for g in self.store.list("implementation_grant", cid)) \
                or any(q["status"] == "pending" and q.get("kind") != "extension_dialog" and asked_here(q) for q in self.store.list("agent_question", cid)) \
                or any(j["status"] in {"queued", "running"} and started_here(j["id"]) for j in self.store.list("fixed_mask_job", cid)):
            return "Unresolved questions or numerical/implementation jobs remain"
        if agent["role"] == LEAD and any(j["status"] in {"running", "awaiting_focus"} and j.get("requested_by") == LEAD
                                         for j in self.store.list("report_writer_job", cid)):
            return "A report you started is still being written, or its writer waits for an answer; wait for it before completing"
        return ""

    def references(self, campaign_id):
        """Findings and other assets of earlier campaigns that the researcher let this campaign's study read."""
        campaign = self.store.get(campaign_id, "campaign")
        return [item for item in self.workspace.assets.manager_references(campaign_id, campaign.get("active_study_id")) if "payload" in item]

    def receipt(self, record):
        """A command receipt the model can hold: a large outcome becomes an index to page with evidence_read."""
        page = command_page(record)
        if serialized_bytes(record) <= COMMAND_RESULT_BYTES:
            return {**record, "page": page, "link": page} if page else record
        operation = record["request"]["operation"]
        brief = {**{key: value for key, value in record.items() if key not in {"outcome", "request"}}, "operation": operation,
            **({"page": page} if page else {}),
            "outcome_bytes": serialized_bytes(record.get("outcome")),
            "retrieval": "The outcome is too large to return whole. Read the parts you need with evidence_read, "
                         "using this record_id and the pointers listed in outcome_index."}
        if operation == "comparison.report":
            brief["comparison"] = comparison_brief(record["outcome"])
        allowance = max(4096, COMMAND_RESULT_BYTES - serialized_bytes(brief))
        brief["outcome_index"] = view_record(record, record_id=record["id"], pointer="/outcome", limit=40,
                                            max_bytes=min(12000, allowance), tool="evidence_read")
        return brief

    def record(self, agent, identity):
        entry = self.store.get_entry(identity)
        if entry["kind"] == "asset" and identity in {item["asset_id"] for item in self.references(agent["campaign_id"])}:
            return entry["data"]
        if entry["kind"] not in READ_KINDS or entry["data"].get("campaign_id", entry["data"].get("id")) != agent["campaign_id"]:
            raise ValueError("Evidence is not readable within this campaign")
        return entry["data"]

    def compute(self, agent, expression, values, identity):
        """An expression over literals and numbers read from this campaign's records, evaluated by the charter's whitelisted
        evaluator (nothing reaches eval). The result is the receipt K2 reads: the expression, each input with its source, the value."""
        from optimization_framework.problem_charter.expressions import evaluate, names as expression_names
        from optimization_framework.campaigns.record_view import _select
        unused = sorted(set(values) - expression_names(expression))
        if unused:
            raise ValueError(f"The expression does not read {', '.join(unused)}; pass only the values it uses")
        inputs = []
        for name, value in values.items():
            source = value if isinstance(value, dict) else None
            if source:
                value = _select(self.record(agent, source["record_id"]), source["pointer"])
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{name}: {source['record_id']} at {source['pointer']} is not a number")
            inputs.append({"name": name, "value": value, "record_id": source and source["record_id"], "pointer": source and source["pointer"]})
        result = evaluate(expression, {item["name"]: item["value"] for item in inputs})
        if isinstance(result, str):
            raise ValueError("The expression gives text, not a number")
        return {"expression": expression, "value": result, "inputs": inputs, "receipt_id": identity}

    def methods(self, tasks):
        """Installed optimizers that can run on these tasks, with the parameters algorithm_config accepts."""
        from optimization_framework.optimizers.registry import capability_reason, methods
        keep = ("type", "enum", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "description")
        result = []
        for method in methods():
            runs_on = [task["id"] for task in tasks if task.get("problem") and capability_reason(method["id"], task["problem"]) is None]
            if runs_on:
                result.append({"id": method["id"], "name": method["name"], "description": method["description"], "task_ids": runs_on,
                    **({"purpose": method["purpose"]} if method.get("purpose") else {}),
                    "parameters": {name: {key: schema[key] for key in keep if key in schema}
                                   for name, schema in method["parameter_schema"]["properties"].items()}})
        return result

    def methods_unavailable(self, campaign_id):
        from optimization_framework.campaigns.method_catalog import unavailable
        try:
            return unavailable(self.workspace, campaign_id)
        except (KeyError, ValueError) as exc:
            return {"error": str(exc)[:300]}

    def inspect(self, agent):
        campaign_id = agent["campaign_id"]
        campaign = self.store.get(campaign_id, "campaign")
        tasks = self.workspace.current_tasks(campaign_id)
        hypotheses = self.store.list("hypothesis", campaign_id)
        from optimization_framework.campaigns.proposals import readiness, hypothesis_revision
        team_view = self.controller.view(campaign_id)
        from optimization_framework.campaigns.experiment_rules import current as experiment_rules
        rules = experiment_rules(self.store, campaign_id)
        team_view["agents"] = [{k: a.get(k) for k in ("id", "role", "parent_agent_id", "status", "model", "usage", "event_cursor")}
            for a in team_view["agents"][-30:]]
        team_view["aliases"] = team_view["aliases"][:100]
        races = []
        for record in self.store.list("adaptive_race", campaign_id):
            view = self.workspace.racing.view(record["id"])
            races.append({**{key: view.get(key) for key in ("id", "study_id", "status", "stage", "revision", "deadline_at",
                "elapsed_seconds", "total_seconds", "max_workers", "running_workers", "worker_seconds_spent", "remaining_worker_seconds", "last_error", "report_path")},
                "preflight_status": view["preflight"]["status"],
                "configurations": [{key: row[key] for key in ("id", "algorithm", "status", "mean_score", "seeds", "rung_seconds", "maturity")}
                    for row in view["configurations"]],
                "recent_decisions": [{"id": row["id"], "action": row["action"], "rationale": row["rationale"][:1000]}
                    for row in view["decisions"][-10:]],
                "retrieval": "Read race_decision and race_endpoint evidence individually; the study race API has full endpoint details."})
        gate = getattr(self.workspace, "definition_gate", None)
        return {"campaign": campaign, "guidance_revision": self.workspace.memory.state(campaign_id)["guidance_revision"],
            # The problem-definition gate: proposals, allocations and autopilot are refused until ready; step says what is missing.
            "definition": gate(campaign) if gate else None,
            "researcher_guidance": self.workspace.memory.state(campaign_id)["guidance"],
            "tasks": [{**t, "evaluator_readiness": self.workspace.evaluators.readiness(t)} for t in tasks[:20]],
            "methods": self.methods(tasks[:20]),
            # What matters here but cannot run (delivered and not installed, incompatible, being built), with why and what next.
            "methods_unavailable": self.methods_unavailable(campaign_id),
            "reference_evidence": [{**{key: item.get(key) for key in ("asset_id", "title", "applicability", "exposure_status")},
                "content": str(item["payload"].get("content", ""))[:600], "classification": item["payload"].get("classification"),
                "read": "evidence_read with record_id=asset_id returns the whole finding"} for item in self.references(campaign_id)],
            "pages": [{"link": link, "name": name, "shows": shows} for link, name, shows in PAGES],
            # How runs are named, where short runs end, how many may go at once, and how runs are chosen: the experiment operator's rules.
            "experiment_rules": {key: rules.get(key) for key in ("revision", "naming", "short_run_seconds", "max_concurrent", "strategy")},
            "hypothesis_count": len(hypotheses), "retrieval": "Use evidence_search to page through further tasks, hypotheses or sessions.",
            "hypotheses": [{"id": h["id"], "candidate_id": h.get("candidate_id"), "title": h["title"],
                "hypothesis_hash": hypothesis_revision(h), "concept_review": readiness(self.store, h),
                "status": h.get("status"), "algorithm": h.get("algorithm"),
                "implementation_readiness": self.workspace.implementations.readiness(h, tasks[0] if tasks else None)} for h in hypotheses[:50]],
            "resources": {"experiments": self.workspace.resources.assessment(campaign_id),
                "implementation_committed_seconds": self.workspace.implementations.compute_committed(campaign_id)},
            "adaptive_testing": races,
            "agent_team": team_view,
            # What the agents in charge of pages were last asked and how they ended it: by the researcher on their page, or by the lead.
            "page_agents": [{"role": a["role"], "agent_id": a["id"], "page": "#" + PAGE_AGENTS[a["role"]], "status": a["status"],
                "request_open": bool(a.get("request_open")), "asked_by": {"researcher": "researcher", None: None}.get(a.get("requested_by"), "lead"),
                "last_summary": (a.get("disposition") or {}).get("summary"),
                "last_run_id": (self.store.list_agent_runs(a["id"]) or [{}])[-1].get("id")}
                for a in self.store.list("agent_session", campaign_id) if a["role"] in PAGE_AGENTS],
            "latest_researcher_requests": [{"id": r["id"], "status": r["status"], "message": r["request"]["message"]}
                for r in self.store.list("manager_command", campaign_id)[-5:]],
            "latest_researcher_messages": [{"id": r["id"], "content": r.get("content", "")[:12000]}
                for r in self.store.list("message", campaign_id) if r.get("role") == "user"][-5:],
            "capabilities": {**self.capabilities(agent),
                "resource_observability": "resource_inspect; live consumption and estimated future demand, without allocating compute",
                "adaptive_testing": "study.race.decide and study.race.control; immutable protocol and fresh-seed confirmation",
                "implementation_execution": implementation_execution(),
                "memory": "evidence_search and evidence_read",
                "guidance": "Use current implementation_readiness, not stale historical executable fields."}}

    def capabilities(self, agent):
        """How experiments, fixed-design checks and implementations are done, as this agent does them, with what the campaign's
        problem packs add."""
        packed = {entry["purpose"]: operation if entry["role"] == agent["role"] else f"{PAGE_AGENT_NAMES[entry['role']]} ({operation})"
                  for operation, entry in self.pack_operations(agent).items()}
        if agent["role"] == LEAD:
            return {"experiment": "the experiment operator (page_agent_message): drafts, runs, continuations, profiles; experiment_progress reads how runs go",
                    "fixed_design_check": FIXED_DESIGN_CHECK, **packed, "implementation": "a library built in a coding workspace (procedure implementation-supervision): Balsamic installs it, binds its proposals and starts the approved runs; or the implementation lead (implementation.commission)"}
        return {"fixed_design_check": "the lead agent (lead_ask): " + FIXED_DESIGN_CHECK, **packed, "implementation": "a library built in a coding workspace (procedure implementation-supervision): Balsamic installs it, binds its proposals (implementation.bind_builtin for one it skipped) and starts the approved runs; or implementation.commission", "experiment": "draft.save then draft.launch; trial.create"}

    def _execute(self, agent, run, name, args, identity):
        cid = agent["campaign_id"]
        if name == "campaign_inspect":
            return self.inspect(agent)
        if name == "resource_inspect":
            from optimization_framework.execution.observability import get_observer
            snapshot = deepcopy(get_observer(self.workspace).snapshot(cid))
            # Numerical archives and long allocation histories have separate
            # evidence reads. Keep a telemetry inspection bounded for the lead agent.
            snapshot["workers"]["jobs"] = snapshot["workers"].get("jobs", [])[:16]
            plans = snapshot.get("plans", [])
            snapshot["plan_count"] = len(plans)
            snapshot["plans"] = plans[-4:]
            for plan in snapshot["plans"]:
                plan["upcoming_jobs"] = plan.get("upcoming_jobs", [])[:12]
                plan["decisions"] = [{**row, "rationale": (row.get("rationale") or "")[:1000]}
                                     for row in plan.get("decisions", [])[-5:]]
                memory_fields = ("fidelity", "harmonic_count", "predicted_bytes", "headroom_bytes",
                                 "measured_peak_bytes", "single_matrix_bytes", "expanded_grid_shape",
                                 "expanded_complex_grid_bytes", "analytical_lower_bound_bytes", "fits_now", "basis")
                plan["memory_checks"] = [{key: row.get(key) for key in memory_fields}
                                         for row in plan.get("memory_checks", [])[:8]]
            budget = snapshot.get("budget")
            if budget:
                budget["grant_count"] = len(budget.get("grants", []))
                budget["grants"] = budget.get("grants", [])[-20:]
            snapshot["warnings"] = [str(value)[:1000] for value in snapshot.get("warnings", [])[:16]]
            admission = getattr(self.workspace, "admission", None)
            if admission is not None:
                # What the resource planner works from: each running run's own memory, and the GPU's processes.
                detail = admission.view(cid, detail=True)
                detail["kinds"] = detail["kinds"][:40]
                detail["waiting"] = detail["waiting"][:40]
                snapshot["admission"] = detail
            return snapshot
        if name == "implementation_workspace_create":
            return self.controller.development.create(cid, args, actor=LEAD, opener={"agent_id": agent["id"], "role": agent["role"]},
                                                     root=self.assignment_origin(agent, run))
        if name == "implementation_workspace_inspect":
            return self.controller.development.events(cid, args["workspace_id"], args.get("after", 0))
        if name == "implementation_workspace_message":
            return self.controller.development.message(cid, args["workspace_id"], {k: v for k, v in args.items() if k != "workspace_id"}, actor=LEAD)
        if name == "implementation_workspace_validate":
            return self.controller.development.validate(cid, args["workspace_id"], {k: v for k, v in args.items() if k != "workspace_id"}, actor=LEAD)
        if name == "evidence_read":
            record = self.record(agent, args["record_id"])
            return view_record(record, record_id=args["record_id"], pointer=args.get("pointer", ""), offset=args.get("offset", 0),
                limit=40, max_bytes=args.get("max_bytes", 12000), tool="evidence_read")
        if name == "evidence_search":
            kind = args.get("kind")
            if kind and kind not in READ_KINDS:
                raise ValueError("Evidence kind is not available")
            kinds = [kind] if kind else sorted(READ_KINDS)
            query = "%" + args.get("query", "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            with self.store.connection() as db:
                rows = db.execute("SELECT id,kind,json_extract(data,'$.title') AS title,json_extract(data,'$.status') AS status FROM records "
                    "WHERE (campaign_id=? OR id=?) AND kind IN (" + ",".join("?" for _ in kinds) + ") AND data LIKE ? ESCAPE '\\' ORDER BY rowid LIMIT ? OFFSET ?",
                    [cid, cid, *kinds, query, args.get("limit", 25), args.get("offset", 0)]).fetchall()
            return {"records": [dict(r) for r in rows], "next_offset": args.get("offset", 0) + len(rows)}
        if name in {"source_search", "source_ingest"}:
            from optimization_framework.research.sources import deliver
            receipt = deliver(self.workspace, {"id": identity, "campaign_id": cid,
                "kind": "literature_search" if name == "source_search" else "source_ingest",
                **({"provider": "arxiv", "limit": 5} if name == "source_search" else {}), **args})
            return receipt
        if name == "source_read":
            self.record(agent, args["source_id"])
            from optimization_framework.research.literature import LiteratureReader
            return LiteratureReader(self.workspace).read(cid, **args)
        if name == "proposal_review":
            from optimization_framework.campaigns.proposals import hypothesis_revision
            hypothesis = self.record(agent, args["hypothesis_id"])
            if self.store.get_entry(hypothesis["id"])["kind"] != "hypothesis" or hypothesis_revision(hypothesis) != args["hypothesis_hash"]:
                raise ValueError("Review must pin the exact current hypothesis revision from campaign_inspect")
            if args["verdict"] == "test" and args.get("required_changes"):
                raise ValueError("Required mechanism changes must be resolved before a test verdict")
            artifact = self.store.put_immutable("agent_artifact", {"id": "artifact_" + identity, "campaign_id": cid,
                "agent_id": agent["id"], "run_id": run["id"], "kind": "proposal_review", "content": args,
                "created_at": now()}, "hypothesis.concept_reviewed")
            hypothesis.setdefault("reviews", []).append({"id": artifact["id"], "author": agent["role"], "kind": "conceptual",
                "verdict": args["verdict"], "text": args["rationale"], "created_at": now()})
            self.store.put("hypothesis", hypothesis)
            return {"review_id": artifact["id"], "verdict": args["verdict"]}
        if name == "artifact_save":
            for ref in args.get("evidence_ids", []):
                self.record(agent, ref)
            if len(json.dumps(args).encode()) > 1024 * 1024:
                raise ValueError("Artifact exceeds 1 MiB; split it into linked artifacts")
            artifact = {"id": "artifact_" + identity, "campaign_id": cid, "agent_id": agent["id"],
                "run_id": run["id"], "created_at": now(), **args}
            saved = self.store.put_immutable("agent_artifact", artifact, "agent.artifact_saved")
            current = self.store.get(agent["id"], "agent_session")
            current["artifact_ids"] = list(dict.fromkeys([*current.get("artifact_ids", []), saved["id"]]))
            self.store.put("agent_session", current)
            return {"artifact_id": saved["id"], "content_hash": saved["content_hash"]}
        if name == "delegate":
            if args["role"].startswith("implementation_"):
                raise ValueError("Commission implementation through implementation.commission; its grant delegates builder, test designer and reviewer automatically")
            for ref in args.get("evidence_ids", []):
                self.record(agent, ref)
            aid = "agent_" + content_hash([agent["id"], args["request_key"]])[:30]
            # The role's output schema (agents/roles/<role>.schema.json) is the result it submits.
            child = self.controller.create_agent(cid, args["role"], args["objective"], aid,
                parent_id=agent["id"], evidence_ids=args.get("evidence_ids"), output_schema=ROLE_OUTPUT_SCHEMAS.get(args["role"]))
            root = self.assignment_origin(agent, run)
            if root:
                child["assignment_origin"] = root
                self.store.put("agent_session", child)
            task = self.controller.enqueue(child, "assignment_" + aid, args["objective"])
            return {"agent_id": aid, "run_id": task["id"], "status": task["status"]}
        if name in {"agent_message", "agent_cancel"}:
            child = self.store.get(args["agent_id"], "agent_session")
            if child["parent_agent_id"] != agent["id"]:
                raise ValueError("Only your own assistants can be written to or stopped")
            if name == "agent_message" and child["role"] in PAGE_AGENTS:
                return self.ask_page_agent(agent, child, args["message"], [], identity, run=run)
            if name == "agent_message":
                return self.controller.enqueue(child, "message_" + identity, args["message"], mode="steer")
            return self.controller.control(cid, {"agent_id": child["id"], "action": "stop", "expected_control_revision": child["control_revision"]}, identity)
        if name == "page_agent_message":
            return self.ask_page_agent(agent, self.controller.page_agent(cid, args["page_agent"]), args["message"], args.get("evidence_ids", []), identity, run=run)
        if name == "experiment_progress":
            from .experiments import progress
            return progress(self.workspace, cid, args.get("finished", 8))
        if name == "compute":
            return self.compute(agent, args["expression"], args.get("values", {}), identity)
        if name == "config_suggest":
            from .experiments import suggest
            return suggest(args["space"], args.get("observations", []), count=args.get("count", 4),
                           maximize=args.get("direction", "maximize") == "maximize", seed=args.get("seed", 0))
        if name in EXTRA_TOOLS:
            return EXTRA_TOOLS[name]["handler"](self, agent, run, args, identity)
        if name == "lead_ask":
            return self.controller.ask_lead(agent, args["question"], identity)
        if name == "command_schema":
            return self.workspace.commands.describe()[args["operation"]]
        if name == "campaign_command":
            if self.page_work(agent, name, args):
                raise ValueError(self.page_work(agent, name, args))
            if args["operation"] == "approval.request" and isinstance(args["payload"], dict) and args["payload"].get("kind") == "compute":
                raise ValueError("A compute go-ahead is now a mandate: propose it with mandate_propose (template screen), with the same plan, "
                                 "worker_seconds, coding_workspaces, hypothesis_ids and runs.")
            campaign = self.store.get(cid, "campaign")
            command_id = "pi_command_" + content_hash([cid, args["operation"], args["request_key"]])[:32]
            # Unknown top-level payload keys are dropped and reported, a near-miss refused (decision 5); nested objects stay strict.
            payload, ignored = args["payload"], []
            known = self.workspace.commands.payload_keys(args["operation"])
            if known is not None and isinstance(payload, dict):
                payload, ignored = lenient(payload, known)
            try:
                accepted = self.store.get(command_id, "work_command")
                if accepted["request"]["operation"] != args["operation"] or accepted["request"]["payload"] != payload:
                    raise ValueError("Request key belongs to a different command")
                return self.receipt(accepted)
            except KeyError:
                pass
            if args["operation"] in {"implementation.commission", "evaluator.commission", "implementation.revalidate"}:
                execution = implementation_execution()
                if not execution["available"]:
                    raise ValueError("Isolated implementation execution is unavailable; no grant was reserved. " + execution["reason"])
            # Pinned from the run, never from the model's memory: the guidance it read and the thread it answers.
            origin = dict(run.get("origin") or {})
            actor = "autopilot" if run.get("autopilot") else "lead" if agent["role"] == LEAD else "page_agent"
            if actor == "autopilot" and not (args.get("rationale") or "").strip():
                raise ValueError("Under autopilot every command states its rationale")
            from optimization_framework.contracts.commands import CommandOrigin
            command = Command(id=command_id, campaign_id=cid,
                # The campaign-wide guidance pin is the run's, or a newer one the agent read in this run (campaign_inspect); a revision the model
                # states is ignored (D7). The thread pin is never overridden.
                operation=args["operation"], expected_revision=campaign["version"], expected_guidance_revision=self.guidance_pin(run),
                expected_thread_revision=run.get("thread_revision"), expected_authority_hash=self.workspace.commands.authority_hash(campaign), payload=payload,
                origin=CommandOrigin(thread_id=origin.get("thread_id"), message_id=origin.get("message_id"), actor=actor, agent_id=agent["id"], run_id=run["id"],
                                     rationale=(args.get("rationale") or None)))
            return self.receipt(self.workspace.commands.execute(command, actor="autopilot" if actor == "autopilot" else "manager", ignored_fields=ignored))
        if name in {"report_write", "report_answer"}:
            writer = self.workspace.report_writer
            if name == "report_write":
                # The writer freezes the campaign's own records; what the agents wrote (verdicts, replies, saved analyses)
                # reaches it only as supplied evidence, read with the same permission as evidence_read.
                references, agent_records = list(dict.fromkeys(args.get("reference_ids") or [])), []
                for ref in references:
                    try:
                        kind = self.store.get_entry(ref)["kind"]
                    except KeyError:
                        raise ValueError(f"No saved record {ref}") from None
                    if kind in AGENT_RECORD_KINDS:
                        agent_records.append({"id": ref, "kind": kind, "record": self.record(agent, ref)})
                job = writer.start(campaign_id=cid, brief=args["notes"], request_id="lead_" + content_hash([cid, args["request_key"]])[:32],
                    references=references, **({"evidence": {"agent_records": agent_records}} if agent_records else {}),
                    literature=args.get("literature", True), requested_by=LEAD)
            else:
                if self.store.get(args["job_id"], "report_writer_job")["campaign_id"] != cid:
                    raise ValueError("That report belongs to another campaign")
                job = writer.answer(args["job_id"], args["answer"])
            return {"job_id": job["id"], "status": job["status"], "stage": job.get("stage"), "question": job.get("question"), "error": job.get("error"),
                "report_id": job.get("result_id"), "draft": "/reports/" + job["result_id"] if job.get("result_id") else None, "page": "#reports",
                "next": "The writer runs by itself. Tell the researcher where to follow it and call yield_work(waiting); its end wakes you."}
        if name == "mandate_propose":
            return self.propose_mandate(agent, run, args, identity)
        if name == "researcher_ask":
            return self.store.put("agent_question", {"id": "question_" + identity, "campaign_id": cid, "agent_id": agent["id"],
                "status": "pending", "created_at": now(), **args}, "agent.question_created")
        if name == "yield_work":
            for ref in args.get("evidence_ids", []):
                self.record(agent, ref)
            if agent.get("output_schema") and args["disposition"] == "complete" and self.store.get(agent["id"], "agent_session").get("output") is None:
                raise ValueError("Submit your result with submit_output first, in your role's schema; then call yield_work(complete).")
            if agent["role"] in STANDING and args["disposition"] == "complete":
                reason = self.outstanding(agent)
                if reason:
                    raise ValueError(reason)
                # A reply announced and never written is the failure this prevents: the request ends with its answer.
                open_request = self.controller.configuration(agent["campaign_id"]).get("request_open") if agent["role"] == LEAD else agent.get("request_open")
                if (open_request or run.get("asked_by")) and not (args.get("report") or "").strip():
                    raise ValueError("Write your reply in report: the answer, with the numbers that answer it. Then call yield_work again.")
            current = self.store.get(agent["id"], "agent_session")
            current["disposition"] = args; self.store.put("agent_session", current, "agent.checkpointed")
            current_run = self.store.get(run["id"], "agent_run")
            current_run["disposition"] = args
            self.store.put("agent_run", current_run)
            return {"saved": True, **args}
        if name == "submit_output":
            import jsonschema
            jsonschema.validate(args["result"], agent["output_schema"])
            current = self.store.get(agent["id"], "agent_session")
            current["output"] = args["result"]; self.store.put("agent_session", current, "agent.output_saved")
            saved_run = self.store.get(run["id"], "agent_run")
            saved_run["output"] = args["result"]; self.store.put("agent_run", saved_run)
            return {"saved": True}
        if name.startswith("file_"):
            from .files import Files
            return getattr(Files(self, agent), name.removeprefix("file_"))(args)
        if name == "analysis_run":
            from .files import analysis_run
            return analysis_run(self, agent, args, root=self.assignment_origin(agent, run))
        if name.startswith("workspace_"):
            return self._files(agent, name, args)
        raise ValueError("Unknown tool")

    def _files(self, agent, name, args):
        directory = self.workspace.directory / "agents" / agent["id"] / "work"
        directory.mkdir(parents=True, exist_ok=True)
        if name == "workspace_list":
            return {"files": [str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file() and not p.is_symlink()][:500]}
        relative = Path(args["path"])
        filename = directory / relative
        if relative.is_absolute() or ".." in relative.parts or directory.resolve() not in filename.resolve().parents:
            raise ValueError("File must stay inside this assignment's development directory")
        if any(p.is_symlink() for p in [filename, *filename.parents] if p != directory.parent):
            raise ValueError("Symlinks are not permitted in development paths")
        if name == "workspace_read":
            if filename.stat().st_size > 262144:
                raise ValueError("File too large; split the work product")
            return {"path": args["path"], "content": filename.read_text()}
        if name == "workspace_write":
            if len(args["content"].encode()) > 262144:
                raise ValueError("File exceeds package source limit")
            filename.parent.mkdir(parents=True, exist_ok=True); filename.write_text(args["content"])
            return {"path": args["path"], "saved": True}
        seconds = min(args.get("seconds", 10), max(0, agent.get("deadline_at", time.time() + 30) - time.time()))
        if seconds <= 0:
            raise ValueError("Implementation grant expired")
        import shutil
        if not shutil.which("bwrap"):
            raise ValueError("Isolated development execution requires bubblewrap")
        command = ["bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        from .files import interpreter
        # Every link between the environment's python and its installation, or the sandbox cannot start it.
        for root in dict.fromkeys(["/usr", "/lib", "/lib64", "/bin", *interpreter()]):
            if Path(root).exists():
                command += ["--ro-bind", root, root]
        wrapper = "import resource,runpy,sys; resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576)); resource.setrlimit(resource.RLIMIT_NOFILE,(128,128)); runpy.run_path(sys.argv[1],run_name='__main__')"
        command += ["--bind", str(directory), "/work", "--chdir", "/work", sys.executable, "-c", wrapper, str(relative)]
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            child = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True,
                env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
            try:
                child.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                import signal
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
                return {"status": "timeout", "seconds": seconds}
            output = {}
            for key, stream in (("stdout", stdout), ("stderr", stderr)):
                stream.seek(max(0, stream.seek(0, 2) - 24000))
                output[key] = stream.read(24000).decode(errors="replace")
        return {"exit_code": child.returncode, **output, "scope": "Development check; protected validation is separate."}
