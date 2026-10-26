"""The problem note: immutable revisions, annotations by tier, Adopt to the formulator, visuals."""
import pytest

from support import activate_team, command, submitted, tool_call

MAIN = "thread_main_demo"


@pytest.fixture
def formulating(client):
    return command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Design a deflector with higher efficiency"}, 0)["outcome"]["campaign"]


@pytest.fixture
def team(client, workspace, formulating, monkeypatch):
    return activate_team(client, workspace, formulating, monkeypatch)


def test_problem_note_revisions_are_immutable_and_adopt_hands_the_note_to_the_formulator(client, workspace, formulating, monkeypatch):
    view = client.get("/api/v1/campaigns/demo/problem-note").json()
    note = view["note"]
    assert note["id"] == "note_demo" and note["status"] == "drafting" and note["current_revision"] == 1
    assert view["revision"]["sections"]["objective"]["text"] == "Design a deflector with higher efficiency"
    receipt = command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"knobs": {"text": "Grating period and fill factor", "items": ["period p", "fill f"], "latex": ["0 < f < 1"]}},
                                                              "glossary": [{"term": "fill factor", "definition": "the fraction of the period that is etched"}], "reason": "first knobs"}, formulating["version"])
    assert receipt["outcome"]["revision"] == 2
    first = workspace.store.get("note_demo_r1", "problem_note_revision")
    with pytest.raises(ValueError, match="immutable"):
        workspace.store.put("problem_note_revision", {**first, "sections": {**first["sections"], "objective": {"text": "changed", "items": [], "latex": []}}})
    view = client.get("/api/v1/problem-notes/note_demo").json()
    assert view["revision"]["revision"] == 2 and view["revision"]["sections"]["knobs"]["items"] == ["period p", "fill f"]
    assert view["revision"]["sections"]["objective"]["text"].startswith("Design"), "an untouched section carries over"
    assert [r["revision"] for r in view["revisions"]] == [1, 2] and view["revisions"][1]["author"] == "researcher"
    assert client.get("/api/v1/problem-notes/note_demo", params={"revision": 1}).json()["revision"]["sections"]["knobs"]["text"] == ""
    assert "## Knobs" in client.get("/api/v1/problem-notes/note_demo/preview").json()["markdown"]
    command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"knobs": {"text": "Grating period and fill factor"}}}, formulating["version"], expect=409)
    command(client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": 1}, formulating["version"], expect=409)
    # Adopt: the note's markdown becomes the statement of a problem import whose formulator writes the charter.
    created, started = [], []
    monkeypatch.setattr(workspace.problem_imports, "create", lambda values: created.append(values) or {"id": "import_1", "status": "collecting"})
    monkeypatch.setattr(workspace.problem_imports, "start", lambda import_id: started.append(import_id))
    monkeypatch.setattr(workspace.problem_imports, "sync", lambda import_id: {"id": import_id, "status": "running", "charter_id": None, "error": None, "reply": None})
    outcome = command(client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": 2}, formulating["version"])["outcome"]
    assert outcome == {"note_id": "note_demo", "revision": 2, "import_id": "import_1"} and started == ["import_1"]
    assert created[0].title == "Demo" and "## Knobs" in created[0].statement and "fill factor" in created[0].statement and "revision 2" in created[0].notes
    assert "installed problem" not in created[0].statement, "a campaign still formulating runs on nothing installed yet"
    note = workspace.store.get("note_demo", "problem_note")
    assert note["status"] == "adopted" and note["adopted_revision"] == 2 and workspace.store.get("demo", "campaign")["problem_note_id"] == "note_demo"
    assert client.get("/api/v1/problem-notes/note_demo").json()["charter"]["status"] == "running"
    assert client.get("/api/v1/campaigns").json()["campaigns"][0]["stage"] == "generate"
    # A revision after adoption reopens the draft; the charter is a formulator proposal the researcher confirms separately.
    command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"noise": {"text": "fabrication tolerance"}}}, formulating["version"])
    assert workspace.store.get("note_demo", "problem_note")["status"] == "drafting"


