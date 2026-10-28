"""Threads: branches of the lead's session; messages follow their branch; one branch runs the lead while the others wait."""
import pytest

from support import activate_team, command, finish_run, lead_run_for, submitted, tool_call

MAIN = "thread_main_demo"


@pytest.fixture
def team(client, workspace, campaign, monkeypatch):
    return activate_team(client, workspace, campaign, monkeypatch)


def say(client, campaign, text, thread_id=MAIN, **extra):
    receipt = command(client, "agent.message", campaign["id"], {"message": text, "thread_id": thread_id, **extra}, campaign["version"], origin={"thread_id": thread_id})
    return "pi_run_" + receipt["id"]


def test_thread_fork_and_messages_follow_the_branch_path(client, workspace, campaign, team):
    run1 = say(client, campaign, "Which coupling wins?")
    finish_run(workspace, run1, "Two candidates; see #hypotheses.", entry_ids={"parent": "e0", "last": "e2"})
    run2 = say(client, campaign, "Try the first.")
    finish_run(workspace, run2, "Started trial_1.", entry_ids={"parent": "e2", "last": "e4"})
    main = workspace.store.get(MAIN, "thread")
    assert main["agent_leaf"] == "e4"
    first_question = "message_" + run1.removeprefix("pi_run_")
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": first_question, "title": "Second coupling instead"}, campaign["version"])
    branch = fork["outcome"]["thread"]
    assert branch["parent_thread_id"] == MAIN and branch["fork_message_id"] == first_question
    assert branch["fork_entry_id"] == "e2", "the branch starts at the lead's reply to the forked message"
    assert branch["guidance_revision"] == main["guidance_revision"] and branch["agent_leaf"] is None
    # The branch's first turn branches the session at that entry; its reply moves the branch's leaf only.
    run3 = say(client, campaign, "Try the second instead.", branch["id"])
    queued = workspace.store.get(run3, "agent_run")
    assert queued["branch_from_entry_id"] == "e2" and queued["leaf_entry_id"] is None and queued["origin"]["thread_id"] == branch["id"]
    finish_run(workspace, run3, "Started trial_2 on the branch.", entry_ids={"parent": "e2", "last": "e6"})
    assert workspace.store.get(branch["id"], "thread")["agent_leaf"] == "e6"
    assert workspace.store.get(MAIN, "thread")["agent_leaf"] == "e4"
    body = client.get(f"/api/v1/threads/{branch['id']}/messages").json()
    assert [m["content"] for m in body["messages"]] == ["Try the second instead.", "Started trial_2 on the branch."]
    assert body["inherited"] == [{"thread_id": MAIN, "title": "Demo", "count": 2, "from": first_question, "to": "message_" + run1}]
    assert [m["content"] for m in body["inherited_messages"]] == ["Which coupling wins?", "Two candidates; see #hypotheses."]
    assert body["parent_path"] == [{"thread_id": MAIN, "title": "Demo", "fork_message_id": first_question}]
    main_body = client.get(f"/api/v1/threads/{MAIN}/messages").json()
    assert len(main_body["messages"]) == 4 and main_body["inherited"] == []
    listing = client.get("/api/v1/campaigns/demo/threads").json()
    assert {t["id"]: t["message_count"] for t in listing["threads"]} == {MAIN: 4, branch["id"]: 2}
    assert workspace.store.get("message_" + run3, "message")["entry_id"] == "e6"


def test_edit_and_resend_forks_instead_of_overwriting(client, workspace, campaign, team):
    run1 = say(client, campaign, "Compare the two at 60 s.")
    finish_run(workspace, run1, "Done.", entry_ids={"parent": "e0", "last": "e2"})
    original = "message_" + run1.removeprefix("pi_run_")
    # The researcher edits the question: a branch starts before the edited message and carries the new wording.
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": original, "title": "edited"}, campaign["version"])["outcome"]["thread"]
    run2 = say(client, campaign, "Compare the two at 600 s.", fork["id"], edit_of_message_id=original)
    edited = workspace.store.get("message_" + run2.removeprefix("pi_run_"), "message")
    assert edited["edited_from_message_id"] == original and edited["thread_id"] == fork["id"]
    assert workspace.store.get(original, "message")["content"] == "Compare the two at 60 s."
    assert workspace.store.get(original, "message").get("thread_id") == MAIN
    assert workspace.store.get(run2, "agent_run")["branch_from_entry_id"] == "e2"


