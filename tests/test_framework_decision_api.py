"""The public inbox explains expired execution authority before a user approves."""
from copy import deepcopy

from fastapi.testclient import TestClient

from balsamic.app import create_app
from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate, TaskInput, TrialInput
from optimization_framework.storage.sqlite import now


def expired_inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name="Decision expiry", autonomy="delegated",
        tasks=[TaskInput(name="Development", problem_id="bounded_continuous")]))
    task = workspace.current_tasks(campaign["id"])[0]
    trial = workspace.create_trial(TrialInput(campaign_id=campaign["id"], task_id=task["id"], algorithm="coordinate", max_steps=2, wall_seconds=5))
    # An executable request made under the first charter: extending a trial spends budget under researcher authority.
    decision = {"id": "old_decision", "campaign_id": campaign["id"], "trial_id": trial["id"], "incremental_solver_calls": 40,
        "estimated_seconds": 30, "title": "Extend the older allocation?", "question": "Extend the older allocation?",
        "context": "Preserve this original reasoning.", "rationale": "Earlier assumptions",
        "charter_version": campaign["version"], "guidance_revision": workspace.memory.state(campaign["id"])["guidance_revision"],
        "status": "pending", "created_at": now(), "audience": "researcher",
        "options": [{"id": "0", "label": "Extend by 30 s", "description": "Runs under your authority."},
                    {"id": "1", "label": "Keep the current allocation", "description": "The trial is unchanged."}],
        "recommendation": "0"}
    workspace.store.put("decision", decision)
    campaign = workspace.update_campaign(campaign["id"], CampaignUpdate(objective="Use the new study scope."))
    return app, workspace, campaign, trial, decision


def test_http_inbox_exposes_expiry_without_rewriting_original_authority(tmp_path, monkeypatch):
    app, workspace, campaign, trial, decision = expired_inbox(tmp_path, monkeypatch)
    original = deepcopy(decision)
    with TestClient(app) as client:
        response = client.get(f"/api/v1/campaigns/{campaign['id']}/inbox")
        assert response.status_code == 200
        view = next(row for row in response.json()["decisions"] if row["id"] == decision["id"])
        assert view["freshness"]["stale"] is True
        assert view["freshness"]["can_accept"] is False
        assert view["freshness"]["can_refresh"] is True
        assert view["freshness"]["blocked_choice_ids"] == ["0"]
        assert view["freshness"]["proposal_charter_version"] == 1
        assert view["freshness"]["current_charter_version"] == 2
        assert view["freshness"]["reason"]
    assert workspace.store.get(decision["id"], "decision") == original
    assert workspace.store.get(trial["id"], "trial")["wall_seconds"] == trial["wall_seconds"]
