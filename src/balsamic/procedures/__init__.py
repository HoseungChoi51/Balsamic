"""Procedures: the instructions for one workflow, read when the workflow starts instead of sitting in every turn's system
prompt (harness plan, Phase 6). Each is a folder here with a SKILL.md in the Agent Skills format (frontmatter `name`,
`description`, `metadata.roles`; bundled files under `references/`), so the same files can be used from the Pi CLI or Claude Code.

At start-up the service layer scans this folder and registers `workspace.procedures`: each role's catalog (name and
description, sorted) goes into its static instructions, `procedure_read` serves a body, and `procedure_hint` names the
matching procedure in the result of a tool that starts a workflow when this run has not read it.

A problem's own procedures live in its pack (roadmap N3), not here: the static catalogs stay generic, since they are cached
per role, and the state block lists the procedures of the campaign's packs, which `procedure_read` serves to that campaign
only."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BODY_BYTES = 24 * 1024
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# The tool, or the command, that starts a workflow, and the procedure for it.
TOOL_HINTS = {"report_write": "report-brief", "problem_note_draft": "problem-formulation", "implementation_workspace_create": "implementation-supervision",
              "panel_render": "panels"}
COMMAND_HINTS = {"hypothesis.create": "proposal-fields", "hypothesis.edit": "proposal-fields", "journal.compaction_request": "journal-cleanup",
                 "finding.record": "recording-findings", "runtime.profile": "runtime-profiling"}


def parse(text):
    """The frontmatter (flat keys, and one level under metadata) and the body of a SKILL.md."""
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not match:
        raise ValueError("A procedure starts with a frontmatter block")
    meta, section = {}, None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        if line.startswith((" ", "\t")) and section is not None:
            meta[section][key.strip()] = value.strip()
        elif value.strip():
            meta[key.strip()], section = value.strip(), None
        else:
            meta[key.strip()], section = {}, key.strip()
    return meta, match.group(2).strip() + "\n"


def load(root):
    """The procedures of one folder, by name."""
    items = {}
    for path in sorted(Path(root).glob("*/SKILL.md")):
        meta, body = parse(path.read_text())
        name = meta.get("name", "")
        if name != path.parent.name or not NAME.fullmatch(name) or not meta.get("description"):
            raise ValueError(f"{path}: the name must match its folder and a description is required")
        roles = {role.strip() for role in (meta.get("metadata") or {}).get("roles", "").split(",") if role.strip()}
        files = sorted(str(file.relative_to(path.parent)) for file in path.parent.glob("references/*.md"))
        items[name] = {"name": name, "description": meta["description"], "roles": roles, "body": body, "files": files, "folder": path.parent}
    return items


class Procedures:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.items = load(self.root)
        self._folders = {}   # a pack's procedure folder, read once

    def campaign(self, workspace, campaign_id):
        """The procedures the campaign's packs bring, by name. A pack may not take the name of a generic procedure."""
        items = {}
        for folder in workspace.packs.procedure_folders(campaign_id):
            if folder not in self._folders:
                self._folders[folder] = load(folder)
            for name, item in self._folders[folder].items():
                if name in self.items:
                    raise ValueError(f"{folder}: the pack's procedure {name} has the name of a generic one")
                items.setdefault(name, item)
        return items

    def campaign_lines(self, workspace, role, campaign_id):
        """The state block's lines naming the campaign's pack procedures for this role; none when there are none."""
        entries = [(name, item["description"]) for name, item in sorted(self.campaign(workspace, campaign_id).items()) if role in item["roles"]]
        return ["Procedures for this campaign's problem (read with procedure_read before the workflow):",
                *(f"- {name}: {description}" for name, description in entries)] if entries else []

    def roles(self):
        return set().union(*(item["roles"] for item in self.items.values())) if self.items else set()

    def catalog(self, role):
        return [(item["name"], item["description"]) for name, item in sorted(self.items.items()) if role in item["roles"]]

    def catalog_text(self, role):
        entries = self.catalog(role)
        if not entries:
            return ""
        return "\nProcedures: before you start one of these workflows, read its procedure with procedure_read.\n" + "\n".join(
            f"- {name}: {description}" for name, description in entries)

    def read(self, role, name, file=None, campaign=None):
        """campaign: the procedures of the reader's campaign's packs (``campaign()``); without it only generic ones are served."""
        item = self.items.get(name) or (campaign or {}).get(name)
        if item is None or role not in item["roles"]:
            raise ValueError(f"No procedure {name} for this role and campaign; the catalog in your instructions and the state block list yours")
        # Models name the body as well: an empty file, "none" or SKILL.md itself.
        if file is None or file.strip().lower() in {"", "none", "skill.md"}:
            text, part = item["body"], "SKILL.md"
        else:
            if file not in item["files"]:
                raise ValueError(f"{name} has no file {file}; its files are: {', '.join(item['files']) or 'none'}")
            text, part = (item["folder"] / file).read_text(), file
        data = text.encode()
        cut = len(data) > BODY_BYTES
        return {"name": name, "file": part, "text": data[:BODY_BYTES].decode(errors="ignore"), "files": item["files"],
                **({"note": f"Cut at {BODY_BYTES} bytes."} if cut else {})}

    def hint(self, tools, agent, run, tool, arguments, result):
        """The procedure a workflow-starting call should have been preceded by, when this run neither read it nor was told."""
        name = TOOL_HINTS.get(tool) or (COMMAND_HINTS.get((arguments or {}).get("operation")) if tool == "campaign_command" else None)
        item = self.items.get(name or "")
        if item is None or agent["role"] not in item["roles"] or not isinstance(result, dict) or "error" in result:
            return None
        with tools.store.connection() as db:
            seen = db.execute("SELECT 1 FROM records WHERE ((kind='agent_tool_intent' AND json_extract(data,'$.tool')='procedure_read' "
                "AND json_extract(data,'$.arguments.name')=?) OR (kind='agent_tool_receipt' AND json_extract(data,'$.result.procedure')=?)) "
                "AND json_extract(data,'$.run_id')=? LIMIT 1", (name, name, run["id"])).fetchone()
        return None if seen else name


def register(workspace):
    from optimization_framework.agents.tools import EXTRA_TOOLS, obj, register_tool, S
    procedures = Procedures()
    workspace.procedures = procedures
    workspace.procedure_hint = procedures.hint
    if "procedure_read" not in EXTRA_TOOLS:   # process-wide; the handler reads the catalog of the workspace that calls it
        def procedure_read(tools, agent, run, args, identity):
            procedures = tools.workspace.procedures
            return procedures.read(agent["role"], args["name"], args.get("file"), procedures.campaign(tools.workspace, agent["campaign_id"]))
        register_tool("procedure_read", "Read a procedure from the catalog in your instructions: the steps and rules of one workflow, to read before "
                      "starting it. file: omit it for the procedure itself, or name one of its bundled files.", obj({"name": S, "file": S}, ["name"]), procedure_read, roles=sorted(procedures.roles()))