def test_one_branch_runs_the_lead_and_the_others_wait_in_the_queue(client, workspace, campaign, team):
    run1 = say(client, campaign, "Start with a baseline.")
    submitted(workspace, run1)
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_")}, campaign["version"])["outcome"]["thread"]
    run2 = say(client, campaign, "Meanwhile, what about CMA-ES?", fork["id"])
    listing = client.get("/api/v1/campaigns/demo/threads").json()
    rows = {t["id"]: t for t in listing["threads"]}
    assert rows[MAIN]["busy"] is True and rows[MAIN]["queued"] == 0
    assert rows[fork["id"]]["busy"] is False and rows[fork["id"]]["queued"] == 1
    assert listing["active_run"] == {"id": run1, "thread_id": MAIN}
    assert workspace.store.get(run2, "agent_run")["status"] == "queued"


def test_a_message_in_one_thread_does_not_stale_commands_of_another(client, workspace, campaign, team):
    run1 = say(client, campaign, "Record a hypothesis when ready.")
    run = submitted(workspace, run1)
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_")}, campaign["version"])["outcome"]["thread"]
    say(client, campaign, "Something else, elsewhere.", fork["id"])
    # The lead's command from the main-thread run is still good: the other thread's message did not stale it.
    receipt = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "h1",
                        "payload": {"title": "Restarts", "mechanism": "restart from the best", "rationale": "cheap"}})
    assert receipt["status"] == "completed" and receipt["origin"]["thread_id"] == MAIN
    # A message in the run's own thread does.
    say(client, campaign, "Wait, change of plan.")
    refused = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "h2",
                        "payload": {"title": "Another", "mechanism": "m", "rationale": "r"}}, call_id="call2")
    assert refused["executed"] is False and "wrote in this conversation" in refused["error"]


def test_lead_commands_pin_guidance_from_their_run_and_ignore_a_stated_revision(client, workspace, campaign, team):
    run = submitted(workspace, say(client, campaign, "Go."))
    receipt = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "k",
                        "payload": {"title": "T", "mechanism": "m", "rationale": "r"}})
    saved = workspace.store.get(receipt["id"], "work_command")
    assert saved["request"]["expected_guidance_revision"] == workspace.store.get(run["id"], "agent_run")["guidance_revision"]
    # A guidance revision the lead states itself is ignored (it is accepted for saved sessions, harness plan D7): the run's is used.
    stated = tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": "k2", "guidance_revision": 99,
                       "payload": {"title": "T2", "mechanism": "m", "rationale": "r"}}, call_id="stated")
    assert "error" not in stated and workspace.store.get(stated["id"], "work_command")["request"]["expected_guidance_revision"] == saved["request"]["expected_guidance_revision"]
    assert saved["request"]["expected_thread_revision"] == workspace.store.get(MAIN, "thread")["guidance_revision"]
    assert saved["origin"] == {"schema_version": 1, "thread_id": MAIN, "message_id": "message_" + run["id"].removeprefix("pi_run_"), "actor": "lead",
                               "agent_id": team["id"], "run_id": run["id"], "rationale": None}
    assert receipt["page"] == "#hypotheses/" + receipt["outcome"]["hypothesis_id"] and receipt["link"] == receipt["page"]


def test_park_writes_a_summary_or_an_activity_strip_without_a_provider(client, workspace, campaign, team):
    run1 = say(client, campaign, "Explore restarts.")
    finish_run(workspace, run1, "Restarts explored; nothing conclusive.", entry_ids={"parent": "e0", "last": "e2"})
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_")}, campaign["version"])["outcome"]["thread"]
    run2 = say(client, campaign, "Try annealing here.", fork["id"])
    finish_run(workspace, run2, "Annealing is slower.", entry_ids={"parent": "e2", "last": "e4"})
    parked = command(client, "thread.park", campaign["id"], {"thread_id": fork["id"]}, campaign["version"])["outcome"]
    assert parked["summary"]["written_by"] == "activity_only" and "1 message from you, 1 from the lead" in parked["summary"]["text"]
    assert [g["glyph"] for g in parked["summary"]["strip"]] == ["message", "message"]
    thread = workspace.store.get(fork["id"], "thread")
    assert thread["status"] == "parked" and thread["summary"]["as_of_message_id"] == "message_" + run2
    command(client, "thread.park", campaign["id"], {"thread_id": MAIN}, campaign["version"], expect=409)
    assert command(client, "thread.unpark", campaign["id"], {"thread_id": fork["id"]}, campaign["version"])["outcome"]["thread_id"] == fork["id"]
    command(client, "thread.rename", campaign["id"], {"thread_id": fork["id"], "title": "Annealing"}, campaign["version"])
    assert workspace.store.get(fork["id"], "thread")["title"] == "Annealing"


