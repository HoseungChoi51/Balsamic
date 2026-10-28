"""When the quick path holds, and the fall back (roadmap P3, decision 31): code criteria on each charter_write of the lead; when one
fails, or the researcher asks for the full path, the note goes to the full path written from the lead's charter, and at Adopt the
formulator takes that charter as its own."""
import copy

import pytest

from support import command, state_of, tool_call
from test_quick_charter import BAKING, GAP, charter, formulating, team, turn, version, write  # noqa: F401  (the fixtures)
from balsamic.evolution.stages import definition
from optimization_framework.contracts.commands import Command


def inputs(count):
    """The baking charter with this many input quantities: the three it needs, and unused ones up to count."""
    extra = {f"spare_{n}": {"description": f"A spare number {n}", "kind": "number", "value": n, "units": "1", "citation": 1} for n in range(count - 3)}
    return charter(quantities={**copy.deepcopy(BAKING["quantities"]), **extra})


def variables(count):
    extra = [{"name": f"knob_{n}", "description": f"A knob {n}", "representation": "continuous", "lower": 0, "upper": 1, "units": "1"} for n in range(count - 1)]
    return charter(variables=copy.deepcopy(BAKING["variables"]) + extra)


def evaluator(**changes):
    return charter(evaluator={**copy.deepcopy(BAKING["evaluator"]), **changes})


BROKEN = charter(quantities={**copy.deepcopy(BAKING["quantities"]), "n_bakes": {**BAKING["quantities"]["n_bakes"], "value": None}})


def ended_note(workspace):
    return workspace.store.get("note_demo", "problem_note")


@pytest.mark.parametrize("case, writes, failed, reason", [
    ("not deterministic", [{"charter": evaluator(deterministic=False)}], "deterministic", "the evaluator is not deterministic"),
    ("an oracle", [{"charter": evaluator(access="oracle")}], "evaluator", "the evaluator is an oracle"),
    ("a fidelity field", [{"charter": evaluator(fidelity={"bakes": "n_bakes"})}], "evaluator", "the evaluator has fidelity fields (bakes)"),
    ("four variables", [{"charter": variables(4)}], "size", "it has 4 decision variables (the quick path takes at most 3)"),
    ("eleven inputs", [{"charter": inputs(11)}], "size", "it has 11 inputs (the quick path takes at most 10)"),
    ("a fourth save with a blocking finding", [{"charter": BROKEN}] * 4, "findings", "2 blocking findings left after 4 saves: n_bakes has no value"),
    ("three questions", [{"questions": [GAP, {**GAP, "id": "second"}, {**GAP, "id": "third"}]}], "questions",
     "it asks 3 questions (the quick path asks at most 2, in one round)"),
    ("a second round", [{"questions": [GAP]}, {"questions": [{**GAP, "id": "again"}]}], "questions", "it asks a second round of questions"),
])
def test_each_criterion_that_fails_ends_the_quick_path_with_its_reason(client, workspace, team, turn, case, writes, failed, reason):
    for number, args in enumerate(writes[:-1]):
        held = write(workspace, team, turn, call=f"held{number}", **args)
        assert held["quick_path"]["holds"] is True and ended_note(workspace)["path"] == "quick", held["quick_path"]
    if case.startswith("a fourth save"):   # the lead is told before the last save it has
        assert held["saves"] == 3 and held["next"].endswith("If your next write still leaves a blocking finding, the quick path ends.")
    written = write(workspace, team, turn, call="last", **writes[-1])
    assert written["quick_path"]["holds"] is False and reason in written["quick_path"]["ended"], written["quick_path"]
    assert written["link"] == "#note" and written["next"].startswith("The quick path ended: ") and "problem-formulation" in written["next"]
    note = ended_note(workspace)
    assert (note["path"], note["charter_id"], note["quick"]["charter_id"], note["quick"]["ended_by"]) == ("full", None, written["charter_id"], "lead")
    assert failed in note["quick"]["failed"] and reason in note["quick"]["ended"]
    # The lead's charter is kept as it wrote it, and is the formulator's to write from now on.
    record = workspace.charters.get(written["charter_id"])
    assert record["revision"] == written["revision"] and record["writer"] == "formulator" and record.get("import_id") is None
    if failed == "questions":   # not asked on the charter: the full path asks them in the conversation
        assert workspace.charters.view(record["id"])["question_rounds"] == len(writes) - 1
        assert any(item.endswith("To ask the researcher (options: No pause (recommended); Five minutes).")
                   for item in workspace.store.get(f"note_demo_r{note['current_revision']}", "problem_note_revision")["sections"]["open_questions"]["items"])
    refused = write(workspace, team, turn, call="after")
    assert refused["error"].startswith("The quick path ended (") and workspace.charters.get(record["id"])["revision"] == record["revision"]


