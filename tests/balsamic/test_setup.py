"""Starting a campaign as a conversation: scripted questions with choices, free text parsed, the model's turn when one answers, create."""
import json

from support import finish_run


def test_scripted_setup_asks_every_field_with_choices_and_creates_the_campaign(client, workspace):
    setup = client.post("/api/v1/setup").json()
    assert setup["mode"] == "scripted" and setup["step"]["field"] == "name" and setup["transcript"][0]["role"] == "assistant"
    sid = setup["id"]
    answer = lambda **body: client.post(f"/api/v1/setup/{sid}/answer", json=body).json()
    s = answer(text="Grating deflector, round 3")
    assert s["draft"]["name"] == "Grating deflector, round 3" and s["draft"]["identity"] == "grating-deflector-round-3" and s["step"]["field"] == "objective"
    assert "identity will be grating-deflector-round-3" in s["transcript"][-1]["text"]
    s = answer(choice="later")
    assert s["draft"]["objective"] == "" and s["step"]["field"] == "problem"
    assert any(c["id"] == "bounded_continuous" for c in s["step"]["choices"]) and s["step"]["choices"][0]["id"] == "formulate"
    s = answer(choice="bounded_continuous")
    assert s["draft"]["problem_id"] == "bounded_continuous" and s["step"]["field"] == "budget"
    s = answer(text="2 h, $7, runs 120 s")
    assert (s["draft"]["compute_budget_seconds"], s["draft"]["llm_budget_usd"], s["draft"]["delegated_trial_seconds"]) == (7200, 7, 120) and s["step"]["field"] == "autonomy"
    bad = answer(text="lots")
    assert bad["step"]["field"] == "autonomy" and "Choose delegated" in bad["transcript"][-1]["text"]
    s = answer(choice="delegated")
    assert s["step"]["field"] == "autopilot"
    s = answer(choice="off")
    assert s["step"]["field"] == "ready" and "So: \"Grating deflector, round 3\"" in s["transcript"][-1]["text"]
    assert [c["id"] for c in s["step"]["choices"]][:2] == ["create", "edit:name"]
    # Change a field from the summary, then create.
    s = answer(choice="edit:budget")
    assert s["step"]["field"] == "budget"
    s = answer(choice="small")
    assert s["step"]["field"] == "ready" and s["draft"]["compute_budget_seconds"] == 600
    created = client.post(f"/api/v1/setup/{sid}/create").json()
    assert created["campaign_id"] == "grating-deflector-round-3" and created["thread_id"] == "thread_main_grating-deflector-round-3"
    campaign = workspace.store.get("grating-deflector-round-3", "campaign")
    assert campaign["compute_budget_seconds"] == 600 and campaign["autonomy"] == "delegated" and campaign["delegated_trial_seconds"] == 60
    assert [t["name"] for t in workspace.store.list("task", campaign["id"])] == ["bounded_continuous"]
    messages = client.get(f"/api/v1/threads/{created['thread_id']}/messages").json()["messages"]
    assert messages[0]["origin"] == "setup" and messages[1]["content"] == "Grating deflector, round 3" and messages[1]["role"] == "user"
    assert client.post(f"/api/v1/setup/{sid}/create").json()["already"] is True
    # A second campaign with the same name gets a distinct identity.
    again = client.post("/api/v1/setup").json()
    s = client.post(f"/api/v1/setup/{again['id']}/answer", json={"text": "Grating deflector, round 3"}).json()
    assert s["draft"]["identity"] == "grating-deflector-round-3-2"


def test_a_formulating_campaign_with_autopilot_is_created_and_the_lead_started(client, workspace, monkeypatch):
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    sid = client.post("/api/v1/setup").json()["id"]
    answer = lambda **body: client.post(f"/api/v1/setup/{sid}/answer", json=body).json()
    answer(text="Overnight"); answer(text="Find a deflector with higher efficiency"); answer(choice="formulate"); answer(choice="medium"); answer(choice="delegated")
    s = answer(choice="on")
    assert s["draft"]["autopilot"] == {"enabled": True, "compute_cap_seconds": 3600} and s["step"]["field"] == "ready"
    created = client.post(f"/api/v1/setup/{sid}/create").json()
    campaign = workspace.store.get(created["campaign_id"], "campaign")
    assert campaign["formulating"] is True and campaign["objective"] == "Find a deflector with higher efficiency"
    # Autopilot waits for the problem-definition gate: the choice is remembered, the lead starts, the switch stays off until the researcher turns it on.
    assert campaign["autopilot"]["enabled"] is False and campaign["autopilot"]["requested"]["compute_cap_seconds"] == 3600 and workspace.pi.owns(campaign["id"])
    assert client.get("/api/v1/campaigns").json()["campaigns"][0]["next_step"]["kind"] == "note"   # the gate is closed until the note is written
    assert client.get("/api/v1/campaigns").json()["campaigns"][0]["stage"] == "formulate"


