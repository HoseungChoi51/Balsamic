"""The quick path's second reading (roadmap P4, decision 30): one call with no tools reads the researcher's own words against each
revision the lead writes without a blocking finding of its own, and lists what the retelling lost, changed or added. The researcher
settles each difference (the charter is right, or the lead fixes it) before the confirmation; a reading that cannot run ends the
quick path."""
import copy
import json

import pytest

from support import command, state_of, submitted, tool_call
from test_quick_charter import BAKING, WORDS, Reader, charter, formulating, team, turn, version, write  # noqa: F401  (the fixtures)
from balsamic.evolution.stages import definition
from balsamic.notes import reading as readings
from optimization_framework.contracts.commands import Command

DUE = {"quote": "Their due times: 210, 130, 200, 110, 190, 100, 40, 120", "path": "quantities.due.value", "kind": "different",
       "explanation": "They gave 110 minutes as the fourth bake's due time; the charter has 150."}
LATE = charter(quantities={**copy.deepcopy(BAKING["quantities"]), "due": {**BAKING["quantities"]["due"], "value": [210, 130, 200, 150, 190, 100, 40, 120]}})
BROKEN = charter(quantities={**copy.deepcopy(BAKING["quantities"]), "n_bakes": {**BAKING["quantities"]["n_bakes"], "value": None}})


def note_of(workspace):
    return workspace.store.get("note_demo", "problem_note")


def confirm(client, workspace, written, *, expect=200, **extra):
    payload = {"note_id": "note_demo", "charter_id": written["charter_id"], "revision": workspace.charters.get(written["charter_id"])["revision"], **extra}
    return command(client, "problem_note.confirm", "demo", payload, version(workspace), expect=expect)


def settle(client, workspace, revision, mismatches, *, expect=200, **extra):
    return command(client, "problem_note.settle", "demo", {"note_id": "note_demo", "revision": revision, "mismatches": mismatches, **extra},
                   version(workspace), expect=expect)


def test_the_reading_holds_the_researchers_words_and_the_charter_and_nothing_else(client, workspace, team, turn):
    reader = workspace.pi.client
    written = write(workspace, team, turn, confounders={"text": "None: the tardiness is computed exactly from the given data."})
    assert len(reader.calls) == 1 and reader.calls[0]["label"] == "charter_reader"
    body = reader.calls[0]
    content = json.loads(body["prompt"])
    assert set(content) == {"words", "charter"} and set(content["words"]) == {"conversation", "answers", "set_on_the_charter"}
    assert WORDS in content["words"]["conversation"] and content["words"]["answers"] == [] and content["words"]["set_on_the_charter"] == {}
    seen = content["charter"]
    assert seen["revision"] == 1 and seen["summary"] == "Order 8 bakes in one oven to minimize their total tardiness."   # texts read with their values
    assert seen["quantities"]["due"] == {"description": "Due time of each bake, by its index", "kind": "data", "role": "input",
                                         "value": [210, 130, 200, 110, 190, 100, 40, 120], "units": "", "origin": "source"}
    assert seen["objective"]["direction"] == "minimize" and seen["evaluator"]["deterministic"] is True and seen["variables"][0]["name"] == "bake_order"
    # Nothing else: not the note's confounders, not the findings, not the lead's citation of the words.
    assert "None: the tardiness" not in body["prompt"] and "findings" not in content["charter"] and "citations" not in content["charter"]
    assert "Return one JSON object matching" in body["system"] and '"enum": ["missing", "different", "added"]' in body["system"]
    # Saved before it is shown: instructions, input, output and usage, on the lead's model while the formulator's tier has none.
    record = workspace.store.get(f"charter_reading_{written['charter_id']}_r1", "charter_reading")
    assert (record["status"], record["output"], record["mismatches"], record["input"], record["instructions"]) == (
        "completed", {"mismatches": []}, [], content, body["system"])
    assert record["usage"]["calls"] == 1 and record["tier"] is None and record["model"]["model"] == team["model"] and record["run_id"] == turn["id"]
    with workspace.store.connection() as db:
        assert [tuple(row) for row in db.execute("SELECT role, agent_id, run_id FROM llm_usage WHERE campaign_id='demo'")] == [("charter_reader", record["id"], turn["id"])]
    # The lead is told, and the note keeps it as the quick path's criterion.
    assert written["reading"] == {"id": record["id"], "revision": 1, "status": "completed", "model": record["model"], "mismatches": []}
    row = next(row for row in written["quick_path"]["criteria"] if row["id"] == "reading")
    assert (row["holds"], row["detail"]) == (True, "Read at revision 1: no difference")
    assert written["next"].startswith("A second reading of the researcher's words found no difference.")
    note = note_of(workspace)
    assert note["quick"]["reading"] == written["reading"] and next(row for row in note["quick"]["criteria"] if row["id"] == "reading")["holds"] is True
    # Each revision is read once; a later write is read again, on the formulator's tier once it has a model.
    assert readings.read(workspace, "demo", workspace.charters.get(written["charter_id"]))["id"] == record["id"] and len(reader.calls) == 1
    from optimization_framework.agents import tiers
    tiers.save(workspace.store, tiers.TierSettings.model_validate({"tiers": [
        {"id": "strong", "label": "Strong", "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": "high"}}], "roles": {"formulator": "strong"}}))
    again = write(workspace, team, turn, call="again", charter=charter(summary="Eight bakes in one oven, as late as little as possible."))
    assert again["reading"]["revision"] == 2 and len(reader.calls) == 2 and (reader.calls[1]["provider"], reader.calls[1]["effort"]) == ("deepseek", "high")
    assert workspace.store.get(again["reading"]["id"], "charter_reading")["tier"] == "strong"
    read = tool_call(workspace, team, turn, "charter_read", {}, call_id="read")
    assert read["quick_path"]["reading"]["revision"] == 2


