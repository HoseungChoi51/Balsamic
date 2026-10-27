"""Explicit researcher inputs for tests that need an existing idea.

Campaign creation intentionally produces no scientific proposals.
"""
from optimization_framework.campaigns.hypotheses import create
from optimization_framework.contracts.requests import HypothesisInput
from optimization_framework.storage.sqlite import identifier


def researcher_idea(workspace, campaign_id):
    return create(workspace, campaign_id, HypothesisInput(campaign_id=campaign_id,
        title="Researcher fixture proposal", algorithm="random", mechanism="Independent feasible samples",
        rationale="Explicit input for this service test"), identity=identifier("fixture_idea"))


def library_job(service, spec, package, *, key, campaign_id="campaign", workspace_id="workspace", hypothesis_id=None, compute_seconds=60):
    """A package the implementation library checked against its specification's frozen checks and published through its own API.
    Since roadmap H8 the library builds nothing and a commission builds in a coding box: a version comes from a supplied package
    (or from before), and a test attaches it to a proposal or binds it to a task. Returns the completed job."""
    from optimization_framework.implementations.models import JobRequest
    job = service.run_job(service.submit(JobRequest(workspace_id=workspace_id, campaign_id=campaign_id, hypothesis_id=hypothesis_id,
        grant_id="grant_" + key, idempotency_key=key, spec=spec, package=package, compute_seconds=compute_seconds))["id"])
    assert job["status"] == "completed", job
    return job


def grant_before_h8(workspace, job, **fields):
    """The grant a commission recorded, settled and attached, before roadmap H8 retired the library's own build route. Such records
    stay readable after the upgrade, and the research inputs one declared still count toward what its version cost."""
    request = job["request"]
    return workspace.store.put("implementation_grant", {"id": request["grant_id"], "campaign_id": job["campaign_id"],
        "hypothesis_id": request.get("hypothesis_id"), "charter_version": 1, "hypothesis_digest": None, "request": request,
        "status": job["status"], "created_at": job["created_at"], "job_id": job["id"], "version_id": job["version_id"],
        "upstream_cost_asset_ids": [], "usage": job.get("usage", {}), "compute_seconds": job.get("compute_seconds", 0),
        "attempts": job.get("attempts", []), "accounting_final": True, "attached": True, "cost_capture_digest": "recorded_before_h8",
        "error": job.get("error"), "updated_at": job.get("updated_at", job["created_at"]), **fields})