def test_note_ask_lookup_and_quick_never_reach_the_bus(client, workspace, formulating):
    command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"objective": {"text": "Maximize efficiency"}},
                                                    "glossary": [{"term": "efficiency", "definition": "power in the target order over incident power"}]}, formulating["version"])
    anchor = {"revision": 2, "section": "objective", "start": 9, "end": 19, "quote": "efficiency"}
    answered = client.post("/api/v1/problem-notes/note_demo/ask", json={"note_id": "note_demo", "anchor": anchor, "question": "What is efficiency?", "kind": "define"}).json()
    assert answered["tier"] == "lookup" and answered["status"] == "answered" and answered["answer"]["answered_by"] == "glossary"
    assert "power in the target order" in answered["answer"]["text"]
    # A quick question with model calls disabled escalates honestly to the lead tier and says why; nothing ran.
    escalated = client.post("/api/v1/problem-notes/note_demo/ask", json={"note_id": "note_demo", "anchor": anchor, "question": "Is 90 % realistic?"}).json()
    assert escalated["tier"] == "lead" and escalated["escalated_from_tier"] == "quick" and "disabled" in escalated["escalation_reason"]
    assert escalated["status"] == "open" and escalated.get("run_id") is None
    assert workspace.store.list("work_command", "demo")[-1]["request"]["operation"] != "note.ask"
    assert [row["tier"] for row in client.get("/api/v1/problem-notes/note_demo").json()["annotations"]] == ["lookup", "lead"]
    challenge = client.post("/api/v1/problem-notes/note_demo/ask", json={"note_id": "note_demo", "anchor": anchor, "question": "Why not minimize loss instead?", "kind": "challenge"})
    assert challenge.status_code == 409 and "command bus" in challenge.json()["detail"]


def test_lead_tier_answers_as_a_proposed_edit_never_a_silent_rewrite(client, workspace, formulating, team):
    anchor = {"revision": 1, "section": "objective", "start": 0, "end": 6, "quote": "Design"}
    receipt = command(client, "note.ask", "demo", {"note_id": "note_demo", "anchor": anchor, "question": "Why not minimize loss instead of maximizing efficiency?", "kind": "challenge"},
                      formulating["version"], origin={"thread_id": MAIN})
    outcome = receipt["outcome"]
    assert outcome["tier"] == "lead" and outcome["run_id"] == "pi_run_" + receipt["id"]
    run = submitted(workspace, outcome["run_id"])
    assert run["origin"]["annotation_id"] == outcome["annotation_id"] and "problem_note_propose" in run["input"]
    answered = tool_call(workspace, team, run, "problem_note_propose", {"annotation_id": outcome["annotation_id"], "answer": "Loss includes absorption we cannot measure; efficiency is what the detector sees.",
                         "proposed_edit": {"sections": {"objective": {"text": "Maximize measured first-order efficiency (not minimize total loss)"}}}})
    assert answered.get("status") == "answered", answered
    note = workspace.store.get("note_demo", "problem_note")
    assert note["current_revision"] == 1, "a proposed edit changes nothing until the researcher accepts it"
    annotation = workspace.store.get(outcome["annotation_id"], "note_annotation")
    assert annotation["proposed_edit"]["sections"]["objective"]["text"].startswith("Maximize measured")
    accepted = command(client, "note.resolve", "demo", {"annotation_id": outcome["annotation_id"], "choice": "accept"}, formulating["version"])["outcome"]
    assert accepted["revision"] == 2
    revision = workspace.store.get("note_demo_r2", "problem_note_revision")
    assert revision["author"] == "researcher" and revision["proposed_by_annotation_id"] == outcome["annotation_id"]
    assert workspace.store.get(outcome["annotation_id"], "note_annotation")["status"] == "accepted"
    # The lead's own draft tool writes a revision in its name, visible as such.
    drafted = tool_call(workspace, team, run, "problem_note_draft", {"sections": {"confounders": {"items": ["detector drift"]}}, "reason": "from the discussion"}, call_id="draft")
    assert drafted["revision"] == 3 and workspace.store.get("note_demo_r3", "problem_note_revision")["author"] == "lead"


