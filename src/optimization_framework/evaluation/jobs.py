"""Connect immutable validation subjects, scheduler jobs, and measured results."""
import json

from optimization_framework.contracts.assets import Asset, CostSlice
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.validation import ValidationRequirement, ValidationResult
from optimization_framework.execution.metrics import PACKED, full_row, pack_candidate, scalar_rows
from optimization_framework.execution.worker import iter_journal
from optimization_framework.storage.sqlite import now


def snapshot_solutions(workspace, trial, candidates):
    """Freeze the observed search prefix without pausing or changing the learner.

    Prefix costs resolve against the same append-only ledger as final outputs.
    Pending ingestion stays unknown; later work lies outside the fixed interval.
    """
    directory, journal = workspace.job_dir(trial["id"]), workspace.job_dir(trial["id"]) / "observations.jsonl"
    # A long search of large designs fills gigabytes of journal. Both journals are looked through
    # for their scalar fields, and only the observations that carry a wanted candidate are read whole.
    requests = [row for _, _, row in scalar_rows(directory / "requests.jsonl")]
    positions = {row["id"]: index for index, row in enumerate(requests)}
    # A journal holds a design as a list or, for a long binary one, as packed bits: look for either.
    serialized = [tuple(json.dumps(form if type(form) is list else form[PACKED], separators=(",", ":")).encode()
                        for form in ([candidate] if pack_candidate(candidate) is candidate else [candidate, pack_candidate(candidate)]))
                  for candidate in candidates]
    carrying, stop = [[] for _ in candidates], 0
    for offset, line, row in scalar_rows(journal):
        if row["request_id"] not in positions:
            continue
        stop = max(stop, positions[row["request_id"]] + 1)
        if row["status"] == "ok":
            for found, forms in zip(carrying, serialized):
                if any(text in line for text in forms):
                    found.append(offset)
    if not stop:
        raise ValueError("No authoritative observation journal is available for this candidate snapshot")
    final_attempt = requests[stop - 1]["attempt_id"]
    prior_attempts = sorted({row["attempt_id"] for row in requests[:stop] if row["attempt_id"] != final_attempt})
    costs = [CostSlice(source_id=trial["id"], stop=stop),
             *[CostSlice(source_id=identity, stop=1) for identity in prior_attempts]]
    if trial.get("isolation_policy"):
        from optimization_framework.assets.execution import ingest_costs
        costs = ingest_costs(workspace.assets, trial, directory, prefix_stop=stop, snapshot_attempt_id=final_attempt)
    dependencies = trial.get("initial_assets", []) + trial.get("contribution_asset_ids", trial.get("implementation_cost_asset_ids", []))
    exposed = {trial["problem"]["scientific_identity"]}
    exposure_known = trial["algorithm"] != "package"
    for identity in dependencies:
        asset = workspace.store.get(identity, "asset")
        exposed.update(asset["exposed_instance_ids"])
        exposure_known &= asset["exposure_status"] == "known"
    result = []
    for candidate, found in zip(candidates, carrying):
        observation = next((row for row in (full_row(journal, offset) for offset in reversed(found)) if row["candidate"] == candidate), None)
        if observation is None:
            # Not found as it would be written today: compare every record before calling it absent.
            for row in iter_journal(journal):
                if row["request_id"] in positions and row["status"] == "ok" and row["candidate"] == candidate:
                    observation = row
        if observation is None:
            raise ValueError("The candidate has no successful authoritative observation in this search prefix" + (
                f"; this experiment's journals were compacted on {trial['journals_compacted_at']} and keep only a spread of its designs"
                if trial.get("journals_compacted_at") else ""))
        request = requests[positions[observation["request_id"]]]
        result.append(workspace.assets.publish(Asset(
            id="snapshot_" + content_hash([trial["id"], stop, observation["id"]]), campaign_id=trial["campaign_id"],
            kind="solution", title=f"Observed candidate at request {stop}", producer_id=trial["id"],
            payload={"candidate": candidate, "objectives": observation["objectives"], "observation": observation,
                     "problem": trial["problem"], "request_prefix_stop": stop},
            dependency_ids=dependencies, costs=costs,
            cost_provenance="partial" if trial["algorithm"] == "package" and not trial.get("implementation_cost_asset_ids") else "complete",
            exposure_status="known" if exposure_known else "unknown", exposed_instance_ids=sorted(exposed),
            applicability={"problem_id": trial["problem"]["definition_id"], "candidate_schema": trial["problem"]["candidate_schema"]},
            authority="observation_journal", created_at=request["created_at"])))
    return result


