"""Problem note records: a mutable head, immutable revisions, annotations with tiers, and Adopt.

Sections: objective, knobs, observables, noise, constraints, confounders, open_questions, each {text, items, latex}.
The lead revises the note through its tools (author lead); the researcher through problem_note.revise. A question on a
span is an annotation; the lookup and quick tiers answer without the bus, the lead tier answers in a turn as a proposed
edit the researcher accepts or rejects, the visual tier adds a drawn answer. Adopt hands the note to the formulator as the
problem statement of a problem import; the charter it writes is linked back, and the researcher confirms it.

That is the note's full path. On the quick path (roadmap track P, decisions 28–32) the lead writes the charter of a simple
problem itself (charter_write); the note is then read from the charter, with the lead's confounders, and is not revised or
adopted; the researcher confirms the charter in one command (problem_note.confirm), which accepts its assumptions and installs
its tasks. A note's path is None until the lead or the researcher writes it, then quick or full.
"""
import os
from typing import Literal

from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.storage.sqlite import now

from balsamic.notes.router import classify

SECTIONS = ("objective", "knobs", "observables", "noise", "constraints", "confounders", "open_questions")
PATHS = ("quick", "full")
TITLES = {"objective": "Objective", "knobs": "Knobs", "observables": "Observables", "noise": "Noise", "constraints": "Constraints",
          "confounders": "Confounders", "open_questions": "Open questions"}
TIERS = ("lookup", "quick", "lead", "visual")


def note_id(campaign_id):
    return "note_" + campaign_id


def empty_sections():
    return {name: {"text": "", "items": [], "latex": []} for name in SECTIONS}


def ensure_note(workspace, campaign_id, *, thread_id=None):
    identity = note_id(campaign_id)
    try:
        return workspace.store.get(identity, "problem_note")
    except KeyError:
        campaign = workspace.store.get(campaign_id, "campaign")
        record = {"id": identity, "campaign_id": campaign_id, "thread_id": thread_id, "title": campaign["name"], "current_revision": 0,
                  "adopted_revision": None, "charter_id": None, "import_id": None, "status": "drafting", "created_at": now(), "updated_at": now()}
        with workspace.lock:
            workspace.store.put("problem_note", record, "problem_note.created")
            revise(workspace, identity, {"sections": {"objective": {"text": campaign.get("objective") or ""}}}, author="researcher",
                   reason="the campaign's question, as written when it was created", path=None)
            return workspace.store.get(identity, "problem_note")


def revision_of(workspace, identity, number):
    return workspace.store.get(f"{identity}_r{number}", "problem_note_revision")


def _merge_sections(previous, patch):
    sections = {name: dict(previous.get(name) or {"text": "", "items": [], "latex": []}) for name in SECTIONS}
    for name, value in (patch or {}).items():
        if name not in SECTIONS:
            raise ValueError(f"Unknown section {name}; the note has " + ", ".join(SECTIONS))
        if not isinstance(value, dict):
            raise ValueError(f"Section {name} is an object with text, items and latex")
        current = sections[name]
        if "text" in value:
            current["text"] = str(value["text"])[:20000]
        if "items" in value:
            current["items"] = [str(item)[:2000] for item in (value["items"] or [])][:100]
        if "latex" in value:
            current["latex"] = [str(item)[:4000] for item in (value["latex"] or [])][:50]
        sections[name] = current
    return sections


def revise(workspace, identity, changes, *, author, reason="", source_message_id=None, run_id=None, annotation_id=None, path="full"):
    """A new immutable revision from a sections patch; the head moves to it. A revision written on a note whose path is not
    taken yet takes the full path (path=None only for the note's first revision, the campaign's question)."""
    if author not in {"lead", "researcher"}:
        raise ValueError("A revision is written by the lead or the researcher")
    with workspace.lock, workspace.store.transaction():
        note = workspace.store.get(identity, "problem_note")
        if note.get("path") == "quick":
            raise ValueError("The note is on the quick path: it is read from the lead's charter and has no revisions of its own. "
                             "Change the charter instead: the lead with charter_write, the researcher on the Charter tab (#note/charter)")
        if note["status"] == "confirmed":
            raise ValueError("The note was adopted and its charter confirmed; fork the campaign to change the problem")
        previous = revision_of(workspace, identity, note["current_revision"]) if note["current_revision"] else {"sections": empty_sections(), "glossary": []}
        sections = _merge_sections(previous["sections"], changes.get("sections"))
        glossary = previous.get("glossary") or []
        if changes.get("glossary") is not None:
            glossary = [{"term": str(entry.get("term", ""))[:200], "definition": str(entry.get("definition", ""))[:2000]} for entry in changes["glossary"] if isinstance(entry, dict) and entry.get("term")][:200]
        if sections == previous["sections"] and glossary == (previous.get("glossary") or []) and not changes.get("title"):
            raise ValueError("The revision changes nothing")
        number = note["current_revision"] + 1
        record = {"id": f"{identity}_r{number}", "note_id": identity, "campaign_id": note["campaign_id"], "revision": number, "sections": sections, "glossary": glossary,
                  "title": (changes.get("title") or note["title"])[:200], "author": author, "reason": (reason or "")[:2000], "source_message_id": source_message_id,
                  "run_id": run_id, "proposed_by_annotation_id": annotation_id, "created_at": now()}
        workspace.store.put_immutable("problem_note_revision", record, "problem_note.revised")
        note.update(current_revision=number, title=record["title"], updated_at=now())
        if path and not note.get("path"):
            note["path"] = path
        if note["status"] == "adopted":
            note["status"] = "drafting"   # a note changed after adoption must be adopted again
        workspace.store.put("problem_note", note, "problem_note.updated")
        return record


