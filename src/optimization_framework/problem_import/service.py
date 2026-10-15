"""A Pi agent reads a researcher's documents and code and proposes a problem formulation.

The import exists before any campaign. Its agent uses its own Pi identity
(``import_<id>``) and only the read-only tools below, confined to the import
folder. The draft is a proposal: the researcher edits it in the New campaign
form, where the campaign's ordinary validation applies.
"""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from optimization_framework.contracts.problem_imports import ProblemDraft, ProblemExample
from optimization_framework.storage.sqlite import now

from .files import ImportFolder

PREFIX = "import_"
ROLE = "problem_importer"
THINKING = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ACTIVE = {"running"}

GUIDELINE = (Path(__file__).with_name("guideline.md")).read_text()

INSTRUCTIONS = """You are the formulator. You turn a researcher's material into a problem charter, following the guideline below.

Material: documents/ holds the extracted text of the supplied documents (PDF pages are marked "=== page N ===", DOCX
paragraphs "[para N]"; a written statement is documents/statement.md.txt). code/ holds a read-only copy of the supplied
code base, if any. You can only list, read and search these files; never run code. Listings give each file's size and
flag large (over 1 MB) and binary files: decide from the name, location and a first few lines whether a file matters.
Reads are paged, and tree-wide searches skip files over 2 MB unless you search one directly.

Tools, in the usual order:
- problem_catalog: installed evaluators with their fields, and the charter's schema.
- charter_read: the current charter with its computed values and findings (the researcher may have changed it).
- charter_check: check a whole draft (charter) or changes to the current one (changes) without saving.
- charter_submit: save a whole draft. Values the researcher set cannot change this way.
- question_ask: put questions to the researcher; their answers start your next turn.
- charter_propose: answer a researcher's request with one to three options of changes.
An error explains what to fix; fix it and call again.

""" + GUIDELINE

S = {"type": "string"}
CHANGE = {"type": "object", "properties": {"op": {"enum": ["set", "add", "remove", "solve"]}, "path": S, "value": {},
          "expression": S, "input": S, "target": S}, "required": ["op"], "additionalProperties": False}
TOOLS = {
    "files_list": ("List files under documents/ (extracted document text) and code/ (the supplied code base).",
        {"type": "object", "properties": {"path": {"type": "string"}, "depth": {"type": "integer", "minimum": 1, "maximum": 6}},
         "additionalProperties": False}),
    "file_read": ("Read a text file with line numbers, at most 400 lines per call.",
        {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1},
         "max_lines": {"type": "integer", "minimum": 1, "maximum": 400}}, "required": ["path"], "additionalProperties": False}),
    "files_search": ("Search file contents with a case-insensitive regular expression.",
        {"type": "object", "properties": {"pattern": {"type": "string", "minLength": 1}, "path": {"type": "string"},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["pattern"], "additionalProperties": False}),
    "problem_catalog": ("Installed evaluators (their configuration and fidelity fields and objectives) and the problem charter's schema.",
        {"type": "object", "properties": {}, "additionalProperties": False}),
    "charter_read": ("The current charter, its computed values, its texts with values, and its findings.",
        {"type": "object", "properties": {}, "additionalProperties": False}),
    "charter_check": ("Check a draft without saving it: give a whole charter, or changes to the current one. "
        "Returns computed values, findings and, for changes, what would change.",
        {"type": "object", "properties": {"charter": {"type": "object"}, "changes": {"type": "array", "items": CHANGE, "maxItems": 50}},
         "additionalProperties": False}),
    "charter_submit": ("Save a whole charter as the new draft. Returns its findings: resolve each blocking one or ask about it.",
        {"type": "object", "properties": {"charter": {"type": "object"}}, "required": ["charter"], "additionalProperties": False}),
    "question_ask": ("Put questions to the researcher. Each has an id, the question, two to four options (recommended first) "
        "and the quantities it is about. End your turn after asking; the answers start your next turn.",
        {"type": "object", "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 10, "items": {"type": "object",
            "properties": {"id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"}, "question": S,
                           "options": {"type": "array", "items": S, "maxItems": 6}, "about": {"type": "array", "items": S, "maxItems": 20},
                           "blocking": {"type": "boolean"}},
            "required": ["id", "question", "options"], "additionalProperties": False}}},
         "required": ["questions"], "additionalProperties": False}),
    "charter_propose": ("Answer the researcher's request with one to three options. Each option is a list of changes with a label "
        "and a reason; the numbers are computed here. An option that leaves a blocking finding needs blocking_reason.",
        {"type": "object", "properties": {"request": S, "options": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object",
            "properties": {"label": S, "reason": S, "changes": {"type": "array", "items": CHANGE, "minItems": 1, "maxItems": 50},
                           "blocking_reason": S}, "required": ["label", "reason", "changes"], "additionalProperties": False}}},
         "required": ["request", "options"], "additionalProperties": False}),
}


class ImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)
    statement: str = Field(default="", max_length=50000, description="The researcher's written problem statement")
    notes: str = Field(default="", max_length=20000)
    tier: str | None = Field(default=None, max_length=40, description="A model tier; defaults to the importer role's tier")
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    effort: THINKING | None = None
    budget_usd: float = Field(default=2.0, gt=0, le=100)


class ImportMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20000)


class ProblemImports:
    def __init__(self, workspace, client=None):
        self.workspace, self.store = workspace, workspace.store
        self._client = client
        self.lock = threading.RLock()

    @property
    def client(self):
        return self._client or self.workspace.pi.client

    def folder(self, record) -> ImportFolder:
        return ImportFolder(self.workspace.directory / "imports" / record["id"])

    def get(self, import_id):
        if not import_id.startswith(PREFIX):
            raise KeyError(import_id)
        return self.store.get(import_id, "problem_import")

    def list(self):
        rows = sorted(self.store.list("problem_import"), key=lambda row: row["created_at"], reverse=True)
        return [{key: row.get(key) for key in ("id", "title", "status", "created_at", "updated_at", "model", "error")}
                | {"has_draft": bool(row.get("draft"))} for row in rows]

    def save(self, record):
        record["updated_at"] = now()
        self.store.put("problem_import", record)
        return record

    # Models --------------------------------------------------------------------
    def models(self):
        status = self.client.status() or {}
        return {"configured": bool(status.get("configured")), "mode": status.get("mode"),
                "default": status.get("defaults") or {}, "providers": status.get("providers", {}),
                "models": [model for model in status.get("models", []) if isinstance(model, dict)]}

    def _check_model(self, choice):
        available = self.models()
        model = next((m for m in available["models"] if m["provider"] == choice["provider"] and m["id"] == choice["model"]), None)
        if model is None:
            raise ValueError(f"{choice['provider']}/{choice['model']} is not available from a signed-in Pi provider")
        if choice.get("effort") and choice["effort"] not in model.get("thinking_levels", [choice["effort"]]):
            raise ValueError(f"{choice['model']} does not offer thinking level {choice['effort']}")
        return available["providers"].get(choice["provider"], {}).get("billing", "unknown")

    # Lifecycle -------------------------------------------------------------------
    def _choice(self, values: ImportCreate):
        if values.provider and values.model:
            return {"provider": values.provider, "model": values.model, "effort": values.effort}, None
        from optimization_framework.agents import tiers
        from optimization_framework.agents.controller import profile_defaults
        settings = tiers.load(self.store, profile_defaults())
        tier_id = values.tier or settings["roles"].get(tiers.IMPORTER)
        tier = next((tier for tier in settings["tiers"] if tier["id"] == tier_id), None)
        if tier is None:
            raise ValueError("Choose a model tier for the importer")
        if not tier["model"].get("provider") or not tier["model"].get("model"):
            raise ValueError("Choose a model for the importer's tier in Models; no model provider is selected by default")
        return {key: tier["model"].get(key) for key in ("provider", "model", "effort")}, tier_id

    def create(self, values: ImportCreate):
        # The model is fixed for the import's lifetime, so revisions continue the same conversation.
        choice, tier = self._choice(values)
        billing = self._check_model(choice)
        identity = PREFIX + uuid.uuid4().hex[:20]
        record = {"id": identity, "title": values.title.strip() or "Untitled import", "notes": values.notes,
                  "model": choice, "tier": tier, "billing": billing, "budget_usd": values.budget_usd, "status": "collecting",
                  "documents": [], "code": None, "runs": [], "draft": None, "draft_run_id": None, "reply": None,
                  "error": None, "activity": [], "cursor": 0,
                  "usage": {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "cost_usd": 0.0, "charged_usd": 0.0},
                  "created_at": now(), "updated_at": now()}
        self.folder(record).create()
        with self.workspace.lock:
            self.save(record)
        if values.statement.strip():
            record = self.add_document(identity, "statement.md", values.statement.strip().encode())
            if not values.title.strip():
                record["title"] = values.statement.strip().splitlines()[0][:80]
                with self.workspace.lock:
                    self.save(record)
        return record

    def formulator_for(self, charter_record):
        """A formulator for a charter that has none yet (one started from an example, a fork or a campaign)."""
        record = self.create(ImportCreate(title=charter_record["title"][:200]))
        record.update(status="ready", charter_id=charter_record["id"])
        with self.workspace.lock:
            return self.save(record)

    def formulate(self, import_id, text, request=None):
        """A turn on the formulator's charter: answers to its questions, or a request for a change."""
        with self.lock:
            record = self.sync(import_id)
            if record["status"] in ACTIVE:
                raise ValueError("The formulator is busy; wait for it to finish or stop it")
            if record["status"] == "collecting":
                raise ValueError("Start the formulator first")
            self._check_model(record["model"])
            if record["status"] == "stopped":
                self.client.control(record["id"], "resume")
            record["request"] = request
            return self._submit(record, text + "\nRead the charter with charter_read before changing anything.")

    def _collecting(self, import_id):
        record = self.get(import_id)
        if record["status"] != "collecting":
            raise ValueError("Files can be added only before the import starts")
        return record

    def add_document(self, import_id, name, raw):
        with self.lock:
            record = self._collecting(import_id)
            document = self.folder(record).add_document(name, raw)
            record["documents"] = [d for d in record["documents"] if d["name"] != document["name"]] + [document]
            if record["title"] == "Untitled import":
                record["title"] = re.sub(r"\.[A-Za-z0-9]+$", "", document["name"])[:200]
            with self.workspace.lock:
                return self.save(record)

    def archive_upload(self, import_id, name):
        """The file an archive upload is streamed into; unpacked by add_code."""
        return self.folder(self._collecting(import_id)).archive_upload(name)

    def add_code(self, import_id, kind, *, name=None, upload=None, url=None, ref="", path=None):
        with self.lock:
            record = self._collecting(import_id)
            folder = self.folder(record)
            if kind == "archive":
                code = folder.add_archive(name, upload)
            elif kind == "git":
                code = folder.add_git(url, ref)
            elif kind == "folder":
                code = folder.add_folder(path)
            else:
                raise ValueError("Code comes from an archive, a git URL or a folder")
            record["code"] = code
            with self.workspace.lock:
                return self.save(record)

    def start(self, import_id):
        with self.lock:
            record = self._collecting(import_id)
            if not record["documents"]:
                raise ValueError("Add a written statement or at least one document before starting")
            self._check_model(record["model"])
            return self._submit(record, self._first_prompt(record))

    def message(self, import_id, values: ImportMessage):
        with self.lock:
            record = self.sync(import_id)
            if record["status"] in ACTIVE | {"collecting"}:
                raise ValueError("The importer is busy; wait for it to finish or stop it")
            self._check_model(record["model"])
            if record["status"] == "stopped":
                self.client.control(record["id"], "resume")
            return self._submit(record, "Researcher request:\n" + values.message +
                "\nIf the formulation changes, save the revised charter with charter_submit, or propose changes with charter_propose.")

    def stop(self, import_id):
        with self.lock:
            record = self.get(import_id)
            if record["status"] not in ACTIVE:
                return record
            self.client.control(record["id"], "stop")
            record.update(status="stopped", error="Stopped by researcher")
            with self.workspace.lock:
                return self.save(record)

    def remove(self, import_id):
        """Delete an import that is not running: its record, its folder and the formulator's saved session."""
        import shutil
        with self.lock:
            record = self.sync(import_id)
            if record["status"] in ACTIVE:
                raise ValueError("The formulator is working; stop it before removing the import")
            charter_id = record.get("charter_id")
            if charter_id:
                try:
                    charter = self.workspace.charters.get(charter_id)
                except KeyError:
                    charter = None
                if charter is not None and charter.get("import_id") == import_id and charter.get("campaign_ids"):
                    raise ValueError("A campaign was made from this import's charter; the import stays with it")
            if record["runs"]:
                try:
                    self.client.forget(import_id)
                except Exception:   # the harness may never have known it, or may be down; the session folder goes below
                    pass
            shutil.rmtree(self.folder(record).root, ignore_errors=True)
            with self.workspace.lock:
                self.store.delete_drafts("problem_import", [import_id])
        if charter_id:
            try:
                charter = self.workspace.charters.get(charter_id)
                if charter.get("import_id") == import_id:
                    self.workspace.charters.remove(charter_id)
            except (KeyError, ValueError):
                pass
        return {"removed": import_id}

    def _submit(self, record, text):
        run_id = f"{record['id']}_run_{len(record['runs']) + 1}"
        agent = {"id": record["id"], "provider": record["model"]["provider"], "model": record["model"]["model"],
                 "reasoning_effort": record["model"].get("effort"), "role": ROLE, "deadline_at": None}
        self.client.submit(agent, {"id": run_id, "input": text, "mode": "follow_up"})
        record["runs"].append(run_id)
        record.update(status="running", error=None, reply=None)
        self._activity(record, "status", "Started" if len(record["runs"]) == 1 else "Revising")
        with self.workspace.lock:
            return self.save(record)

    def _first_prompt(self, record):
        lines = ["Formulate the optimization problem described by the supplied material.", "", "Documents (extracted text):"]
        for document in record["documents"]:
            pages = f", {document['pages']} pages" if document.get("pages") else ""
            lines.append(f"- {document['text_file']} ({document['name']}{pages}, {document['characters']} characters)")
        code = record.get("code")
        if code:
            origin = {"archive": "uploaded archive", "git": "git repository", "folder": "local folder"}[code["kind"]]
            commit = f" at commit {code['commit']}" if code.get("commit") else ""
            lines += ["", f"Code base under code/: {origin} {code['source']}{commit}, {code['files']} files"
                          f" ({code.get('large_files', 0)} over 1 MB)."]
            if code.get("not_copied"):
                lines.append(f"{code['not_copied']} files were not copied because the import reached its size limit.")
        else:
            lines += ["", "No code base was supplied."]
        if record["notes"].strip():
            lines += ["", "Researcher notes:", record["notes"].strip()]
        lines += ["", "Start with problem_catalog and read the material. Write the charter, check it with charter_check, "
                  "save it with charter_submit, and ask about what the material leaves open with question_ask."]
        return "\n".join(lines)

    # Harness callbacks -------------------------------------------------------------
    def manifest(self, agent_id, run_id):
        record = self.get(agent_id)
        if run_id not in record["runs"]:
            raise ValueError("Unknown import run")
        return {"instructions": INSTRUCTIONS,
                "tools": [{"name": name, "description": description, "input_schema": schema}
                          for name, (description, schema) in sorted(TOOLS.items())]}

    def call(self, agent_id, run_id, call_id, name, arguments):
        import jsonschema
        record = self.get(agent_id)
        if run_id not in record["runs"] or record["status"] not in ACTIVE:
            raise ValueError("This import is not running; preserve findings and stop")
        if name not in TOOLS:
            raise ValueError("Tool is not available to the problem importer")
        try:
            jsonschema.validate(arguments, TOOLS[name][1])
            result = self._execute(record, run_id, name, arguments)
        except (ValueError, KeyError, OSError, jsonschema.ValidationError) as exc:
            message = exc.message if isinstance(exc, jsonschema.ValidationError) else str(exc)
            result = {"error": message[:3000]}
        self._note_tool(agent_id, name, arguments, result)
        return result

    def _execute(self, record, run_id, name, arguments):
        folder = self.folder(record)
        if name == "files_list":
            return folder.listing(arguments.get("path", ""), arguments.get("depth", 2))
        if name == "file_read":
            return folder.read(arguments["path"], arguments.get("start_line", 1), arguments.get("max_lines", 200))
        if name == "files_search":
            return folder.search(arguments["pattern"], arguments.get("path", ""), arguments.get("max_results", 50))
        if name == "problem_catalog":
            return catalog()
        return self._charter_tool(record, run_id, name, arguments)

    def _charter_tool(self, record, run_id, name, arguments):
        from optimization_framework.problem_charter import charter as mechanics
        charters = self.workspace.charters
        charter_id = self.get(record["id"]).get("charter_id")
        if name == "charter_check":
            if "charter" in arguments:
                return {**mechanics.describe(arguments["charter"]), "saved": False}
            if not charter_id:
                return {"error": "There is no charter yet; check a whole charter instead"}
            return {**charters.preview(charter_id, arguments.get("changes", [])), "saved": False}
        if name == "charter_submit":
            if charter_id:
                saved = charters.submit(charter_id, arguments["charter"], run_id=run_id)
            else:
                saved = charters.create(charters.from_formulator(None, arguments["charter"]), source={"kind": "import", "id": record["id"], "name": record["title"]},
                                        by="formulator", rationale="First draft from the formulator", import_id=record["id"])
                with self.lock, self.workspace.lock:
                    current = self.get(record["id"])
                    current["charter_id"] = saved["id"]
                    self.save(current)
            view = mechanics.describe(saved["charter"])
            return {"saved": True, "revision": saved["revision"], "blocking": view["blocking"],
                    "findings": [row for row in view["findings"] if not row.get("waived")],
                    "next": "Resolve each blocking finding from the sources or ask about it with question_ask; then reply briefly."}
        if name == "question_ask":
            if not charter_id:
                stub = {"title": record["title"] or "Untitled problem", "summary": "Waiting for the researcher's answers."}
                saved = charters.create(stub, source={"kind": "import", "id": record["id"], "name": record["title"]},
                                        by="formulator", rationale="Questions before a first draft", import_id=record["id"])
                charter_id = saved["id"]
                with self.lock, self.workspace.lock:
                    current = self.get(record["id"])
                    current["charter_id"] = charter_id
                    self.save(current)
            saved = charters.ask(charter_id, arguments["questions"])
            return {"asked": len(arguments["questions"]), "revision": saved["revision"],
                    "next": "End your turn with a short reply; the researcher's answers start your next turn."}
        if not charter_id:
            return {"error": "There is no charter yet; write one with charter_submit first"}
        if name == "charter_read":
            view = charters.view(charter_id)
            return {key: view[key] for key in ("revision", "status", "charter", "values", "errors", "rendered", "findings", "references")}
        if name == "charter_propose":
            request = arguments["request"] or self.get(record["id"]).get("request") or ""
            proposal = charters.propose(charter_id, request, arguments["options"], run_id=run_id)
            return {"proposed": proposal["id"], "options": [{"label": option["label"], "changes": option["diff"],
                    "blocking": [row["message"] for row in option["findings"]]} for option in proposal["options"]],
                    "next": "Reply briefly; the researcher accepts one option or rejects them on the charter page. "
                            "Quote numbers only from these computed changes."}
        raise ValueError("Tool is not available to the formulator")

    def _note_tool(self, import_id, name, arguments, result):
        detail = arguments.get("path") or arguments.get("pattern") or ""
        summary = {"files_list": "Listed", "file_read": "Read", "files_search": "Searched for",
                   "problem_catalog": "Checked the problem catalog", "charter_read": "Read the charter",
                   "charter_check": "Checked a draft", "charter_submit": "Saved a draft of the charter",
                   "question_ask": "Asked the researcher", "charter_propose": "Proposed changes"}[name]
        text = f"{summary} {detail}".strip()
        if "error" in result:
            text += f" — {result['error'][:200]}"
        with self.lock, self.workspace.lock:
            record = self.get(import_id)
            self._activity(record, "tool", text)
            self.save(record)

    def _activity(self, record, kind, text):
        record["activity"] = (record["activity"] + [{"at": now(), "kind": kind, "text": text[:500]}])[-80:]

    # Progress -------------------------------------------------------------------------
    def notify(self, agent_ids):
        for agent_id in agent_ids:
            try:
                self.sync(agent_id)
            except (KeyError, ValueError):
                continue
        return {"accepted": len(agent_ids)}

    def sync(self, import_id):
        """Pull the harness's events for a running import; status follows its latest run."""
        with self.lock:
            record = self.get(import_id)
            if record["status"] not in ACTIVE:
                return record
            view = None
            while True:
                page = self.client.inspect(record["id"], record["cursor"])
                if not page:
                    break
                view = page
                for event in page.get("events", []):
                    self._event(record, event)
                record["cursor"] = page.get("cursor", record["cursor"])
                if len(page.get("events", [])) < 200:
                    break
            if view is not None:
                run = (view.get("runs") or {}).get(record["runs"][-1]) if record["runs"] else None
                if run and run.get("status") in {"completed", "failed", "stopped", "interrupted", "paused"}:
                    if run["status"] == "completed":
                        record["reply"] = (run.get("result") or {}).get("text") or None
                        if record.get("draft") or record.get("charter_id"):
                            record.update(status="ready", error=None)
                        else:
                            record.update(status="failed", error="The formulator finished without saving a charter; ask it to continue.")
                    else:
                        record.update(status="stopped" if run["status"] in {"stopped", "paused"} else "failed",
                                      error=run.get("error") or f"The importer run {run['status']}")
                    self._activity(record, "status", {"ready": "Draft ready"}.get(record["status"], record["error"] or record["status"]))
            if record["status"] in ACTIVE and record["billing"] == "api" and record["usage"]["charged_usd"] >= record["budget_usd"]:
                self.client.control(record["id"], "stop")
                record.update(status="stopped", error=f"Reached this import's ${record['budget_usd']:.2f} API budget")
                self._activity(record, "status", record["error"])
            with self.workspace.lock:
                return self.save(record)

    def _event(self, record, event):
        if event.get("type") == "assistant.message":
            usage = event.get("usage") or {}
            total = record["usage"]
            total["calls"] += 1
            for key, source in (("input", "input"), ("output", "output"), ("cache_read", "cacheRead"), ("reasoning", "reasoning")):
                total[key] += int(usage.get(source) or 0)
            cost = float(usage.get("cost_usd") or 0)
            total["cost_usd"] = round(total["cost_usd"] + cost, 6)
            if event.get("billing") == "api":
                total["charged_usd"] = round(total["charged_usd"] + cost, 6)
            text = (event.get("text") or "").strip()
            if text:
                self._activity(record, "message", text)
        elif event.get("type") in {"auto_retry_start", "auto_compaction_start"}:
            self._activity(record, "status", event["type"].replace("_", " ").replace("auto ", "Automatic "))

    # Examples ---------------------------------------------------------------------------
    def save_example(self, import_id=None, example=None, name=None, summary=None):
        if import_id:
            record = self.get(import_id)
            if record.get("charter_id"):
                from optimization_framework.problem_charter import charter as mechanics
                charter = self.workspace.charters.get(record["charter_id"])["charter"]
                title = name or charter["title"]
                values = mechanics.resolve(charter)["values"]
                example = {"name": title, "summary": summary or mechanics.render(charter["summary"], values, charter),
                           "instances": mechanics.compile_setups(charter), "charter": charter,
                           "campaign": {"name": title}, "import_id": import_id}
            elif record.get("draft"):
                draft = ProblemDraft.model_validate(record["draft"])
                title = name or draft.title
                example = {"name": title, "summary": summary or draft.summary,
                           "instances": [setup.model_dump(mode="json") for setup in draft.instances],
                           "campaign": {"name": title, "objective": draft.objective}, "import_id": import_id}
            else:
                raise ValueError("This import has no formulation to save")
        if not example:
            raise ValueError("Provide an import or an example to save")
        slug = re.sub(r"[^a-z0-9]+", "_", (example.get("name") or "problem").lower()).strip("_")[:60] or "problem"
        values = ProblemExample.model_validate({**{k: v for k, v in example.items() if k not in {"id", "source", "schema_version"}},
            "id": f"{slug}_{uuid.uuid4().hex[:6]}", "source": "saved"})
        for setup in values.instances:
            setup.task_input()
        record = {**values.model_dump(mode="json"), "created_at": now(), "archived": False}
        with self.workspace.lock:
            self.store.put("problem_example", record)
        return record

    def archive_example(self, example_id):
        with self.workspace.lock:
            record = self.store.get(example_id, "problem_example")
            record["archived"] = True
            self.store.put("problem_example", record)
        return {"id": example_id, "archived": True}

    def examples(self):
        from optimization_framework.evaluation.registry import problems
        installed = sorted((ProblemExample.model_validate(item).model_dump(mode="json") for item in problems.examples()),
                           key=lambda row: (row["order"], row["name"]))
        saved = [row for row in self.store.list("problem_example") if not row.get("archived")]
        return installed + sorted(saved, key=lambda row: row["created_at"], reverse=True)


