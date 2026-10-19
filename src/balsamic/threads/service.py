"""Thread records and reads: the researcher's conversations with the lead as branches of one Pi session.

Every campaign has a ``main`` thread. A fork starts a new thread at a message; the lead's first turn in it branches the
session tree at that message's reply. Parking writes a summary card; merging posts one note into the target thread,
parks the source, and gives the lead a turn on the target's leaf. Lab events (a command that completed in another thread)
reach every other active thread as one line. Messages carry ``thread_id`` (absent means main) and a ``desk`` when written
to a page agent.
"""
from pydantic import Field

from optimization_framework.agents.models import LEAD, PAGE_AGENTS
from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

MAIN = "main"
MESSAGE_LIMIT = 200
INHERITED_LIMIT = 60
ACTIVE_RUN = {"queued", "submitted", "running"}


def main_thread_id(campaign_id):
    return f"thread_{MAIN}_{campaign_id}"


def ensure_main(workspace, campaign_id):
    """The campaign's main thread record; written once."""
    identity = main_thread_id(campaign_id)
    try:
        return workspace.store.get(identity, "thread")
    except KeyError:
        campaign = workspace.store.get(campaign_id, "campaign")
        record = {"id": identity, "campaign_id": campaign_id, "name": MAIN, "title": campaign["name"], "parent_thread_id": None,
                  "fork_message_id": None, "fork_entry_id": None, "agent_leaf": None, "status": "active", "merged_into": None,
                  "pinned_ids": [], "excluded_ids": [], "anchors": [], "summary": None, "guidance_revision": 0,
                  "last_seen_message_id": None, "created_at": campaign.get("created_at") or now(), "updated_at": now()}
        with workspace.lock:
            return workspace.store.put("thread", record, "thread.created")


def thread_of(workspace, thread_id):
    return workspace.store.get(thread_id, "thread")


def lead_agent(workspace, campaign_id):
    return next((agent for agent in workspace.store.list("agent_session", campaign_id) if agent["role"] == LEAD), None)


def conversation(workspace, campaign_id):
    """The researcher's conversation with the lead: its messages and the lab's own lines, never a page agent's desk."""
    page_agents = {agent["id"] for agent in workspace.store.list("agent_session", campaign_id) if agent["role"] in PAGE_AGENTS}
    return [message for message in workspace.store.list("message", campaign_id)
            if not message.get("desk") and message.get("agent_id") not in page_agents and message.get("to_agent_id") not in page_agents]


def event_cursor(workspace, campaign_id):
    with workspace.store.connection() as db:
        return db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE campaign_id=?", (campaign_id,)).fetchone()[0]


def thread_messages(workspace, thread, rows=None):
    main = main_thread_id(thread["campaign_id"])
    rows = conversation(workspace, thread["campaign_id"]) if rows is None else rows
    return [message for message in rows if message.get("thread_id", main) == thread["id"]]


def parent_path(workspace, thread):
    """The threads this one descends from, root first, each with the message it was forked at."""
    path, seen = [], set()
    current = thread
    while current.get("parent_thread_id") and current["parent_thread_id"] not in seen:
        seen.add(current["parent_thread_id"])
        try:
            parent = thread_of(workspace, current["parent_thread_id"])
        except KeyError:
            break
        path.insert(0, {"thread_id": parent["id"], "title": parent["title"], "fork_message_id": current.get("fork_message_id")})
        current = parent
    return path


