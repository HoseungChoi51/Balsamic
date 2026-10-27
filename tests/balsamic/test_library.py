"""The strategy library: immutable entries with signature and evidence; search ranks the same problem first; apply makes an inspired_by root; the lead's first reply knows."""
from support import activate_team, command, submitted, tool_call

MAIN = "thread_main_demo"


def finalist(client, workspace, campaign, title="Winner"):
    h = command(client, "hypothesis.create", campaign["id"], {"title": title, "mechanism": "restart from the best", "rationale": "it won", "algorithm": "random"}, campaign["version"])["outcome"]["hypothesis"]
    workspace.store.put("trial", {"id": "trial_" + h["id"], "campaign_id": campaign["id"], "task_id": workspace.store.list("task", campaign["id"])[0]["id"], "algorithm": "random", "status": "completed",
                                  "seed": 0, "max_steps": 10, "wall_seconds": 60, "execution_seconds": 50, "hypothesis_id": h["id"], "control_revision": 0, "created_at": "2026-10-19T00:00:00Z",
                                  "result": {"best_objective": 0.9, "evaluations": 10, "scientific_complete": True}}, "trial.evidence_cataloged")
    current = workspace.store.get(h["id"], "hypothesis")
    current["status"] = "finalist"
    workspace.store.put("hypothesis", current, "hypothesis.status")
    return current


def test_library_entry_carries_signature_and_evidence_and_is_immutable(client, workspace, campaign):
    loser = command(client, "hypothesis.create", campaign["id"], {"title": "Loser", "mechanism": "m", "rationale": "r"}, campaign["version"])["outcome"]["hypothesis"]
    command(client, "library.publish", campaign["id"], {"hypothesis_id": loser["id"]}, campaign["version"], expect=409)
    winner = finalist(client, workspace, campaign)
    outcome = command(client, "library.publish", campaign["id"], {"hypothesis_id": winner["id"], "notes": "won the deflector round"}, campaign["version"])["outcome"]
    entry = outcome["entry"]
    assert entry["signature"]["problem_id"] == "bounded_continuous" and entry["signature"]["objective"]["direction"] in {"minimize", "maximize"}
    assert entry["signature"]["representation"] == "continuous" and entry["signature"]["constraint_digest"] and entry["signature"]["instance_digest"]
    assert entry["evidence"]["best_score"] == 0.9 and entry["evidence"]["best_basis"] == "measured" and entry["evidence"]["worker_seconds"] == 50 and entry["evidence"]["trial_ids"] == ["trial_" + winner["id"]]
    assert entry["strategy"]["algorithm"] == "random" and entry["graph"]["stage"] == "finalist" and entry["content_hash"]
    assert workspace.store.get(winner["id"], "hypothesis")["library_entry_id"] == entry["id"]
    again = command(client, "library.publish", campaign["id"], {"hypothesis_id": winner["id"]}, campaign["version"])["outcome"]
    assert again["already"] is True and again["entry_id"] == entry["id"]
    import pytest
    with pytest.raises(ValueError, match="immutable"):
        workspace.store.put("library_entry", {**entry, "notes": "edited"})
    assert client.get(f"/api/v1/library/{entry['id']}").json()["id"] == entry["id"]


def test_only_the_researcher_publishes_to_the_library(client, workspace, campaign):
    import pytest
    from balsamic.library.service import PublishInput, publish
    winner = finalist(client, workspace, campaign)
    for actor in ("manager", "autopilot", "balsamic"):
        with pytest.raises(ValueError, match="Only the researcher publishes"):
            publish(workspace, campaign["id"], PublishInput(hypothesis_id=winner["id"]), command_id="by_" + actor, actor=actor)
    assert workspace.store.list("library_entry") == [] and not workspace.store.get(winner["id"], "hypothesis").get("library_entry_id")


