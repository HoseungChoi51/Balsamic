"""Accept a changed evaluator as the same science only where it reproduces recorded results.

A faster evaluator is worth nothing if it answers differently. The check replays a sample of
one finished trial's recorded candidates under the current source and compares every objective
and constraint with what that trial recorded. A passing record lets a run continue under the
new source as the same run; it is evidence for the sampled candidates, not a proof.
"""
import math

from optimization_framework.contracts.base import content_hash
from optimization_framework.storage.sqlite import identifier, now

ACTIVE = {"queued", "running", "pausing", "stopping"}


def sample(observations, count, utility, whole=lambda row: row):
    """The best recorded candidates and an even spread of the rest, each candidate once.

    `whole` reads the full record of a considered row, so a long journal of large designs can
    be chosen from by its scalar fields alone.
    """
    chosen, seen = [], set()
    def take(row):
        if len(chosen) < count:
            row = whole(row)
            key = content_hash(row["candidate"])
            if key not in seen:
                seen.add(key)
                chosen.append(row)
    spacing = max(1, len(observations) // max(1, count))
    for rows in (sorted(observations, key=utility, reverse=True)[:(count + 1) // 2], observations[::spacing], observations):
        for row in rows:
            if len(chosen) == count:
                return chosen
            take(row)
    return chosen


def compare(expected, observed, absolute, relative):
    """The largest disagreement between recorded and replayed measurements, and whether any exceeds the tolerance."""
    largest, failures = 0., []
    for index, (before, after) in enumerate(zip(expected, observed)):
        if after.get("status") != "ok" or after["candidate"] != before["candidate"]:
            failures.append({"index": index, "reason": "The candidate was not evaluated again"})
            continue
        for name, value in before["objectives"].items():
            other = after["objectives"].get(name)
            if type(value) not in (int, float) or type(other) not in (int, float):
                if value != other:
                    failures.append({"index": index, "objective": name, "recorded": value, "replayed": other})
                continue
            difference = abs(value - other)
            largest = max(largest, difference)
            if not difference <= absolute + relative * abs(value):
                failures.append({"index": index, "objective": name, "recorded": value, "replayed": other})
        if before.get("constraints", {}) != after.get("constraints", {}):
            failures.append({"index": index, "reason": "Constraint results differ"})
    if len(observed) != len(expected):
        failures.append({"reason": f"{len(observed)} of {len(expected)} candidates were evaluated"})
    return largest, failures


class Equivalences:
    def __init__(self, workspace):
        self.workspace, self.store = workspace, workspace.store
        self.running = None

    def _running(self):
        if self.running is None:
            self.running = {row["id"] for row in self.store.list("evaluator_equivalence") if row["status"] == "running"}
        return self.running

    def start(self, campaign_id, request):
        from optimization_framework.contracts.problems import ProblemInstance
        from optimization_framework.contracts.requests import TrialInput
        from optimization_framework.execution.compaction import has_design
        from optimization_framework.execution.metrics import full_row, scalar_rows
        trial = self.store.get(request.trial_id, "trial")
        if trial["campaign_id"] != campaign_id or trial.get("recipe") or trial["algorithm"] in {"validate", "recipe", "replay"}:
            raise ValueError("Select an optimization experiment of this campaign as the recorded reference")
        if trial["status"] in ACTIVE:
            raise ValueError("The reference experiment is still running; pause or stop it first")
        task = self.workspace.evaluators.task_view(self.store.get(trial["task_id"], "task"))
        if task.get("problem") and content_hash(task["problem"]) != content_hash(trial["problem"]):
            raise ValueError("The task's problem changed since this experiment; its results are not a reference for the current problem")
        journal = self.workspace.job_dir(trial["id"]) / "observations.jsonl"
        # A compacted journal keeps the designs of its archive and of a spread of evaluations: those can still be replayed.
        observations = [(offset, row["objectives"]) for offset, _, row in scalar_rows(journal) if row.get("status") == "ok" and has_design(row)]
        if not observations:
            raise ValueError("The reference experiment recorded no successful observation whose design is still in its journal")
        objective = ProblemInstance(**trial["problem"]).primary_objective
        chosen = sample(observations, request.sample, lambda row: objective.utility(row[1][objective.name]), lambda row: full_row(journal, row[0]))
        replay = self.workspace.create_trial(TrialInput(campaign_id=campaign_id, task_id=trial["task_id"], algorithm="replay",
            algorithm_config={"candidates": [row["candidate"] for row in chosen]}, max_steps=len(chosen), wall_seconds=request.wall_seconds,
            priority=100, question=f"Evaluator equivalence check: replay {len(chosen)} candidates recorded by {trial['id']} under the current source."),
            runtime_gate=False)
        record = {"id": identifier("evaluator_equivalence"), "campaign_id": campaign_id, "task_id": trial["task_id"],
                  "reference_trial_id": trial["id"], "replay_trial_id": replay["id"], "problem": content_hash(trial["problem"]),
                  "from_source": trial["scientific_source_hash"], "to_source": replay["scientific_source_hash"],
                  "tolerance": {"absolute": request.absolute_tolerance, "relative": request.relative_tolerance},
                  "expected": [{key: row.get(key) for key in ("id", "candidate", "objectives", "constraints")} for row in chosen],
                  "status": "running", "created_at": now()}
        self.store.put("evaluator_equivalence", record, "evaluator.equivalence_started")
        self._running().add(record["id"])
        return record

    def advance(self):
        """Called by the scheduler: compare once the replay has finished."""
        from optimization_framework.execution.worker import iter_journal
        for identity in list(self._running()):
            record = self.store.get(identity, "evaluator_equivalence")
            replay = self.store.get(record["replay_trial_id"], "trial")
            if replay["status"] in ACTIVE:
                continue
            observed = list(iter_journal(self.workspace.job_dir(replay["id"]) / "observations.jsonl"))
            largest, failures = compare(record["expected"], observed, record["tolerance"]["absolute"], record["tolerance"]["relative"])
            record.update(status="completed", verdict="failed" if failures else "passed", candidates=len(record["expected"]),
                          largest_difference=largest if math.isfinite(largest) else None, failures=failures[:20], finished_at=now())
            # The recorded values stay in the reference trial's journal; the record keeps what identifies them.
            record["expected"] = [{"id": row["id"], "objectives": row["objectives"]} for row in record["expected"]]
            self.store.put("evaluator_equivalence", record, "evaluator.equivalence_completed")
            self.running.discard(identity)

    def passing(self, problem, from_source, to_source):
        """A passing comparison that covers this change of source for this problem, if one exists."""
        return next((row for row in reversed(self.store.list("evaluator_equivalence")) if row["status"] == "completed"
                     and row["verdict"] == "passed" and row["problem"] == problem
                     and row["from_source"] == from_source and row["to_source"] == to_source), None)