def test_the_hand_over_writes_the_note_from_the_charter_and_adopt_gives_the_formulator_that_charter(client, workspace, team, turn, monkeypatch):
    assumed = evaluator(deterministic=False)
    assumed["assumptions"] = [{"statement": "Bakes run back to back, with no pause between them", "about": ["minutes"]}]
    written = write(workspace, team, turn, charter=assumed, confounders={"text": "The oven's temperature drifts over the day."})
    reason = written["quick_path"]["ended"]
    assert reason == "the evaluator is not deterministic: evaluations of one design differ"
    # The note is on the full path, its sections a revision of the lead's written from the charter.
    note = ended_note(workspace)
    revision = workspace.store.get(f"note_demo_r{note['current_revision']}", "problem_note_revision")
    assert revision["author"] == "lead" and revision["reason"] == f"Written from the lead's charter, revision 1: the quick path ended ({reason})"
    sections = revision["sections"]
    assert sections["objective"]["text"].startswith("One oven takes 8 bakes") and sections["noise"]["text"].startswith("Not deterministic")
    assert any(item.startswith("minutes = [30, 45, 20, 60, 35, 25, 50, 40]") for item in sections["knobs"]["items"])
    assert sections["confounders"]["text"] == "The oven's temperature drifts over the day."
    assert sections["open_questions"]["items"] == ["Assumption: Bakes run back to back, with no pause between them"]
    # The gate is the full path's, says why the quick path ended, and the quick path's confirmation is refused.
    gate = definition(workspace, workspace.store.get("demo", "campaign"))
    assert (gate["step"]["kind"], gate["step"]["path"], gate["step"]["quick_ended"]) == ("adopt", "full", reason)
    assert "the formulator then revises that charter" in gate["step"]["text"]
    assert f"Gate: closed on the full path. Next: adopt the problem note (#note). The quick path ended: {reason}." in state_of(workspace, team)
    payload = {"note_id": "note_demo", "charter_id": written["charter_id"], "revision": 1}
    assert "full path" in command(client, "problem_note.confirm", "demo", payload, version(workspace), expect=409)["detail"]
    read = tool_call(workspace, team, turn, "charter_read", {}, call_id="read")
    assert (read["id"], read["writer"], read["path"], read["quick_path"]["ended"]) == (written["charter_id"], "formulator", "full", reason)
    # Adopt: the formulator takes the lead's charter as its own, and its first prompt says why the quick path did not hold.
    pi = formulator_model(workspace, monkeypatch)
    adopted = command(client, "problem_note.adopt", "demo", {"note_id": "note_demo", "revision": note["current_revision"]}, version(workspace))["outcome"]
    record = workspace.problem_imports.get(adopted["import_id"])
    assert record["charter_id"] == written["charter_id"] and record["lead_draft"] == {"charter_id": written["charter_id"], "revision": 1, "reason": reason}
    charter_record = workspace.charters.get(written["charter_id"])
    assert (charter_record["import_id"], charter_record["writer"]) == (record["id"], "formulator")
    agent, run = pi.submitted[-1]
    assert agent["role"] == "formulator" and "documents/researcher.md.txt" in run["input"]
    assert f"the quick path did not hold: {reason}. It is your charter now: read it with charter_read" in run["input"]
    # Its charter_submit revises the same charter, and the note's Charter tab follows it.
    saved = workspace.problem_imports.call(record["id"], run["id"], "c1", "charter_submit", {"charter": evaluator(deterministic=False)})
    assert saved["saved"] and saved["revision"] == 2 and workspace.charters.get(written["charter_id"])["history"][-1]["by"] == "formulator"
    view = client.get("/api/v1/campaigns/demo/problem-note").json()
    assert view["note"]["charter_id"] == written["charter_id"] and view["charter"]["charter"]["writer"] == "formulator"