def test_context_layers_report_sizes_and_pins(client, workspace, campaign, team):
    run = submitted(workspace, say(client, campaign, "Keep the task in mind."))
    task = workspace.store.list("task", "demo")[0]
    pinned = tool_call(workspace, team, run, "thread_pin", {"record_id": task["id"]})
    assert pinned["pinned_ids"] == [task["id"]]
    command(client, "thread.pin", campaign["id"], {"thread_id": MAIN, "record_id": campaign["id"], "excluded": True}, campaign["version"])
    view = client.get(f"/api/v1/threads/{MAIN}/context").json()
    layers = view["layers"]
    assert {item["kind"] for item in layers["project"]["items"]} >= {"campaign", "task", "guidance"} and layers["project"]["bytes"] > 0
    assert layers["branch"]["measured"] is False and layers["branch"]["entries_since_fork"] == 1
    assert [(item["id"], item["excluded"]) for item in layers["live"]["items"]] == [(task["id"], False), ("demo", True)]
    assert view["pinned_ids"] == [task["id"]] and view["excluded_ids"] == ["demo"]


def test_lab_events_reach_every_active_thread(client, workspace, campaign, team):
    run1 = say(client, campaign, "Start.")
    finish_run(workspace, run1, "Ok.", entry_ids={"parent": "e0", "last": "e2"})
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_")}, campaign["version"])["outcome"]["thread"]
    parked = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_")}, campaign["version"])["outcome"]["thread"]
    command(client, "thread.park", campaign["id"], {"thread_id": parked["id"]}, campaign["version"])
    command(client, "hypothesis.create", campaign["id"], {"title": "From main", "mechanism": "m", "rationale": "r"}, campaign["version"], origin={"thread_id": MAIN})
    branch_messages = client.get(f"/api/v1/threads/{fork['id']}/messages").json()["messages"]
    assert len(branch_messages) == 1 and branch_messages[0]["origin"] == "lab_event"
    assert "You ran hypothesis.create on hypothesis_" in branch_messages[0]["content"] and 'in the branch "Demo"' in branch_messages[0]["content"]
    assert client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"][-1]["origin"] != "lab_event"
    assert client.get(f"/api/v1/threads/{parked['id']}/messages").json()["messages"] == []
    tools_view = tool_call(workspace, team, submitted(workspace, say(client, campaign, "What happened?", fork["id"])), "lab_events", {})
    assert len(tools_view["events"]) == 1


def test_placeholders_resolve_when_hypotheses_land(client, workspace, campaign, team):
    receipt = command(client, "research.generate", campaign["id"], {"operation": "diversify", "count": 2, "note": "cheap ones"}, campaign["version"], origin={"thread_id": MAIN})
    outcome = receipt["outcome"]
    assert len(outcome["placeholders"]) == 2 and outcome["run_id"] == "pi_run_" + receipt["id"]
    body = client.get(f"/api/v1/threads/{MAIN}/messages").json()
    assert body["messages"][-1]["refs"] == outcome["placeholders"] and len(body["placeholders"]) == 2
    run = submitted(workspace, outcome["run_id"])
    assert run["origin"]["batch_id"] == outcome["batch_id"]
    for key in ("a", "b"):
        tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.create", "request_key": key, "payload": {"title": key, "mechanism": "m", "rationale": "r"}}, call_id=key)
    rows = [row for row in workspace.store.list("placeholder", "demo") if row["batch_id"] == outcome["batch_id"]]
    assert [row["status"] for row in rows] == ["resolved", "resolved"] and all(row["hypothesis_id"] for row in rows)
    assert client.get(f"/api/v1/threads/{MAIN}/messages").json()["placeholders"] == []


