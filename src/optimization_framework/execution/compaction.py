"""Remove evaluated designs from finished experiments' journals, once the researcher confirms.

The request and observation journals hold every design a search evaluated. They are working data:
needed while a campaign is analysed, and afterwards the bulk of its disk use. Compaction keeps
every row and every number. It removes the designs, except those of each experiment's archive,
of its best evaluations and of an even spread of the rest, so that a later evaluator can still
be checked against the run (evaluator.equivalence). What it removes cannot be brought back.
"""
import fcntl
import hashlib
from itertools import zip_longest
import json
import os
import threading

from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.execution.metrics import scalar_rows
from optimization_framework.storage.sqlite import now, read_json

JOURNALS = ("requests.jsonl", "observations.jsonl")
FINISHED = {"completed", "budget_exhausted", "stopped", "failed"}
KEPT_BEST = KEPT_SPREAD = 32
REMOVED = {"removed": "journal.compact"}


def dumps(row):
    return json.dumps(row, allow_nan=False, separators=(",", ":")).encode() + b"\n"


def parsed(line):
    """The record a line holds, or None for an unfinished write, which is kept as it is."""
    if not line or not line.endswith(b"\n"):
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None


def has_design(row):
    """Whether a record, read whole or for its scalar fields, still carries its design."""
    return "candidate" in row and row["candidate"] is not None and row["candidate"] != REMOVED