def test_only_the_researcher_takes_the_note_to_the_full_path(client, workspace, team, turn):
    written = write(workspace, team, turn)
    assert written["quick_path"]["holds"] is True and {row["id"] for row in written["quick_path"]["criteria"]} == {
        "conversation", "evaluator", "deterministic", "size", "findings", "questions", "reading"}
    pinned = {"expected_guidance_revision": workspace.memory.state("demo")["guidance_revision"],
              "expected_authority_hash": workspace.commands.authority_hash(workspace.store.get("demo", "campaign"))}
    with pytest.raises(ValueError, match="needs researcher authorization"):
        workspace.commands.execute(Command(id="cmd_autopilot", campaign_id="demo", operation="problem_note.full_path", expected_revision=version(workspace),
                                           payload={"note_id": "note_demo"}, **pinned), actor="autopilot")
    assert ended_note(workspace)["path"] == "quick"
    outcome = command(client, "problem_note.full_path", "demo", {"note_id": "note_demo"}, version(workspace))["outcome"]
    note = ended_note(workspace)
    assert (outcome["path"], outcome["charter_id"], note["path"], note["quick"]["ended"], note["quick"]["ended_by"]) == (
        "full", written["charter_id"], "full", "the researcher chose the full path", "researcher")
    assert workspace.store.get(f"note_demo_r{note['current_revision']}", "problem_note_revision")["sections"]["knobs"]["items"]
    assert "not on the quick path: it ended (the researcher chose the full path)" in command(
        client, "problem_note.full_path", "demo", {"note_id": "note_demo"}, version(workspace), expect=409)["detail"]


def test_a_confirmed_quick_charter_stays_on_the_quick_path(client, workspace, team, turn):
    written = write(workspace, team, turn)
    command(client, "problem_note.confirm", "demo", {"note_id": "note_demo", "charter_id": written["charter_id"], "revision": 1}, version(workspace))
    refused = command(client, "problem_note.full_path", "demo", {"note_id": "note_demo"}, version(workspace), expect=409)
    assert "The charter is confirmed" in refused["detail"] and ended_note(workspace)["path"] == "quick"


class Model:
    """The formulator's model client, as the harness answers it: one signed-in model, runs recorded."""
    def __init__(self):
        self.submitted = []

    def status(self):
        return {"configured": True, "mode": "dev", "defaults": {}, "providers": {"deepseek": {"auth": "api_key", "billing": "api"}},
                "models": [{"provider": "deepseek", "id": "deepseek-v4-pro", "thinking_levels": ["off", "high"]}]}

    def submit(self, agent, run):
        self.submitted.append((agent, run))

    def inspect(self, agent_id, after=0):
        return {"runs": {}, "events": [], "cursor": after}

    def control(self, agent_id, action):
        pass


def formulator_model(workspace, monkeypatch):
    from optimization_framework.agents import tiers
    tiers.save(workspace.store, tiers.TierSettings.model_validate({"tiers": [
        {"id": "strong", "label": "Strong", "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "effort": "high"}}], "roles": {"formulator": "strong"}}))
    model = Model()
    monkeypatch.setattr(workspace.problem_imports, "_client", model)
    return model