def test_a_revision_with_a_blocking_finding_of_the_leads_is_not_read(client, workspace, team, turn):
    broken = write(workspace, team, turn, charter=BROKEN)
    assert broken["reading"] is None and not workspace.pi.client.calls
    row = next(row for row in broken["quick_path"]["criteria"] if row["id"] == "reading")
    assert (row["holds"], row["detail"]) == (None, "Read once the charter has no blocking finding of the lead's")
    # The researcher's own blocking findings (an open question, an assumption) do not wait: the revision is read.
    asked = write(workspace, team, turn, call="asked", questions=[{"id": "gap", "question": "Does the oven need a pause between bakes?",
                                                                   "options": ["No pause (recommended)", "Five minutes"], "about": ["minutes"]}])
    assert asked["reading"]["status"] == "completed" and len(workspace.pi.client.calls) == 1
    assert json.loads(workspace.pi.client.calls[0]["prompt"])["charter"]["questions"] == [
        {"question": "Does the oven need a pause between bakes?", "options": ["No pause (recommended)", "Five minutes"]}]


def test_a_difference_refuses_the_confirmation_until_the_researcher_settles_it_and_who_settled_is_kept(client, workspace, team, turn):
    workspace.pi.client.reply = {"mismatches": [DUE]}
    written = write(workspace, team, turn, charter=LATE)
    assert written["reading"]["mismatches"] == [{"id": "m1", **DUE, "verbatim": True}] and written["quick_path"]["holds"] is True
    assert next(row for row in written["quick_path"]["criteria"] if row["id"] == "reading")["detail"] == "Read at revision 1: 1 difference for the researcher to settle"
    assert "found 1 difference with your charter" in written["next"] and "name each difference you leave" in written["next"]
    # The gate and the lead's state block name it; the confirmation is refused until it is settled.
    step = definition(workspace, workspace.store.get("demo", "campaign"))["step"]
    assert step["differences"] == ["quantities.due.value"] and "A second reading found 1 difference between your words and the charter" in step["text"]
    assert "The second reading found differences between the researcher's words and your charter, for them to settle: quantities.due.value." in state_of(workspace, team)
    refused = confirm(client, workspace, written, expect=409)["detail"]
    assert "Settle each difference the second reading found" in refused and "m1 (quantities.due.value): They gave 110 minutes" in refused
    assert workspace.charters.get(written["charter_id"])["status"] == "draft" and not workspace.current_tasks("demo")
    # Only the researcher settles, and only what the reading of that revision found.
    pinned = {"expected_guidance_revision": workspace.memory.state("demo")["guidance_revision"],
              "expected_authority_hash": workspace.commands.authority_hash(workspace.store.get("demo", "campaign"))}
    with pytest.raises(ValueError, match="needs researcher authorization"):
        workspace.commands.execute(Command(id="cmd_autopilot", campaign_id="demo", operation="problem_note.settle", expected_revision=version(workspace),
                                           payload={"note_id": "note_demo", "revision": 1, "mismatches": {"m1": "right"}}, **pinned), actor="autopilot")
    assert "stands at revision 1, not 2" in settle(client, workspace, 2, {"m1": "right"}, expect=409)["detail"]
    assert "found no m2; it found m1" in settle(client, workspace, 1, {"m2": "right"}, expect=409)["detail"]
    outcome = settle(client, workspace, 1, {"m1": "right"})["outcome"]
    assert (outcome["left"], outcome["run_id"]) == ([], None)
    kept = note_of(workspace)["quick"]
    assert kept["reading"]["mismatches"][0]["settled"]["how"] == "right" and kept["reading"]["mismatches"][0]["settled"]["by"] == "researcher"
    assert [(row["path"], row["kind"], row["revision"], row["by"]) for row in kept["settled"]] == [("quantities.due.value", "different", 1, "researcher")]
    assert "Already settled: m1" in settle(client, workspace, 1, {"m1": "ask_lead"}, expect=409)["detail"]
    assert "differences" not in definition(workspace, workspace.store.get("demo", "campaign"))["step"]
    assert confirm(client, workspace, written)["outcome"]["charter"] == {"id": written["charter_id"], "revision": 1}


