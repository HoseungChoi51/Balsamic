"""Problem charters kept in the workspace: revisions, the researcher's edits, questions, proposals,
confirmation and forks.

A charter record is mutable and points at its current revision. Every revision is kept as an
immutable snapshot, so a campaign can name exactly the revision it was created from. The formulator
(the formulator agent) writes drafts and proposals; only the researcher edits values directly,
accepts proposals, waives findings and confirms.
"""
from __future__ import annotations

from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.problem_charter import ProblemCharter
from optimization_framework.storage.sqlite import identifier, now

from . import charter as mechanics

KIND, REVISION, PROPOSAL = "problem_charter", "problem_charter_revision", "problem_charter_proposal"


def core_hash(charter: dict) -> str:
    """The charter's content apart from questions and waivers: a proposal holds while this is unchanged."""
    return content_hash({key: value for key, value in charter.items() if key not in {"questions", "waivers"}})



# Questions come in rounds: all at once, sent together. The researcher answers what they can; the rest the formulator decides
# and records as assumptions. A charter takes at most this many rounds, so the researcher knows when the asking ends.
QUESTION_ROUNDS = 2


def question_rounds(record) -> int:
    return sum(1 for row in record.get("history", []) if row.get("by") == "formulator" and str(row.get("rationale", "")).startswith("Asked "))