def inherited(workspace, thread, rows):
    """What a branch inherits from its ancestors: their messages up to the fork, oldest ancestor first."""
    result, messages = [], []
    for hop in parent_path(workspace, thread):
        parent = thread_of(workspace, hop["thread_id"])
        parent_rows = thread_messages(workspace, parent, rows)
        if hop["fork_message_id"]:
            # Through the lead's reply to the forked message: that reply's entry is where the branch starts.
            index = next((i for i, row in enumerate(parent_rows) if row["id"] == hop["fork_message_id"]), len(parent_rows) - 1)
            end = index
            for later in range(index + 1, len(parent_rows)):
                if parent_rows[later].get("role") == "assistant" and parent_rows[later].get("origin") != "lab_event":
                    end = later
                    break
                if parent_rows[later].get("role") == "user":
                    break
            parent_rows = parent_rows[:end + 1]
        if parent_rows:
            result.append({"thread_id": parent["id"], "title": parent["title"], "count": len(parent_rows), "from": parent_rows[0]["id"], "to": parent_rows[-1]["id"]})
            messages.extend(parent_rows)
    return result, messages[-INHERITED_LIMIT:]


def queued_runs(workspace, campaign_id):
    lead = lead_agent(workspace, campaign_id)
    if not lead:
        return [], None
    runs = [run for run in workspace.store.list("agent_run", campaign_id) if run["agent_id"] == lead["id"] and run["status"] in ACTIVE_RUN]
    active = next((run for run in runs if run["status"] in {"submitted", "running"}), None)
    return runs, active


def threads(workspace, campaign_id):
    ensure_main(workspace, campaign_id)
    lead = lead_agent(workspace, campaign_id)
    config = workspace.pi.configuration(campaign_id) or {}
    runs, active = queued_runs(workspace, campaign_id)
    main = main_thread_id(campaign_id)
    rows = conversation(workspace, campaign_id)
    out = []
    for thread in workspace.store.list("thread", campaign_id):
        messages = thread_messages(workspace, thread, rows)
        last = messages[-1] if messages else None
        own = [run for run in runs if (run.get("origin") or {}).get("thread_id", main) == thread["id"]]
        out.append({**thread, "message_count": len(messages), "last_message_id": last["id"] if last else None,
                    "last_activity_at": last.get("created_at") if last else thread.get("updated_at") or thread.get("created_at"),
                    "busy": bool(active and (active.get("origin") or {}).get("thread_id", main) == thread["id"]),
                    "queued": sum(1 for run in own if run["status"] == "queued"),
                    "unread": bool(last and last["id"] != thread.get("last_seen_message_id") and last.get("role") != "user"),
                    "strip": activity_strip(workspace, thread, messages)[-24:]})
    return {"threads": out, "lead": {"id": lead["id"], "status": lead["status"]} if lead else None, "request_open": bool(config.get("request_open")),
            "active_run": {"id": active["id"], "thread_id": (active.get("origin") or {}).get("thread_id", main)} if active else None}


def messages(workspace, thread_id, *, limit=MESSAGE_LIMIT, before=None):
    thread = thread_of(workspace, thread_id)
    rows = conversation(workspace, thread["campaign_id"])
    own = thread_messages(workspace, thread, rows)
    if before:
        index = next((i for i, row in enumerate(own) if row["id"] == before), len(own))
        own = own[:index]
    summaries, inherited_rows = inherited(workspace, thread, rows)
    questions = [q for q in workspace.store.list("agent_question", thread["campaign_id"]) if q["status"] == "pending"]
    placeholders = [row for row in workspace.store.list("placeholder", thread["campaign_id"]) if row.get("thread_id") == thread_id and row["status"] == "pending"]
    return {"thread_id": thread_id, "campaign_id": thread["campaign_id"], "messages": own[-limit:], "truncated": len(own) > limit,
            "inherited": summaries, "inherited_messages": inherited_rows, "parent_path": parent_path(workspace, thread),
            "fork_message_id": thread.get("fork_message_id"), "questions": questions, "placeholders": placeholders,
            "status": thread["status"], "merged_into": thread.get("merged_into"), "summary": thread.get("summary")}


# Activity strip and summaries -----------------------------------------------------------------------------
GLYPHS = {"message": "message", "lab_event": "run", "hypothesis": "strategy", "trial": "run", "decision": "decision", "note": "note"}