def test_the_confirmation_settles_what_the_researcher_marks_right_in_the_same_action(client, workspace, team, turn):
    workspace.pi.client.reply = {"mismatches": [DUE, {"quote": "", "path": "evaluator.notes", "kind": "added",
                                                      "explanation": "The charter says the oven starts at time 0; they did not say when it starts."}]}
    written = write(workspace, team, turn, charter=LATE)
    refused = confirm(client, workspace, written, expect=409, right=["m1"])["detail"]
    assert "m2 (evaluator.notes)" in refused and "m1" not in refused.split("fix it. ")[1]
    assert not note_of(workspace)["quick"]["reading"]["mismatches"][0]["settled"]   # a refused confirmation records nothing
    outcome = confirm(client, workspace, written, right=["m1", "m2"])["outcome"]
    assert outcome["tasks"] == ["Eight bakes"]
    settled = [row["settled"] for row in note_of(workspace)["quick"]["reading"]["mismatches"]]
    assert [(row["how"], row["by"], row["with"]) for row in settled] == [("right", "researcher", "confirm")] * 2


def test_asking_the_lead_starts_a_turn_naming_the_difference_and_its_next_write_is_read_again(client, workspace, team, turn):
    workspace.pi.client.reply = lambda body: {"mismatches": [DUE] if json.loads(body["prompt"])["charter"]["quantities"]["due"]["value"][3] != 110 else []}
    written = write(workspace, team, turn, charter=LATE)
    outcome = settle(client, workspace, 1, {"m1": "ask_lead"}, text="The fourth bake is due at 110.")["outcome"]
    run = workspace.store.get(outcome["run_id"], "agent_run")
    assert run["agent_id"] == team["id"] and run["origin"]["actor"] == "researcher" and run["origin"]["charter_id"] == written["charter_id"]
    assert ("second reading found it differs from their words (revision 1)" in run["input"] and "quantities.due.value (different): They gave 110" in run["input"]
            and f"Their words: \"{DUE['quote']}\"" in run["input"] and "They add: The fourth bake is due at 110." in run["input"] and "charter_read" in run["input"])
    settled = note_of(workspace)["quick"]["reading"]["mismatches"][0]["settled"]
    assert (settled["how"], settled["by"], settled["text"]) == ("ask_lead", "researcher", "The fourth bake is due at 110.")
    assert "The lead is fixing what you asked it to (quantities.due.value)" in confirm(client, workspace, written, expect=409)["detail"]
    step = definition(workspace, workspace.store.get("demo", "campaign"))["step"]
    assert step["asked"] == ["quantities.due.value"] and "differences" not in step
    assert "The researcher asked you to fix: quantities.due.value (charter_read has the reading)." in state_of(workspace, team)
    # The lead's turn writes the charter again from their words: that revision is read again, and is the one to confirm.
    fixed = write(workspace, team, submitted(workspace, run["id"]), call="fixed")
    assert (fixed["revision"], fixed["reading"]["revision"], fixed["reading"]["mismatches"]) == (2, 2, [])
    assert confirm(client, workspace, fixed)["outcome"]["charter"] == {"id": written["charter_id"], "revision": 2}


def test_the_researchers_word_that_the_charter_is_right_holds_for_a_later_reading_while_the_charter_says_the_same(client, workspace, team, turn):
    workspace.pi.client.reply = {"mismatches": [DUE]}
    write(workspace, team, turn, charter=LATE)
    settle(client, workspace, 1, {"m1": "right"})
    # The lead writes again without changing the due times: the same difference is found, and stays settled.
    write(workspace, team, turn, call="again", charter={**LATE, "summary": "Eight bakes, one oven, as little lateness as possible."})
    held = note_of(workspace)["quick"]
    assert held["reading"]["revision"] == 2 and held["reading"]["mismatches"][0]["settled"] == {
        "how": "right", "by": "researcher", "at": held["settled"][0]["at"], "carried_from": 1}
    assert readings.check(workspace, note_of(workspace))["id"] == "note_demo"   # nothing is left to settle before confirming
    # Once the charter says something else there, the researcher's word no longer covers it.
    changed = charter(quantities={**copy.deepcopy(BAKING["quantities"]), "due": {**BAKING["quantities"]["due"], "value": [210, 130, 200, 160, 190, 100, 40, 120]}})
    other = write(workspace, team, turn, call="other", charter=changed)
    assert note_of(workspace)["quick"]["reading"]["mismatches"][0]["settled"] is None
    assert "Settle each difference" in confirm(client, workspace, other, expect=409)["detail"]


