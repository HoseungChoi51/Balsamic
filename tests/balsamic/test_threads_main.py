from optimization_framework.storage.sqlite import now


def test_every_campaign_has_a_main_thread_and_scoped_reads_answer_unchanged(client, campaign):
    listing = client.get("/api/v1/campaigns/demo/threads").json()
    assert listing["unchanged"] is False and listing["event_cursor"] > 0
    thread, = listing["threads"]
    assert thread["id"] == "thread_main_demo" and thread["name"] == "main" and thread["title"] == "Demo" and thread["status"] == "active"
    assert thread["message_count"] == 0 and thread["busy"] is False and listing["lead"] is None
    again = client.get("/api/v1/campaigns/demo/threads", params={"after": listing["event_cursor"]}).json()
    assert again == {"campaign_id": "demo", "event_cursor": listing["event_cursor"], "unchanged": True}
    assert client.get("/api/v1/threads/thread_main_demo").json()["campaign_id"] == "demo"
    assert client.get("/api/v1/threads/thread_other").status_code == 404
    assert client.get("/api/v1/campaigns/nope/threads").status_code == 404


def test_messages_follow_their_thread_and_lab_events_show_in_main(client, campaign, workspace):
    store = workspace.store
    store.put("message", {"id": "message_q1", "campaign_id": "demo", "role": "user", "origin": "researcher", "content": "Which coupling wins?", "created_at": now()}, "message.created")
    store.put("message", {"id": "message_a1", "campaign_id": "demo", "role": "assistant", "origin": "lead", "content": "Let me look.", "created_at": now(), "thread_id": "thread_main_demo"}, "message.created")
    store.put("message", {"id": "message_other", "campaign_id": "demo", "role": "user", "origin": "researcher", "content": "elsewhere", "created_at": now(), "thread_id": "thread_fork_demo"}, "message.created")
    workspace.memory.issue("demo", "operation_blocked", "A worker refused", affected="/api/v1/commands")
    body = client.get("/api/v1/threads/thread_main_demo/messages").json()
    ids = [message["id"] for message in body["messages"]]
    assert ids[:2] == ["message_q1", "message_a1"] and "message_other" not in ids
    assert body["messages"][-1]["origin"] == "lab_event" and body["messages"][-1]["content"] == "A worker refused"
    assert body["truncated"] is False and body["questions"] == []
    listing = client.get("/api/v1/campaigns/demo/threads").json()
    assert listing["threads"][0]["message_count"] == 3 and listing["threads"][0]["last_message_id"].startswith("message_issue_")
    before = client.get("/api/v1/threads/thread_main_demo/messages", params={"before": "message_a1", "limit": 5}).json()
    assert [m["id"] for m in before["messages"]] == ["message_q1"]


def test_a_desk_message_to_a_page_agent_stays_off_the_lead_thread(client, campaign, workspace):
    store = workspace.store
    store.put("message", {"id": "message_desk", "campaign_id": "demo", "role": "user", "origin": "researcher", "content": "Operator, hide trial 3", "created_at": now(), "desk": "experiment_operator"}, "message.created")
    body = client.get("/api/v1/threads/thread_main_demo/messages").json()
    assert body["messages"] == []
