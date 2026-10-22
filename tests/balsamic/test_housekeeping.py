"""The housekeeper: the lightest model names branches and labels hypotheses on the maintenance tick."""
import pytest

from balsamic import housekeeping

from support import activate_team, command, finish_run

MAIN = "thread_main_demo"


def say(client, campaign, text, thread_id=MAIN, **extra):
    receipt = command(client, "agent.message", campaign["id"], {"message": text, "thread_id": thread_id, **extra}, campaign["version"], origin={"thread_id": thread_id})
    return "pi_run_" + receipt["id"]


@pytest.fixture
def team(client, workspace, campaign, monkeypatch):
    return activate_team(client, workspace, campaign, monkeypatch)


@pytest.fixture
def light_model(workspace, monkeypatch):
    """Model calls on, a housekeeper model, and a scripted harness completion that records what it was asked."""
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    calls = []
    monkeypatch.setattr(housekeeping, "model", lambda ws: {"provider": "centinels", "model": "clef-flash", "effort": None})

    def complete(call_id, body, timeout=60):
        calls.append({"id": call_id, **body})
        if body["label"] == "branch title":
            return {"text": "Title: \"Second coupling first.\"\n", "usage": {"cost_usd": 0.0001}}
        if body["label"] == "hypothesis label":
            return {"text": "Warm-start CMA-ES", "usage": {}}
        if body["label"] == "exchange title":
            return {"text": "Asked which coupling wins; the lead named two candidates.", "usage": {}}
        if body["label"] == "next suggestions":
            return {"text": '```json\n[{"label": "Try the first candidate", "text": "Run the first candidate as a short screening run."}, {"label": "Why two?", "text": "Why only two candidates, and what did you rule out?"}, {"label": "Three more strategies", "text": "/generate 3"}]\n```', "usage": {}}
        return {"text": "A branch about the second coupling; nothing concluded yet.", "usage": {}}
    monkeypatch.setattr(workspace.pi.client, "complete", complete)
    return calls


def test_a_forked_branch_is_named_by_the_housekeeper_on_the_tick(client, workspace, campaign, team, light_model):
    long = "Let's think about whether the coupling efficiency can be pushed above 0.8 with a two-layer grating while the feature size stays at 80 nm"
    run1 = say(client, campaign, long)
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    question = "message_" + run1.removeprefix("pi_run_")
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": question}, campaign["version"])
    branch = fork["outcome"]["thread"]
    assert branch["title_pending"] and branch["title_source"] == "message" and branch["title"].endswith("…")
    assert housekeeping.tick(workspace) == 2, "the branch title, and suggestions for the main thread after the lead's reply"
    named = workspace.store.get(branch["id"], "thread")
    assert named["title"] == "Second coupling first" and named["name"] == named["title"] and named["title_source"] == "housekeeper"
    assert not named["title_pending"] and named["housekeeping"]["title"]["status"] == "done" and named["housekeeping"]["title"]["model"] == "clef-flash"
    asked = [c for c in light_model if c["label"] == "branch title"]
    assert len(asked) == 1 and asked[0]["model"] == "clef-flash" and asked[0]["effort"] == "low" and long in asked[0]["prompt"] and "Two candidates." in asked[0]["prompt"]
    assert housekeeping.tick(workspace) == 0, "a named branch is not renamed again"
    assert any(e["kind"] == "thread.renamed" and e["data"].get("record_id") == branch["id"] for e in workspace.store.events(campaign["id"], limit=1000))


def test_an_explicit_title_is_the_researchers_and_is_kept(client, workspace, campaign, team, light_model):
    run1 = say(client, campaign, "Which coupling wins?")
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    question = "message_" + run1.removeprefix("pi_run_")
    fork = command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": question, "title": "Second coupling instead"}, campaign["version"])
    assert fork["outcome"]["thread"]["title_pending"] is False and fork["outcome"]["thread"]["title_source"] == "researcher"
    assert housekeeping.tick(workspace) == 1, "only the main thread's suggestions"
    assert not [c for c in light_model if c["label"] == "branch title"]