def test_the_model_phrases_the_questions_and_fills_the_draft_from_free_text(client, workspace, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    monkeypatch.setattr(workspace.pi, "lead_model", lambda: {"provider": "openai-codex", "model": "gpt-6-astra", "effort": "medium"})
    workspace.pi.harness_status = {"configured": True}
    calls = []
    def complete(call_id, body, timeout=0):
        calls.append(body)
        prompt = body["prompt"]
        if "'name'" in prompt:
            return {"text": json.dumps({"reply": "A deflector campaign, nice.", "draft_patch": {"name": "Deflector v2"}, "field": "objective",
                                        "question": "What would success look like for the deflector?", "choices": [{"id": "eff", "label": "Higher first-order efficiency", "patch": {"objective": "Maximize first-order efficiency"}}], "free_text": True}),
                    "usage": {"cost_usd": 0.001}}
        return {"text": "```json\n" + json.dumps({"reply": "Got it.", "draft_patch": {"objective": "Reach 95 % efficiency at 1100 nm"}, "field": "problem", "question": "", "choices": []}) + "\n```", "usage": {"cost_usd": 0.001}}
    monkeypatch.setattr(workspace.pi.client, "complete", complete)
    setup = client.post("/api/v1/setup").json()
    assert setup["mode"] == "model" and setup["model"]["model"] == "gpt-6-astra"
    sid = setup["id"]
    s = client.post(f"/api/v1/setup/{sid}/answer", json={"text": "I want to call it deflector v2, the second try at the grating"}).json()
    assert s["draft"]["name"] == "Deflector v2" and s["draft"]["identity"] == "deflector-v2" and s["step"]["field"] == "objective"
    assert s["transcript"][-1]["text"].startswith("A deflector campaign, nice. What would success look like") and s["step"]["choices"][0]["label"] == "Higher first-order efficiency"
    s = client.post(f"/api/v1/setup/{sid}/answer", json={"text": "95 % at 1100 nm would be a win"}).json()
    assert s["draft"]["objective"] == "Reach 95 % efficiency at 1100 nm" and s["step"]["field"] == "problem" and s["cost_usd"] > 0
    assert "Which problem does it run on" in s["transcript"][-1]["text"], "the scripted question stands in when the model gives none"
    assert len(calls) == 2 and calls[0]["label"] == "campaign setup" and "Installed problems" in calls[0]["prompt"]
    # A choice never needs the model.
    s = client.post(f"/api/v1/setup/{sid}/answer", json={"choice": "formulate"}).json()
    assert s["step"]["field"] == "budget" and len(calls) == 2
    # When the model fails, the scripted parser answers and says so.
    monkeypatch.setattr(workspace.pi.client, "complete", lambda *a, **k: (_ for _ in ()).throw(ValueError("harness down")))
    s = client.post(f"/api/v1/setup/{sid}/answer", json={"text": "1 h and $3"}).json()
    assert s["draft"]["compute_budget_seconds"] == 3600 and s["draft"]["llm_budget_usd"] == 3 and "scripted questions" in s["model_note"]


def test_an_open_setup_runs_on_the_lead_model_chosen_after_it_opened(client, workspace, monkeypatch):
    monkeypatch.setenv("GRATING_LLM_DISABLED", "false")
    lead = {"provider": "centinels", "model": "gpt-6-luna", "effort": None}
    monkeypatch.setattr(workspace.pi, "lead_model", lambda: dict(lead))
    workspace.pi.harness_status = {"configured": True}
    calls = []
    def complete(call_id, body, timeout=0):
        calls.append(body)
        return {"text": json.dumps({"reply": "Noted.", "draft_patch": {"name": "Deflector v3"}, "field": "objective", "question": "", "choices": []}), "usage": {}}
    monkeypatch.setattr(workspace.pi.client, "complete", complete)
    sid = client.post("/api/v1/setup").json()["id"]
    lead["model"] = "gpt-6.1-sol"   # the researcher sets the lead's tier on Monitor → Models, then comes back
    assert client.get(f"/api/v1/setup/{sid}").json()["model"]["model"] == "gpt-6.1-sol"
    client.post(f"/api/v1/setup/{sid}/answer", json={"text": "call it deflector v3"})
    assert calls[0]["model"] == "gpt-6.1-sol"


def test_a_setup_is_abandoned_by_a_word_a_choice_or_the_button_and_never_created(client, workspace):
    sid = client.post("/api/v1/setup").json()["id"]
    client.post(f"/api/v1/setup/{sid}/answer", json={"text": "Wrong one"})
    s = client.post(f"/api/v1/setup/{sid}/answer", json={"text": "start over"}).json()
    assert s["status"] == "abandoned" and s["transcript"][-1]["text"] == "Abandoned. Starting over."
    assert client.post(f"/api/v1/setup/{sid}/answer", json={"text": "x"}).status_code == 409
    assert client.post(f"/api/v1/setup/{sid}/create").status_code == 409
    assert workspace.store.list("campaign") == []
    sid2 = client.post("/api/v1/setup").json()["id"]
    assert client.post(f"/api/v1/setup/{sid2}/abandon").json()["status"] == "abandoned"
    sid3 = client.post("/api/v1/setup").json()["id"]
    answer = lambda **body: client.post(f"/api/v1/setup/{sid3}/answer", json=body).json()
    answer(text="Right one"); answer(choice="later"); answer(choice="formulate"); answer(choice="small"); answer(choice="manual"); s = answer(choice="off")
    assert any(c["id"] == "restart" for c in s["step"]["choices"])
    assert answer(choice="restart")["status"] == "abandoned"


def test_every_offered_problem_creates_its_campaign_on_a_runnable_task(client, workspace):
    """The 2D deflector declares every configuration field, so the setup starts it on its published example, not on defaults."""
    sid = client.post("/api/v1/setup").json()["id"]
    answer = lambda setup_id, **body: client.post(f"/api/v1/setup/{setup_id}/answer", json=body).json()
    answer(sid, text="Probe")
    offered = [c["id"] for c in answer(sid, choice="later")["step"]["choices"] if c["id"] != "formulate"]
    assert "meent_2d_dual_polarization_deflector" in offered
    client.post(f"/api/v1/setup/{sid}/abandon")
    for problem_id in offered:
        sid = client.post("/api/v1/setup").json()["id"]
        answer(sid, text=f"On {problem_id}"); answer(sid, choice="later"); answer(sid, choice=problem_id)
        answer(sid, choice="small"); answer(sid, choice="manual"); answer(sid, choice="off")
        response = client.post(f"/api/v1/setup/{sid}/create")
        assert response.status_code == 200, (problem_id, response.text)
        tasks = workspace.store.list("task", response.json()["campaign_id"])
        assert [t["problem"]["definition_id"] for t in tasks] == [problem_id]
    flrl = workspace.store.list("task", "on-meent-2d-dual-polarization-deflector")[0]
    assert flrl["problem"]["configuration"]["grid_x"] == 256 and flrl["problem"]["fidelity"] == {"rcwa_order_x": 10, "rcwa_order_y": 5}


def test_a_campaign_on_an_installed_problem_has_the_lead_write_the_note_from_it(client, workspace, monkeypatch):
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    sid = client.post("/api/v1/setup").json()["id"]
    answer = lambda **body: client.post(f"/api/v1/setup/{sid}/answer", json=body).json()
    answer(text="Deflector"); answer(choice="later"); answer(choice="meent_2d_dual_polarization_deflector"); answer(choice="medium"); answer(choice="delegated")
    assert answer(choice="off")["step"]["field"] == "ready"
    created = client.post(f"/api/v1/setup/{sid}/create").json()
    cid, thread = created["campaign_id"], created["thread_id"]
    # The installed problem states the problem: Create starts the lead and asks it for the whole note, nothing of the researcher.
    run = workspace.store.get("pi_run_note_" + cid, "agent_run")
    assert run["origin"]["note_request"] == "installed_problem" and run["origin"]["thread_id"] == thread and workspace.pi.owns(cid)
    assert "flrl_2d_deflector_1050nm_75deg" in run["input"] and "every section in one call" in run["input"] and "Do not propose skips" in run["input"]
    messages = client.get(f"/api/v1/threads/{thread}/messages").json()["messages"]
    assert messages[-1]["origin"] == "setup" and "writes the problem note from the installed problem" in messages[-1]["content"]
    view = client.get(f"/api/v1/campaigns/{cid}/problem-note").json()
    assert view["writing"] == {"run_id": run["id"], "status": "queued"} and view["installed"][0]["problem_id"] == "meent_2d_dual_polarization_deflector"
    # While sections are unwritten the gate sends the researcher to the lead, not to skips.
    assert "ask the lead to write them from it" in client.get("/api/v1/campaigns").json()["campaigns"][0]["next_step"]["text"]
    finish_run(workspace, run["id"], "The note is written from the installed problem; nothing is missing.")
    assert client.get(f"/api/v1/campaigns/{cid}/problem-note").json()["writing"] is None


def test_without_a_model_the_setup_says_the_lead_could_not_start_the_note(client, workspace):
    sid = client.post("/api/v1/setup").json()["id"]
    answer = lambda **body: client.post(f"/api/v1/setup/{sid}/answer", json=body).json()
    answer(text="Deflector"); answer(choice="later"); answer(choice="meent_2d_dual_polarization_deflector"); answer(choice="medium"); answer(choice="delegated"); answer(choice="off")
    created = client.post(f"/api/v1/setup/{sid}/create").json()
    assert not workspace.store.list("agent_run", created["campaign_id"])
    last = client.get(f"/api/v1/threads/{created['thread_id']}/messages").json()["messages"][-1]
    assert last["origin"] == "setup" and "could not start writing the problem note" in last["content"] and "/note" in last["content"]
