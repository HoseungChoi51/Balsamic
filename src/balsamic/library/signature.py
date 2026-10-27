"""A campaign's problem signature: what a library entry is matched on. Built from the first development task's problem instance."""
from optimization_framework.contracts.base import content_hash


def signature_of(workspace, campaign_id):
    campaign = workspace.store.get(campaign_id, "campaign")
    tasks = [t for t in workspace.store.list("task", campaign_id) if not t.get("archived")]
    task = next((t for t in tasks if str(t.get("split", "development")).lower() in {"development", "dev", "train", "training"}), tasks[0] if tasks else None)
    if task is None:
        return {"problem_id": None, "basis": "no problem instance yet"}
    problem = task.get("problem") or {}
    schema = problem.get("candidate_schema") or {}
    objective = problem.get("primary_objective") or {}
    charter = (campaign.get("charter") or {}).get("id")
    return {"problem_id": problem.get("definition_id") or task.get("problem_id"), "evaluator_version": problem.get("evaluator_version"),
            "objective": {"name": objective.get("name"), "direction": objective.get("direction"), "units": objective.get("units")},
            "representation": schema.get("representation"), "dimensions": schema.get("dimensions"),
            "constraint_digest": content_hash(schema.get("constraints") or [])[:16], "instance_digest": content_hash({"configuration": problem.get("configuration"), "fidelity": problem.get("fidelity")})[:16],
            "charter_id": charter, "task_id": task["id"], "basis": "the first development task's problem instance"}


def match(entry_signature, signature, text=""):
    """How well an entry fits a campaign: the plan's scores, with the reasons."""
    score, reasons = 0, []
    if not signature.get("problem_id") or not entry_signature.get("problem_id"):
        return 0, ["no problem to match on"]
    if entry_signature["problem_id"] == signature["problem_id"]:
        score += 3; reasons.append("same problem")
    objective, mine = entry_signature.get("objective") or {}, signature.get("objective") or {}
    if objective.get("name") and objective.get("name") == mine.get("name") and objective.get("direction") == mine.get("direction"):
        score += 2; reasons.append("same objective and direction")
    if entry_signature.get("representation") and entry_signature["representation"] == signature.get("representation"):
        score += 1; reasons.append("same representation")
    if entry_signature.get("constraint_digest") and entry_signature["constraint_digest"] == signature.get("constraint_digest"):
        score += 1; reasons.append("same constraints")
    if entry_signature.get("instance_digest") and entry_signature["instance_digest"] == signature.get("instance_digest"):
        reasons.append("same instance")
    return score, reasons
