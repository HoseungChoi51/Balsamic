"""The specialist roles: a brief, a tool scope and an output schema each (harness plan, Phase 7), read from editable files
in Pi's agent-definition format, so they work as Pi CLI agent definitions too:

    roles/<role>.md            frontmatter name, description, tools, model (a tier hint); the brief as the body (at most 200 words)
    roles/<role>.schema.json   the JSON schema of the result the role submits with submit_output

A specialist is told SPECIALIST_CONTRACT instead of the shared instructions: it reports to the agent that asked it, submits its
result, and starts nothing. The proposal reviewer's structured output is its proposal_review; it has no schema file.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "roles"
BRIEF_WORDS = 200
# Tool calls a specialist may make in one run; past them only submit_output and yield_work remain.
SPECIALIST_TOOL_CALLS = 40
SPECIALIST_CONTRACT = f"""You are an assistant to the agent that asked you (the lead or the discussion moderator), not to the researcher: you report to it,
and it decides what is done with your result. Your role's brief and your assignment are below.
Work only on the assignment. Start no new work: no commands, no experiments, no assistants of your own; if the assignment needs
more than you can do, say so in your result. A message from the agent that asked you, while you work, is part of the assignment.
Read the campaign with campaign_inspect and the records named in your assignment (Evidence IDs) with evidence_read; read
evidence on demand, not the whole archive. Cite exact record ids for every claim. A number comes from a record or a script you
ran, never from memory; a source's reported number is prior literature, not a measurement of this platform.
You have {SPECIALIST_TOOL_CALLS} tool calls for an assignment; spend them on what it asks. Save a long intermediate analysis with
artifact_save and cite its id.
When you are done, record your result (submit_output in the schema below; a reviewer records its verdict with proposal_review),
then call yield_work(complete) with a one-line summary in plain words. If you cannot finish, record what you have, say in it what
is missing, and complete."""


def _frontmatter(text):
    if not text.startswith("---\n"):
        raise ValueError("A role file starts with a frontmatter block")
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def _load():
    briefs, schemas = {}, {}
    for path in sorted(ROOT.glob("*.md")):
        meta, body = _frontmatter(path.read_text())
        role = meta.get("name")
        if role != path.stem:
            raise ValueError(f"{path}: name must match the file")
        if len(body.split()) > BRIEF_WORDS:
            raise ValueError(f"{path}: a brief is at most {BRIEF_WORDS} words")
        briefs[role] = {"name": role, "description": meta.get("description", ""), "tools": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()],
                        "model": meta.get("model") or None, "brief": body}
        schema = path.with_suffix(".schema.json")
        if schema.exists():
            schemas[role] = json.loads(schema.read_text())
    return briefs, schemas


ROLE_BRIEFS, ROLE_OUTPUT_SCHEMAS = _load()