def annotations_of(workspace, identity):
    return [row for row in workspace.store.list("note_annotation", workspace.store.get(identity, "problem_note")["campaign_id"]) if row["note_id"] == identity]


def view(workspace, identity, *, revision=None):
    note = workspace.store.get(identity, "problem_note")
    number = revision or note["current_revision"]
    # On the quick path the note is read from the charter's current revision; its stored revisions are history.
    current = rendered(workspace, note) if note.get("path") == "quick" and revision is None else revision_of(workspace, identity, number) if number else None
    revisions = [{key: row[key] for key in ("id", "revision", "author", "reason", "created_at", "source_message_id", "proposed_by_annotation_id")}
                 for row in workspace.store.list("problem_note_revision", note["campaign_id"]) if row["note_id"] == identity]
    charter = None
    if note.get("import_id"):
        try:
            record = workspace.problem_imports.sync(note["import_id"]) if hasattr(workspace, "problem_imports") else workspace.store.get(note["import_id"], "problem_import")
        except (KeyError, ValueError):
            record = None
        if record:
            if record.get("charter_id") and note.get("charter_id") != record["charter_id"]:
                # The note follows the charter of its current adoption: adopting again writes a new charter.
                note["charter_id"] = record["charter_id"]
                with workspace.lock:
                    workspace.store.put("problem_note", note, "problem_note.linked")
            charter = {"import_id": record["id"], "status": record.get("status"), "error": record.get("error"), "charter_id": record.get("charter_id"), "reply": record.get("reply"),
                       "model": record.get("model"), "tier": record.get("tier"), "usage": record.get("usage")}   # which model the formulator runs on: fixed for the import's lifetime
    if note.get("charter_id"):
        try:
            charter = {**(charter or {}), "charter": workspace.charters.view(note["charter_id"])}
        except KeyError:
            pass
    from balsamic.notes import installed, skips
    return {"note": note, "revision": current, "revisions": revisions, "annotations": annotations_of(workspace, identity), "charter": charter, "sections": list(SECTIONS), "titles": TITLES,
            "skips": skips.view(workspace, note), "writing": installed.writing(workspace, note["campaign_id"]),
            "installed": [{"problem_id": row["problem_id"], "name": row["name"]} for row in installed.problems_of(workspace, note["campaign_id"])]}


# Annotations and tiers ------------------------------------------------------------------------------------
class Anchor(Contract):
    revision: int = Field(ge=1)
    section: Literal["objective", "knobs", "observables", "noise", "constraints", "confounders", "open_questions"]
    item_index: int | None = Field(default=None, ge=0)
    start: int = Field(default=0, ge=0)
    end: int = Field(default=0, ge=0)
    quote: str = Field(default="", max_length=2000)


class AskInput(Contract):
    note_id: str
    anchor: Anchor
    question: str = Field(min_length=1, max_length=8000)
    kind: Literal["ask", "define", "explain", "challenge", "visualize"] = "ask"
    tier: Literal["lookup", "quick", "lead", "visual"] | None = None


class ResolveInput(Contract):
    annotation_id: str
    choice: Literal["accept", "reject", "resolve"]


def lookup(revision, question):
    text = question.lower()
    for entry in revision.get("glossary") or []:
        term = entry["term"].lower()
        if term and (term in text):
            return f"{entry['term']}: {entry['definition']}"
    return None


def quick_answer(workspace, note, revision, question):
    """One cheap model call with the note as its only context; no tools, nothing recorded as a decision."""
    if os.environ.get("GRATING_LLM_DISABLED"):
        raise ValueError("Model calls are disabled in this workspace; ask the lead instead")
    config = workspace.pi.configuration(note["campaign_id"]) or {}
    default = (config.get("models") or {}).get("default")
    if not default:
        raise ValueError("No model is configured for quick answers; ask the lead instead")
    context = "\n".join(f"## {TITLES[name]}\n{section.get('text', '')}\n" + "\n".join("- " + item for item in section.get("items", []))
                        for name, section in revision["sections"].items())
    reply = workspace.pi.client.complete("note_quick_" + content_hash([note["id"], question])[:16], {
        "provider": default.get("provider"), "model": default.get("model"), "effort": "low", "max_tokens": 400, "label": "quick answer",
        "system": "Answer the researcher's question about this problem note in at most four sentences, from the note alone. Say when the note does not say.",
        "prompt": "Problem note:\n" + context + "\n\nQuestion: " + question}, timeout=120)
    return {"text": (reply or {}).get("text", "").strip(), "cost_usd": ((reply or {}).get("usage") or {}).get("cost_usd"), "model": default.get("model")}


