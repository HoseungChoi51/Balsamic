"""The quick path (roadmap P2, decisions 28–32): the lead writes the charter of a simple problem itself, the problem note is read
from it, and the researcher's one action is problem_note.confirm, which accepts the assumptions, confirms and installs the tasks."""
import copy

import pytest

from support import activate_team, command, finish_run, state_of, submitted, tool_call
from balsamic.evolution.stages import campaign_stage, definition
from balsamic.notes.service import write_charter

MAIN = "thread_main_demo"
WORDS = ("One oven takes 8 bakes, one after another. Their durations in minutes: 30, 45, 20, 60, 35, 25, 50, 40. Their due times: "
         "210, 130, 200, 110, 190, 100, 40, 120. Find the order that minimizes the total lateness.")
SAID = {"id": 1, "source": "the researcher's message", "quote": "Their durations in minutes: 30, 45, 20, 60, 35, 25, 50, 40"}
BAKING = {
    "title": "Baking order", "summary": "Order {n_bakes:.0f} bakes in one oven to minimize their total tardiness.",
    "text": "One oven takes {n_bakes:.0f} bakes, one after another. A bake that ends after its due time is late by the difference.",
    "quantities": {"n_bakes": {"description": "Bakes to schedule", "kind": "integer", "value": 8, "units": "1", "citation": 1},
                   "minutes": {"description": "Duration of each bake, by its index", "kind": "data", "value": [30, 45, 20, 60, 35, 25, 50, 40], "citation": 1},
                   "due": {"description": "Due time of each bake, by its index", "kind": "data", "value": [210, 130, 200, 110, 190, 100, 40, 120], "citation": 1}},
    "variables": [{"name": "bake_order", "description": "The order the bakes go into the oven", "representation": "permutation", "shape": ["n_bakes"],
                   "meaning": "Each entry is the index of a bake in minutes and due"}],
    "objective": {"name": "total_tardiness", "direction": "minimize", "units": "min", "definition": "The sum over bakes of max(0, end time - due time)"},
    "evaluator": {"kind": "declared", "problem_id": "baking_order", "deterministic": True, "configuration": {"minutes": "minutes", "due": "due"},
                  "notes": "Run the bakes in the given order from time 0; sum each bake's lateness past its due time."},
    "instances": [{"name": "Eight bakes", "split": "development"}], "citations": [SAID]}
GAP = {"id": "gap", "question": "Does the oven need a pause between bakes?", "options": ["No pause (recommended)", "Five minutes"], "about": ["minutes"]}


def charter(**changes):
    return {**copy.deepcopy(BAKING), **changes}


@pytest.fixture
def formulating(client):
    return command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Order the bakes"}, 0)["outcome"]["campaign"]


@pytest.fixture
def team(client, workspace, formulating, monkeypatch):
    return activate_team(client, workspace, formulating, monkeypatch)


@pytest.fixture
def turn(client, workspace, team):
    """The lead's turn on the researcher's message, which states the whole problem."""
    receipt = command(client, "agent.message", "demo", {"message": WORDS, "thread_id": MAIN}, workspace.store.get("demo", "campaign")["version"],
                      origin={"thread_id": MAIN})
    return submitted(workspace, "pi_run_" + receipt["id"])


def version(workspace):
    return workspace.store.get("demo", "campaign")["version"]


def write(workspace, team, run, call="write", **args):
    return tool_call(workspace, team, run, "charter_write", {"charter": BAKING, "reason": "From your message", **args}, call_id=call)


