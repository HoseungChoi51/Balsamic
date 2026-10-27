"""The implementation allocation is the researcher's optional ceiling (roadmap B3): with none set, an agent's commission
needs only the compute go-ahead the bus guard asks for, a positive ceiling still caps, and an agent cannot ask to raise it."""
import pytest
from framework_fixtures import researcher_idea

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate, TaskInput
from optimization_framework.execution.service import Workspace
from optimization_framework.implementations.models import ImplementationSpec


class Library:
    def __init__(self):
        self.jobs = {}

    def versions(self):
        return []

    def submit(self, request):
        return self.jobs.setdefault(request["idempotency_key"], {"id": "job_" + request["idempotency_key"], "status": "queued"})


def lab(tmp_path, ceiling=0):
    library = Library()
    workspace = library.workspace = Workspace(tmp_path, implementation_client=library)
    campaign = workspace.create_campaign(CampaignInput(name="Ceiling", autonomy="delegated", compute_budget_seconds=20000, delegated_trial_seconds=1500, validation_reserve_seconds=0,
        implementation_compute_budget_seconds=ceiling, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    return workspace, campaign["id"], researcher_idea(workspace, campaign["id"])


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def commission(hypothesis, seconds):
    spec = ImplementationSpec(name="Coordinate variant", mechanism="Bounded coordinate search", problem_id="bounded_continuous",
        capabilities=["continuous"], acceptance_criteria=["Feasible candidates"]).model_dump(mode="json")
    return {"hypothesis_id": hypothesis["id"], "spec": spec, "compute_seconds": seconds}


def go_ahead(workspace, campaign_id, hypothesis, seconds):
    send(workspace, campaign_id, "ask", "approval.request", {"kind": "compute", "plan": "Build the coordinate variant",
        "rationale": "The proposal needs code", "wall_seconds": seconds, "worker_seconds": seconds,
        "meanwhile": "Read the earlier results", "hypothesis_ids": [hypothesis["id"]]})
    decision = workspace.store.list("decision", campaign_id)[-1]
    send(workspace, campaign_id, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
        "expected_resolution_revision": 0}, actor="researcher")


def test_with_no_ceiling_a_commission_needs_only_the_compute_go_ahead(tmp_path):
    workspace, cid, hypothesis = lab(tmp_path)
    with pytest.raises(ValueError, match="approval.request with kind compute"):
        send(workspace, cid, "build_early", "implementation.commission", commission(hypothesis, 900))
    assert workspace.store.list("implementation_grant", cid) == []
    go_ahead(workspace, cid, hypothesis, 900)
    receipt = send(workspace, cid, "build", "implementation.commission", commission(hypothesis, 900))
    assert receipt["status"] == "completed"
    assert workspace.implementations.compute_committed(cid) == 900
    assert workspace.store.get(cid, "campaign")["implementation_compute_budget_seconds"] == 0   # no raise was needed


def test_a_positive_ceiling_still_caps(tmp_path):
    workspace, cid, hypothesis = lab(tmp_path, ceiling=60)
    spec = ImplementationSpec(name="Coordinate", mechanism="Bounded coordinate search", problem_id="bounded_continuous",
        capabilities=["continuous"], acceptance_criteria=["Feasible candidates"])
    workspace.implementations.commission(hypothesis["id"], spec, compute_seconds=50, idempotency_key="first")
    with pytest.raises(ValueError, match=r"implementation ceiling the researcher set \(60s\)"):
        workspace.implementations.commission(hypothesis["id"], spec, compute_seconds=20, idempotency_key="second")
    # A revalidation goes through the same check (bridge.over_ceiling).
    assert workspace.implementations.over_ceiling(workspace.store.get(cid, "campaign"), 20)
    # The researcher may lower the ceiling only to what is committed, or remove it with 0.
    with pytest.raises(ValueError, match="exceed the proposed implementation compute cap"):
        workspace.update_campaign(cid, CampaignUpdate(implementation_compute_budget_seconds=40))
    workspace.update_campaign(cid, CampaignUpdate(implementation_compute_budget_seconds=0))
    workspace.implementations.commission(hypothesis["id"], spec, compute_seconds=20, idempotency_key="second")
    assert workspace.implementations.compute_committed(cid) == 70


def test_an_agent_asking_to_raise_the_allocation_is_sent_to_the_compute_go_ahead(tmp_path):
    workspace, cid, _ = lab(tmp_path, ceiling=60)
    redirect = r"Ask for a compute go-ahead \(kind compute\) instead; the implementation allocation is only an optional ceiling"
    for identity, value in (("raise", 600), ("remove", 0)):
        with pytest.raises(ValueError, match=redirect):
            send(workspace, cid, identity, "approval.request", {"kind": "campaign_limits", "rationale": "Room to build",
                "limits": {"implementation_compute_budget_seconds": value}})
    assert workspace.store.list("decision", cid) == []
    send(workspace, cid, "lower", "approval.request", {"kind": "campaign_limits", "rationale": "Keep builds short",
        "limits": {"implementation_compute_budget_seconds": 30}})               # lowering a ceiling may still be asked
    [decision] = workspace.store.list("decision", cid)
    assert "implementation_compute_budget_seconds 60 to 30" in decision["title"]


def test_with_no_ceiling_any_raise_is_refused(tmp_path):
    workspace, cid, _ = lab(tmp_path)
    with pytest.raises(ValueError, match="kind compute"):
        send(workspace, cid, "raise", "approval.request", {"kind": "campaign_limits", "rationale": "Room to build",
            "limits": {"implementation_compute_budget_seconds": 600}})
