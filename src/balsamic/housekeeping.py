"""Housekeeping: naming and labelling done by the lightest model, outside every agent's session.

The housekeeper is a role on the model tiers (default: the "fast" tier), not an agent: each job is one
short completion through the harness. Jobs run on the maintenance tick, a few per tick, and each record
remembers the outcome so a failed call is retried a bounded number of times and never storms the model.

Jobs: a title for a forked branch (2 to 6 words from the forked message and the turns around it), a short
label for every hypothesis (2 or 3 words) that fits a lineage node, and a one-sentence title for each finished
exchange with the lead (the chat folds earlier exchanges under it). Branch summaries (threads/summaries.py) use
the same model.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

from optimization_framework.agents import tiers
from optimization_framework.agents.controller import dev_profile, profile_defaults
from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import now

ROLE = tiers.HOUSEKEEPER
JOBS_PER_TICK = 3
ATTEMPTS = 3
RETRY_AFTER = timedelta(hours=1)   # a record whose attempts are spent is tried again later (a key or model may have been fixed)
log = logging.getLogger("balsamic.housekeeping")
LAST_ERROR = {"text": None, "at": None}
THREAD_TITLE_LIMIT = 48
LABEL_LIMIT = 26


def enabled():
    return not (os.environ.get("GRATING_LLM_DISABLED", "false").lower() == "true" or os.environ.get("GRATING_LLM_ENABLED", "true").lower() == "false")


def model(workspace):
    """The housekeeper's model: its tier when tiers are saved, else the profile default; None without a model."""
    choice, _ = workspace.pi.tier_choice(ROLE)
    if choice:
        return choice
    if dev_profile():
        return profile_defaults()
    for campaign in workspace.store.list("campaign"):
        config = workspace.pi.configuration(campaign["id"]) or {}
        if (config.get("models") or {}).get("default"):
            return dict(config["models"]["default"])
    return None


def complete(workspace, call_id, system, prompt, *, max_tokens=80, label="housekeeping", timeout=60):
    """One completion on the housekeeper's model; None when there is no model, calls are off, or the call fails."""
    if not enabled():
        return None
    choice = model(workspace)
    if not choice or not choice.get("model"):
        return None
    try:
        reply = workspace.pi.client.complete(call_id, {"provider": choice.get("provider"), "model": choice["model"], "effort": "low",
                                                       "max_tokens": max_tokens, "label": label, "system": system, "prompt": prompt}, timeout=timeout)
    except (ValueError, OSError) as error:
        LAST_ERROR.update(text=f"{choice.get('provider')}/{choice['model']}: {str(error)[:300]}", at=now())
        log.warning("housekeeping %s on %s/%s failed: %s", label, choice.get("provider"), choice["model"], str(error)[:300])
        return None
    text = ((reply or {}).get("text") or "").strip()
    if not text:
        LAST_ERROR.update(text=f"{choice.get('provider')}/{choice['model']}: empty reply", at=now())
        return None
    LAST_ERROR.update(text=None, at=None)
    return {"text": text, "model": choice.get("model"), "cost_usd": ((reply or {}).get("usage") or {}).get("cost_usd")}