def annotate(workspace, values, *, tier, escalated_from=None, answer=None, run_id=None, identity=None):
    note = workspace.store.get(values.note_id, "problem_note")
    record = {"id": identity or "annotation_" + content_hash([values.note_id, values.anchor.model_dump(), values.question, now()])[:20], "note_id": note["id"],
              "campaign_id": note["campaign_id"], "anchor": values.anchor.model_dump(), "kind": values.kind, "question": values.question, "tier": tier,
              "escalated_from_tier": escalated_from, "answer": answer, "proposed_edit": None, "proposed_revision_id": None, "visual_id": None,
              "status": "answered" if answer else "open", "run_id": run_id, "created_at": now(), "updated_at": now()}
    with workspace.lock:
        workspace.store.put("note_annotation", record, "note.annotated")
    return record


def ask(workspace, values, *, actor="researcher"):
    """The lookup and quick tiers, answered here and now; the lead and visual tiers are refused here (they go through the bus)."""
    note = workspace.store.get(values.note_id, "problem_note")
    revision = revision_of(workspace, note["id"], values.anchor.revision)
    tier = values.tier or classify(values.question, values.kind, revision.get("glossary") or [])
    escalated = None
    if tier == "lookup":
        found = lookup(revision, values.question)
        if found:
            return annotate(workspace, values, tier="lookup", answer={"text": found, "answered_by": "glossary"})
        tier, escalated = "quick", "lookup"
    if tier == "quick":
        try:
            answer = quick_answer(workspace, note, revision, values.question)
            return annotate(workspace, values, tier="quick", escalated_from=escalated, answer={**answer, "answered_by": "model"})
        except ValueError as exc:
            # Honest escalation: the next tier is the lead, through the bus; the annotation says why.
            record = annotate(workspace, values, tier="lead", escalated_from=escalated or "quick")
            record["escalation_reason"] = str(exc)
            with workspace.lock:
                workspace.store.put("note_annotation", record)
            return record
    raise ValueError(f"The {tier} tier runs a turn of the lead: send note.ask through the command bus")


def propose_edit(workspace, annotation_id, *, answer, proposed_edit=None, author="lead", run_id=None):
    with workspace.lock:
        record = workspace.store.get(annotation_id, "note_annotation")
        if record["status"] in {"accepted", "rejected", "resolved"}:
            raise ValueError("This annotation is closed")
        record.update(answer={"text": answer, "answered_by": author, "run_id": run_id}, proposed_edit=proposed_edit or None,
                      status="answered", updated_at=now())
        workspace.store.put("note_annotation", record, "note.edit_proposed" if proposed_edit else "note.answered")
        return record


def attach_visual(workspace, annotation_id, artifact_id):
    with workspace.lock:
        record = workspace.store.get(annotation_id, "note_annotation")
        record.update(visual_id=artifact_id, status="answered" if record["status"] == "open" else record["status"], updated_at=now())
        workspace.store.put("note_annotation", record, "note.answered")
        return record


# Adopt -------------------------------------------------------------------------------------------------------
def held_skips(workspace, note):
    from balsamic.notes.skips import held
    return held(workspace, note)


def markdown(revision, skipped=None):
    lines = ["# " + revision.get("title", "Problem note"), ""]
    for name, section in revision["sections"].items():
        if not (section.get("text") or section.get("items") or section.get("latex")):
            if name in (skipped or {}):   # left unwritten by agreement: the formulator reads why
                lines += ["## " + TITLES[name], "", "Skipped with the researcher's agreement: " + skipped[name]["reason"], ""]
            continue
        lines += ["## " + TITLES[name], ""]
        if section.get("text"):
            lines += [section["text"], ""]
        lines += ["- " + item for item in section.get("items", [])]
        lines += ["$$" + formula + "$$" for formula in section.get("latex", [])]
        lines.append("")
    if revision.get("glossary"):
        lines += ["## Glossary", ""] + [f"- **{entry['term']}**: {entry['definition']}" for entry in revision["glossary"]]
    return "\n".join(lines)


WORDS_LIMIT = 60000


