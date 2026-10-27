"""What a coding workspace did, as one history the researcher can read: built from the records the workspace already leaves
(its events, commands, questions, submissions, validations, installs and stall issues), newest first.

A spell of work (from the coding agent starting to settling) is one entry: how long, how many tool calls, how many failed,
and what it said last; its failed calls are listed inside it, since a failing command while debugging is routine. Errors that
are not routine (a refused submission, a blocked host, the CPU allowance) are entries of their own.
"""
from __future__ import annotations

from datetime import datetime
import re

ACTORS = {"researcher": "You", "lead": "The lead", "pi": "The lead", "system": "Balsamic"}
OPENERS = {"lead": "the lead", "implementation_lead": "the implementation lead"}
VERDICTS = {"ready": "ready", "ready_with_limits": "ready, with limits", "not_ready": "not ready"}
VERDICT_TONES = {"ready": "ok", "ready_with_limits": "warn", "not_ready": "bad"}
ERRORISH = re.compile(r"error|fail|traceback|denied|not found|no such|invalid|must ", re.I)


def _seconds(start, end):
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _minutes(seconds):
    return f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def _first_line(text, limit=160):
    line = (str(text or "").strip().splitlines() or [""])[0]
    return line if len(line) <= limit else line[:limit - 1] + "…"


def _failure(output):
    """What a failed tool call said: its last line that reads as an error (else its last line), and its exit code."""
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    code = next((line for line in reversed(lines) if line.startswith("Command exited with code")), None)
    lines = [line for line in lines if not line.startswith("Command exited with code")]
    pick = next((line for line in reversed(lines) if ERRORISH.search(line)), lines[-1] if lines else "")
    return _first_line(pick, 200) + (f" (exit {code.rsplit(' ', 1)[-1]})" if code else "")


def tests_text(tests):
    if not tests:
        return ""
    return f"{tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed" + (f", {tests['skipped']} skipped" if tests.get("skipped") else "")


def delivery(submission):
    """A delivery as the researcher reads it: the coding agent's verdict, what it says, each method's state, and what comes next."""
    report = submission.get("report")
    if not report:
        return f"Delivered commit {submission['commit'][:7]}, without a delivery report", submission.get("notes", ""), "", []
    parts = [report["summary"], "Tests: " + tests_text(report["tests"]) + (f" (`{report['tests']['command']}`)" if report["tests"].get("command") else "")]
    if report.get("limitations"):
        parts.append("Limitations:\n" + "\n".join(f"- {item}" for item in report["limitations"]))
    if report.get("next_actions"):
        parts.append("Next:\n" + "\n".join(f"- {action['owner']}: {action['action']}" for action in report["next_actions"]))
    methods = [f"{m['method_id']}: {m['state'].replace('_', ' ')}, conformance {m['conformance'].replace('_', ' ')}"
               + (f", {tests_text(m['tests'])}" if m.get("tests") else "") for m in report["methods"]]
    return (f"Delivered commit {submission['commit'][:7]}: {VERDICTS[report['verdict']]}", "\n\n".join(parts),
            VERDICT_TONES[report["verdict"]], methods)


def entry(at, kind, title, detail="", tone="", ref=None, items=None):
    return {"at": at, "kind": kind, "title": title, "detail": str(detail or "")[:4000], "tone": tone, "ref": ref, "items": items or []}