def activity_strip(workspace, thread, messages=None):
    """What happened in a thread, as glyphs in order: computed from records, never from a model."""
    messages = thread_messages(workspace, thread) if messages is None else messages
    strip = []
    for message in messages:
        if message.get("merge_of_thread_id"):
            strip.append({"at": message["created_at"], "glyph": "merge", "id": message["id"]})
        elif message.get("origin") == "lab_event":
            strip.append({"at": message["created_at"], "glyph": "run" if "trial" in (message.get("content") or "") else "decision" if "ecision" in (message.get("content") or "") else "note", "id": message["id"]})
        else:
            strip.append({"at": message["created_at"], "glyph": "message", "id": message["id"], "who": "you" if message.get("role") == "user" else "lead"})
    for command in workspace.store.list("work_command", thread["campaign_id"]):
        operation = command["request"]["operation"]
        # Messages, pins and the thread's own bookkeeping are not work; the strip shows what the thread did to the campaign.
        if (command.get("origin") or {}).get("thread_id") == thread["id"] and not operation.startswith(("agent.", "thread.", "note.", "campaign.stage")):
            glyph = "strategy" if operation.startswith("hypothesis") or operation == "research.generate" else "run" if operation.startswith(("trial", "draft", "study")) else "decision" if operation in {"decision.resolve", "approval.request"} else "note" if operation.startswith(("problem_note", "note")) else "command"
            strip.append({"at": command["created_at"], "glyph": glyph, "id": command["id"], "operation": operation})
    return sorted(strip, key=lambda row: row["at"])


def write_summary(workspace, thread_id, *, reason, model=True):
    """A summary card for a thread: a model's two sentences when calls are allowed, else the activity alone, labelled so."""
    from balsamic.threads.summaries import summarize
    with workspace.lock:
        thread = thread_of(workspace, thread_id)
        messages = thread_messages(workspace, thread)
        summary = summarize(workspace, thread, messages, reason=reason, model=model)
        thread["summary"] = summary
        thread["updated_at"] = now()
        workspace.store.put("thread", thread, "thread.summary_written")
        return summary


# Commands ---------------------------------------------------------------------------------------------------
class ForkInput(Contract):
    thread_id: str
    message_id: str
    title: str | None = Field(default=None, max_length=200)
    anchors: list[str] = Field(default_factory=list, max_length=20)


class ThreadInput(Contract):
    thread_id: str
    title: str | None = Field(default=None, max_length=200)


class PinInput(Contract):
    thread_id: str
    record_id: str
    pinned: bool = True
    excluded: bool = False


class MergeInput(Contract):
    thread_id: str
    into_thread_id: str
    note: str = Field(min_length=1, max_length=20000)


class SeenInput(Contract):
    thread_id: str
    message_id: str | None = None


def _own(workspace, command, thread_id):
    thread = thread_of(workspace, thread_id)
    if thread["campaign_id"] != command.campaign_id:
        raise ValueError("The thread belongs to another campaign")
    return thread


def fork_entry(workspace, thread, message_id):
    """Where the new branch starts in the session tree: the entry of the lead's reply to the message, else the message's own."""
    rows = thread_messages(workspace, thread)
    index = next((i for i, row in enumerate(rows) if row["id"] == message_id), None)
    if index is None:
        raise ValueError("The message is not in this thread")
    for row in rows[index:]:
        if row.get("role") == "assistant" and row.get("entry_id"):
            return row["entry_id"]
    for row in reversed(rows[:index + 1]):
        if row.get("entry_id"):
            return row["entry_id"]
    return thread.get("agent_leaf")