class Charters:
    def __init__(self, workspace, registry=None):
        self.workspace, self.store = workspace, workspace.store
        self.registry = registry

    # Records -------------------------------------------------------------------------------------------
    def get(self, charter_id):
        return self.store.get(charter_id, KIND)

    def revision(self, charter_id, number):
        return self.store.get(f"{charter_id}_r{number}", REVISION)

    def list(self):
        rows = sorted(self.store.list(KIND), key=lambda row: row["updated_at"], reverse=True)
        return [{key: row.get(key) for key in ("id", "title", "status", "revision", "confirmed_revision", "source",
                 "campaign_ids", "import_id", "created_at", "updated_at")} for row in rows]

    def view(self, charter_id):
        record = self.get(charter_id)
        rounds = question_rounds(record)
        proposals = [row for row in self.store.list(PROPOSAL) if row["charter_id"] == charter_id]
        current = core_hash(record["charter"])
        proposals = [{**row, "status": "stale"} if row["status"] == "open" and row["base_hash"] != current else row for row in proposals]
        origin = record["charter"].get("forked_from")
        lineage = None
        if origin:   # what differs from the charter it was forked from, as it stands now
            base = self.revision(origin["charter_id"], origin["revision"])["charter"]
            lineage = {**origin, "title": base["title"], "changes": [row for row in mechanics.diff(base, record["charter"])
                                                                      if row["part"] in {"value", "relation", "quantity"}]}
        return {**record, **mechanics.describe(record["charter"], self.registry), "lineage": lineage,
                "question_rounds": rounds, "question_rounds_max": QUESTION_ROUNDS,
                "proposals": sorted(proposals, key=lambda row: row["created_at"], reverse=True)[:20],
                "history": record["history"][-50:]}

    def _save(self, record, charter: dict, by: str, rationale: str):
        charter = ProblemCharter.model_validate(charter).model_dump(mode="json")
        number = record.get("revision", 0) + 1
        self.store.put_immutable(REVISION, {"id": f"{record['id']}_r{number}", "charter_id": record["id"], "revision": number,
                                            "charter": charter, "by": by, "rationale": rationale[:2000], "created_at": now()})
        record.update(charter=charter, revision=number, title=charter["title"], status="draft", updated_at=now())
        record["history"] = record.get("history", []) + [{"revision": number, "at": now(), "by": by, "rationale": rationale[:500],
                                                          "hash": content_hash(charter)}]
        self.store.put(KIND, record)
        return record

    def create(self, charter: dict, *, source: dict, by: str = "researcher", rationale: str = "Started", import_id=None):
        record = {"id": identifier("problem_charter"), "source": source, "import_id": import_id, "campaign_ids": [],
                  "confirmed": [], "confirmed_revision": None, "history": [], "revision": 0, "created_at": now()}
        with self.workspace.lock, self.store.transaction():
            return self._save(record, charter, by, rationale)

    def _current(self, charter_id, expected_revision):
        record = self.get(charter_id)
        if expected_revision is not None and record["revision"] != expected_revision:
            raise ValueError(f"The charter changed (now revision {record['revision']}); reload it and try again")
        return record

    # Starting points -------------------------------------------------------------------------------------
    def from_example(self, example_id):
        from optimization_framework.contracts.problem_imports import ProblemExample
        examples = self.workspace.problem_imports.examples() if hasattr(self.workspace, "problem_imports") else []
        example = next((row for row in examples if row["id"] == example_id), None)
        if example is None:
            raise KeyError(example_id)
        example = ProblemExample.model_validate(example).model_dump(mode="json")
        charter = example.get("charter") or mechanics.from_setups(example["name"], example["instances"], summary=example["summary"],
            text=(example.get("campaign") or {}).get("objective") or "", registry=self.registry)
        return self.create(charter, source={"kind": "example", "id": example_id, "name": example["name"],
            "campaign": example.get("campaign") or {}}, rationale=f"Started from the example {example['name']}")

    def from_evaluator(self, problem_id):
        """A charter for an installed evaluator, from the defaults its schemas declare; missing values are left to fill in."""
        from optimization_framework.evaluation.registry import problems
        registry = self.registry or problems
        definition = registry.get(problem_id).describe()

        def defaults(schema):
            return {key: rule["default"] for key, rule in (schema or {}).get("properties", {}).items()
                    if isinstance(rule, dict) and "default" in rule and key != "schema_version"}
        setup = {"name": definition.name, "problem_id": problem_id, "configuration": defaults(definition.configuration_schema),
                 "fidelity": defaults(definition.fidelity_schema)}
        try:
            charter = mechanics.from_setups(definition.name, [setup], registry=self.registry)
        except (ValueError, TypeError):   # the defaults do not make a problem yet: every declared field becomes an input to fill in
            kinds = {"integer": "integer", "number": "number", "boolean": "boolean", "string": "text", "array": "data", "object": "data"}
            quantities, binding = {}, {"configuration": {}, "fidelity": {}}
            for part, schema in (("configuration", definition.configuration_schema), ("fidelity", definition.fidelity_schema)):
                for field, rule in (schema or {}).get("properties", {}).items():
                    if field == "schema_version" or not isinstance(rule, dict):
                        continue
                    name = field if field not in quantities else "fidelity_" + field
                    quantities[name] = {"description": rule.get("description") or rule.get("title") or f"{part.capitalize()} field {field}",
                                        "kind": kinds.get(rule.get("type"), "text"), "role": "input", "value": rule.get("default"), "origin": "researcher"}
                    binding[part][field] = name
            charter = {"title": definition.name, "quantities": quantities,
                       "evaluator": {"kind": "installed", "problem_id": problem_id, **binding},
                       "instances": [{"name": definition.name, "split": "development"}]}
        return self.create(charter, source={"kind": "evaluator", "id": problem_id, "name": definition.name},
                           rationale=f"Started from the installed evaluator {definition.name}")

    def for_campaign(self, campaign_id):
        """The charter a campaign was made from, or one made from its stored instances."""
        campaign = self.store.get(campaign_id, "campaign")
        if campaign.get("charter"):
            return self.get(campaign["charter"]["id"])
        tasks = [task for task in self.store.list("task", campaign_id) if not task.get("archived")]
        setups = [{"name": task["name"], "split": task.get("split", "development"),
                   **({"evaluator_manifest": task["evaluator_manifest"]} if task.get("evaluator_manifest") else {"problem_id": task["problem_id"]}),
                   "configuration": task.get("configuration") or {}, "fidelity": task.get("fidelity") or {}} for task in tasks]
        charter = mechanics.from_setups(campaign["name"], setups, text=campaign.get("objective", ""), origin="researcher", registry=self.registry)
        record = self.create(charter, source={"kind": "campaign", "id": campaign_id, "name": campaign["name"]},
                             rationale="Made from the campaign's stored problem instances")
        record.update(campaign_ids=[campaign_id], confirmed=[{"revision": record["revision"], "at": now(), "hash": content_hash(record["charter"])}],
                      confirmed_revision=record["revision"], status="confirmed")
        with self.workspace.lock:
            self.store.put(KIND, record)
            self.store.put("campaign", {**self.store.get(campaign_id, "campaign"),
                                        "charter": {"id": record["id"], "revision": record["revision"]}})
        return record

    # The researcher's edits ------------------------------------------------------------------------------
    def edit(self, charter_id, changes, *, expected_revision=None, rationale="", charter=None):
        """Typed inputs and other direct edits; a whole charter when edited as JSON."""
        with self.workspace.lock, self.store.transaction():
            record = self._current(charter_id, expected_revision)
            if charter is not None:
                updated = ProblemCharter.model_validate(charter).model_dump(mode="json")
            else:
                updated = mechanics.apply_changes(record["charter"], changes, origin="researcher")
            return self._save(record, updated, "researcher", rationale or "Edited by the researcher")

    def preview(self, charter_id, changes):
        """What edits would give, without saving them."""
        record = self.get(charter_id)
        updated = mechanics.apply_changes(record["charter"], changes, origin="researcher")
        return {"charter": updated, **mechanics.describe(updated, self.registry), "diff": mechanics.diff(record["charter"], updated)}

    def accept_assumptions(self, charter_id, names=None, *, expected_revision=None):
        with self.workspace.lock, self.store.transaction():
            record = self._current(charter_id, expected_revision)
            charter = record["charter"]
            for name, quantity in charter["quantities"].items():
                if quantity["origin"] == "assumed" and (names is None or name in names):
                    quantity["accepted"] = True
            for index, assumption in enumerate(charter["assumptions"]):
                if names is None or f"statement{index}" in names:
                    assumption["accepted"] = True
            return self._save(record, charter, "researcher", "Accepted assumptions")

    def waive(self, charter_id, key, reason, *, expected_revision=None):
        with self.workspace.lock, self.store.transaction():
            record = self._current(charter_id, expected_revision)
            row = next((row for row in mechanics.findings(record["charter"], self.registry) if row["key"] == key), None)
            if row is None:
                raise ValueError("There is no such finding now")
            if not row["waivable"]:
                raise ValueError("This finding cannot be waived; the charter cannot be compiled while it stands")
            charter = record["charter"]
            charter["waivers"] = [w for w in charter["waivers"] if w["key"] != key] + [{"key": key, "reason": reason, "at": now()}]
            return self._save(record, charter, "researcher", f"Waived ({row['key']}): {reason}")

    def answer(self, charter_id, question_id, text, *, expected_revision=None):
        with self.workspace.lock, self.store.transaction():
            record = self._current(charter_id, expected_revision)
            charter = record["charter"]
            question = next((q for q in charter["questions"] if q["id"] == question_id), None)
            if question is None:
                raise KeyError(question_id)
            question.update(answer=text, answered_at=now(), sent=False)
            record = self._save(record, charter, "researcher", f"Answered: {question['question'][:200]}")
        if not [q for q in record["charter"]["questions"] if q["answer"] is None and not q.get("sent")]:
            record = self._send_round(record)   # the last open one answered: the round goes by itself
        return record

    def send_answers(self, charter_id, *, expected_revision=None):
        """Send the round as it stands. The researcher is not expected to know every answer: what is left unanswered goes
        to the formulator as a decision it makes from the answers, the sources and convention, and records as an assumption
        the researcher can change later, when a run has shown what the question meant."""
        with self.workspace.lock:
            record = self._current(charter_id, expected_revision)
        return self._send_round(record)

    def _send_round(self, record):
        if not record.get("import_id"):
            return record
        questions = record["charter"]["questions"]
        answered = [q for q in questions if q["answer"] is not None and not q.get("sent")]
        left = [q for q in questions if q["answer"] is None and not q.get("sent")]
        if not answered and not left:
            return record
        rounds = question_rounds(record)
        text = f"The researcher answered your questions (round {rounds} of {QUESTION_ROUNDS}):\n"
        if answered:
            text += "\n".join(f"- {q['question']}\n  Answer: {q['answer']}" for q in answered) + "\n"
        else:
            text += "- (none answered)\n"
        if left:
            text += ("The researcher left these unanswered. They do not know yet, and will understand them better after a campaign "
                     "run; do not ask them again. Decide each yourself: from the answers above and the sources where they imply "
                     "it, otherwise by convention or the option you recommended. Record each decision as an assumption the "
                     "researcher can change later (a quantity with origin 'assumed', or an assumption statement, with a note "
                     "naming the question and why you chose as you did), and drop the question from the charter.\n" +
                     "\n".join(f"- {q['question']} (options: {'; '.join(q.get('options') or []) or 'none given'})" for q in left) + "\n")
        follow = ("Ask again only for a decision no answer, source or convention can make, in one round with every question "
                  "together; do not ask again what the answers already cover, and prefer an assumption with a note to a question."
                  if rounds < QUESTION_ROUNDS else
                  "No more questions can be asked on this charter. Record what is still open as assumptions (origin 'assumed', "
                  "with a note naming the answer each rests on) for the researcher to accept or change, or leave it as a "
                  "blocking finding the researcher settles on the page.")
        self._tell_formulator(record, text + "Revise the charter with charter_submit so it follows these answers and decisions, "
                              "then report briefly: say what you decided for the researcher and why. " + follow)
        with self.workspace.lock:
            record = self.get(record["id"])
            for q in record["charter"]["questions"]:
                q["sent"] = True
            self.store.put(KIND, record)
        return record

    # The formulator ----------------------------------------------------------------------------------------
    @staticmethod
    def from_formulator(current: dict | None, proposed: dict) -> dict:
        """What the formulator may write: only the researcher waives findings, accepts assumptions and answers questions."""
        proposed = ProblemCharter.model_validate(proposed).model_dump(mode="json")
        current = current or {"quantities": {}, "assumptions": [], "questions": [], "waivers": []}
        proposed["waivers"] = current["waivers"]
        for name, quantity in proposed["quantities"].items():
            previous = current["quantities"].get(name)
            quantity["accepted"] = bool(previous and previous.get("accepted") and quantity["origin"] == "assumed" and
                                        (previous.get("value"), previous.get("expression")) == (quantity.get("value"), quantity.get("expression")))
        accepted = {a["statement"] for a in current["assumptions"] if a.get("accepted")}
        for assumption in proposed["assumptions"]:
            assumption["accepted"] = assumption["statement"] in accepted
        answered = {q["id"]: q for q in current["questions"] if q.get("answer") is not None}
        sent = {q["id"]: bool(q.get("sent")) for q in current["questions"]}   # a question left to the formulator stays so
        proposed["questions"] = [answered.get(q["id"], {**q, "answer": None, "answered_at": None, "sent": sent.get(q["id"], False)}) for q in proposed["questions"]] + \
            [q for q in answered.values() if q["id"] not in {p["id"] for p in proposed["questions"]}]
        return proposed

    def submit(self, charter_id, charter: dict, *, run_id: str):
        """A whole draft from the formulator. Values the researcher set, answers and waivers are kept as they are."""
        with self.workspace.lock, self.store.transaction():
            record = self.get(charter_id)
            current, proposed = record["charter"], ProblemCharter.model_validate(charter).model_dump(mode="json")
            for name, quantity in current["quantities"].items():
                if quantity["origin"] != "researcher":
                    continue
                other = proposed["quantities"].get(name)
                if other is None or (other.get("value"), other.get("expression")) != (quantity.get("value"), quantity.get("expression")):
                    raise ValueError(f"{name} was set by the researcher; keep it as it is, or use charter_propose to suggest a change")
                other["origin"] = "researcher"
            return self._save(record, self.from_formulator(current, proposed), "formulator", f"Draft from the formulator ({run_id})")

    def ask(self, charter_id, questions: list[dict]):
        with self.workspace.lock, self.store.transaction():
            record = self.get(charter_id)
            rounds = question_rounds(record)
            if rounds >= QUESTION_ROUNDS:
                raise ValueError(f"The researcher has answered {rounds} rounds of questions; no more can be asked on this charter. "
                                 "Record what is still open as assumptions (origin 'assumed', with a note naming the answer each rests on) "
                                 "for the researcher to accept or change, or leave it as a blocking finding the researcher settles on the page.")
            charter = record["charter"]
            taken = {q["id"] for q in charter["questions"]}
            for question in questions:
                if question["id"] in taken:
                    raise ValueError(f"A question named {question['id']} exists; choose another name")
                charter["questions"].append({**question, "answer": None, "answered_at": None})
            return self._save(record, charter, "formulator", f"Asked {len(questions)} question{'s' if len(questions) != 1 else ''}")

    def propose(self, charter_id, request: str, options: list[dict], *, run_id: str, asked: str | None = None):
        """Options of changes, each computed and checked here; the formulator's own numbers are never taken.
        `request` is the formulator's phrasing; `asked` the researcher's own words it answers, when it answers a request."""
        record = self.get(charter_id)
        built = []
        for option in options:
            updated = mechanics.apply_changes(record["charter"], option["changes"], origin="researcher")
            rows = mechanics.findings(updated, self.registry)
            new_blocking = [row for row in mechanics.blocking(rows)
                            if row["key"] not in {old["key"] for old in mechanics.blocking(mechanics.findings(record["charter"], self.registry))}]
            if new_blocking and not option.get("blocking_reason"):
                raise ValueError(f"Option “{option['label']}” leaves blocking findings: " + "; ".join(row["message"] for row in new_blocking[:3]) +
                                 ". Fix them, or give blocking_reason if the researcher should still see this option.")
            built.append({"label": option["label"], "reason": option.get("reason", ""), "changes": option["changes"],
                          "blocking_reason": option.get("blocking_reason"), "charter": updated,
                          "diff": mechanics.diff(record["charter"], updated),
                          "findings": new_blocking})
        proposal = {"id": identifier("charter_proposal"), "charter_id": charter_id, "base_revision": record["revision"],
                    "base_hash": core_hash(record["charter"]),
                    "request": request, "asked": asked or None, "run_id": run_id, "options": built, "status": "open", "accepted_option": None,
                    "created_at": now(), "decided_at": None}
        with self.workspace.lock:
            for old in self.store.list(PROPOSAL):
                if old["charter_id"] == charter_id and old["status"] == "open":
                    self.store.put(PROPOSAL, {**old, "status": "superseded", "decided_at": now()})
            self.store.put(PROPOSAL, proposal)
        return proposal

    def decide(self, proposal_id, option: int | None):
        """Accept one option (its index) or reject the proposal (None)."""
        with self.workspace.lock, self.store.transaction():
            proposal = self.store.get(proposal_id, PROPOSAL)
            if proposal["status"] != "open":
                raise ValueError(f"This proposal is {proposal['status']}")
            record = self.get(proposal["charter_id"])
            if option is None:
                self.store.put(PROPOSAL, {**proposal, "status": "rejected", "decided_at": now()})
                return record
            if core_hash(record["charter"]) != proposal["base_hash"]:
                self.store.put(PROPOSAL, {**proposal, "status": "stale", "decided_at": now()})
                raise ValueError("The charter changed after this proposal was made; ask again")
            if not 0 <= option < len(proposal["options"]):
                raise ValueError("No such option")
            chosen = proposal["options"][option]
            # Applied to the current charter, so answers and waivers given meanwhile are kept.
            updated = mechanics.apply_changes(record["charter"], chosen["changes"], origin="researcher")
            self.store.put(PROPOSAL, {**proposal, "status": "accepted", "accepted_option": option, "decided_at": now()})
            return self._save(record, updated, "researcher", f"Accepted “{chosen['label']}” for: {proposal['request'][:300]}")

    def request(self, charter_id, text: str):
        """The researcher asks for a change in words; the formulator answers with a proposal."""
        record = self.get(charter_id)
        prompt = (f"Researcher request about charter {charter_id} (revision {record['revision']}):\n{text}\n\n"
                  "Answer with charter_propose: one to three options of changes. Use solve for a wanted derived value and "
                  "expressions for computed values; never state a computed number yourself. Then report briefly.")
        self._tell_formulator(record, prompt, create=True, request=text)
        return self.get(charter_id)

    def _tell_formulator(self, record, text, *, create=False, request=None):
        imports = getattr(self.workspace, "problem_imports", None)
        if imports is None:
            raise ValueError("The formulator is not available in this workspace")
        if not record.get("import_id"):
            if not create:
                return
            created = imports.formulator_for(record)
            with self.workspace.lock:
                record = self.get(record["id"])
                record["import_id"] = created["id"]
                self.store.put(KIND, record)
        imports.formulate(record["import_id"], text, request=request)

    def remove(self, charter_id):
        """Delete a charter that no campaign uses, with its revisions, proposals and formulator."""
        with self.workspace.lock, self.store.transaction():
            record = self.get(charter_id)
            if record.get("campaign_ids"):
                raise ValueError("A campaign was made from this charter; it stays as long as the campaign does")
            proposals = [row["id"] for row in self.store.list(PROPOSAL) if row["charter_id"] == charter_id]
            self.store.delete_drafts(PROPOSAL, proposals)
            self.store.delete_drafts(REVISION, [f"{charter_id}_r{n}" for n in range(1, record["revision"] + 1)])
            self.store.delete_drafts(KIND, [charter_id])
        imports = getattr(self.workspace, "problem_imports", None)
        if record.get("import_id") and imports is not None:
            try:
                imports.remove(record["import_id"])
            except KeyError:   # already removed, as when the import itself is being removed
                pass
        return {"removed": charter_id, "revisions": record["revision"], "proposals": len(proposals)}

    # Confirmation and forks ------------------------------------------------------------------------------
    def confirm(self, charter_id, *, expected_revision=None):
        with self.workspace.lock, self.store.transaction():
            record = self._current(charter_id, expected_revision)
            try:
                setups = mechanics.compile_setups(record["charter"], self.registry)
            except Exception as exc:   # noqa: BLE001 - a plain refusal, never "record not found"
                raise ValueError(f"The charter cannot be compiled as it stands ({type(exc).__name__}: {exc}); this is for the formulator "
                                 "or a developer, not a scientific decision. Its findings say what fails.") from exc
            record["confirmed"] = record.get("confirmed", []) + [{"revision": record["revision"], "at": now(), "hash": content_hash(record["charter"])}]
            record.update(confirmed_revision=record["revision"], status="confirmed", updated_at=now())
            self.store.put(KIND, record)
        return {"charter": {"id": charter_id, "revision": record["revision"]}, "setups": setups,
                "text": mechanics.render(record["charter"]["text"], mechanics.resolve(record["charter"])["values"], record["charter"])}

    def confirmed(self, reference: dict) -> dict:
        """A confirmed revision a campaign may be created from, with its compiled setups and text."""
        record = self.get(reference["id"])
        if reference["revision"] not in {row["revision"] for row in record.get("confirmed", [])}:
            raise ValueError("A campaign can only be made from a confirmed charter revision")
        charter = self.revision(reference["id"], reference["revision"])["charter"]
        values = mechanics.resolve(charter)["values"]
        return {"charter": charter, "setups": mechanics.compile_setups(charter, self.registry),
                "text": mechanics.render(charter["text"], values, charter)}

    def link(self, charter_id, campaign_id):
        with self.workspace.lock:
            record = self.get(charter_id)
            if campaign_id not in record["campaign_ids"]:
                record["campaign_ids"] = record["campaign_ids"] + [campaign_id]
                self.store.put(KIND, record)

    def fork(self, charter_id, changes: list[dict], *, revision=None, title=None, rationale=""):
        """A new draft from a confirmed revision with inputs changed; it records where it came from."""
        record = self.get(charter_id)
        number = revision or record.get("confirmed_revision")
        if number is None:
            raise ValueError("Only a confirmed charter can be forked")
        base = self.revision(charter_id, number)["charter"]
        updated = mechanics.apply_changes(base, changes, origin="researcher")
        old, new = mechanics.resolve(base)["values"], mechanics.resolve(updated)["values"]
        changed = {name: [old.get(name), new.get(name)] for name, quantity in ProblemCharter.model_validate(updated).quantities.items()
                   if quantity.role == "input" and old.get(name) != new.get(name)}
        updated["forked_from"] = {"charter_id": charter_id, "revision": number, "changes": changed}
        if title:
            updated["title"] = title
        return self.create(updated, source={"kind": "fork", "id": charter_id, "revision": number},
                           rationale=rationale or "Forked: " + ", ".join(f"{k} {v[0]} → {v[1]}" for k, v in changed.items()))