def researcher_words(workspace, campaign_id):
    """The researcher's own words on the campaign so far, verbatim and in time order: the objective recorded at setup, the setup
    conversation (its questions too, so a short answer reads in context) and every message they sent the agents. The note is the
    lead's account of these; the formulator reads both, so nothing the researcher said is lost in the retelling. None when there
    is nothing to read."""
    campaign = workspace.store.get(campaign_id, "campaign")
    titles = {thread["id"]: thread.get("title") or thread.get("name") or thread["id"] for thread in workspace.store.list("thread", campaign_id)}
    said = [m for m in sorted(workspace.store.list("message", campaign_id), key=lambda m: m.get("created_at") or "")
            if (m.get("content") or "").strip() and (m.get("origin") == "setup" or (m.get("role") == "user" and m.get("origin", "researcher") == "researcher"))]

    def turn(m):
        who = "Setup assistant" if m.get("origin") == "setup" else "Researcher"
        return f"**{who}** ({titles.get(m.get('thread_id'), 'no thread')}, {(m.get('created_at') or '')[:16].replace('T', ' ')}):\n\n{m['content'].strip()}\n"
    head = ["# The researcher's own words", "",
            "Verbatim and in time order: the setup conversation and the researcher's messages to the agents, before this adoption.", ""]
    if (campaign.get("objective") or "").strip():
        head += ["## Objective recorded at setup", "", campaign["objective"].strip(), ""]
    turns = [turn(m) for m in said]
    # Too much to read: the setup conversation stays (it states the problem), the oldest later messages go first.
    left_out = 0
    while turns and len("\n".join(head + turns)) > WORDS_LIMIT:
        later = next((i for i, m in enumerate(said) if not m.get("setup_id")), None)
        if later is None:
            break
        del turns[later], said[later]
        left_out += 1
    if left_out:
        head += [f"({left_out} older messages are left out for length.)", ""]
    if not turns and len(head) == 4:
        return None
    return "\n".join(head + (["## Conversation", ""] if turns else []) + turns)[:WORDS_LIMIT]


def adopt(workspace, identity, revision_number, *, actor):
    if actor != "researcher":
        raise ValueError("Only the researcher adopts the note")
    with workspace.lock:
        note = workspace.store.get(identity, "problem_note")
        if note.get("path") == "quick":
            raise ValueError("The note is on the quick path: the lead wrote the charter, and the note is read from it. Confirm the charter "
                             "on the Charter tab (#note/charter); nothing is adopted")
        if revision_number != note["current_revision"]:
            raise ValueError("Adopt the current revision; the note changed")
        revision = revision_of(workspace, identity, revision_number)
        if not (revision["sections"]["objective"].get("text") or "").strip():
            raise ValueError("The note needs an objective before it is adopted")
    imports = getattr(workspace, "problem_imports", None)
    if imports is None:
        raise ValueError("The formulator is not available in this workspace")
    from optimization_framework.problem_import.service import ImportCreate
    from balsamic.notes import installed
    # The installed problem the tasks already run on goes with the note: the formulator builds on it instead of asking whether to.
    statement = markdown(revision, held_skips(workspace, note)) + "\n\n" + installed.statement(installed.problems_of(workspace, note["campaign_id"]))
    record = imports.create(ImportCreate(title=revision["title"][:200], statement=statement.strip()[:50000], notes=f"Adopted from problem note {identity} revision {revision_number}"))
    words = researcher_words(workspace, note["campaign_id"])
    if words:
        imports.add_document(record["id"], "researcher.md", words.encode())
    imports.start(record["id"])
    with workspace.lock:
        note = workspace.store.get(identity, "problem_note")
        note.update(adopted_revision=revision_number, import_id=record["id"], status="adopted", path="full", updated_at=now())
        workspace.store.put("problem_note", note, "problem_note.adopted")
        campaign = workspace.store.get(note["campaign_id"], "campaign")
        campaign["problem_note_id"] = identity
        workspace.store.put("campaign", campaign)
    return {"note_id": identity, "revision": revision_number, "import_id": record["id"]}


# The quick path (roadmap P2) -----------------------------------------------------------------------------------
FORMS = {"quantities": "a test on the values", "linear": "linear in the design", "design": "a condition on the design",
         "outcome": "a condition on the measured result", "evaluator": "enforced by the evaluator", "qualitative": "in words only"}


def _section(text="", items=()):
    return {"text": str(text)[:20000], "items": [str(item)[:2000] for item in items][:100], "latex": []}


def _units(units):
    return "" if not units or str(units).strip() in {"1", "dimensionless"} else " " + str(units).strip()