def requirements(workspace, trial, recipe, subjects, authority):
    rule = recipe.get("validation_rule")
    if not rule:
        return []  # A diagnostic without an assertion must not invent a pass.
    result = []
    if rule.get("subject") == "evaluator":
        task = workspace.evaluators.task_view(workspace.store.get(trial["task_id"], "task"))
        subjects = [workspace.store.get(task["problem_instance_id"], "problem_instance")]
    for index, subject in enumerate(subjects):
        scope = {"parameters": recipe["parameters"], "rule": rule, "parent_trial_id": trial["id"],
                 "subject_index": index, "recipe_cases_hash": content_hash(recipe["cases"]), "recipe": recipe}
        identity = "requirement_" + content_hash([trial["study_id"], subject["id"], recipe["recipe_id"], scope])
        try:
            required = workspace.store.get(identity, "validation_requirement")
        except KeyError:
            required = workspace.validations.require(ValidationRequirement(id=identity, campaign_id=trial["campaign_id"],
                study_id=trial["study_id"], subject_id=subject["id"], subject_digest=workspace.validations.subject_digest(subject["id"]),
                kind=rule["kind"], recipe_id=recipe["recipe_id"], scope=scope,
                evidence_requirements=rule.get("evidence_requirements", []), authority=authority, created_at=now()))
        result.append(required["id"])
    return result


def finish(workspace, trial):
    if not trial.get("validation_requirement_ids"):
        return
    terminal = trial.get("result") or trial.get("progress") or {}
    summary = terminal.get("recipe_result", {})
    findings = summary.get("subjects", [])
    for index, requirement_id in enumerate(trial["validation_requirement_ids"]):
        requirement = workspace.store.get(requirement_id, "validation_requirement")
        rule = requirement["scope"]["rule"]
        measurements = summary if rule.get("subject") == "evaluator" else findings[index] if index < len(findings) else {}
        if trial["status"] == "failed":
            verdict, rationale = "error", "The validation job failed; its measurements remain available."
        elif not terminal.get("scientific_complete") or not measurements.get("complete", False):
            verdict, rationale = "inconclusive", "The declared validation procedure did not finish."
        else:
            measured = measurements.get("verdict")
            verdict = measured if measured in {"passed", "failed", "inconclusive"} else "inconclusive"
            rationale = measurements.get("rationale", "The adapter assessed the frozen recipe's declared assertion.")
        result = ValidationResult(id="validation_" + content_hash([trial["id"], terminal.get("attempt_id"), requirement_id]),
            campaign_id=trial["campaign_id"], requirement_id=requirement_id, subject_digest=requirement["subject_digest"],
            recipe_id=requirement["recipe_id"], verdict=verdict, evidence_ids=[trial["id"], *trial.get("latest_output_asset_ids", [])],
            measurements=measurements, rationale=rationale, producer="trusted_service", authority="experiment_service",
            created_at=trial.get("finished_at") or trial["created_at"])
        workspace.validations.record_result(result)
        if verdict in {"failed", "error", "inconclusive"}:
            workspace.memory.issue(trial["campaign_id"], "validation_requires_attention", rationale,
                affected=requirement_id, evidence=[trial["id"], result.id])