def test_the_confirmation_waits_for_a_reading_that_runs_and_asks_for_one_that_never_ran(client, workspace, team, turn):
    seen = []

    def reply(body):   # the researcher confirms while the call runs
        charter_id = workspace.store.get("note_demo", "problem_note")["charter_id"]
        seen.append(command(client, "problem_note.confirm", "demo", {"note_id": "note_demo", "charter_id": charter_id, "revision": 1},
                            version(workspace), expect=409)["detail"])
        return {"mismatches": []}
    workspace.pi.client.reply = reply
    written = write(workspace, team, turn)
    assert seen == ["The second reading of the lead's charter (revision 1) is running: confirm when the lead has replied"]
    assert written["reading"]["status"] == "completed"
    # A write the lead left with a blocking finding is not read; the researcher fills the value on the Charter tab.
    broken = write(workspace, team, turn, call="broken", charter=BROKEN)
    assert broken["reading"] is None
    response = client.post(f"/api/v1/problem-charters/{broken['charter_id']}/edit", json={"expected_revision": 2, "changes": [
        {"op": "set", "path": "quantities.n_bakes.value", "value": 8}]})
    assert response.status_code == 200, response.text
    refused = confirm(client, workspace, broken, expect=409)["detail"]
    assert refused.startswith("The lead's charter (revision 2) has not been read against your words: it had blocking findings of the lead's")
    # The lead writes it again (the researcher's value kept), and that revision is read: their value is their word.
    workspace.pi.client.reply = None
    again = write(workspace, team, turn, call="again")
    assert again["reading"]["revision"] == 4 and json.loads(workspace.pi.client.calls[-1]["prompt"])["words"]["set_on_the_charter"] == {"n_bakes": "8"}
    assert confirm(client, workspace, again)["outcome"]["charter"]["revision"] == 4


class Billed(Reader):
    """The formulator's model billed per token, with its price listed."""
    def status(self):
        status = super().status()
        for provider in status["providers"].values():
            provider["billing"] = "api"
        for model in status["models"]:
            model["cost"] = {"input": 5.0, "output": 20.0}
        return status


@pytest.mark.parametrize("case, reply, refused, reason", [
    ("a reply off its schema", {"mismatches": [{"quote": "x", "path": "due", "kind": "wrong"}]}, False,
     "the second reading could not run: The model returned an invalid structured result"),
    ("a failed call", ValueError("the agent service is down"), False, "the second reading could not run: The model call failed: the agent service is down"),
    ("no model", "no model", True, "the second reading could not run: the agent service offers no model for it"),
    ("over the budget", "budget", True, "the second reading could not run: the campaign's model budget cannot cover it: it may cost up to $"),
])
def test_a_reading_that_cannot_run_ends_the_quick_path(client, workspace, team, turn, monkeypatch, case, reply, refused, reason):
    if reply == "no model":
        monkeypatch.setattr(workspace.pi.client, "status", lambda: {"configured": True, "providers": {}, "models": []})
    elif reply == "budget":
        monkeypatch.setattr(workspace.pi, "client", Billed(team))
        campaign = workspace.store.get("demo", "campaign")
        workspace.store.put("campaign", {**campaign, "llm_budget_usd": 0.01})
    else:
        workspace.pi.client.reply = reply
    written = write(workspace, team, turn)
    record = workspace.store.get(f"charter_reading_{written['charter_id']}_r1", "charter_reading")
    assert record["status"] == ("refused" if refused else "failed") and reason.split("could not run: ")[1] in record["error"]
    assert written["quick_path"]["holds"] is False and written["quick_path"]["ended"].startswith(reason), written["quick_path"]
    assert written["link"] == "#note" and written["next"].startswith("The quick path ended: the second reading could not run")
    note = note_of(workspace)
    assert (note["path"], note["quick"]["failed"], note["quick"]["ended_by"], note["quick"]["reading"]["status"]) == ("full", ["reading"], "lead", record["status"])
    assert workspace.charters.get(written["charter_id"])["writer"] == "formulator"
    assert "full path" in confirm(client, workspace, written, expect=409)["detail"]