def from_charter(charter, *, confounders=None, registry=None):
    """The note's sections read from a charter (the quick path). The charter states the objective, the knobs (decision
    variables and inputs), the observables, the noise and the constraints; the confounders are the lead's, given with
    charter_write; the open questions are the charter's questions and assumptions. Values are the charter's, computed where
    they are derived, never typed here."""
    from optimization_framework.problem_charter import charter as mechanics
    described = mechanics.describe(charter, registry)
    values, texts = described["values"], described["rendered"]
    quantities, objective, binding = charter.get("quantities") or {}, charter.get("objective"), charter.get("evaluator") or {}

    def value(name):
        return mechanics.show(values.get(name), (quantities.get(name) or {}).get("units", ""))

    knobs = []
    for variable in charter.get("variables") or []:
        shape = " × ".join(f"{part} = {value(part)}" if isinstance(part, str) else str(part) for part in variable.get("shape") or [])
        kind = variable["representation"]
        if kind == "permutation":
            words = f"an order of {shape or 'its items'}, each item once"
        elif kind == "continuous":
            words = f"a number from {variable.get('lower')} to {variable.get('upper')}{_units(variable.get('units'))}" + (f", for each of {shape}" if shape else "")
        elif kind == "discrete":
            words = "one of " + ", ".join(mechanics.show(item) for item in variable.get("values") or []) + (f", for each of {shape}" if shape else "")
        elif kind == "binary":
            words = "0 or 1" + (f", for each of {shape}" if shape else "")
        else:
            words = "a structured value" + (f" laid out as {variable['layout']}" if variable.get("layout") else "")
        knobs.append(f"{variable['name']} (decision variable): {variable['description']}; {words}." + (f" {variable['meaning']}" if variable.get("meaning") else ""))
    for name, quantity in quantities.items():
        if quantity.get("role") == "derived":
            knobs.append(f"{name} = {value(name)}: {quantity['description']} (computed: {quantity['expression']}).")
        else:
            knobs.append(f"{name} = {value(name)}: {quantity['description']}." + (" Assumed" + (f": {quantity['note']}" if quantity.get("note") else "") + "."
                                                                                   if quantity.get("origin") == "assumed" else ""))
    observables = []
    if objective:
        observables.append(f"{objective['name']} ({objective['units']}), to {objective['direction']}: {texts.get('objective') or objective['definition']}")
    for metric in charter.get("metrics") or []:
        observables.append(f"{metric['name']} ({metric['units']}), recorded" + (f", to {metric['direction']}" if metric.get("direction") else "")
                           + (f": {texts.get('metric ' + metric['name']) or metric['definition']}" if metric.get("definition") else ""))
    if binding.get("kind") == "installed":
        observables.append(f"Computed by the installed problem {binding['problem_id']}.")
    elif binding.get("kind") == "declared":
        observables.append(f"Computed by a new problem, {binding['problem_id']}, built for this campaign: " + ((binding.get("notes") or "").strip()[:1500] or "see the charter."))
    noise = "" if not binding else ("Deterministic: a design always gets the same score." if binding.get("deterministic", True) else
                                    "Not deterministic: evaluations of the same design differ; the objective says how repeats are combined.")
    fidelity = [f"Fidelity {field} = {value(name)} ({name}): a score belongs to the fidelity it was computed at." for field, name in (binding.get("fidelity") or {}).items()]
    constraints = [f"{texts.get('constraint ' + rule['id']) or rule['statement']} ({rule.get('kind', 'hard')}, {FORMS.get(rule['form'], rule['form'])}"
                   + (f": {rule['test']}" if rule.get("test") else "") + ")" for rule in charter.get("constraints") or []]
    questions = []
    for question in charter.get("questions") or []:
        if question.get("answer") is not None:
            questions.append(f"{question['question']} Answered: {question['answer']}")
        elif question.get("sent"):
            questions.append(f"{question['question']} Left to the lead to decide.")
        else:
            questions.append(f"{question['question']} To answer on the Charter tab" + (f" (options: {'; '.join(question['options'])})" if question.get("options") else "") + ".")
    for assumption in charter.get("assumptions") or []:
        questions.append(f"Assumption: {assumption['statement']}" + (" (accepted)" if assumption.get("accepted") else " (confirming accepts it)"))
    for name, quantity in quantities.items():
        if quantity.get("origin") == "assumed":
            questions.append(f"Assumed: {name} = {value(name)}" + (f", {quantity['note']}" if quantity.get("note") else "")
                             + (" (accepted)" if quantity.get("accepted") else " (confirming accepts it)"))
    named = confounders or {}
    return {"objective": _section(texts.get("text") or texts.get("summary") or "", observables[:1] if objective else []),
            "knobs": _section("" if knobs else "No decision variable yet.", knobs),
            "observables": _section("" if observables else "No objective yet.", observables),
            "noise": _section(noise, fidelity),
            "constraints": _section("" if constraints else "None beyond the decision variables' own bounds.", constraints),
            "confounders": _section(named.get("text") or ("" if named.get("items") else "None named."), named.get("items") or []),
            "open_questions": _section("" if questions else "None remaining.", questions)}


def rendered(workspace, note):
    """The quick note as a revision: its sections read from the charter's current revision."""
    record = workspace.charters.get(note["charter_id"])
    return {"id": f"{note['id']}_charter_r{record['revision']}", "note_id": note["id"], "campaign_id": note["campaign_id"], "revision": record["revision"],
            "sections": from_charter(record["charter"], confounders=note.get("confounders"), registry=workspace.charters.registry),
            "glossary": [], "title": record["charter"]["title"], "author": "lead", "reason": f"Read from the charter, revision {record['revision']}",
            "source_message_id": None, "run_id": None, "proposed_by_annotation_id": None, "created_at": record.get("updated_at"),
            "charter_id": record["id"], "charter_revision": record["revision"]}