def kept(directory, utility):
    """(observation ids, request ids) whose designs stay: the archive, the best, an even spread, and an unanswered last request."""
    result = read_json(directory / "result.json", None) or read_json(directory / "progress.json", {})
    archive = read_json(directory / "archive.json", None) or result.get("archive") or []
    observations = {entry["observation_id"] for entry in archive if isinstance(entry, dict) and entry.get("observation_id")}
    rows, compacted = [], False
    for _, _, row in scalar_rows(directory / "observations.jsonl"):
        compacted |= row.get("candidate") == REMOVED
        if has_design(row):
            rows.append((row["id"], row.get("request_id"), row.get("status"), row.get("objectives") or {}))
    if compacted:
        # Already compacted: what it kept stays. Choosing a spread again from the remainder would thin it each time.
        observations.update(identity for identity, _, _, _ in rows)
    scored = [(utility(objectives), identity) for identity, _, status, objectives in rows if status == "ok" and utility(objectives) is not None]
    observations.update(identity for _, identity in sorted(scored, reverse=True)[:KEPT_BEST])
    observations.update(identity for _, identity in scored[::max(1, len(scored) // KEPT_SPREAD)][:KEPT_SPREAD])
    requests = {request for identity, request, _, _ in rows if identity in observations}
    answered = {row.get("request_id") for _, _, row in scalar_rows(directory / "observations.jsonl")}
    last = None
    for _, _, row in scalar_rows(directory / "requests.jsonl"):
        last = row.get("id")
    if last is not None and last not in answered:
        requests.add(last)   # a restart turns it into an uncertain observation and needs its design
    return observations, requests


def rewrite(path, keep):
    """Write a journal again without the designs of the rows not kept; replace it only once the copy reads back right.

    Rows, their order and every other field are unchanged. Returns what was done, with digests of both files.
    """
    if not path.exists():
        return {"journal": path.name, "rows": 0, "designs_removed": 0, "bytes_before": 0, "bytes_after": 0}
    temporary = path.with_name(path.name + ".compacting")
    before, after, rows, removed = hashlib.sha256(), hashlib.sha256(), 0, 0
    with path.open("rb") as source, temporary.open("wb") as target:
        for line in source:
            before.update(line)
            row = parsed(line)
            if row is not None and has_design(row) and row.get("id") not in keep:
                line = dumps({**row, "candidate": REMOVED})
                removed += 1
            rows += row is not None
            after.update(line)
            target.write(line)
        target.flush()
        os.fsync(target.fileno())
    with path.open("rb") as source, temporary.open("rb") as target:
        for old, new in zip_longest(source, target):
            if old != new and (parsed(old) is None or parsed(new) != {**parsed(old), "candidate": REMOVED}):
                temporary.unlink()
                raise ValueError(f"The compacted copy of {path.name} does not read back as the original; nothing was replaced")
    summary = {"journal": path.name, "rows": rows, "designs_removed": removed, "bytes_before": path.stat().st_size,
               "bytes_after": temporary.stat().st_size, "sha256_before": before.hexdigest(), "sha256_after": after.hexdigest()}
    if removed:
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    else:
        temporary.unlink()
    return summary


def compact_trial(directory, utility):
    """Compact one finished experiment's journals; refuses while its worker holds the directory."""
    with (directory / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("The experiment's worker is running") from None
        observations, requests = kept(directory, utility)
        return [rewrite(directory / "requests.jsonl", requests), rewrite(directory / "observations.jsonl", observations)]


class JournalCompaction:
    """Compaction jobs: planned and approved through commands, carried out one at a time off the scheduler's loop."""

    def __init__(self, workspace):
        self.workspace, self.store = workspace, workspace.store
        self.worker = None

    def size(self, trial_id):
        directory = self.workspace.job_dir(trial_id)
        return sum((directory / name).stat().st_size for name in JOURNALS if (directory / name).exists())

    def plan(self, campaign_id, *, trial_ids=None, study_id=None):
        """The finished experiments a compaction would cover, how much they hold and which no finding cites yet."""
        trials = self.store.list("trial", campaign_id)
        by_id = {trial["id"]: trial for trial in trials}
        if trial_ids is not None:
            if missing := sorted(set(trial_ids) - set(by_id)):
                raise ValueError("Not experiments of this campaign: " + ", ".join(missing))
            chosen = [by_id[identity] for identity in dict.fromkeys(trial_ids)]
            if unfinished := [trial["id"] for trial in chosen if trial["status"] not in FINISHED]:
                raise ValueError("Only finished experiments are compacted; still open: " + ", ".join(unfinished))
        else:
            chosen = [trial for trial in trials if trial["status"] in FINISHED and (study_id is None or trial.get("study_id") == study_id)]
        chosen = [trial for trial in chosen if not trial.get("journals_compacted_at") and self.size(trial["id"])]
        cited = {identity for note in self.store.list("manager_note", campaign_id) if note.get("kind") in {"finding", "counterevidence"}
                 for identity in note.get("source_ids", [])}
        return {"trial_ids": [trial["id"] for trial in chosen], "bytes": sum(self.size(trial["id"]) for trial in chosen),
                "not_cited_by_a_finding": [trial["id"] for trial in chosen if trial["id"] not in cited]}

    def start(self, campaign_id, trial_ids, *, authority, identity):
        plan = self.plan(campaign_id, trial_ids=trial_ids)
        if not plan["trial_ids"]:
            raise ValueError("None of these experiments has journals left to compact")
        record = {"id": identity, "campaign_id": campaign_id, "status": "queued", "trial_ids": plan["trial_ids"], "bytes_before": plan["bytes"],
                  "kept": f"every row and number; the designs of each archive, of the {KEPT_BEST} best evaluations and of {KEPT_SPREAD} spread over the run",
                  "authority": authority, "created_at": now(), "trials": []}
        self.store.put("journal_compaction", record, "journal.compaction_queued")
        return record

    def advance(self):
        """Start the next queued job on its own thread: rewriting gigabytes must not hold up the scheduler."""
        if self.worker and self.worker.is_alive():
            return
        waiting = [job for job in self.store.list("journal_compaction") if job["status"] in {"queued", "running"}]
        if waiting:
            self.worker = threading.Thread(target=self.run, args=(waiting[0]["id"],), name="journal-compaction", daemon=True)
            self.worker.start()

    def run(self, identity):
        job = self.store.get(identity, "journal_compaction")
        job.update(status="running", started_at=job.get("started_at") or now())
        self.store.put("journal_compaction", job)
        done = {row["trial_id"] for row in job["trials"]}
        try:
            for trial_id in job["trial_ids"]:
                if trial_id in done:
                    continue   # finished before a restart; a compacted journal is left as it is anyway
                trial = self.store.get(trial_id, "trial")
                if trial["status"] not in FINISHED:
                    job["trials"].append({"trial_id": trial_id, "skipped": "The experiment was reopened"})
                    continue
                objective = ProblemInstance(**trial["problem"]).primary_objective
                utility = lambda objectives: objective.utility(objectives[objective.name]) if isinstance(objectives.get(objective.name), (int, float)) else None
                journals = compact_trial(self.workspace.job_dir(trial_id), utility)
                with self.workspace.lock:
                    trial = self.store.get(trial_id, "trial")
                    trial.update(journals_compacted_at=now(), journal_compaction_id=identity)
                    self.store.put("trial", trial, "trial.journals_compacted")
                    job["trials"].append({"trial_id": trial_id, "journals": journals})
                    self.store.put("journal_compaction", job)
            job.update(status="completed", bytes_after=sum(journal["bytes_after"] for row in job["trials"] for journal in row.get("journals", [])))
        except Exception as error:
            job.update(status="failed", error=f"{type(error).__name__}: {error}"[:2000])
        job["finished_at"] = now()
        self.store.put("journal_compaction", job, "journal.compaction_" + job["status"])
