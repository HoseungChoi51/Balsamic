"""The quick path's screens on the service side (roadmap P5): each revision the lead writes that is read against the researcher's
words is put before them as a card in the conversation, which confirms it in one click; the note's view says what that click waits
on, in the confirmation's own words; and the confirmation waits while the lead revises the charter on what they sent it."""
from support import command, finish_run, submitted
from test_quick_charter import GAP, MAIN, charter, formulating, team, turn, version, write  # noqa: F401  (the fixtures)
from test_quick_reading import BROKEN, DUE, confirm, note_of
from balsamic.notes import service


def cards(workspace):
    return [message for message in workspace.store.list("message", "demo") if message.get("kind") == service.CARD]


def view(client):
    return client.get("/api/v1/campaigns/demo/problem-note").json()


def test_a_read_revision_is_put_before_the_researcher_as_one_card_per_turn_of_the_lead(client, workspace, team, turn):
    written = write(workspace, team, turn)
    [card] = cards(workspace)
    assert card["id"] == written["card"]
    assert {key: card[key] for key in ("role", "origin", "note_id", "charter_id", "charter_revision", "thread_id", "run_id")} == {
        "role": "assistant", "origin": "lab_event", "note_id": "note_demo", "charter_id": written["charter_id"], "charter_revision": 1,
        "thread_id": MAIN, "run_id": turn["id"]}
    assert "a card in the conversation, which confirms it in one click" in written["next"]
    # It is in the conversation the lead wrote in, after the researcher's words.
    listed = [message["id"] for message in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"]]
    assert listed[-1] == card["id"] and len(listed) == 2
    # Another write of the same turn moves that turn's card to its revision, where it stands in the conversation.
    again = write(workspace, team, turn, call="again", charter=charter(summary="Eight bakes in one oven, as little late as possible."))
    moved = workspace.store.get(card["id"], "message")
    assert again["card"] == card["id"] and moved["charter_revision"] == 2 and moved["created_at"] == card["created_at"] and len(cards(workspace)) == 1
    # A write with a blocking finding of the lead's is not read, so it has no card; the note's quick path moved past the card's.
    broken = write(workspace, team, turn, call="broken", charter=BROKEN)
    assert broken["card"] is None and len(cards(workspace)) == 1 and "card in the conversation" not in broken["next"]
    assert note_of(workspace)["quick"]["revision"] == broken["revision"] == 3
    # A later turn of the lead (on the researcher's request) has a card of its own; the earlier one stays, out of date.
    client.post(f"/api/v1/problem-charters/{written['charter_id']}/requests", json={"text": "Keep the eight bakes as they are."}).raise_for_status()
    run = next(run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == written["charter_id"])
    later = write(workspace, team, submitted(workspace, run["id"]), call="later")
    assert later["card"] not in {None, card["id"]} and [row["charter_revision"] for row in cards(workspace)] == [2, 4]
    assert workspace.store.get(later["card"], "message")["thread_id"] == MAIN


def test_a_write_the_quick_path_does_not_hold_for_has_no_card(client, workspace, team, turn):
    # The second reading cannot run: the quick path ends, and nothing is put before the researcher to confirm.
    workspace.pi.client.reply = RuntimeError("the model is down")
    written = write(workspace, team, turn)
    assert written["card"] is None and written["quick_path"]["holds"] is False and cards(workspace) == []
    assert view(client)["confirmation"] is None


def test_the_view_says_what_the_one_click_waits_on_in_the_confirmations_own_words(client, workspace, team, turn):
    asked = write(workspace, team, turn, questions=[GAP])
    waits = view(client)["confirmation"]
    assert (waits["revision"], waits["confirmed"]) == (asked["revision"], False)
    assert waits["why"] == confirm(client, workspace, asked, expect=409)["detail"] and waits["why"].startswith("Answer the lead's questions")
    # A difference the second reading found: the same words as the refusal.
    workspace.pi.client.reply = {"mismatches": [DUE]}
    found = write(workspace, team, turn, call="found")
    client.post(f"/api/v1/problem-charters/{found['charter_id']}/send-answers", json={"expected_revision": found["revision"]}).raise_for_status()
    run = next(run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == found["charter_id"])
    decided = write(workspace, team, submitted(workspace, run["id"]), call="decided", charter=charter(assumptions=[{"statement": "No pause between bakes."}]))
    waits = view(client)["confirmation"]
    assert waits["why"] == confirm(client, workspace, decided, expect=409)["detail"] and waits["why"].startswith("Settle each difference")
    # Settled: one click confirms it (accepting the assumption), and the view says it is confirmed.
    command(client, "problem_note.settle", "demo", {"note_id": "note_demo", "revision": decided["revision"], "mismatches": {"m1": "right"}}, version(workspace))
    assert view(client)["confirmation"] == {"revision": decided["revision"], "confirmed": False, "why": None}
    confirm(client, workspace, decided)
    assert view(client)["confirmation"] == {"revision": decided["revision"] + 1, "confirmed": True, "why": None}


def test_the_confirmation_waits_while_the_lead_revises_on_what_the_researcher_sent_it(client, workspace, team, turn):
    written = write(workspace, team, turn)
    # A request in words starts a turn of the lead on the charter: until the lead writes again, the click waits for that revision.
    client.post(f"/api/v1/problem-charters/{written['charter_id']}/requests", json={"text": "The oven needs five minutes between bakes."}).raise_for_status()
    detail = confirm(client, workspace, written, expect=409)["detail"]
    assert detail == service.REVISING == view(client)["confirmation"]["why"]
    run = next(run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == written["charter_id"])
    # The lead's next write is what the researcher confirms, though its turn is still running (its reply).
    revised = write(workspace, team, submitted(workspace, run["id"]), call="revised", charter=charter(summary="Eight bakes, five minutes apart."))
    assert view(client)["confirmation"]["why"] is None
    assert confirm(client, workspace, revised)["outcome"]["charter"]["revision"] == revised["revision"]


def test_a_turn_that_ends_without_writing_leaves_the_last_revision_to_confirm(client, workspace, team, turn):
    written = write(workspace, team, turn)
    client.post(f"/api/v1/problem-charters/{written['charter_id']}/requests", json={"text": "Is the order 0 to 7 right?"}).raise_for_status()
    run = next(run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == written["charter_id"])
    assert view(client)["confirmation"]["why"] == service.REVISING
    finish_run(workspace, run["id"], "Yes: the bakes are numbered 0 to 7 as you gave them. Nothing to change.")
    assert view(client)["confirmation"]["why"] is None
    assert confirm(client, workspace, written)["outcome"]["charter"]["revision"] == written["revision"]