def test_the_lead_writes_the_charter_and_the_note_is_read_from_it(client, workspace, team, turn):
    written = write(workspace, team, turn, confounders={"text": "None: the tardiness is computed exactly from the given data."})
    assert "error" not in written, written
    assert (written["revision"], written["blocking"], written["link"], written["note_id"]) == (1, 0, "#note/charter", "note_demo")
    record = workspace.charters.get(written["charter_id"])
    assert record["writer"] == "lead" and record["history"][-1]["by"] == "lead" and record["source"] == {"kind": "lead", "id": "demo", "name": "Demo", "thread_id": MAIN}
    note = workspace.store.get("note_demo", "problem_note")
    assert (note["path"], note["charter_id"], note["status"]) == ("quick", written["charter_id"], "drafting")
    # The note is read from the charter's current revision: values come from the charter, computed where they are derived.
    view = client.get("/api/v1/campaigns/demo/problem-note").json()
    sections = view["revision"]["sections"]
    assert view["revision"]["charter_revision"] == 1 and view["charter"]["charter"]["writer"] == "lead"
    assert sections["objective"]["text"].startswith("One oven takes 8 bakes")
    assert any(item.startswith("bake_order (decision variable)") and "an order of n_bakes = 8, each item once" in item for item in sections["knobs"]["items"])
    assert any(item.startswith("minutes = [30, 45, 20, 60, 35, 25, 50, 40]") for item in sections["knobs"]["items"])
    assert sections["observables"]["items"][0].startswith("total_tardiness (min), to minimize") and "baking_order" in sections["observables"]["items"][-1]
    assert sections["noise"]["text"].startswith("Deterministic") and sections["confounders"]["text"].startswith("None: the tardiness")
    assert sections["open_questions"]["text"] == "None remaining." and all(sections[name]["text"] or sections[name]["items"] for name in sections)
    # The gate names the path and its one step; the sections and Adopt are not steps of it.
    gate = definition(workspace, workspace.store.get("demo", "campaign"))
    assert gate["ready"] is False and gate["missing"] == [] and (gate["step"]["kind"], gate["step"]["path"], gate["step"]["page"]) == ("confirm", "quick", "#note/charter")
    assert "Gate: closed on the quick path. Next: confirm the charter (#note/charter)." in state_of(workspace, team)
    # The note has no revisions of its own on this path, and nothing is adopted or skipped.
    refused = command(client, "problem_note.revise", "demo", {"note_id": "note_demo", "sections": {"noise": {"text": "x"}}}, version(workspace), expect=409)
    assert "quick path" in refused["detail"]
    refused = command(client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": 1}, version(workspace), expect=409)
    assert "quick path" in refused["detail"]
    skip = tool_call(workspace, team, turn, "problem_note_skip", {"skips": [{"section": "noise", "basis": "not_applicable", "reason": "The tardiness is exact for an order.",
                                                                              "confirm": "Nothing about the oven is random here."}]}, call_id="skip")
    assert "quick path" in skip["error"]
    # A later write revises the same charter.
    again = write(workspace, team, turn, call="again", charter=charter(summary="Order {n_bakes:.0f} bakes to minimize their total lateness."))
    assert (again["charter_id"], again["revision"]) == (written["charter_id"], 2) and workspace.charters.get(written["charter_id"])["history"][-1]["by"] == "lead"
    assert workspace.charters.view(written["charter_id"])["rendered"]["summary"] == "Order 8 bakes to minimize their total lateness."
    # The lead reads the charter back, with what the researcher changed.
    read = tool_call(workspace, team, turn, "charter_read", {}, call_id="read")
    assert (read["id"], read["revision"], read["path"], read["writer"]) == (written["charter_id"], 2, "quick", "lead")


def test_one_confirm_accepts_the_assumptions_confirms_the_revision_and_installs_the_tasks(client, workspace, team, turn):
    assumed = charter(assumptions=[{"statement": "Bakes run back to back, with no pause between them", "about": ["minutes"]}])
    written = write(workspace, team, turn, charter=assumed)
    assert written["blocking"] == 1 and [row["code"] for row in written["findings"] if row["severity"] == "blocking"] == ["assumption.unaccepted"]
    payload = {"note_id": "note_demo", "charter_id": written["charter_id"], "revision": 1}
    # The revision the researcher read, or nothing: a later write makes it stale.
    write(workspace, team, turn, call="again", charter={**assumed, "summary": "Eight bakes, one oven."})
    refused = command(client, "problem_note.confirm", "demo", payload, version(workspace), expect=409)
    assert "changed since you read it (now revision 2)" in refused["detail"]
    outcome = command(client, "problem_note.confirm", "demo", {**payload, "revision": 2}, version(workspace))["outcome"]
    assert outcome["accepted"] == ["statement0"] and outcome["charter"] == {"id": written["charter_id"], "revision": 3} and outcome["tasks"] == ["Eight bakes"]
    record = workspace.charters.get(written["charter_id"])
    assert (record["status"], record["confirmed_revision"]) == ("confirmed", 3) and record["charter"]["assumptions"][0]["accepted"] is True
    campaign = workspace.store.get("demo", "campaign")
    assert campaign["charter"] == {"id": written["charter_id"], "revision": 3} and campaign["problem_note_id"] == "note_demo"
    assert [task["evaluator_manifest"]["id"] for task in workspace.current_tasks("demo")] == ["baking_order"]
    assert workspace.store.get("note_demo", "problem_note")["status"] == "confirmed"
    assert definition(workspace, campaign)["ready"] is True and campaign_stage(workspace, campaign)["stage"] == "generate"
    assert "Gate: open" in state_of(workspace, team)
    # Confirming again changes nothing; the lead no longer writes the confirmed charter: a change is the researcher's.
    refused = command(client, "problem_note.confirm", "demo", {**payload, "revision": 3}, version(workspace), expect=409)
    assert "tasks are installed" in refused["detail"]
    late = write(workspace, team, turn, call="late")
    assert "confirmed" in late["error"] and workspace.charters.get(written["charter_id"])["revision"] == 3


def test_only_the_researcher_confirms_and_only_what_the_page_cannot_settle_waits(client, workspace, team, turn, monkeypatch):
    broken = charter(quantities={**copy.deepcopy(BAKING["quantities"]), "n_bakes": {**BAKING["quantities"]["n_bakes"], "value": None}})
    written = write(workspace, team, turn, charter=broken)
    payload = {"note_id": "note_demo", "charter_id": written["charter_id"], "revision": 1}
    refused = command(client, "problem_note.confirm", "demo", payload, version(workspace), expect=409)
    assert "Settle these on the Charter tab" in refused["detail"] and "n_bakes has no value" in refused["detail"]
    assert workspace.charters.get(written["charter_id"])["status"] == "draft" and not workspace.current_tasks("demo")
    from balsamic.notes.service import confirm
    with pytest.raises(ValueError, match="is not the charter of this campaign's note"):
        confirm(workspace, workspace.store.get("note_demo", "problem_note"), "problem_charter_other", 1, campaign_id="demo")
    # The bus takes the command from the researcher only: an agent's or autopilot's authority is refused before the handler.
    from optimization_framework.contracts.commands import Command
    pinned = {"expected_guidance_revision": workspace.memory.state("demo")["guidance_revision"],
              "expected_authority_hash": workspace.commands.authority_hash(workspace.store.get("demo", "campaign"))}
    with pytest.raises(ValueError, match="needs researcher authorization"):
        workspace.commands.execute(Command(id="cmd_autopilot", campaign_id="demo", operation="problem_note.confirm", expected_revision=version(workspace),
                                           payload=payload, **pinned), actor="autopilot")


def test_a_value_the_researcher_set_stays_and_an_adopted_note_keeps_the_formulator(client, workspace, team, turn):
    written = write(workspace, team, turn)
    path = f"/api/v1/problem-charters/{written['charter_id']}"
    due = [210, 130, 200, 110, 190, 100, 60, 120]
    client.post(path + "/edit", json={"expected_revision": 1, "changes": [{"op": "set", "path": "quantities.due.value", "value": due}]}).raise_for_status()
    refused = write(workspace, team, turn, call="again")
    assert "due was set by the researcher" in refused["error"] and "ask them to change it on the Charter tab" in refused["error"]
    kept = write(workspace, team, turn, call="kept", charter=charter(quantities={**copy.deepcopy(BAKING["quantities"]), "due": {**BAKING["quantities"]["due"], "value": due}}))
    assert kept["revision"] == 3 and workspace.charters.get(written["charter_id"])["charter"]["quantities"]["due"]["origin"] == "researcher"
    # A note on the full path, adopted for the formulator, is not the lead's to write a charter for.
    note = workspace.store.get("note_demo", "problem_note")
    workspace.store.put("problem_note", {**note, "path": "full", "import_id": "import_1", "adopted_revision": 1, "status": "adopted"})
    with pytest.raises(ValueError, match="adopted, so it is on the full path"):
        write_charter(workspace, "demo", copy.deepcopy(BAKING))


def test_the_quick_path_asks_one_round_of_at_most_two_questions_and_the_answers_start_a_lead_turn(client, workspace, team, turn):
    # Three questions: refused whole, and nothing is saved.
    third = {**GAP, "id": "third"}
    refused = write(workspace, team, turn, charter=charter(questions=[{**GAP, "id": "first"}]), questions=[GAP, third])
    assert "at most 2 questions" in refused["error"]
    assert workspace.store.list("problem_charter") == [] and workspace.store.list("problem_note", "demo") == []
    written = write(workspace, team, turn, call="asked", questions=[GAP])
    assert written["questions_asked"] == 1 and written["revision"] == 2 and written["blocking"] == 1
    record = workspace.charters.get(written["charter_id"])
    assert [q["id"] for q in record["charter"]["questions"]] == ["gap"] and workspace.charters.view(record["id"])["question_rounds"] == 1
    assert workspace.charters.view(record["id"])["question_rounds_max"] == 1
    payload = {"note_id": "note_demo", "charter_id": record["id"], "revision": 2}
    assert "Answer the lead's questions" in command(client, "problem_note.confirm", "demo", payload, version(workspace), expect=409)["detail"]
    # One round only; a whole charter that leaves the open question out keeps it until the researcher answers.
    assert "one round of questions" in write(workspace, team, turn, call="more", questions=[{**GAP, "id": "again"}])["error"]
    kept = write(workspace, team, turn, call="kept")
    assert [q["id"] for q in workspace.charters.get(record["id"])["charter"]["questions"]] == ["gap"] and kept["revision"] == 3
    # The researcher's answer goes to the lead, in the thread it wrote the charter in, as a turn of its own.
    client.post(f"/api/v1/problem-charters/{record['id']}/answers", json={"expected_revision": 3, "question_id": "gap", "answer": "No pause (recommended)"}).raise_for_status()
    runs = [run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == record["id"]]
    assert len(runs) == 1 and runs[0]["agent_id"] == team["id"] and runs[0]["origin"]["thread_id"] == MAIN and runs[0]["origin"]["actor"] == "researcher"
    assert "(round 1 of 1)" in runs[0]["input"] and "No pause (recommended)" in runs[0]["input"] and "charter_write" in runs[0]["input"]
    assert "No more questions can be asked" in runs[0]["input"]
    assert all(q["sent"] for q in workspace.charters.get(record["id"])["charter"]["questions"])
    # The lead writes again from the answer; the answered question stays with its answer, and the charter can be confirmed.
    answered = submitted(workspace, runs[0]["id"])
    final = write(workspace, team, answered, call="final")
    assert final["blocking"] == 0 and [q["answer"] for q in workspace.charters.get(record["id"])["charter"]["questions"]] == ["No pause (recommended)"]
    finish_run(workspace, answered["id"], "Revised from your answer: no pause between bakes. [Confirm the charter](#note/charter).")
    outcome = command(client, "problem_note.confirm", "demo", {**payload, "revision": final["revision"]}, version(workspace))["outcome"]
    assert outcome["accepted"] == [] and outcome["charter"]["revision"] == final["revision"]


def test_a_request_in_words_on_the_quick_charter_goes_to_the_lead(client, workspace, team, turn):
    written = write(workspace, team, turn)
    client.post(f"/api/v1/problem-charters/{written['charter_id']}/requests", json={"text": "Add a ninth bake of 30 minutes due at 150."}).raise_for_status()
    runs = [run for run in workspace.store.list("agent_run", "demo") if (run.get("origin") or {}).get("charter_id") == written["charter_id"]]
    assert len(runs) == 1 and "Researcher request about your charter" in runs[0]["input"] and "ninth bake" in runs[0]["input"]
    assert workspace.charters.get(written["charter_id"]).get("import_id") is None, "no formulator is started for the lead's charter"