def write_charter(workspace, campaign_id, charter, *, confounders=None, questions=(), reason="", run_id=None, thread_id=None):
    """The lead's charter_write (decision 29): the first call creates the campaign's charter and puts its note on the quick
    path, a later one revises it. Values the researcher set, answers and waivers are kept. A question is asked with the
    write (at most QUICK_QUESTIONS, in one round); a question the researcher has not answered stays when a later write leaves
    it out. Refused once the note is adopted (the formulator writes its charter) and once the charter has been confirmed
    (a change is then the researcher's, on the Charter tab). All or nothing: a refusal saves nothing."""
    from optimization_framework.contracts.problem_charter import ProblemCharter
    from optimization_framework.problem_charter import charter as mechanics
    from optimization_framework.problem_charter.service import QUICK_QUESTIONS, QUICK_ROUNDS, question_rounds
    charters = workspace.charters
    with workspace.lock, workspace.store.transaction():
        note = ensure_note(workspace, campaign_id, thread_id=thread_id)
        if note.get("import_id") or note.get("adopted_revision") is not None:
            raise ValueError("The note was adopted, so it is on the full path: the formulator writes the charter (#note/charter). Answer "
                             "its questions there, or ask the researcher to request a change on the Charter tab")
        record = charters.get(note["charter_id"]) if note.get("path") == "quick" and note.get("charter_id") else None
        if record is not None and record.get("confirmed_revision") is not None:
            raise ValueError("The charter was confirmed and the campaign's tasks run on it: a change is the researcher's now, a value they "
                             "change or a request they make on the Charter tab (#note/charter)")
        # A question the charter did not hold yet is asked, as one given in questions is: it counts toward the round.
        held = [q for q in (record["charter"]["questions"] if record else [])]
        known = {q["id"] for q in held}
        given = [q for q in charter.get("questions") or [] if isinstance(q, dict)]
        asked = [q for q in given if q.get("id") not in known] + list(questions or [])
        proposed = {**charter, "questions": [q for q in given if q.get("id") in known]}
        kept = {q["id"] for q in proposed["questions"]}
        # A question the researcher has not answered yet stays until they do, though a whole charter leaves it out.
        proposed["questions"] += [q for q in held if q.get("answer") is None and not q.get("sent") and q["id"] not in kept]
        proposed = ProblemCharter.model_validate(proposed).model_dump(mode="json")
        if asked:
            if len(asked) > QUICK_QUESTIONS:
                raise ValueError(f"The quick path asks at most {QUICK_QUESTIONS} questions, in one round; decide the rest as assumptions "
                                 "(origin assumed, with a note) for the researcher to accept or change")
            if record is not None and question_rounds(record) >= QUICK_ROUNDS:
                raise ValueError("The quick path asks one round of questions, and it was asked; record what is still open as an assumption "
                                 "(origin assumed, with a note) for the researcher to accept or change")
            charters.asked({"questions": held + proposed["questions"]}, asked)
        campaign = workspace.store.get(campaign_id, "campaign")
        rationale = (reason or "").strip()[:400]
        if record is None:
            record = charters.create(charters.from_formulator(None, proposed), by="lead", writer="lead",
                                     source={"kind": "lead", "id": campaign_id, "name": campaign["name"], "thread_id": thread_id},
                                     rationale="First draft from the lead" + (f": {rationale}" if rationale else ""))
        else:
            record = charters.submit(record["id"], proposed, run_id=run_id or "lead", by="lead")
        if asked:
            record = charters.ask(record["id"], asked, by="lead")
        note = workspace.store.get(note["id"], "problem_note")
        note.update(path="quick", charter_id=record["id"], updated_at=now())
        if isinstance(confounders, dict):
            note["confounders"] = _section(confounders.get("text") or "", confounders.get("items") or [])
        workspace.store.put("problem_note", note, "problem_note.quick")
    described = mechanics.describe(record["charter"], charters.registry)
    return {"charter_id": record["id"], "revision": record["revision"], "note_id": note["id"], "blocking": described["blocking"],
            "values": described["values"], "errors": described["errors"], "rendered": described["rendered"],
            "findings": [row for row in described["findings"] if not row.get("waived")], "questions_asked": len(asked), "link": "#note/charter"}