def test_merge_posts_one_turn_and_parks_the_source(client, workspace, campaign, team):
    run1 = say(client, campaign, "Start.")
    finish_run(workspace, run1, "Ok.", entry_ids={"parent": "e0", "last": "e2"})
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": "message_" + run1.removeprefix("pi_run_"), "title": "Side quest"}, campaign["version"])["outcome"]["thread"]
    run2 = say(client, campaign, "Try annealing.", fork["id"])
    finish_run(workspace, run2, "Annealing loses.", entry_ids={"parent": "e2", "last": "e5"})
    before = workspace.store.get(MAIN, "thread")["guidance_revision"]
    merged = command(client, "thread.merge", campaign["id"], {"thread_id": fork["id"], "into_thread_id": MAIN, "note": "Annealing loses; drop it."}, campaign["version"])["outcome"]
    source = workspace.store.get(fork["id"], "thread")
    assert source["status"] == "merged" and source["merged_into"] == MAIN and source["summary"]["written_by"] == "activity_only"
    target = workspace.store.get(MAIN, "thread")
    assert target["guidance_revision"] == before + 1
    main_messages = client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"]
    assert main_messages[-1]["merge_of_thread_id"] == fork["id"] and main_messages[-1]["content"] == "Annealing loses; drop it."
    run = workspace.store.get(merged["run_id"], "agent_run")
    assert run["origin"]["thread_id"] == MAIN and run["leaf_entry_id"] == "e2" and "Side quest" in run["input"]
    command(client, "agent.message", campaign["id"], {"message": "more", "thread_id": fork["id"]}, campaign["version"], expect=409)


def test_branch_titles_fit_the_switcher(client, workspace, campaign, team):
    from balsamic.threads.service import TITLE_LIMIT, branch_title
    long = ("Let's think about whether the coupling efficiency can be pushed above 0.8 with a two-layer grating "
            "while the fabrication constraint on the minimum feature size stays at 80 nm, and what that costs")
    assert branch_title(long).endswith("…") and len(branch_title(long)) <= TITLE_LIMIT + 1
    assert branch_title("/fork  Second coupling. Then more words that are not needed") == "Second coupling."
    assert branch_title("**Bold** _start_ of a `line`\nsecond line") == "Bold start of a line"
    assert branch_title("") == "Branch" and branch_title(None) == "Branch"
    run1 = say(client, campaign, long)
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"})
    question = "message_" + run1.removeprefix("pi_run_")
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": question}, campaign["version"])
    branch = fork["outcome"]["thread"]
    assert len(branch["title"]) <= TITLE_LIMIT + 1 and branch["name"] == branch["title"]
    version = lambda: workspace.store.get(campaign["id"], "campaign")["version"]
    explicit = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": question, "title": long}, version())
    assert len(explicit["outcome"]["thread"]["title"]) <= TITLE_LIMIT + 1
    command(client, "thread.rename", campaign["id"], {"thread_id": branch["id"], "title": long}, version())
    assert len(workspace.store.get(branch["id"], "thread")["title"]) <= TITLE_LIMIT + 1


