def test_ui_events_are_stored_once_and_listed(client, campaign):
    workspace_id = client.get("/api/v1/workspace").json()["workspace_id"]
    batch = {"workspace_id": workspace_id, "events": [
        {"kind": "page.open", "at": "2026-10-19T10:00:00Z", "campaign_id": "demo", "thread_id": "thread_main_demo", "page": "monitor", "session": "s1", "data": {"page": "monitor"}},
        {"kind": "thread.fork", "at": "2026-10-19T10:01:00Z", "campaign_id": "demo", "thread_id": "thread_main_demo", "page": "hypotheses", "session": "s1", "data": {}}]}
    assert client.post("/api/v1/ui-events", json=batch).status_code == 202
    assert client.post("/api/v1/ui-events", json=batch).json() == {"recorded": 2}
    listed = client.get("/api/v1/ui-events", params={"campaign_id": "demo"}).json()
    assert listed["total"] == 2 and {row["kind"] for row in listed["events"]} == {"page.open", "thread.fork"}
    assert client.post("/api/v1/ui-events", json={**batch, "workspace_id": "workspace_other"}).status_code == 404
    assert client.post("/api/v1/ui-events", json={"workspace_id": workspace_id, "events": [{"kind": "page.open", "at": "t", "campaign_id": "ghost"}]}).status_code == 404
    assert client.post("/api/v1/ui-events", json={"workspace_id": workspace_id, "events": [{"kind": "Page Open", "at": "t"}]}).status_code == 422


def test_the_gate_summarizes_the_signals_of_a_milestone(client, campaign):
    workspace_id = client.get("/api/v1/workspace").json()["workspace_id"]
    events = [{"kind": kind, "at": f"2026-10-19T10:0{i}:00Z", "campaign_id": "demo", "thread_id": thread, "page": "evolution", "session": "s1", "data": data}
              for i, (kind, thread, data) in enumerate([("thread.fork", "thread_main_demo", {}), ("thread.switch", "thread_b_demo", {}), ("page.open", "thread_b_demo", {}),
                                                        ("intervention.send", "thread_main_demo", {"kind": "stop", "count": 2, "override": True}),
                                                        ("round.next_action", "thread_main_demo", {"seconds_since_round_end": 90}), ("note.ask", "thread_main_demo", {"tier": "quick", "escalated": True})])]
    client.post("/api/v1/ui-events", json={"workspace_id": workspace_id, "events": events})
    gate = client.get("/api/v1/ui-events/gate", params={"campaign_id": "demo", "milestone": "M2"}).json()
    assert gate["focus"] == ["interventions", "rounds"]
    signals = gate["signals"]
    assert signals["branching"]["forks_per_session"] == 1 and signals["branching"]["share_of_page_opens_outside_main"] == 1.0
    assert signals["interventions"] == {"total": 1, "by_kind": {"stop": 1}, "overrides": 1, "override_rate": 1.0, "question": "Which controls stay?"}
    assert signals["rounds"]["median_seconds_to_next_action"] == 90
    assert signals["note"]["asks_by_tier"] == {"quick": 1} and signals["note"]["escalations"] == 1
    assert client.get("/api/v1/ui-events/gate", params={"milestone": "M9"}).status_code == 422