def entries(store, record):
    """Every history entry of one workspace, oldest first."""
    cid, wid = record["campaign_id"], record["id"]
    events = sorted((e for e in store.list("development_event", cid) if e["workspace_id"] == wid), key=lambda e: e["seq"])
    found = []
    opener = record.get("opened_by") or {}
    who = OPENERS.get(opener.get("role") or opener.get("actor"), "you" if opener.get("actor") == "researcher" else None)
    consent = record.get("consent")   # workspaces opened before this was recorded say neither
    found.append(entry(record["created_at"], "opened", ("Opened" + (f" by {who}" if who else "")) + (" under your go-ahead" if consent else ""),
                       (f"Approved plan: {consent['plan']}\n\n" if consent and consent.get("plan") else "") + f"Task: {record.get('objective', '')}",
                       "info", consent["decision_id"] if consent else None))
    spell = None
    for event in events:
        kind, payload, at = event["type"], event.get("payload") or {}, event["occurred_at"]
        if kind == "agent_start":
            spell = {"start": at, "tools": 0, "failed": [], "last": ""}
        elif kind == "tool":
            if spell is not None:
                spell["tools"] += 1
                if payload.get("error"):
                    spell["failed"].append(f"{payload.get('tool')}: {_failure(payload.get('output'))}")
        elif kind == "message":
            if spell is not None and payload.get("text"):
                spell["last"] = payload["text"]
        elif kind == "agent_settled" and spell is not None:
            failed = len(spell["failed"])
            title = (f"Worked {_minutes(_seconds(spell['start'], at))} · {spell['tools']} tool calls" + (f" · {failed} failed" if failed else "")
                     if spell["tools"] else "Replied")
            found.append(entry(at, "work", title, spell["last"][-1500:], "", None, spell["failed"][:20]))
            spell = None
        elif kind == "checkpoint":
            parts = [payload.get("summary", "")]
            if payload.get("next_steps"):
                parts.append("Next: " + str(payload["next_steps"]))
            if payload.get("blocker"):
                parts.append("Blocker: " + str(payload["blocker"]))
            if payload.get("question"):
                parts.append("Question: " + str(payload["question"]))
            found.append(entry(at, "checkpoint", "Checkpoint: " + _first_line(payload.get("summary")), "\n\n".join(parts),
                               "warn" if payload.get("blocker") else "attention" if payload.get("question") else ""))
        elif kind == "instruction":
            actor = ACTORS.get(payload.get("actor"), "Someone")
            found.append(entry(at, "instruction", f"{actor} wrote to the coding agent", payload.get("text", ""),
                               "you" if payload.get("actor") == "researcher" else "", payload.get("command_id")))
        elif kind == "bridge_error":
            found.append(entry(at, "refused", "Refused: " + _first_line(payload.get("error")), payload.get("error", ""), "warn"))
        elif kind == "host_blocked":
            found.append(entry(at, "blocked", "The workspace could not run", payload.get("error", ""), "bad"))
        elif kind == "host_recovered":
            found.append(entry(at, "recovered", "The workspace runs again", "", "ok"))
        elif kind == "budget_warning":
            found.append(entry(at, "budget", f"CPU allowance nearly used: {payload.get('used', 0):.0f} of {payload.get('budget', 0):.0f} s",
                               "The coding agent was asked to save a checkpoint.", "warn"))
        elif kind == "budget_reached":
            found.append(entry(at, "budget", f"CPU allowance used up ({payload.get('budget', 0):.0f} s): paused",
                               "The workspace and its session are saved; resuming needs a larger allowance.", "bad"))
    if spell is not None:
        found.append(entry(events[-1]["occurred_at"], "work", f"Working since {spell['start'][11:16]} UTC · {spell['tools']} tool calls so far"
                           + (f" · {len(spell['failed'])} failed" if spell["failed"] else ""), spell["last"][-1500:], "agent", None, spell["failed"][:20]))
    for command in store.list("development_command", cid):
        if command["workspace_id"] == wid and command.get("operation") in {"pause", "resume", "stop"}:
            found.append(entry(command["created_at"], "control", f"{ACTORS.get(command.get('actor'), 'Someone')} asked to {command['operation']} it",
                               "", "", command["id"]))
    for question in store.list("development_question", cid):
        if question["workspace_id"] == wid and question.get("answered_at"):
            found.append(entry(question["answered_at"], "answer", "Question answered", f"{question['question']}\n\nAnswer: {question.get('answer', '')}",
                               "", question["id"]))
    for submission in store.list("development_submission", cid):
        if submission["workspace_id"] != wid:
            continue
        title, detail, tone, methods = delivery(submission)
        found.append(entry(submission["created_at"], "delivery", title, detail, tone, submission["id"], methods))
        if submission.get("grant_id"):
            try:
                grant = store.get(submission["grant_id"], "implementation_grant")
            except KeyError:
                grant = {}
            found.append(entry(grant.get("created_at") or submission["created_at"], "validation", "Independent validation requested", "", "",
                               submission["grant_id"]))
            outcome = submission.get("validation_outcome")
            if outcome:
                findings = [str(item.get("detail") or item.get("review") or item.get("check") or "") for item in outcome.get("findings", [])]
                found.append(entry(grant.get("finished_at") or grant.get("updated_at") or submission["created_at"], "validation",
                                   "Validated" if submission["status"] == "validated" else "Validation found problems",
                                   outcome.get("error") or "", "ok" if submission["status"] == "validated" else "bad", submission["grant_id"], findings[:20]))
    for install in store.list("library_install", cid):
        if install.get("workspace_id") == wid:
            state = install.get("status")
            found.append(entry(install.get("finished_at") or install["requested_at"], "install",
                               {"installed": f"Installed {install.get('package')} {install.get('version') or ''}".strip(),
                                "failed": "Install failed", "needs_confirmation": "Install waits for your confirmation: it would change installed packages"
                                }.get(state, "Install requested"),
                               install.get("error") or ", ".join(install.get("methods_added") or []), "ok" if state == "installed" else "bad" if state == "failed" else "",
                               install["id"]))
    for issue in store.list("manager_issue", cid):
        if issue.get("code") == "coding_quiet" and issue.get("affected", "").startswith(wid):
            found.append(entry(issue["created_at"], "quiet", "Went quiet", issue.get("message", ""), "warn", issue["id"]))
    return sorted(found, key=lambda item: item["at"] or "")


def timeline(store, record, before=None, limit=100):
    """The newest entries first, `limit` at a time; next_before continues with older ones."""
    rows = [item for item in reversed(entries(store, record)) if before is None or item["at"] < before]
    page = rows[:limit]
    return {"entries": page, "next_before": page[-1]["at"] if len(rows) > limit else None}