def catalog():
    """Installed evaluators, with their fields and objectives, and the charter's schema."""
    from optimization_framework.contracts.problem_charter import ProblemCharter
    from optimization_framework.evaluation.registry import problems
    adapters = []
    examples = problems.examples()
    for name in problems.ids():
        definition = problems.get(name).describe()
        own = [example for example in examples if any(s.get("problem_id") == name for s in example["instances"])]
        adapter = {"problem_id": name, "name": definition.name, "evaluator": definition.evaluator_id,
            "capabilities": definition.capabilities, "configuration_schema": definition.configuration_schema,
            "fidelity_schema": definition.fidelity_schema,
            "examples": [{"name": example["name"], "summary": example.get("summary", ""), "instances": example["instances"],
                          **({"charter": outline(example["charter"])} if example.get("charter") else {})} for example in own]}
        setup = next((s for example in own for s in example["instances"] if s.get("problem_id") == name), None)
        if setup is not None:
            try:
                problem = problems.resolve(name, setup["configuration"], setup.get("fidelity"))
            except ValueError:
                problem = None
            if problem is not None:
                adapter.update(objective=problem.primary_objective.model_dump(mode="json"),
                               metrics=[metric.model_dump(mode="json") for metric in problem.extra_metrics],
                               candidate={"representation": problem.candidate_schema.representation,
                                          "dimensions_in_example": problem.candidate_schema.dimensions})
        adapters.append(adapter)
    return {"adapters": adapters, "charter_schema": ProblemCharter.model_json_schema(),
            "notes": "An installed evaluator's objective is fixed. A declared problem needs a new lowercase problem_id. "
                     "Map every required configuration and fidelity field of an installed evaluator to one quantity. "
                     "Example charters show the format; their tables are shortened here."}


def outline(charter):
    """An example charter for reading, with long tables cut to their first points."""
    tables = {name: {**table, "points": table["points"][:3], "points_shown": f"3 of {len(table['points'])}"}
              for name, table in (charter.get("tables") or {}).items()}
    return {**charter, "tables": tables}


def is_import_agent(agent_id: str) -> bool:
    return isinstance(agent_id, str) and agent_id.startswith(PREFIX)
