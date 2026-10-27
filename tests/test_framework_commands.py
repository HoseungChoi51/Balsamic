"""A command's allocation and outcome are one transaction, even under retries."""
from framework_fixtures import researcher_idea
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate, TaskInput
from optimization_framework.execution.service import Workspace


def prepare(tmp_path, autonomy="guided"):
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name="Commands", autonomy=autonomy, compute_budget_seconds=100, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    task = workspace.current_tasks(campaign["id"])[0]
    command = Command(id="command_once", campaign_id=campaign["id"], expected_revision=campaign["version"],
        operation="trial.create", payload={"task_id": task["id"], "algorithm": "coordinate", "max_steps": 5, "wall_seconds": 10})
    return workspace, campaign, command


def test_concurrent_retries_reserve_and_launch_only_one_experiment(tmp_path):
    workspace, campaign, command = prepare(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: workspace.commands.execute(command), range(2)))
    assert results[0] == results[1]
    assert len(workspace.store.list("trial")) == len(workspace.store.list("work_command")) == 1
    assert workspace.allocated_seconds(campaign["id"]) == 10
    workspace.update_campaign(campaign["id"], CampaignUpdate(name="New name"))
    assert workspace.commands.execute(command) == results[0]
    with pytest.raises(ValueError, match="identity"):
        workspace.commands.execute(command.model_copy(update={"payload": {**command.payload, "seed": 9}}))


def test_failure_before_commit_leaves_no_experiment_or_allocation(tmp_path, monkeypatch):
    workspace, campaign, command = prepare(tmp_path)
    original = workspace.commands._apply
    def fail(request, actor):
        original(request, actor)
        raise RuntimeError("Could not commit the command outcome")
    monkeypatch.setattr(workspace.commands, "_apply", fail)
    with pytest.raises(RuntimeError):
        workspace.commands.execute(command)
    assert workspace.store.list("trial") == workspace.store.list("work_command") == []
    assert workspace.allocated_seconds(campaign["id"]) == 0


def test_manager_commands_pin_current_guidance_and_resource_authority(tmp_path):
    workspace, campaign, command = prepare(tmp_path, "delegated")
    with pytest.raises(ValueError, match="pin guidance"):
        workspace.commands.execute(command, actor="manager")
    with pytest.raises(ValueError, match="pin guidance"):
        workspace.commands.execute(command, actor="manager")
    assert len(workspace.store.list("command_rejection")) == 1
    command = command.model_copy(update={"expected_guidance_revision": 0,
        "expected_authority_hash": workspace.commands.authority_hash(campaign)})
    outcome = workspace.commands.execute(command, actor="manager")
    assert outcome["actor"] == "manager"
    workspace.update_campaign(campaign["id"], CampaignUpdate(autonomy="guided"))
    with pytest.raises(ValueError, match="revision"):
        workspace.commands.execute(command.model_copy(update={"id": "another_command"}), actor="manager")


def test_versioned_http_command_returns_durable_outcome(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name="HTTP", compute_budget_seconds=100, validation_reserve_seconds=0,
        tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})]))
    task = workspace.current_tasks(campaign["id"])[0]
    payload = {"id": "http_command", "campaign_id": campaign["id"], "expected_revision": campaign["version"],
        "operation": "trial.create", "payload": {"task_id": task["id"], "algorithm": "coordinate", "max_steps": 2, "wall_seconds": 5}}
    with TestClient(app) as client:
        first = client.post("/api/v1/commands", json=payload)
        second = client.post("/api/v1/commands", json=payload)
        assert first.status_code == second.status_code == 200, first.text
        assert first.json() == second.json()
        assert client.get("/api/v1/commands/http_command").json() == first.json()


def commission(workspace, campaign, identity="build_once"):
    from optimization_framework.implementations.models import ImplementationSpec
    updated = workspace.update_campaign(campaign["id"], CampaignUpdate(implementation_compute_budget_seconds=20))
    hypothesis = researcher_idea(workspace, campaign["id"])
    return Command(id=identity, campaign_id=campaign["id"], expected_revision=updated["version"], operation="implementation.commission",
        payload={"hypothesis_id": hypothesis["id"], "compute_seconds": 10,
            "spec": ImplementationSpec(name="Coordinate variant", mechanism="A bounded specialized search",
                problem_id="bounded_continuous", capabilities=["continuous"], acceptance_criteria=["Feasible proposals"]).model_dump()})


def test_a_commission_reserves_no_service_job_and_never_contacts_the_implementation_service(tmp_path, monkeypatch):
    """Since roadmap H8 a commission builds only in a coding box: with coding workspaces off it is refused with the switch that
    turns them on, and nothing reserves a grant, queues a delivery or reaches the implementation library for it."""
    workspace, campaign, _ = prepare(tmp_path)
    command = commission(workspace, campaign)
    monkeypatch.setattr(workspace.implementations.client, "submit", lambda request: pytest.fail("A commission reached the implementation service"))
    with pytest.raises(ValueError, match="code is built only in them"):
        workspace.commands.execute(command)
    workspace.dispatch_outbox()
    assert workspace.store.list("implementation_grant") == workspace.store.list("outbox") == []