def test_agents_talk_in_a_side_thread_linked_from_the_request(client, workspace, campaign, team):
    from support import submitted, tool_call
    run_id = say(client, campaign, "Let agents review the proposals.")
    run = submitted(workspace, run_id)
    delegated = tool_call(workspace, team, run, "delegate", {"role": "literature_specialist", "objective": "Find the literature on the five proposals.", "request_key": "review-1"}, call_id="c1")
    child = workspace.store.get(delegated["agent_id"], "agent_session")
    assert child["assignment_origin"] == {"thread_id": MAIN, "message_id": "message_" + run_id.removeprefix("pi_run_"), "run_id": run_id}
    finish_run(workspace, delegated["run_id"], "Found sources on all five.", entry_ids={"parent": "x0", "last": "x1"}, disposition="complete")
    listing = client.get(f"/api/v1/campaigns/{campaign['id']}/threads").json()["threads"]
    side = next(t for t in listing if t.get("kind") == "agents")
    assert side["parent_thread_id"] == MAIN and side["root_run_id"] == run_id and side["title_pending"] and side["title"] == "Let agents review the proposals."
    side_messages = client.get(f"/api/v1/threads/{side['id']}/messages").json()["messages"]
    assert [(m["origin"], m["agent_role"], m["content"]) for m in side_messages] == [("page_agent", "literature_specialist", "Found sources on all five.")]
    main_messages = client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"]
    link = [m for m in main_messages if m.get("kind") == "agents_link"]
    assert len(link) == 1 and link[0]["link_thread_id"] == side["id"] and link[0]["origin"] == "lab_event"
    assert side["participant_roles"] == ["literature_specialist"] and "link_page" not in link[0]
    assert not [m for m in main_messages if m.get("origin") == "page_agent"], "no agent's reply leaks into the researcher's thread"
    # The lead's request to a page agent and the agents' further assistants join the same side conversation.
    asked = tool_call(workspace, team, run, "page_agent_message", {"page_agent": "discussion_moderator", "message": "Run a review round."}, call_id="c2")
    moderator = workspace.store.get(asked["agent_id"], "agent_session")
    assert moderator["assignment_origin"]["run_id"] == run_id
    sub = submitted(workspace, asked["run_id"])
    grand = tool_call(workspace, moderator, sub, "delegate", {"role": "methodology_specialist", "objective": "Assess methods.", "request_key": "m-1"}, call_id="c3")
    finish_run(workspace, grand["run_id"], "Methods assessed.", entry_ids={"parent": "y0", "last": "y1"}, disposition="complete")
    finish_run(workspace, asked["run_id"], "Round complete.", entry_ids={"parent": "z0", "last": "z1"}, disposition="complete")
    side_messages = client.get(f"/api/v1/threads/{side['id']}/messages").json()["messages"]
    assert [m["content"] for m in side_messages] == ["Found sources on all five.", "Run a review round.", "Methods assessed.", "Round complete."]
    assert [m.get("agent_role") for m in side_messages] == ["literature_specialist", "lead", "methodology_specialist", "discussion_moderator"]
    assert len([m for m in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"] if m.get("kind") == "agents_link"]) == 1
    # The lead's reply to the researcher stays in the main thread.
    finish_run(workspace, run_id, "The review is done; see the side conversation.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    assert client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"][-1]["content"] == "The review is done; see the side conversation."


def test_a_side_conversation_with_implementation_work_links_to_the_implementations_page(client, workspace, campaign, team):
    from support import submitted, tool_call
    run_id = say(client, campaign, "Implement the four algorithms.")
    run = submitted(workspace, run_id)
    asked = tool_call(workspace, team, run, "page_agent_message", {"page_agent": "implementation_lead", "message": "Build the library."}, call_id="c1")
    finish_run(workspace, asked["run_id"], "Opened a coding workspace.", entry_ids={"parent": "a0", "last": "a1"}, disposition="complete")
    side = next(t for t in client.get(f"/api/v1/campaigns/{campaign['id']}/threads").json()["threads"] if t.get("kind") == "agents")
    assert "implementation_lead" in side["participant_roles"]
    link = next(m for m in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"] if m.get("kind") == "agents_link")
    assert link["link_page"] == "hypotheses/implementations"


def test_a_notice_continues_its_request_and_the_side_conversation_closes_when_the_work_ends(client, workspace, campaign, team):
    from datetime import datetime, timedelta, timezone
    from balsamic.threads import closing
    from optimization_framework.contracts.base import content_hash
    cid = campaign["id"]
    run_id = say(client, campaign, "Let agents review the proposals.")
    run = submitted(workspace, run_id)
    first = tool_call(workspace, team, run, "delegate", {"role": "literature_specialist", "objective": "Find the literature on the five proposals.", "request_key": "r-1"}, call_id="c1")
    finish_run(workspace, run_id, "Reviewers are on it.", entry_ids={"parent": "e0", "last": "e1"}, disposition="waiting")
    finish_run(workspace, first["run_id"], "Verdicts recorded.", entry_ids={"parent": "x0", "last": "x1"}, disposition="complete")
    # The lead's notice that its assistant finished continues the researcher's request: what it starts joins the same side conversation.
    notice = submitted(workspace, "pi_child_result_" + content_hash(first["run_id"])[:28])
    assert notice["origin"]["root"]["run_id"] == run_id and notice["origin"]["thread_id"] == MAIN
    second = tool_call(workspace, team, notice, "delegate", {"role": "literature_specialist", "objective": "Find the literature on the revisions.", "request_key": "r-2"}, call_id="c2")
    assert workspace.store.get(second["agent_id"], "agent_session")["assignment_origin"]["run_id"] == run_id
    finish_run(workspace, second["run_id"], "Revisions reviewed.", entry_ids={"parent": "y0", "last": "y1"}, disposition="complete")
    [side] = [t for t in client.get(f"/api/v1/campaigns/{cid}/threads").json()["threads"] if t.get("kind") == "agents"]
    # Lab events go to the researcher's threads only: the side conversation records its own request's work.
    command(client, "hypothesis.create", cid, {"title": "From main", "mechanism": "m", "rationale": "r"}, campaign["version"], origin={"thread_id": MAIN})
    assert [m["content"] for m in client.get(f"/api/v1/threads/{side['id']}/messages").json()["messages"]] == ["Verdicts recorded.", "Revisions reviewed."]

    later = datetime.now(timezone.utc) + timedelta(seconds=closing.QUIET_SECONDS + 1)
    assert closing.check(workspace, cid, later)["closed"] == []   # the lead's turns on the request are still to run
    finish_run(workspace, notice["id"], "Both reviews are in.", entry_ids={"parent": "e1", "last": "e2"}, disposition="complete")
    finish_run(workspace, "pi_child_result_" + content_hash(second["run_id"])[:28], "Nothing more to add.", entry_ids={"parent": "e2", "last": "e3"}, disposition="complete")
    assert closing.check(workspace, cid)["closed"] == []   # quiet for less than QUIET_SECONDS
    assert closing.check(workspace, cid, later)["closed"] == [side["id"]]
    closed = workspace.store.get(side["id"], "thread")
    assert closed["status"] == "closed" and closed["summary"]["text"].startswith("2 messages between the agents.") and closed["summary"]["reason"] == "closed"

    # Work on the request resumes (a later notice continues it): the conversation opens again.
    workspace.pi.enqueue(team, "pi_events_resumed", "An event for the request.", root=notice["origin"]["root"])
    assert closing.check(workspace, cid, later)["reopened"] == [side["id"]]
    assert workspace.store.get(side["id"], "thread")["status"] == "active" and workspace.store.get(side["id"], "thread")["summary"]["stale"]


def test_a_desk_request_is_answered_on_the_desk_and_read_there(client, workspace, campaign, team):
    from support import submitted, tool_call
    # The lead asks the moderator first (a side conversation), then the researcher writes on the desk.
    run = submitted(workspace, say(client, campaign, "Review the proposals."))
    asked = tool_call(workspace, team, run, "page_agent_message", {"page_agent": "discussion_moderator", "message": "Run a review round."}, call_id="d1")
    finish_run(workspace, asked["run_id"], "Round complete.", entry_ids={"parent": "z0", "last": "z1"}, disposition="complete")
    version = lambda: workspace.store.get(campaign["id"], "campaign")["version"]
    receipt = command(client, "agent.message", campaign["id"], {"message": "Which proposal looked weakest?", "page_agent": "discussion_moderator"}, version())
    finish_run(workspace, "pi_run_" + receipt["id"], "The third: its mechanism is underspecified.", entry_ids={"parent": "z1", "last": "z2"}, disposition="complete")
    desk = client.get(f"/api/v1/campaigns/{campaign['id']}/desks/discussion_moderator").json()
    assert desk["agent"]["role"] == "discussion_moderator" and desk["page"] == "#hypotheses"
    assert [(m["role"], m["content"]) for m in desk["messages"]] == [("user", "Which proposal looked weakest?"), ("assistant", "The third: its mechanism is underspecified.")]
    side = next(t for t in client.get(f"/api/v1/campaigns/{campaign['id']}/threads").json()["threads"] if t.get("kind") == "agents")
    assert [m["content"] for m in client.get(f"/api/v1/threads/{side['id']}/messages").json()["messages"]] == ["Run a review round.", "Round complete."]
    assert not [m for m in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"] if m.get("desk")]
    assert client.get(f"/api/v1/campaigns/{campaign['id']}/desks/nobody").status_code == 404


def test_a_page_agent_asked_from_the_chat_answers_in_the_chat(client, workspace, campaign, team):
    """/plan asks the resource planner from the chat: its answer showed only on the Resources page, and the chat that asked
    looked unanswered. The lead's branch of the thread stays where the lead's own turn left it."""
    first = say(client, campaign, "Hello.")
    finish_run(workspace, first, "Hello.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    asked = say(client, campaign, "Plan how this campaign uses the machine within the resource level, and report the plan.", page_agent="resource_planner")
    finish_run(workspace, asked, "Two runs at once; no per-kind caps yet.", entry_ids={"parent": "p0", "last": "p1"}, disposition="complete")
    chat = [(m["role"], m["content"]) for m in client.get(f"/api/v1/threads/{MAIN}/messages").json()["messages"]]
    assert chat[-2:] == [("user", "Plan how this campaign uses the machine within the resource level, and report the plan."),
                         ("assistant", "Two runs at once; no per-kind caps yet.")]
    # The desk keeps the requests made on the page.
    assert client.get(f"/api/v1/campaigns/{campaign['id']}/desks/resource_planner").json()["messages"] == []
    assert workspace.store.get(MAIN, "thread")["agent_leaf"] == "e2", "the planner's session is not the lead's"