def test_hypotheses_get_short_labels_and_failures_stop_after_three_attempts(client, workspace, campaign, team, light_model, monkeypatch):
    created = command(client, "hypothesis.create", campaign["id"], {"title": "Covariance matrix adaptation with a warm start from the best screening run", "mechanism": "m", "rationale": "r"},
                      campaign["version"], origin={"thread_id": MAIN})["outcome"]["hypothesis"]
    assert housekeeping.tick(workspace) == 1
    labelled = workspace.store.get(created["id"], "hypothesis")
    assert labelled["short_title"] == "Warm-start CMA-ES"
    row = next(r for r in client.get(f"/api/v1/campaigns/{campaign['id']}/evolution").json()["nodes"] if r["id"] == created["id"])
    assert row["short_title"] == "Warm-start CMA-ES"
    layout = next(n for n in client.get(f"/api/v1/campaigns/{campaign['id']}/evolution").json()["layout"] if n["id"] == created["id"])
    assert layout["short_title"] == "Warm-start CMA-ES"
    # A model that keeps failing is asked three times, then left alone; the full title stands.
    def failing(call_id, body, timeout=60):
        raise OSError("harness away")
    monkeypatch.setattr(workspace.pi.client, "complete", failing)
    version = lambda: workspace.store.get(campaign["id"], "campaign")["version"]
    other = command(client, "hypothesis.create", campaign["id"], {"title": "Second", "mechanism": "m", "rationale": "r"}, version(), origin={"thread_id": MAIN})["outcome"]["hypothesis"]
    assert [housekeeping.tick(workspace) for _ in range(5)] == [1, 1, 1, 0, 0]
    spent = workspace.store.get(other["id"], "hypothesis")
    assert spent.get("short_title") is None and "harness away" in spent["housekeeping"]["label"]["error"]
    assert "harness away" in housekeeping.status(workspace)["last_error"]["text"]
    # An hour later the record is tried again (a key may have been fixed since).
    spent["housekeeping"]["label"]["at"] = "2026-10-20T00:00:00+00:00"
    workspace.store.put("hypothesis", spent)
    assert housekeeping.tick(workspace) == 1 and workspace.store.get(other["id"], "hypothesis")["housekeeping"]["label"]["attempts"] == 1


def test_nothing_runs_without_a_model_or_with_calls_off(client, workspace, campaign, team, monkeypatch):
    run1 = say(client, campaign, "Which coupling wins?")
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    question = "message_" + run1.removeprefix("pi_run_")
    command(client, "thread.fork", campaign["id"], {"thread_id": MAIN, "message_id": question}, campaign["version"])
    assert housekeeping.tick(workspace) == 0, "GRATING_LLM_DISABLED is set by the suite"
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setattr(housekeeping, "model", lambda ws: None)
    assert housekeeping.tick(workspace) == 0


def test_the_housekeeper_is_an_assignable_tier_role_on_the_fast_tier(client):
    view = client.get("/api/v1/model-tiers").json()
    assert "housekeeper" in view["assignable"] and view["roles"]["housekeeper"] == "fast"


def test_a_continuation_checkpoint_does_not_post_the_answer_twice(client, workspace, campaign, team):
    run1 = say(client, campaign, "Is the lead ready?")
    finish_run(workspace, run1, "Yes: running, no jobs pending.", entry_ids={"parent": "e0", "last": "e2"})
    nudges = [r for r in workspace.store.list("agent_run") if r["id"].startswith("pi_continue_")]
    assert len(nudges) == 1, "a turn without yield_work is asked for its checkpoint"
    # The lead answers the nudge as asked: yield_work(complete) with a report, and no further text.
    nudge = nudges[0]
    nudge["disposition"] = {"disposition": "complete", "summary": "answered", "report": "Yes, the lead is ready: running with no pending jobs."}
    workspace.store.put("agent_run", nudge)
    finish_run(workspace, nudge["id"], "", entry_ids={"parent": "e2", "last": "e3"})
    replies = [m for m in workspace.store.list("message", campaign["id"]) if m.get("role") == "assistant"]
    assert [m["content"] for m in replies] == ["Yes: running, no jobs pending."]
    assert workspace.store.get(MAIN, "thread")["agent_leaf"] == "e3", "the branch still ends where the checkpoint turn ended"


def test_the_lead_corrects_proposal_fields_and_the_page_says_when_the_lane_was_not_chosen(client, workspace, campaign, team):
    from support import submitted, tool_call

    def attempt(key, payload):
        try:
            return tool_call(workspace, team, run, "campaign_command", {"operation": "hypothesis.edit", "request_key": key, "payload": payload}, call_id=key)
        except ValueError as error:
            return {"error": str(error)}
    version = lambda: workspace.store.get(campaign["id"], "campaign")["version"]
    created = command(client, "hypothesis.create", campaign["id"], {"title": "Proportional rule", "mechanism": "m", "rationale": "r"}, version(), origin={"thread_id": MAIN})["outcome"]["hypothesis"]
    assert created["algorithm"] == "hillclimb" and created["algorithm_chosen"] is False
    chosen = command(client, "hypothesis.create", campaign["id"], {"title": "Annealed caps", "mechanism": "m", "rationale": "r", "algorithm": "annealing"}, version(), origin={"thread_id": MAIN})["outcome"]["hypothesis"]
    assert chosen["algorithm_chosen"] is True
    # The lead edits through its tool: the lane, the label and the title.
    run = submitted(workspace, say(client, campaign, "Fix the proposals."))
    receipt = attempt("fix-1", {"hypothesis_id": created["id"], "algorithm": "annealing", "short_title": "Proportional caps", "title": "Proportional rule with annealed caps", "reason": "the default lane was not a choice"})
    assert receipt["outcome"]["fields"] == ["algorithm", "short_title", "title"], receipt
    edited = workspace.store.get(created["id"], "hypothesis")
    assert edited["algorithm"] == "annealing" and edited["algorithm_chosen"] is True and edited["short_title"] == "Proportional caps"
    assert edited["edits"][-1]["fields"] == ["algorithm", "short_title", "title"] and edited["edits"][-1]["before"]["algorithm"] == "hillclimb"
    assert edited["housekeeping"]["label"]["status"] == "done", "a label the lead wrote is not overwritten by the housekeeper"
    page = client.get(f"/api/v1/campaigns/{campaign['id']}/hypotheses").json()
    row = next(h for h in page["hypotheses"] if h["id"] == created["id"])
    assert row["short_title"] == "Proportional caps" and row["algorithm_chosen"] is True
    # An unknown lane and an empty patch are refused; a lane bound to a trial is refused.
    assert "Unknown algorithm" in str(attempt("fix-2", {"hypothesis_id": created["id"], "algorithm": "no_such_lane"}))
    assert "Nothing to change" in str(attempt("fix-3", {"hypothesis_id": created["id"]}))
    workspace.store.put("trial", {"id": "trial_x", "campaign_id": campaign["id"], "hypothesis_id": created["id"], "status": "completed", "algorithm": "annealing", "created_at": "2026-10-20T00:00:00Z"})
    assert "bound to 1 trial" in str(attempt("fix-4", {"hypothesis_id": created["id"], "algorithm": "population"}))
    assert attempt("fix-5", {"hypothesis_id": created["id"], "rationale": "better stated"})["outcome"]["fields"] == ["rationale"]
    # What each field must say is a procedure the lead reads before recording proposals; its catalog names it.
    procedure = workspace.procedures.read("lead", "proposal-fields")["text"]
    assert "# Proposal fields" in procedure and "hypothesis.edit" in procedure and "not chosen" in procedure
    assert "proposal-fields" in workspace.procedures.catalog_text("lead")