def confirm(workspace, note, charter_id, revision, *, campaign_id):
    """The researcher's one action on the quick path (decision 32): it accepts the assumptions of the revision they read,
    confirms that revision and installs its tasks. Refused on a stale revision, on a blocking question still open and on any
    other blocking finding: those are settled on the Charter tab first."""
    from optimization_framework.contracts.requests import CampaignUpdate, CharterReference
    from optimization_framework.problem_charter import charter as mechanics
    charters = workspace.charters
    if note.get("path") != "quick":
        raise ValueError("The note is on the full path: its charter is confirmed on the Charter tab (#note/charter)")
    if note.get("charter_id") != charter_id:
        raise ValueError(f"{charter_id} is not the charter of this campaign's note")
    record = charters.get(charter_id)
    if record["revision"] != revision:
        raise ValueError(f"The charter changed since you read it (now revision {record['revision']}): read that revision and confirm it")
    accepted = []
    if record.get("status") != "confirmed":
        rows = [row for row in mechanics.findings(record["charter"], charters.registry) if row["severity"] == "blocking" and not row.get("waived")]
        left = {q["id"] for q in record["charter"]["questions"] if q.get("sent")}
        questions = [row for row in rows if row["code"] == "question.open"]
        if [row for row in questions if row["key"].split(":", 1)[1] not in left]:
            raise ValueError("Answer the lead's questions on the Charter tab (#note/charter) first, or leave them to the lead: "
                             + "; ".join(row["message"] for row in questions)[:1500])
        if questions:
            raise ValueError("The lead is deciding the questions you left to it; confirm the revision it writes next")
        settled = [row for row in rows if row["code"] != "assumption.unaccepted"]
        if settled:
            raise ValueError("Settle these on the Charter tab (#note/charter) before confirming: " + "; ".join(row["message"] for row in settled)[:1500])
        if rows:
            accepted = [row["key"].split(":", 1)[1] for row in rows]
            record = charters.accept_assumptions(charter_id, expected_revision=revision)
        charters.confirm(charter_id, expected_revision=record["revision"])
    reference = {"id": charter_id, "revision": record["revision"]}
    campaign = workspace.store.get(campaign_id, "campaign")
    if campaign.get("charter") == reference and workspace.current_tasks(campaign_id):
        raise ValueError(f"The charter is confirmed at revision {record['revision']} and its tasks are installed")
    campaign = workspace.update_campaign(campaign_id, CampaignUpdate(charter=CharterReference(**reference)))
    campaign["problem_note_id"] = note["id"]
    workspace.store.put("campaign", campaign)
    note = workspace.store.get(note["id"], "problem_note")
    note.update(status="confirmed", confirmed_charter=reference, updated_at=now())
    workspace.store.put("problem_note", note, "problem_note.confirmed")
    return {"note_id": note["id"], "charter": reference, "accepted": accepted, "campaign_revision": campaign["version"],
            "tasks": [task["name"] for task in workspace.current_tasks(campaign_id)], "link": "#note/charter"}


def tell_lead(workspace, record, text):
    """The researcher's answers to the lead's questions on its charter, or their request for a change: a turn of the lead in the
    thread it wrote the charter in (workspace.charter_lead, called by the charter service as it would tell the formulator)."""
    from balsamic.threads.service import ensure_main, lead_agent, thread_of
    campaign_id = (record.get("source") or {}).get("id")
    lead = lead_agent(workspace, campaign_id) if campaign_id else None
    if lead is None or not workspace.pi.owns(campaign_id):
        raise ValueError("The lead writes this charter and the campaign's agent team is not started: start it, then send this again")
    try:
        thread = thread_of(workspace, (record.get("source") or {}).get("thread_id") or "")
    except KeyError:
        thread = ensure_main(workspace, campaign_id)
    placement = {"thread_revision": thread.get("guidance_revision"),
                 **({"leaf_entry_id": thread["agent_leaf"]} if thread.get("agent_leaf") else {"branch_from_entry_id": thread.get("fork_entry_id")})}
    with workspace.lock, workspace.store.transaction():
        workspace.pi._request(campaign_id, True)
        return workspace.pi.enqueue(lead, "pi_run_charter_" + content_hash([record["id"], record["revision"], text])[:24], text, mode="steer",
                                    origin={"thread_id": thread["id"], "actor": "researcher", "charter_id": record["id"]}, **placement)


# Commands ----------------------------------------------------------------------------------------------------
class ReviseInput(Contract):
    note_id: str
    sections: dict = Field(default_factory=dict)
    glossary: list[dict] | None = None
    title: str | None = Field(default=None, max_length=200)
    reason: str = Field(default="", max_length=2000)
    source_message_id: str | None = None
    annotation_id: str | None = None


class AdoptInput(Contract):
    note_id: str
    revision: int = Field(ge=1)


class ConfirmInput(Contract):
    note_id: str
    charter_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1, description="The charter revision the researcher read")