def test_render_visual_is_bounded_and_saved_as_an_artifact(client, workspace, formulating, team):
    run = submitted(workspace, workspace.pi.enqueue(team, "pi_run_v", "Draw the geometry", origin={"thread_id": MAIN, "actor": "researcher"})["id"])
    saved = tool_call(workspace, team, run, "render_visual", {"title": "Grating cross-section", "html": "<svg viewBox='0 0 10 10'><rect width='5' height='10'/></svg>", "note_id": "note_demo"})
    artifact = workspace.store.get(saved["artifact_id"], "agent_artifact")
    assert artifact["kind"] == "visual" and artifact["content"]["html"].startswith("<svg") and artifact["thread_id"] == MAIN and artifact["content_hash"]
    assert saved["link"] == "#note?sel=" + saved["artifact_id"]
    too_big = tool_call(workspace, team, run, "render_visual", {"title": "big", "html": "<p>" + "x" * (256 * 1024) + "</p>"}, call_id="big")
    assert too_big["executed"] is False and "at most" in too_big["error"]
    external = tool_call(workspace, team, run, "render_visual", {"title": "ext", "html": "<img src='https://example.org/x.png'>"}, call_id="ext")
    assert external["executed"] is False and "self-contained" in external["error"]


def test_the_note_follows_the_charter_of_its_latest_adoption(client, workspace, campaign):
    from balsamic.notes import service
    from optimization_framework.storage.sqlite import now
    note = service.ensure_note(workspace, campaign["id"])
    note.update(charter_id="charter_old", import_id="import_new", status="adopted", adopted_revision=note["current_revision"])
    workspace.store.put("problem_note", note)
    workspace.store.put("problem_import", {"id": "import_new", "campaign_id": campaign["id"], "status": "ready", "charter_id": "charter_new", "error": None, "reply": "", "created_at": now()})
    if hasattr(workspace, "problem_imports"):
        workspace.problem_imports.sync = lambda identity: workspace.store.get(identity, "problem_import")
    body = service.view(workspace, note["id"])
    assert body["note"]["charter_id"] == "charter_new" and body["charter"]["charter_id"] == "charter_new"
    assert workspace.store.get(note["id"], "problem_note")["charter_id"] == "charter_new"


def test_adopt_hands_the_formulator_the_installed_problem_the_tasks_run_on(client, workspace, monkeypatch):
    from balsamic.setup.service import starting_task
    campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Develop an effective optimizer for the chosen problem.",
                                                           "tasks": [starting_task("meent_2d_dual_polarization_deflector")], "compute_budget_seconds": 600, "llm_budget_usd": 1}, 0)["outcome"]["campaign"]
    view = client.get("/api/v1/campaigns/demo/problem-note").json()
    assert view["installed"] == [{"problem_id": "meent_2d_dual_polarization_deflector", "name": "FLRL 2D silicon/air dual-polarization beam deflector"}] and view["writing"] is None
    created = []
    monkeypatch.setattr(workspace.problem_imports, "create", lambda values: created.append(values) or {"id": "import_1", "status": "collecting"})
    monkeypatch.setattr(workspace.problem_imports, "start", lambda import_id: None)
    command(client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": 1}, campaign["version"])
    # The formulator is told what the tasks already run on, with the example whose charter it builds from, and not to ask about it.
    statement = created[0].statement
    assert "## The installed problem this campaign runs on" in statement and "`meent_2d_dual_polarization_deflector`" in statement
    assert "2D dual-polarization beam deflector · Octavian FLRL" in statement and '"wavelength_nm": 1050.0' in statement and "do not ask" in statement