def test_finished_exchanges_get_a_one_sentence_fold_title(client, workspace, campaign, team, light_model):
    run1 = say(client, campaign, "Which coupling wins?")
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    assert housekeeping.tick(workspace) == 1, "suggestions only: the last exchange is open until the researcher writes again"
    assert workspace.store.get("message_" + run1.removeprefix("pi_run_"), "message").get("fold_title") is None
    run2 = say(client, campaign, "Try the first.")
    assert housekeeping.tick(workspace) == 1
    first = workspace.store.get("message_" + run1.removeprefix("pi_run_"), "message")
    assert first["fold_title"] == "Asked which coupling wins; the lead named two candidates"
    asked = [c for c in light_model if c["label"] == "exchange title"]
    assert len(asked) == 1 and "Which coupling wins?" in asked[0]["prompt"] and "Two candidates." in asked[0]["prompt"]
    finish_run(workspace, run2, "Started trial_1.", entry_ids={"parent": "e2", "last": "e4"}, disposition="complete")
    assert housekeeping.tick(workspace) == 1, "suggestions for the new reply; the open exchange has no fold title"
    assert housekeeping.tick(workspace) == 0
    body = client.get(f"/api/v1/threads/{MAIN}/messages").json()
    assert [m.get("fold_title") for m in body["messages"] if m["role"] == "user"] == [first["fold_title"], None]


def test_live_suggestions_follow_the_leads_latest_reply(client, workspace, campaign, team, light_model):
    run1 = say(client, campaign, "Which coupling wins?")
    assert housekeeping.tick(workspace) == 0, "nothing to suggest while the researcher's message is the last one"
    finish_run(workspace, run1, "Two candidates.", entry_ids={"parent": "e0", "last": "e2"}, disposition="complete")
    assert housekeeping.tick(workspace) == 1
    main = workspace.store.get(MAIN, "thread")
    reply_id = "message_" + run1
    assert main["suggestions"]["as_of_message_id"] == reply_id and [s["label"] for s in main["suggestions"]["items"]] == ["Try the first candidate", "Why two?", "Three more strategies"]
    assert main["suggestions"]["items"][2]["text"] == "/generate 3"
    asked = [c for c in light_model if c["label"] == "next suggestions"]
    assert len(asked) == 1 and "Campaign stage:" in asked[0]["prompt"] and "Two candidates." in asked[0]["prompt"] and "/generate" in asked[0]["prompt"]
    assert housekeeping.tick(workspace) == 0, "suggested once per reply"
    listed = next(t for t in client.get(f"/api/v1/campaigns/{campaign['id']}/threads").json()["threads"] if t["id"] == MAIN)
    assert listed["suggestions"]["as_of_message_id"] == reply_id
    # The next reply brings fresh suggestions; the researcher's own message makes the old ones stale (the chat hides them).
    run2 = say(client, campaign, "Try the first.")
    assert housekeeping.tick(workspace) == 1, "the first exchange's fold title"
    assert housekeeping.tick(workspace) == 0
    finish_run(workspace, run2, "Started trial_1.", entry_ids={"parent": "e2", "last": "e4"}, disposition="complete")
    assert housekeeping.tick(workspace) == 1
    assert workspace.store.get(MAIN, "thread")["suggestions"]["as_of_message_id"] == "message_" + run2
    assert housekeeping.parse_suggestions("no json here") == [] and housekeeping.parse_suggestions('[{"text": " /probe ", "label": ""}]') == [{"label": "/probe", "text": "/probe"}]
