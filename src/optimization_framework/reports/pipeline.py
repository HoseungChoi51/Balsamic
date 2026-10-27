"""Persisted editorial stages; bounded investigation, independent reviews, no silent retries."""
from copy import deepcopy
from html.parser import HTMLParser
import json
import re

from optimization_framework.llm.adapter import LLMAdapter
from optimization_framework.storage.sqlite import now
from .document import sections, writer_document
from .editorial import Brief, Draft, Investigation, LIMITS, Review, ROLES, RULES, STAGES, Selection
from .evidence import EvidenceTools


def normalize(value):
    return re.sub(r"\s+", " ", value).strip()


TYPOGRAPHY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " "})


def located(quote, plain):
    """Whether a claim's passage is in the draft: verbatim, or sentence by sentence in order when it runs across a heading.

    Typographic quotes and dashes count as their plain forms, so a passage is not lost to a changed apostrophe.
    """
    quote, plain = normalize(quote.translate(TYPOGRAPHY)), normalize(plain.translate(TYPOGRAPHY))
    if not quote:
        return False
    if quote in plain:
        return True
    position = 0
    for sentence in re.split(r"(?<=[.!?])\s+", quote):
        found = plain.find(sentence, position)
        if found < 0:
            return False
        position = found + len(sentence)
    return True


def validate_feedback(result, source, feedback):
    text = normalize("\n".join(sections(source).values()))
    for mark in feedback.get("annotations", []):
        if not result.feedback_response.get(mark["id"], "").strip():
            raise ValueError("Writer did not account for every annotation; source and feedback are unchanged")
        if mark["tier"] == "good" and normalize(mark["exact"]) not in text and not result.preservation_exceptions.get(mark["id"], "").strip():
            raise ValueError("Writer changed a green phrase without explaining why; source and feedback are unchanged")


class Stopped(Exception):
    pass