def register(workspace):
    commands = workspace.commands
    original = workspace.create_campaign

    def create_campaign(values, *args, **kwargs):
        campaign = original(values, *args, **kwargs)
        ensure_main(workspace, campaign["id"])
        return campaign
    workspace.create_campaign = create_campaign

    def researcher_only(actor):
        if actor != "researcher":
            raise ValueError("Threads are the researcher's: the lead works in them and does not fork, park or merge them")

    def fork(command, actor):
        researcher_only(actor)
        values = ForkInput(**command.payload)
        source = _own(workspace, command, values.thread_id)
        entry = fork_entry(workspace, source, values.message_id)
        message = workspace.store.get(values.message_id, "message")
        identity = f"thread_{content_hash(command.id)[:10]}_{command.campaign_id}"
        title = values.title or ((message.get("content") or "").strip().split("\n")[0][:80] or "Branch")
        record = {"id": identity, "campaign_id": command.campaign_id, "name": title[:40], "title": title, "parent_thread_id": source["id"],
                  "fork_message_id": values.message_id, "fork_entry_id": entry, "agent_leaf": None, "status": "active", "merged_into": None,
                  "pinned_ids": list(source.get("pinned_ids") or []), "excluded_ids": list(source.get("excluded_ids") or []), "anchors": values.anchors,
                  "summary": None, "guidance_revision": int(source.get("guidance_revision", 0)), "last_seen_message_id": None, "created_at": now(), "updated_at": now()}
        workspace.store.put("thread", record, "thread.created")
        return {"thread_id": identity, "thread": record}

    def rename(command, actor):
        researcher_only(actor)
        values = ThreadInput(**command.payload)
        thread = _own(workspace, command, values.thread_id)
        if not values.title:
            raise ValueError("A thread needs a title")
        thread.update(title=values.title, name=values.title[:40] if thread["name"] != MAIN else MAIN, updated_at=now())
        workspace.store.put("thread", thread, "thread.renamed")
        return {"thread_id": thread["id"]}

    def park(command, actor):
        researcher_only(actor)
        values = ThreadInput(**command.payload)
        thread = _own(workspace, command, values.thread_id)
        if thread["name"] == MAIN:
            raise ValueError("The main thread stays open; park a branch")
        if thread["status"] == "merged":
            raise ValueError("A merged thread is already closed")
        thread.update(status="parked", updated_at=now())
        workspace.store.put("thread", thread, "thread.parked")
        summary = write_summary(workspace, thread["id"], reason="parked")
        return {"thread_id": thread["id"], "summary": summary}

    def unpark(command, actor):
        researcher_only(actor)
        values = ThreadInput(**command.payload)
        thread = _own(workspace, command, values.thread_id)
        if thread["status"] != "parked":
            raise ValueError("Only a parked thread is taken up again")
        thread.update(status="active", updated_at=now())
        workspace.store.put("thread", thread, "thread.unparked")
        return {"thread_id": thread["id"]}

    def pin(command, actor):
        values = PinInput(**command.payload)
        thread = _own(workspace, command, values.thread_id)
        workspace.store.get_entry(values.record_id)
        pinned = [rid for rid in thread.get("pinned_ids") or [] if rid != values.record_id]
        excluded = [rid for rid in thread.get("excluded_ids") or [] if rid != values.record_id]
        if values.excluded:
            excluded.append(values.record_id)
        elif values.pinned:
            pinned.append(values.record_id)
        thread.update(pinned_ids=pinned[-50:], excluded_ids=excluded[-50:], updated_at=now())
        workspace.store.put("thread", thread, "thread.pinned")
        return {"thread_id": thread["id"], "pinned_ids": thread["pinned_ids"], "excluded_ids": thread["excluded_ids"]}

    def seen(command, actor):
        values = SeenInput(**command.payload)
        thread = _own(workspace, command, values.thread_id)
        thread["last_seen_message_id"] = values.message_id
        workspace.store.put("thread", thread)
        return {"thread_id": thread["id"]}

    def merge(command, actor):
        researcher_only(actor)
        values = MergeInput(**command.payload)
        source = _own(workspace, command, values.thread_id)
        target = _own(workspace, command, values.into_thread_id)
        if source["id"] == target["id"]:
            raise ValueError("A thread cannot merge into itself")
        if source["status"] == "merged":
            raise ValueError("This thread was already merged")
        if target["status"] == "merged":
            raise ValueError("The target thread was merged; choose an open one")
        merge_message = {"id": "message_" + command.id, "campaign_id": command.campaign_id, "role": "user", "origin": "researcher",
                         "content": values.note, "thread_id": target["id"], "merge_of_thread_id": source["id"], "created_at": now()}
        workspace.store.put("message", merge_message, "message.created")
        source.update(status="merged", merged_into=target["id"], updated_at=now())
        workspace.store.put("thread", source, "thread.merged")
        write_summary(workspace, source["id"], reason="merged", model=False)
        # The target's revision moves (its researcher wrote), and the lead reads the note as a request on the target's leaf.
        target = thread_of(workspace, target["id"])
        target["guidance_revision"] = int(target.get("guidance_revision", 0)) + 1
        target["updated_at"] = now()
        workspace.store.put("thread", target, "thread.guidance_changed")
        run = None
        if workspace.pi.owns(command.campaign_id):
            lead = lead_agent(workspace, command.campaign_id)
            workspace.pi._request(command.campaign_id, True)
            run = workspace.pi.enqueue(lead, "pi_run_" + command.id, "The researcher merged the branch \"" + source["title"] + "\" into this conversation with this note:\n" + values.note
                                       + "\nTake the note as the researcher's request here; what the branch concluded is in its summary (thread " + source["id"] + ").",
                                       mode="steer", origin={"thread_id": target["id"], "message_id": merge_message["id"], "actor": "researcher"},
                                       **({"leaf_entry_id": target["agent_leaf"]} if target.get("agent_leaf") else {"branch_from_entry_id": target.get("fork_entry_id")}),
                                       thread_revision=target["guidance_revision"])
        return {"thread_id": source["id"], "into_thread_id": target["id"], "message_id": merge_message["id"], "run_id": run["id"] if run else None}

    commands.register("thread.fork", fork, model=ForkInput)
    commands.register("thread.rename", rename, model=ThreadInput)
    commands.register("thread.park", park, model=ThreadInput)
    commands.register("thread.unpark", unpark, model=ThreadInput)
    commands.register("thread.pin", pin, model=PinInput, delegable=True)
    commands.register("thread.merge", merge, model=MergeInput)
    commands.listeners.append(lambda record: post_lab_event(workspace, record))


