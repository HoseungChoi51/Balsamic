from support import QUADRATIC, command


def test_the_app_answers_health_and_workspace_and_has_no_legacy_routes(client):
    assert client.get("/api/health").json()["service"] == "balsamic"
    info = client.get("/api/v1/workspace").json()
    assert info["workspace_id"].startswith("workspace_") and info["max_workers"] == 2
    assert client.get("/api/state").status_code == 404
    assert client.get("/api/v1/state").status_code == 404
    assert client.post("/api/campaigns", json={"name": "x"}).status_code in {404, 405}
    assert client.get("/api/campaigns/demo/discovery").status_code == 404


def test_a_campaign_without_tasks_starts_in_its_formulation_stage(client):
    receipt = command(client, "campaign.create", "fresh", {"name": "Fresh", "objective": "A vague question"}, 0)
    campaign = receipt["outcome"]["campaign"]
    assert campaign["formulating"] is True and campaign["active_study_id"] is None
    rows = client.get("/api/v1/campaigns").json()["campaigns"]
    assert rows[0]["stage"] == "formulate" and rows[0]["active_thread_id"] == "thread_main_fresh"
    summary = client.get("/api/v1/campaigns/fresh/summary").json()
    assert summary["tasks"] == [] and summary["stage"]["stage"] == "formulate" and summary["counts"]["thread"] == 1


def test_a_campaign_with_a_problem_instance_is_generating_and_can_be_pinned(client, campaign):
    rows = client.get("/api/v1/campaigns").json()["campaigns"]
    assert rows[0]["stage"] == "generate" and rows[0]["stage_pinned"] is False
    command(client, "campaign.stage_pin", campaign["id"], {"stage": "report", "reason": "writing up early"}, campaign["version"])
    row = client.get("/api/v1/campaigns").json()["campaigns"][0]
    assert row["stage"] == "report" and row["stage_pinned"] is True and row["stage_basis"] == "writing up early"
    command(client, "campaign.stage_pin", campaign["id"], {"stage": None}, campaign["version"])
    assert client.get("/api/v1/campaigns").json()["campaigns"][0]["stage"] == "generate"


def test_a_stale_workspace_header_is_refused_before_anything_runs(client, campaign):
    body = {"id": "ui_stale", "campaign_id": campaign["id"], "operation": "campaign.stage_pin", "expected_revision": campaign["version"], "payload": {"stage": "report"}}
    response = client.post("/api/v1/commands", json=body, headers={"X-Workspace-Id": "workspace_other"})
    assert response.status_code == 412
    assert client.get("/api/v1/commands/ui_stale").status_code == 404


def test_page_reads_answer_on_a_fresh_campaign(client, campaign):
    cid = campaign["id"]
    for path in (f"/api/v1/campaigns/{cid}/summary", f"/api/v1/campaigns/{cid}/experiments", f"/api/v1/campaigns/{cid}/hypotheses", f"/api/v1/campaigns/{cid}/inbox",
                 f"/api/v1/campaigns/{cid}/monitor", f"/api/v1/campaigns/{cid}/files", f"/api/v1/campaigns/{cid}/threads", f"/api/v1/campaigns/{cid}/agents",
                 f"/api/v1/campaigns/{cid}/guidance", "/api/v1/command-catalog", "/api/v1/problems"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
    monitor = client.get(f"/api/v1/campaigns/{cid}/monitor").json()
    assert monitor["pill"]["state"] == "clear" and monitor["rows"]["compute"]["limit"] == 2
    experiments = client.get(f"/api/v1/campaigns/{cid}/experiments").json()
    assert experiments["short"] == [] and experiments["rules"]["revision"] == 0
    assert "problem_id" in QUADRATIC
