"""What waits in the inbox stays in front of the researcher until they acknowledge it; an item raised again or revised is
new again, and acknowledging is the researcher's alone (HTTP), never an agent's."""


def test_inbox_items_stay_unacknowledged_until_the_researcher_acknowledges_them(client, workspace, campaign):
    cid = campaign["id"]
    inbox = lambda: client.get(f"/api/v1/campaigns/{cid}/inbox").json()
    issue = workspace.memory.issue(cid, "evidence_capture_failed", "Catalog registration failed.\nThe masks stay in the run's files.", affected="trial_x")
    [item] = inbox()["unacknowledged"]
    assert item["key"] == f"{issue['id']}:{issue['revision']}" and item["kind"] == "issue" and item["title"] == "Catalog registration failed."
    after = client.post(f"/api/v1/campaigns/{cid}/inbox/acknowledge", json={"keys": [item["key"]]}).json()
    assert after["unacknowledged"] == [] and [row["id"] for row in inbox()["issues"]] == [issue["id"]], "acknowledged is not resolved"
    # Raised again with a new message, the issue is new to the researcher again; the old acknowledgement is dropped.
    again = workspace.memory.issue(cid, "evidence_capture_failed", "A different failure.", affected="trial_x")
    [item] = inbox()["unacknowledged"]
    assert item["key"] == f"{again['id']}:{again['revision']}"
    client.post(f"/api/v1/campaigns/{cid}/inbox/acknowledge", json={"keys": [item["key"]]})
    assert workspace.store.get(f"inbox_seen_{cid}", "inbox_seen")["keys"] == [item["key"]]
    assert client.post(f"/api/v1/campaigns/{cid}/inbox/acknowledge", json={"keys": []}).status_code == 422
