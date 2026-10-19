import pytest

from support import command


def test_only_declared_operations_can_be_registered(workspace):
    with pytest.raises(ValueError, match="not a declared command operation"):
        workspace.commands.register("thread.teleport", lambda command, actor: {})


def test_the_catalog_lists_the_bus_without_the_legacy_manager(client):
    catalog = client.get("/api/v1/command-catalog").json()
    assert "campaign.stage_pin" in catalog and catalog["campaign.stage_pin"]["delegable"] is False
    assert "agent.message" in catalog and "hypothesis.create" in catalog
    for gone in ("research.start", "discovery.start", "decision.refresh", "context.import", "models.configure"):
        assert gone not in catalog


def test_a_receipt_carries_the_command_origin(client, campaign):
    receipt = command(client, "campaign.stage_pin", campaign["id"], {"stage": "generate"}, campaign["version"],
                      origin={"thread_id": "thread_main_demo", "message_id": "message_1", "actor": "researcher"})
    assert receipt["origin"] == {"schema_version": 1, "thread_id": "thread_main_demo", "message_id": "message_1", "actor": "researcher", "agent_id": None, "run_id": None, "rationale": None}
    saved = client.get(f"/api/v1/commands/{receipt['id']}").json()
    assert saved["origin"]["thread_id"] == "thread_main_demo"


def test_a_command_pinned_to_an_older_thread_revision_is_refused(client, campaign, workspace):
    thread = workspace.store.get("thread_main_demo", "thread")
    assert thread["guidance_revision"] == 0
    workspace.memory.bump_thread("thread_main_demo")
    response = client.post("/api/v1/commands", json={"id": "ui_thread_stale", "campaign_id": campaign["id"], "operation": "campaign.stage_pin",
        "expected_revision": campaign["version"], "expected_thread_revision": 0, "origin": {"thread_id": "thread_main_demo"}, "payload": {"stage": "report"}})
    assert response.status_code == 409 and "wrote in this conversation" in response.json()["detail"]
    ok = command(client, "campaign.stage_pin", campaign["id"], {"stage": "report"}, campaign["version"], expected_thread_revision=1, origin={"thread_id": "thread_main_demo"})
    assert ok["status"] == "completed"


def test_the_campaign_guidance_revision_still_moves_with_researcher_hypothesis_commands(client, campaign, workspace):
    before = workspace.memory.state(campaign["id"])["guidance_revision"]
    command(client, "hypothesis.create", campaign["id"], {"title": "Try restarts", "mechanism": "Restart from the best", "rationale": "cheap"}, campaign["version"])
    assert workspace.memory.state(campaign["id"])["guidance_revision"] == before + 1
    assert not [row for row in workspace.store.list("outbox", campaign["id"]) if row["kind"] == "manager_context_projection"]