def test_library_search_ranks_the_same_problem_first(client, workspace, campaign):
    winner = finalist(client, workspace, campaign)
    command(client, "library.publish", campaign["id"], {"hypothesis_id": winner["id"]}, campaign["version"])
    other = workspace.store.put_immutable("library_entry", {"id": "library_other", "origin_campaign_id": "elsewhere", "hypothesis_id": "h_x", "strategy": {"title": "Grating hill climb", "algorithm": "hillclimb", "mechanism": "flip cells"},
        "signature": {"problem_id": "meent_grating", "objective": {"name": "efficiency", "direction": "maximize"}, "representation": "binary", "constraint_digest": "x", "instance_digest": "y"},
        "evidence": {"best_score": 0.5}, "graph": {}, "notes": "", "published_by": "researcher", "created_at": "2026-01-01T00:00:00Z"}, "library.published")
    body = client.get("/api/v1/library", params={"campaign_id": "demo"}).json()
    assert [row["entry"]["origin_campaign_id"] for row in body["entries"]] == ["demo", "elsewhere"]
    top = body["entries"][0]["match"]
    assert top["score"] >= 6 and "same problem" in top["reasons"] and "same objective and direction" in top["reasons"] and "same representation" in top["reasons"]
    assert body["entries"][1]["match"]["score"] == 0
    assert body["signature"]["basis"].startswith("the first development task")
    words = client.get("/api/v1/library", params={"campaign_id": "demo", "q": "grating"}).json()["entries"]
    assert [row["entry"]["id"] for row in words] == [other["id"]] and "matches 1 of 1 words" in words[0]["match"]["reasons"]
    assert client.get("/api/v1/library", params={"problem_id": "meent_grating"}).json()["entries"][0]["entry"]["id"] == "library_other"


def test_apply_creates_an_inspired_by_root(client, workspace, campaign):
    winner = finalist(client, workspace, campaign)
    entry_id = command(client, "library.publish", campaign["id"], {"hypothesis_id": winner["id"]}, campaign["version"])["outcome"]["entry_id"]
    second = command(client, "campaign.create", "second", {"name": "Second", "objective": "again", "tasks": [{"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}]}, 0)["outcome"]["campaign"]
    outcome = command(client, "library.apply", "second", {"entry_id": entry_id, "note": "start from the winner"}, second["version"], origin={"thread_id": "thread_main_second"})["outcome"]
    applied = workspace.store.get(outcome["hypothesis_id"], "hypothesis")
    assert applied["campaign_id"] == "second" and applied["library_entry_id"] == entry_id and applied["parent_ids"] == []
    assert applied["parent_links"] == [{"id": entry_id, "kind": "inspired_by"}] and applied["algorithm"] == "random"
    assert "Applied from library entry" in applied["rationale"] and "same problem" in applied["rationale"] and outcome["match"]["score"] >= 6
    graph = client.get("/api/v1/campaigns/second/evolution").json()
    assert graph["edges"] == [{"from": entry_id, "to": applied["id"], "kind": "inspired_by", "external": True}]
    assert graph["layout"][0]["round"] == 0


def test_lead_first_reply_mentions_library_matches(client, workspace, campaign, monkeypatch):
    winner = finalist(client, workspace, campaign)
    command(client, "library.publish", campaign["id"], {"hypothesis_id": winner["id"]}, campaign["version"])
    second = command(client, "campaign.create", "second", {"name": "Second", "objective": "again", "tasks": [{"name": "Quadratic", "problem_id": "bounded_continuous", "configuration": {}}]}, 0)["outcome"]["campaign"]
    lead = activate_team(client, workspace, second, monkeypatch)
    run = submitted(workspace, "pi_run_" + command(client, "agent.message", "second", {"message": "Hello", "thread_id": "thread_main_second"}, second["version"], origin={"thread_id": "thread_main_second"})["id"])
    from optimization_framework.agents.tools import PiTools
    manifest = PiTools(workspace.pi).manifest(lead["id"], run["id"])
    assert "Library (strategies that won earlier campaigns of this problem): Winner" in PiTools(workspace.pi).turn_state(lead["id"], run["id"])["text"]
    assert "Winner" not in manifest["instructions"]
    assert "library_search" in {tool["name"] for tool in manifest["tools"]}
    found = tool_call(workspace, lead, run, "library_search", {"query": ""})
    assert found["entries"][0]["title"] == "Winner" and found["entries"][0]["match"]["score"] >= 6
    # Thread search and exports.
    hits = client.get("/api/v1/campaigns/second/threads", params={"q": "hello"}).json()
    assert hits["messages"][0]["thread_id"] == "thread_main_second" and "Hello" in hits["messages"][0]["excerpt"]
    export = client.get("/api/v1/threads/thread_main_second/export")
    assert export.status_code == 200 and "# Second" in export.text and "Hello" in export.text
    graph = client.get("/api/v1/campaigns/demo/evolution/export")
    assert graph.headers["content-disposition"].endswith('"demo-evolution.json"') and graph.json()["nodes"][0]["id"] == winner["id"]