def clean(text, limit):
    """One line, no quotes or markdown, no trailing period, cut at a word when still too long."""
    line = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    line = re.sub(r"^(title|label|name)\s*:\s*", "", line, flags=re.I).strip().strip("\"'`*_").rstrip(".").strip()
    if len(line) > limit:
        head = line[:limit]
        line = (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(" ,;:-") + "…"
    return line


# ---- jobs ---------------------------------------------------------------------------------------------------

def _attempt(record, job):
    state = dict(record.get("housekeeping") or {})
    previous = state.get(job) or {}
    attempts = int(previous.get("attempts", 0))
    if attempts >= ATTEMPTS and _stale(previous.get("at")):
        attempts = 0   # a new round of attempts, an hour later
    state[job] = {"attempts": attempts + 1, "at": now()}
    record["housekeeping"] = state
    return state[job]["attempts"]


def _failed(record, job):
    record["housekeeping"][job]["error"] = LAST_ERROR["text"] or "no model answer"


def _stale(at):
    if not at:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(at) > RETRY_AFTER
    except ValueError:
        return True


def _done(record, job, **fields):
    record["housekeeping"][job].update(status="done", **fields)


def pending(record, job):
    state = (record.get("housekeeping") or {}).get(job) or {}
    return state.get("status") != "done" and (int(state.get("attempts", 0)) < ATTEMPTS or _stale(state.get("at")))


def thread_context(workspace, thread):
    """The forked message, the lead's reply to it and the two turns before: what the branch is about."""
    rows = []
    try:
        forked = workspace.store.get(thread["fork_message_id"], "message")
    except KeyError:
        return rows
    parent = workspace.store.list("message", thread["campaign_id"])
    parent = sorted((m for m in parent if m.get("thread_id") == thread.get("parent_thread_id") and m.get("origin") != "lab_event"),
                    key=lambda m: m.get("created_at") or "")
    index = next((i for i, m in enumerate(parent) if m["id"] == forked["id"]), None)
    window = parent[max(0, index - 2): index + 2] if index is not None else [forked]
    for m in window:
        who = "Researcher" if m.get("role") == "user" else "Lead"
        rows.append(f"{who}: {(m.get('content') or '').strip()[:800]}")
    return rows


def name_thread(workspace, thread):
    """Give a branch a short title; the capped placeholder stays when the model cannot be asked."""
    attempt = _attempt(thread, "title")
    lines = thread_context(workspace, thread)
    anchors = thread.get("anchors") or []
    prompt = "\n".join(lines) + (f"\nThe branch discusses: {', '.join(anchors)}" if anchors else "")
    reply = complete(workspace, "name_thread_" + content_hash([thread["id"], attempt])[:16],
                     "Name a branch of a research conversation. The branch starts at the last researcher message shown and will explore it. "
                     "Answer with a title of two to six words, like a short chapter heading: concrete, no quotes, no trailing period, no markdown.",
                     prompt, max_tokens=24, label="branch title")
    title = clean(reply["text"], THREAD_TITLE_LIMIT) if reply else ""
    if title and len(title.split()) <= 8:
        thread.update(title=title, name=title, title_source="housekeeper")
        _done(thread, "title", model=reply["model"], cost_usd=reply.get("cost_usd"))
    else:
        _failed(thread, "title")
    workspace.store.put("thread", thread, "thread.renamed" if title else None)
    return title or None


def label_hypothesis(workspace, hypothesis):
    """A two or three word label for lineage nodes and chips; the title stays the full statement."""
    attempt = _attempt(hypothesis, "label")
    prompt = f"Title: {hypothesis.get('title', '')}\nMechanism: {(hypothesis.get('mechanism') or '')[:500]}"
    reply = complete(workspace, "label_hypothesis_" + content_hash([hypothesis["id"], attempt])[:16],
                     "Give a strategy a label of two or three words that tells it apart from its siblings, like a tag on a graph node "
                     "(for example: Warm-start CMA-ES, Greedy knapsack, Bandit caps). No quotes, no period, no markdown, at most 26 characters.",
                     prompt, max_tokens=16, label="hypothesis label")
    label = clean(reply["text"], LABEL_LIMIT) if reply else ""
    if label:
        hypothesis["short_title"] = label
        _done(hypothesis, "label", model=reply["model"], cost_usd=reply.get("cost_usd"))
    else:
        _failed(hypothesis, "label")
    workspace.store.put("hypothesis", hypothesis, "hypothesis.labeled" if label else None)
    return label or None


FOLD_LIMIT = 110


def exchanges(workspace, campaign_id):
    """Finished exchanges: a researcher message and the lead's replies before the next researcher message in the same thread."""
    from balsamic.threads.service import main_thread_id
    main = main_thread_id(campaign_id)
    by_thread = {}
    for message in sorted(workspace.store.list("message", campaign_id), key=lambda m: m.get("created_at") or ""):
        if message.get("origin") in {"lab_event", "manager_system", "setup"} or message.get("kind") == "agents_link":
            continue
        by_thread.setdefault(message.get("thread_id") or main, []).append(message)
    for rows in by_thread.values():
        question, replies = None, []
        for message in rows:
            if message.get("role") == "user":
                if question and replies:
                    yield question, replies
                question, replies = message, []
            elif question and message.get("origin") in {"lead", "autopilot", "pi"}:
                replies.append(message)
        # The last exchange is open until the next researcher message: the chat shows it unfolded anyway.


def title_exchange(workspace, question, replies):
    attempt = _attempt(question, "fold")
    transcript = f"Researcher: {(question.get('content') or '')[:1500]}\n" + "\n".join(f"Lead: {(r.get('content') or '')[:1500]}" for r in replies[-3:])
    reply = complete(workspace, "fold_" + content_hash([question["id"], attempt])[:16],
                     "Write one sentence of at most 14 words that says what the researcher asked and what came of it, in the past tense. "
                     "Plain words, no quotes, no markdown, no trailing period.", transcript, max_tokens=40, label="exchange title")
    title = clean(reply["text"], FOLD_LIMIT) if reply else ""
    if title:
        question["fold_title"] = title
        _done(question, "fold", model=reply["model"], cost_usd=reply.get("cost_usd"))
    else:
        _failed(question, "fold")
    workspace.store.put("message", question, "message.titled" if title else None)
    return title or None


def jobs(workspace):
    """Pending work, oldest first: branches awaiting a title, hypotheses awaiting a label, exchanges awaiting a fold title."""
    for thread in workspace.store.list("thread"):
        if thread.get("title_pending") and pending(thread, "title") and thread.get("status") != "merged":
            yield ("thread", thread)
    for hypothesis in workspace.store.list("hypothesis"):
        if not hypothesis.get("short_title") and pending(hypothesis, "label"):
            yield ("hypothesis", hypothesis)
    for campaign in workspace.store.list("campaign"):
        for question, replies in exchanges(workspace, campaign["id"]):
            if not question.get("fold_title") and pending(question, "fold"):
                yield ("exchange", (question, replies))


def status(workspace):
    """What the monitor shows: the model, the last failure, and how much work waits."""
    waiting = sum(1 for _ in jobs(workspace)) if enabled() else 0
    return {"enabled": enabled(), "model": model(workspace), "waiting": waiting, "last_error": dict(LAST_ERROR)}


def tick(workspace, limit=JOBS_PER_TICK):
    """Run a few housekeeping jobs; nothing when calls are off or no model is configured."""
    if not enabled() or not model(workspace):
        return 0
    done = 0
    for kind, record in jobs(workspace):
        if done >= limit:
            break
        if kind == "thread":
            if name_thread(workspace, record) or not pending(record, "title"):
                record["title_pending"] = False
                workspace.store.put("thread", record, None)
        elif kind == "hypothesis":
            label_hypothesis(workspace, record)
        else:
            title_exchange(workspace, *record)
        done += 1
    return done