def register(workspace):
    commands = workspace.commands

    def _own(command, identity):
        if identity == note_id(command.campaign_id):
            ensure_note(workspace, command.campaign_id, thread_id=(command.origin.thread_id if command.origin else None))
        note = workspace.store.get(identity, "problem_note")
        if note["campaign_id"] != command.campaign_id:
            raise ValueError("The note belongs to another campaign")
        return note

    def revise_command(command, actor):
        values = ReviseInput(**command.payload)
        _own(command, values.note_id)
        origin = command.origin.model_dump() if command.origin else {}
        record = revise(workspace, values.note_id, values.model_dump(exclude={"note_id", "reason", "source_message_id", "annotation_id"}),
                        author="lead" if actor != "researcher" else "researcher", reason=values.reason, source_message_id=values.source_message_id or origin.get("message_id"),
                        run_id=origin.get("run_id"), annotation_id=values.annotation_id)
        return {"note_id": values.note_id, "revision": record["revision"], "revision_id": record["id"]}

    def adopt_command(command, actor):
        values = AdoptInput(**command.payload)
        _own(command, values.note_id)
        return adopt(workspace, values.note_id, values.revision, actor=actor)

    def confirm_command(command, actor):
        if actor != "researcher":
            raise ValueError("Only the researcher confirms the charter")
        values = ConfirmInput(**command.payload)
        note = _own(command, values.note_id)
        return confirm(workspace, note, values.charter_id, values.revision, campaign_id=command.campaign_id)

    def ask_command(command, actor):
        """The lead and visual tiers: a turn of the lead on the thread, told to answer as a proposed edit (or a visual)."""
        values = AskInput(**command.payload)
        note = _own(command, values.note_id)
        revision = revision_of(workspace, note["id"], values.anchor.revision)
        tier = values.tier or classify(values.question, values.kind, revision.get("glossary") or [])
        if tier in {"lookup", "quick"}:
            record = ask(workspace, values, actor=actor)
            return {"annotation_id": record["id"], "tier": record["tier"], "status": record["status"]}
        if not workspace.pi.owns(command.campaign_id):
            raise ValueError("Start the agent team first: this question needs a turn of the lead")
        origin = command.origin.model_dump() if command.origin else {}
        record = annotate(workspace, values, tier=tier, identity="annotation_" + content_hash(command.id)[:20])
        quote = values.anchor.quote or values.anchor.section
        prompt = (f"The researcher asks on the problem note (annotation {record['id']}, section {values.anchor.section}, revision {values.anchor.revision}; quoted: \"{quote[:300]}\"): "
                  f"{values.question}\n" + ("Answer with render_visual (give the annotation_id), then problem_note_propose with a short answer. "
                                             if tier == "visual" else "Answer with problem_note_propose: your answer, and, only if the note should change, the proposed_edit "
                                             "(a sections patch). Never rewrite the note silently.") + " Then yield_work.")
        from balsamic.threads.service import lead_agent, thread_of
        lead = lead_agent(workspace, command.campaign_id)
        workspace.pi._request(command.campaign_id, True)
        placement = {}
        if origin.get("thread_id"):
            thread = thread_of(workspace, origin["thread_id"])
            placement = {"thread_revision": thread.get("guidance_revision"), **({"leaf_entry_id": thread["agent_leaf"]} if thread.get("agent_leaf") else {"branch_from_entry_id": thread.get("fork_entry_id")})}
        run = workspace.pi.enqueue(lead, "pi_run_" + command.id, prompt, mode="steer", origin={**origin, "actor": "researcher", "annotation_id": record["id"]}, **placement)
        record.update(run_id=run["id"])
        with workspace.lock:
            workspace.store.put("note_annotation", record)
        return {"annotation_id": record["id"], "tier": tier, "status": record["status"], "run_id": run["id"]}

    def resolve_command(command, actor):
        if actor != "researcher":
            raise ValueError("Only the researcher accepts or rejects a proposed edit")
        values = ResolveInput(**command.payload)
        with workspace.lock:
            record = workspace.store.get(values.annotation_id, "note_annotation")
            if record["campaign_id"] != command.campaign_id:
                raise ValueError("The annotation belongs to another campaign")
            if record["status"] in {"accepted", "rejected", "resolved"}:
                raise ValueError("This annotation is closed")
            outcome = {"annotation_id": record["id"]}
            if values.choice == "accept":
                if not record.get("proposed_edit"):
                    raise ValueError("There is no proposed edit to accept")
                revision = revise(workspace, record["note_id"], record["proposed_edit"], author="researcher", reason="accepted the lead's proposed edit",
                                  annotation_id=record["id"])
                record["proposed_revision_id"] = revision["id"]
                outcome["revision"] = revision["revision"]
            record.update(status={"accept": "accepted", "reject": "rejected", "resolve": "resolved"}[values.choice], updated_at=now())
            workspace.store.put("note_annotation", record, "note.resolved")
        return outcome

    commands.register("problem_note.revise", revise_command, model=ReviseInput, delegable=True)
    commands.register("problem_note.adopt", adopt_command, model=AdoptInput)
    commands.register("problem_note.confirm", confirm_command, model=ConfirmInput)
    # The quick path's charter is the lead's: the researcher's answers and requests on it start a turn of the lead.
    workspace.charter_lead = lambda record, text: tell_lead(workspace, record, text)
    commands.register("note.ask", ask_command, model=AskInput)
    commands.register("note.resolve", resolve_command, model=ResolveInput)