class Pipeline:
    def __init__(self, writer, job):
        self.writer, self.workspace, self.store, self.job = writer, writer.workspace, writer.store, job
        self.figures = deepcopy(job["figures"])
        self.tools = EvidenceTools(self.workspace, job, self.figures)
        self.adapter = LLMAdapter(max_calls=LIMITS["model_calls"], max_output_tokens=8192, budget_usd=0,
            usage=job.get("usage"), config=job["provider_snapshot"],
            reservation_callback=lambda event: writer.capture(job["id"], event),
            spend_guard=self.afford, harness=self.workspace.pi.client)

    def afford(self, dollars):
        """Refuse a billed call that the campaign's model budget, or the model-spend envelope of the request that asked for the
        report (R5), cannot cover at its upper bound."""
        allowance = self.workspace.pi.model_allowance(self.job["campaign_id"]) if self.job["campaign_id"] else None
        if allowance is not None and dollars > allowance + 1e-9:
            raise ValueError(f"The campaign's model budget cannot cover the next stage: it may cost up to ${dollars:.2f} and "
                             f"${max(0.0, allowance):.2f} is left. The finished stages are saved; raise the budget and ask for the report again.")
        if self.job["campaign_id"] and self.job.get("request_root"):
            from optimization_framework.campaigns import mandates
            mandate = mandates.current(self.workspace, self.job["campaign_id"], self.job["request_root"])
            left = mandates.model_left(mandate) if mandate else None
            if left is not None and dollars > left + 1e-9:
                raise ValueError(f"The request's model-spend envelope cannot cover the next stage: it may cost up to ${dollars:.2f} and "
                                 f"${left:.2f} is left. The finished stages are saved; raise the envelope and ask for the report again.")

    def update(self, event=None, **values):
        with self.store.transaction():
            job = self.store.get(self.job["id"], "report_writer_job")
            self.job = self.store.put("report_writer_job", {**job, **values}, event)

    def log_stage(self, key, purpose, status):
        """The stages of this job in order, small enough for the page that follows its progress."""
        log = [row for row in self.job.get("stage_log", []) if row["key"] != key]
        started = next((row["started_at"] for row in self.job.get("stage_log", []) if row["key"] == key), now())
        return [*log, {"key": key, "purpose": purpose, "status": status, "started_at": started,
                       **({"finished_at": now()} if status != "running" else {})}]

    def check_stop(self):
        self.job = self.store.get(self.job["id"], "report_writer_job")
        if self.job.get("cancel_requested") or self.workspace.shutdown_event.is_set():
            raise Stopped()

    def stage(self, key, purpose, content, schema, check=None):
        self.check_stop()
        identity = self.job["id"] + "_" + key
        try:
            previous = self.store.get(identity, "report_writer_stage")
        except KeyError:
            previous = None
        if previous:
            if previous["status"] != "completed":
                raise ValueError("A previous stage was interrupted or failed; it will not be replayed automatically")
            return schema.model_validate(previous["output"])
        single = self.job["workflow"] == "single"
        role = "technical_report_writer" if single else ROLES[purpose]
        from .writer import WRITER_INSTRUCTIONS
        instructions = RULES + "\n" + STAGES[purpose]
        if schema is Draft:
            instructions += "\n" + WRITER_INSTRUCTIONS.replace("Preserve supplied figure placeholders", "Preserve SELECTED figure placeholders")
        if single:
            instructions += "\nYou are the same scientific author throughout this workflow. Self-review critically; use the saved working notes below."
            content = {**content, "working_notes": [{"stage": row["stage"], "output": row["output"]}
                for row in self.artifacts() if row["status"] == "completed" and row["stage"] in {"brief", "science", "reader"}]}
        instructions += "\nReturn JSON matching: " + json.dumps(schema.model_json_schema())
        if len((instructions + json.dumps(content, ensure_ascii=False)).encode()) > LIMITS["max_prompt_bytes"]:
            raise ValueError("Editorial context exceeds the bounded prompt size; saved stages remain available. Use a narrower evidence scope")
        record = {"id": identity, "job_id": self.job["id"], "campaign_id": self.job["campaign_id"], "stage": key,
            "purpose": purpose, "role": role, "status": "running", "started_at": now(),
            "instructions": instructions, "input": content, "usage_before": deepcopy(self.adapter.usage)}
        with self.store.transaction():
            self.store.put("report_writer_stage", record)
            self.update(stage=key, stage_ids=[*self.job.get("stage_ids", []), identity], stage_log=self.log_stage(key, purpose, "running"))
        try:
            result = self.adapter.call_with_prompt(role, instructions, content, result_type=schema)
            self.store.put_immutable("report_writer_stage", {**record, "status": "completed", "output": result.model_dump(),
                **(check(result) if check else {}), "finished_at": now(), "usage_after": deepcopy(self.adapter.usage)})
            self.update(usage=deepcopy(self.adapter.usage), stage_log=self.log_stage(key, purpose, "completed"))
            return result
        except Exception:
            self.store.put_immutable("report_writer_stage", {**record, "status": "failed", "finished_at": now(),
                "usage_after": deepcopy(self.adapter.usage)})
            self.update(stage_log=self.log_stage(key, purpose, "failed"))
            raise

    def artifacts(self):
        return [self.store.get(key, "report_writer_stage") for key in self.job.get("stage_ids", [])]

    def evidence(self):
        return [{key: value for key, value in receipt.items() if key not in {"content_hash", "campaign_id", "job_id"}}
                for receipt in self.tools.receipts]

    def context(self):
        feedback = deepcopy(self.job["input"].get("feedback", {}))
        # Many marks in one paragraph should not repeat that entire paragraph in
        # every prompt. Keep exact selections and one full context per section.
        contexts = {}
        for mark in feedback.get("annotations", []):
            if "context" in mark:
                contexts[mark["section_id"]] = mark.pop("context")
        if contexts:
            feedback["section_contexts"] = contexts
        return {"researcher_notes": self.job["input"]["instruction"], "focus_answer": self.job.get("focus_answer"),
            "previous_focus": self.job["input"].get("previous_focus"), "inventory": self.tools.inventory(),
            "feedback": feedback, "limits": LIMITS, "tool_limit_notes": self.job.get("tool_limit_notes", [])}

    def read_requests(self, requests, *, reserve=0):
        for index, request in enumerate(requests):
            self.check_stop()
            if len(self.tools.receipts) >= LIMITS["tool_calls"] - reserve:
                self.update(tool_limit_notes=[*self.job.get("tool_limit_notes", []),
                    f"{len(requests) - index} requested tools were not run because this stage's tool allowance was exhausted."])
                break
            self.tools.execute(request)

    def validate_claims(self, investigation):
        receipts = {row["id"]: row for row in self.tools.receipts if row["status"] == "completed"}
        seen = set()
        if not investigation.claims:
            raise ValueError("Investigation produced no supported claims. Read the saved coverage assessment before requesting a narrower draft")
        for claim in investigation.claims:
            if claim.id in seen:
                raise ValueError("Duplicate assessed claim ID")
            seen.add(claim.id)
            for identity in claim.support + claim.counterevidence:
                row = receipts.get(identity)
                if (not row or row["request"]["tool"] == "source.search" or row["request"].get("record_id") == "inventory"
                    or isinstance(row.get("result"), dict) and row["result"].get("record_projection") in {"field_index", "reference"}
                    or self.tools.snapshot["kinds"].get(row["request"].get("record_id")) == "source"
                    or row["request"]["tool"] == "source.read" and not row["result"].get("passages")):
                    raise ValueError("Claims must cite successful evidence reads or analyses, not search metadata, inventory entries, or invented receipts")

    def unverified_numbers(self, investigation):
        """Each claim's numbers that none of the receipts in its support holds (K2), by claim id; claims without any are left out."""
        from optimization_framework.analysis.claims import unverified
        receipts = {row["id"]: row for row in self.tools.receipts if row["status"] == "completed"}
        found = {}
        for claim in investigation.claims:
            missing = unverified(claim.statement, [receipts[identity].get("result") for identity in claim.support if identity in receipts])
            if missing:
                found[claim.id] = missing
        return found

    def validate_selection(self, selection, investigation):
        ids = [row.claim_id for row in selection.claims]
        if len(ids) != len(set(ids)) or set(ids) != {claim.id for claim in investigation.claims}:
            raise ValueError("Editorial selection must account for every assessed claim exactly once")
        if not any(row.place == "main" for row in selection.claims):
            raise ValueError("Editorial selection needs a main claim")
        if len(set(selection.figure_ids)) != len(selection.figure_ids) or not set(selection.figure_ids) <= set(self.figures):
            raise ValueError("Editorial selection names an unavailable or repeated figure")
        if any(not selection.figure_reasons.get(key, "").strip() for key in self.figures):
            raise ValueError("Editorial selection must explain each included or omitted figure")

    def validate_draft(self, draft, selection, reviews=()):
        source = writer_document(draft.title, draft.body_html, {key: self.figures[key] for key in selection.figure_ids})
        validate_feedback(draft, source, self.job["input"].get("feedback", {}))
        plain = normalize("\n".join(sections(source).values()))
        expected = {row.claim_id for row in selection.claims if row.place != "archive"}
        if set(draft.claim_uses) != expected or not all(located(quote, plain) for quote in draft.claim_uses.values()):
            raise ValueError("Draft must locate every selected claim in its actual prose")
        for review in reviews:
            for issue in review.issues:
                if not draft.review_response.get(issue.id, "").strip():
                    raise ValueError("Editor did not account for every review issue")
        urls = set()
        for row in self.tools.receipts:
            if row["status"] == "completed" and row["request"]["tool"] == "source.read":
                urls.add(row["result"]["capture"]["url"])
                if row["result"].get("source", {}).get("url"):
                    urls.add(row["result"]["source"]["url"])
        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                href = dict(attrs).get("href", "")
                if tag == "a" and href.startswith(("https://", "http://")) and href not in urls:
                    raise ValueError("Draft cites a URL without a source reading receipt")
        Links().feed(draft.body_html)
        return source

    def validate_review(self, review, prefix):
        ids = [issue.id for issue in review.issues]
        available = {row["id"] for row in self.tools.receipts if row["status"] == "completed"}
        if len(ids) != len(set(ids)) or any(not identity.startswith(prefix + "_") for identity in ids):
            raise ValueError("Review issue IDs must be unique and identify their reviewing role")
        if any(not set(issue.evidence_ids) <= available for issue in review.issues):
            raise ValueError("Review cites an unavailable evidence receipt")

    def run(self):
        brief = self.stage("brief", "brief", {**self.context(),
            "prior_draft_excerpt": self.job["input"].get("source_html", "")[:12000],
            "excerpt_basis": "Opening excerpt for understanding the existing article; not independent scientific evidence."}, Brief)
        if brief.question and not self.job.get("focus_answer"):
            self.update("report.writer_question", status="awaiting_focus", question=brief.question, focus=brief.focus)
            return
        investigation = None
        for turn in range(LIMITS["investigation_rounds"]):
            final = turn == LIMITS["investigation_rounds"] - 1
            investigation = self.stage(f"investigate_{turn + 1}", "investigate", {**self.context(), "brief": brief.model_dump(),
                "read_receipts": self.evidence(), "previous_assessment": investigation.model_dump() if investigation else None,
                "remaining_tools": max(0, LIMITS["tool_calls"] - 3 - len(self.tools.receipts)),
                "finish_now": final, "instruction": "Return requests=[] and consolidate claims now." if final else "Inspect evidence before concluding."}, Investigation,
                check=lambda result: {"unverified_numbers": self.unverified_numbers(result)})
            if final or not investigation.requests:
                break
            self.read_requests(investigation.requests, reserve=3)
        if investigation.requests:
            raise ValueError("Investigator did not finish within the call limit; its evidence reads and assessment are saved")
        self.validate_claims(investigation)
        figure_catalog = {key: re.sub(r"<[^>]+>", " ", re.search(r"<figcaption[^>]*>(.*?)</figcaption>", html, re.S)[1])
            if re.search(r"<figcaption[^>]*>(.*?)</figcaption>", html, re.S) else "Original figure; consult the prior draft"
            for key, html in self.figures.items()}
        basis = {**self.context(), "brief": brief.model_dump(), "investigation": investigation.model_dump(),
                 "read_receipts": self.evidence(), "figures": figure_catalog}
        selection = self.stage("select", "select", {**basis, "source_html": self.job["input"].get("source_html")}, Selection)
        self.validate_selection(selection, investigation)
        self.update(focus=selection.focus)
        basis.update(selection=selection.model_dump(), selected_figures=selection.figure_ids)
        draft = self.stage("draft", "draft", {**basis, "source_html": self.job["input"].get("source_html")}, Draft)
        self.validate_draft(draft, selection)
        # Separate initial contexts: neither reviewer sees the other's assessment.
        science = self.stage("science", "science", {**basis, "draft": draft.model_dump(),
            "remaining_tools": LIMITS["tool_calls"] - len(self.tools.receipts)}, Review)
        if science.requests:
            self.read_requests(science.requests)
            basis["read_receipts"] = self.evidence()
            science = self.stage("science_checked", "science", {**basis, "draft": draft.model_dump(),
                "initial_review": science.model_dump(), "instruction": "Return requests=[] with your consolidated assessment; no tools remain."}, Review)
        if science.requests:
            raise ValueError("Scientific review did not finish within the investigation limit")
        self.validate_review(science, "science")
        reader = self.stage("reader", "reader", {**basis, "draft": draft.model_dump()}, Review)
        if reader.requests:
            raise ValueError("Expert reader review requested tools outside its editorial scope")
        self.validate_review(reader, "reader")
        reviews = [science, reader]
        for turn in range(LIMITS["edit_rounds"]):
            draft = self.stage(f"edit_{turn + 1}", "edit", {**basis, "draft": draft.model_dump(),
                "reviews": [review.model_dump() for review in reviews]}, Draft)
            source = self.validate_draft(draft, selection, reviews)
            verification = self.stage(f"verify_{turn + 1}", "verify", {**basis, "draft": draft.model_dump(),
                "reviews": [review.model_dump() for review in reviews]}, Review)
            if verification.requests:
                raise ValueError("Final verification cannot start another investigation")
            self.validate_review(verification, "verify")
            if not any(issue.severity == "blocking" for issue in verification.issues):
                break
            reviews = [science, reader, verification]
        self.check_stop()
        unresolved = [issue.model_dump() for issue in verification.issues if issue.severity == "blocking"]
        unsourced = self.unverified_numbers(investigation)
        editorial = {"workflow": self.job["workflow"], "focus": selection.focus, "brief": brief.model_dump(),
            "focus_answer": self.job.get("focus_answer"), "selection": selection.model_dump(),
            "claims": [{**claim.model_dump(), **({"unverified_numbers": unsourced[claim.id]} if claim.id in unsourced else {})}
                       for claim in investigation.claims], "coverage": investigation.coverage,
            "snapshot_gaps": self.tools.snapshot["gaps"], "missing_evidence": investigation.missing_evidence,
            "proposed_experiments": investigation.proposed_experiments, "verification": verification.model_dump(),
            "unresolved": unresolved, "snapshot_id": self.job["snapshot_id"]}
        with self.store.transaction():
            report = self.writer.reports.add(source, draft.title, campaign_id=self.job["campaign_id"],
                parent_id=self.job["report_id"], evidence=self.job["input"].get("evidence", {}),
                revision={"job_id": self.job["id"], "submission_id": self.job.get("submission_id"), "editorial": editorial,
                          **draft.model_dump(exclude={"body_html", "title"})})
            self.update("report.writer_completed", status="needs_attention" if unresolved else "completed", result_id=report["id"],
                finished_at=now(), usage=deepcopy(self.adapter.usage),
                error="The revision limit was reached with unresolved scientific issues. Inspect the draft's writing notes." if unresolved else None)

    def execute(self):
        try:
            self.run()
        except Stopped:
            self.update("report.writer_cancelled", status="cancelled", finished_at=now(), usage=deepcopy(self.adapter.usage))
        except Exception as error:
            self.update("report.writer_failed", status="failed", finished_at=now(), usage=deepcopy(self.adapter.usage),
                error=str(error) if isinstance(error, ValueError) else "Report writing failed. Saved stages, evidence, original and feedback are retained; no automatic retry was made.")
