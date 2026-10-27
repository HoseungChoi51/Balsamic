"""The implementation allocation is the researcher's optional ceiling (roadmap B3): with none set, an agent's commission
needs only the compute go-ahead the bus guard asks for, a positive ceiling still caps, and an agent cannot ask to raise it.
Since roadmap H8 a commission is a headless coding box (test_commission_box's lab, over a fake driver), and the ceiling counts
its compute time as it counted a service job's."""
import pytest
from framework_fixtures import researcher_idea

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate, TaskInput
from optimization_framework.execution.service import Workspace
from test_commission_box import Lab, commission


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


def box_lab(tmp_path, monkeypatch, ceiling=0):
    """A campaign whose implementation lead commissions under the researcher's go-ahead (a Screen mandate for 2,400 worker
    seconds), coding workspaces on, and the researcher's implementation ceiling (0: none)."""
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "true")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    monkeypatch.setenv("GRATING_AUTO_INSTALL", "false")
    lab = Lab(tmp_path)
    store = lab.workspace.store
    store.put("campaign", {**store.get(lab.cid, "campaign"), "implementation_compute_budget_seconds": ceiling})
    return lab


def test_with_no_ceiling_a_commission_needs_only_the_compute_go_ahead(tmp_path, monkeypatch):
    lab = box_lab(tmp_path, monkeypatch)
    store = lab.workspace.store
    with pytest.raises(ValueError, match="mandate_propose"):
        commission(lab, "build_early", compute_seconds=5000)   # more than the go-ahead covers
    assert store.list("development_workspace", lab.cid) == []
    receipt = commission(lab, "build", compute_seconds=900)
    assert receipt["status"] == "completed" and receipt["outcome"]["workspace_id"]
    assert lab.workspace.implementations.compute_committed(lab.cid) == 900
    assert store.get(lab.cid, "campaign")["implementation_compute_budget_seconds"] == 0   # no raise was needed


def test_a_positive_ceiling_still_caps(tmp_path, monkeypatch):
    lab = box_lab(tmp_path, monkeypatch, ceiling=1000)
    workspace, cid = lab.workspace, lab.cid
    commission(lab, "first", compute_seconds=900)
    with pytest.raises(ValueError, match=r"implementation ceiling the researcher set \(1000s\)"):
        commission(lab, "second", compute_seconds=200)
    # A revalidation goes through the same check (bridge.over_ceiling).
    assert workspace.implementations.over_ceiling(workspace.store.get(cid, "campaign"), 200)
    # The researcher may lower the ceiling only to what is committed, or remove it with 0.
    with pytest.raises(ValueError, match="exceed the proposed implementation compute cap"):
        workspace.update_campaign(cid, CampaignUpdate(implementation_compute_budget_seconds=800))
    workspace.update_campaign(cid, CampaignUpdate(implementation_compute_budget_seconds=0))
    commission(lab, "second_without_ceiling", compute_seconds=200)
    assert workspace.implementations.compute_committed(cid) == 1100


def test_an_agent_asking_to_raise_the_allocation_is_sent_to_the_compute_go_ahead(tmp_path):
    workspace, cid, _ = lab(tmp_path, ceiling=60)
    redirect = r"Propose a mandate with mandate_propose instead; the implementation allocation is only an optional ceiling"
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
    with pytest.raises(ValueError, match="mandate_propose"):
        send(workspace, cid, "raise", "approval.request", {"kind": "campaign_limits", "rationale": "Room to build",
            "limits": {"implementation_compute_budget_seconds": 600}})
