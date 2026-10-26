"""Nothing that computes for more than a minute starts from an agent without the researcher's go-ahead, at any step: the agent
asks with approval.request (kind compute), the researcher's approval covers that plan's worker time, and nothing beyond it."""
import pytest

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace


@pytest.fixture
def lab(tmp_path):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Consent", autonomy="delegated", compute_budget_seconds=20000,
        validation_reserve_seconds=0, delegated_trial_seconds=1500, tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    return workspace, campaign, workspace.current_tasks(campaign["id"])[0]


def send(workspace, campaign_id, identity, operation, payload, actor="manager"):
    campaign = workspace.store.get(campaign_id, "campaign")
    pins = {"expected_guidance_revision": workspace.memory.state(campaign_id)["guidance_revision"],
            "expected_authority_hash": workspace.commands.authority_hash(campaign)} if actor != "researcher" else {}
    return workspace.commands.execute(Command(id=identity, campaign_id=campaign_id, expected_revision=campaign["version"],
        operation=operation, payload=payload, **pins), actor=actor)


def run(task, seconds):
    return {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": seconds}


def test_an_agent_starts_nothing_over_a_minute_without_the_researchers_go_ahead(lab):
    workspace, campaign, task = lab
    cid = campaign["id"]
    with pytest.raises(ValueError, match="approval.request with kind compute") as refused:
        send(workspace, cid, "screen_1", "trial.create", run(task, 590))
    assert "about 10 min" in str(refused.value) and "even when a request implies the work" in str(refused.value)
    send(workspace, cid, "short_probe", "trial.create", run(task, 30))           # a minute or less needs no go-ahead
    send(workspace, cid, "researcher_run", "trial.create", run(task, 590), actor="researcher")   # the researcher's own run
    with pytest.raises(ValueError, match="approval.request with kind compute"):
        send(workspace, cid, "profile", "runtime.profile", {"task_id": task["id"]})   # every step, not only experiments

    send(workspace, cid, "ask", "approval.request", {"kind": "compute", "plan": "Two screening runs of H13, seeds 0 and 1",
        "rationale": "Screen H13 against H12 at matched cost", "wall_seconds": 600, "worker_seconds": 1200,
        "meanwhile": "Read the H12 results on the Experiments page"})
    decision = workspace.store.list("decision", cid)[-1]
    assert decision["title"] == "Start this work now? About 10 min until results"
    assert "Meanwhile: Read the H12 results" in decision["proposal"] and [o["label"] for o in decision["options"]] == ["Start now", "Not now"]
    send(workspace, cid, "approve", "decision.resolve", {"decision_id": decision["id"], "choice": "0", "comment": "",
        "expected_resolution_revision": 0}, actor="researcher")
    [consent] = workspace.store.list("compute_consent", cid)
    assert consent["worker_seconds"] == 1200 and workspace.store.get(decision["id"], "decision")["outcome"] == {"consent_id": consent["id"]}

    send(workspace, cid, "screen_2", "trial.create", run(task, 590))
    send(workspace, cid, "screen_3", "trial.create", run(task, 590))
    assert workspace.store.get(consent["id"], "compute_consent")["used_seconds"] == 1180
    with pytest.raises(ValueError, match="Approved and unused: 20 s of worker time"):
        send(workspace, cid, "screen_4", "trial.create", run(task, 590))


def test_autopilot_runs_within_the_cap_the_researcher_set(lab):
    workspace, campaign, task = lab
    send(workspace, campaign["id"], "autopilot_run", "trial.create", run(task, 590), actor="autopilot")
    assert workspace.store.list("compute_consent", campaign["id"]) == []


def test_a_compute_plan_states_its_times_and_what_to_do_meanwhile(lab):
    workspace, campaign, task = lab
    with pytest.raises(ValueError, match="wall_seconds, worker_seconds and what the researcher can do meanwhile"):
        send(workspace, campaign["id"], "vague", "approval.request", {"kind": "compute", "plan": "Some runs", "rationale": "Screening"})