# Lab events ------------------------------------------------------------------------------------------------
LAB_EVENT_OPERATIONS = {"trial.create", "draft.launch", "trial.control", "trial.continue", "hypothesis.create", "hypothesis.status", "hypothesis.nominate",
                        "hypothesis.allocate", "intervention.batch", "study.race.create", "study.race.decide", "research.generate", "finding.record",
                        "problem_note.adopt", "report.write", "autopilot.set", "library.publish"}


def post_lab_event(workspace, record):
    """A command that completed in one thread becomes one line in every other active thread of the campaign."""
    origin = record.get("origin") or {}
    operation = record["request"]["operation"]
    if not origin.get("thread_id") or operation not in LAB_EVENT_OPERATIONS:
        return
    campaign_id = record["campaign_id"]
    try:
        source = thread_of(workspace, origin["thread_id"])
    except KeyError:
        return
    actor = {"researcher": "You", "lead": "The lead", "page_agent": "An agent", "autopilot": "Autopilot"}.get(origin.get("actor"), "Someone")
    outcome = record.get("outcome") or {}
    target = outcome.get("trial_id") or outcome.get("hypothesis_id") or outcome.get("race_id") or outcome.get("decision_id") or ""
    line = f"{actor} ran {operation}{' on ' + target if target else ''} in the branch \"{source['title']}\"."
    for thread in workspace.store.list("thread", campaign_id):
        if thread["id"] == source["id"] or thread["status"] != "active":
            continue
        workspace.store.put("message", {"id": f"message_lab_{content_hash([record['id'], thread['id']])[:16]}", "campaign_id": campaign_id, "role": "assistant",
                                        "origin": "lab_event", "content": line, "thread_id": thread["id"], "command_id": record["id"], "created_at": now()}, "message.created")
