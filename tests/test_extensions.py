"""Pi extensions inside Balsamic (harness plan, Phase 4): the per-role allowlist in the manifest, receipts of extension tool
calls, and extension dialogs answered by the researcher without a turn."""
import json
import time

import pytest

from optimization_framework.agents.models import NOTICE
from optimization_framework.agents.tools import PiTools

from test_pi_agents import activated


@pytest.fixture
def allowlist(tmp_path, monkeypatch):
    folder = tmp_path / "extensions"
    (folder / "session" / "web").mkdir(parents=True)
    (folder / "session" / "web" / "index.ts").write_text("export default function () {}\n")
    (folder / "allowlist.json").write_text(json.dumps({"extensions": {"web": {"path": "session/web/index.ts", "tools": {"web_read": {"read_only": True}}}},
                                                       "roles": {"lead": ["web"], "methodology_specialist": ["web"]}}))
    monkeypatch.setenv("GRATING_PI_EXTENSIONS", str(folder / "allowlist.json"))
    return folder


@pytest.fixture
def team(tmp_path, monkeypatch, allowlist):
    w, c, lead = activated(tmp_path / "workspace", monkeypatch)
    run = w.pi.message(c["id"], {"message": "Read the paper."}, "first")
    w.store.put("agent_run", {**w.store.get(run["id"], "agent_run"), "status": "submitted"})
    return w, c, lead, w.store.get(run["id"], "agent_run")


def receipt(w, agent, run, call_id="call_1", tool="web_read", **extra):
    return PiTools(w.pi).external_receipt(agent["id"], run["id"], call_id, tool, "web", {"url": "https://example.org/paper"},
                                          "The paper reports 0.93.", 2100, **extra)


def test_the_manifest_names_the_roles_extensions_and_a_grant_has_none(team, allowlist):
    w, c, lead, run = team
    tools = PiTools(w.pi)
    manifest = tools.manifest(lead["id"], run["id"])
    assert manifest["extension_host"] is True
    assert manifest["extensions"] == [{"name": "web", "path": str((allowlist / "session" / "web" / "index.ts").resolve()), "tools": ["web_read"]}]
    operator_run = w.pi.message(c["id"], {"message": "Wait.", "page_agent": "experiment_operator"}, "op")
    w.store.put("agent_run", {**w.store.get(operator_run["id"], "agent_run"), "status": "submitted"})
    operator = tools.manifest(operator_run["agent_id"], operator_run["id"])
    assert operator["extension_host"] is True and operator["extensions"] == []
    builder = w.pi.create_agent(c["id"], "implementation_builder", "Build", "builder_x", parent_id=lead["id"], grant_id="grant_x")
    built = w.pi.enqueue(builder, "builder_run", "Build it")
    w.store.put("agent_run", {**built, "status": "submitted"})
    grant = tools.manifest(builder["id"], built["id"])
    assert grant["extension_host"] is False and grant["extensions"] == []
    # An allowlist that names a path outside its folder is refused.
    (allowlist / "allowlist.json").write_text(json.dumps({"extensions": {"evil": {"path": "../../evil.ts"}}, "roles": {}}))
    with pytest.raises(ValueError, match="outside"):
        tools.manifest(lead["id"], run["id"])


def test_an_extension_tool_call_is_receipted_once_and_readable_in_its_campaign_only(team, tmp_path, monkeypatch):
    w, c, lead, run = team
    first = receipt(w, lead, run)
    assert receipt(w, lead, run) == first, "the same call posted again is the same receipt"
    saved = w.store.get(first["receipt_id"], "agent_tool_receipt")
    assert saved["external"] is True and saved["extension"] == "web" and saved["tool"] == "web_read" and saved["run_id"] == run["id"]
    assert saved["result"] == {"external": True, "excerpt": "The paper reports 0.93.", "bytes": 2100, "is_error": False, "annotations": None}
    with pytest.raises(ValueError, match="another request"):
        PiTools(w.pi).external_receipt(lead["id"], run["id"], "call_1", "web_read", "web", {"url": "https://other"}, "x", 1)
    with pytest.raises(ValueError):
        w.store.put_immutable("agent_tool_receipt", {**saved, "result": {"excerpt": "changed"}})
    # The lead reads it like any record of its campaign.
    assert PiTools(w.pi).call(lead["id"], run["id"], "read", "evidence_read", {"record_id": first["receipt_id"], "pointer": "/result/excerpt"}) == "The paper reports 0.93."
    # An agent of another campaign cannot read it.
    with pytest.raises(ValueError, match="not readable within this campaign"):
        PiTools(w.pi).record({**lead, "campaign_id": "campaign_elsewhere"}, first["receipt_id"])


def test_a_receipt_is_refused_for_a_tool_off_the_list_a_foreign_agent_or_a_finished_run(team):
    w, c, lead, run = team
    with pytest.raises(ValueError, match="not an extension tool allowlisted for the lead"):
        receipt(w, lead, run, tool="shell_exec")
    with pytest.raises(ValueError, match="receipted by the workspace itself"):
        receipt(w, lead, run, tool="campaign_inspect")
    operator_run = w.pi.message(c["id"], {"message": "Wait.", "page_agent": "experiment_operator"}, "op")
    operator = w.store.get(operator_run["agent_id"], "agent_session")
    with pytest.raises(ValueError, match="not owned"):
        receipt(w, operator, run)   # another agent's run
    w.store.put("agent_run", {**w.store.get(run["id"], "agent_run"), "status": "completed"})
    with pytest.raises(ValueError, match="not active"):
        receipt(w, lead, run, call_id="late")


def test_an_extension_dialog_is_answered_without_a_turn_and_can_be_dismissed(team):
    w, c, lead, run = team
    tools = PiTools(w.pi)
    runs_before = len(w.store.list("agent_run"))
    asked = tools.ui_request(lead["id"], run["id"], "req_1", "select", "Which source?", options=["arXiv", "Crossref"])
    assert asked["status"] == "pending" and tools.ui_request(lead["id"], run["id"], "req_1", "select", "Which source?", options=["arXiv", "Crossref"])["question_id"] == asked["question_id"]
    question = w.store.get(asked["question_id"], "agent_question")
    assert question["kind"] == "extension_dialog" and question["dialog"] == {"method": "select", "title": "Which source?", "options": ["arXiv", "Crossref"]}
    assert question["deadline_at"] - time.time() == pytest.approx(900, abs=5)
    assert asked["question_id"] in {q["id"] for q in w.pi.view(c["id"])["questions"]}, "it shows where the researcher's questions show"
    # It holds no request open and is not one of the questions the state block lists.
    assert tools.outstanding(lead) == "" and "Which source?" not in tools.turn_state(lead["id"], run["id"])["text"]
    # Answered by message it is refused; with agent.ui_respond, a listed option only.
    with pytest.raises(ValueError, match="agent.ui_respond"):
        w.pi.message(c["id"], {"message": "arXiv", "question_id": asked["question_id"]}, "by_message")
    with pytest.raises(ValueError, match="options"):
        w.pi.ui_respond(c["id"], {"question_id": asked["question_id"], "value": "PubMed"})
    request_open, guidance = w.pi.configuration(c["id"])["request_open"], w.memory.state(c["id"])["guidance_revision"]
    w.pi.ui_respond(c["id"], {"question_id": asked["question_id"], "value": "arXiv"})
    assert tools.ui_state(lead["id"], asked["question_id"]) == {"question_id": asked["question_id"], "status": "answered", "deadline_at": question["deadline_at"], "value": "arXiv"}
    assert len(w.store.list("agent_run")) == runs_before and w.pi.configuration(c["id"])["request_open"] == request_open
    assert w.memory.state(c["id"])["guidance_revision"] == guidance, "an answer to a dialog changes no guidance"
    # Dismissed, it is cancelled; a confirm takes yes or no; past its deadline it expires.
    confirm = tools.ui_request(lead["id"], run["id"], "req_2", "confirm", "Fetch 40 pages?", message="It takes a minute.")
    with pytest.raises(ValueError, match="yes or no"):
        w.pi.ui_respond(c["id"], {"question_id": confirm["question_id"], "value": "yes"})
    w.pi.dismiss_question(c["id"], {"question_id": confirm["question_id"]})
    assert tools.ui_state(lead["id"], confirm["question_id"])["status"] == "cancelled"
    short = tools.ui_request(lead["id"], run["id"], "req_3", "input", "Your name?", timeout_ms=1000)
    w.store.put("agent_question", {**w.store.get(short["question_id"], "agent_question"), "deadline_at": time.time() - 1})
    assert tools.ui_state(lead["id"], short["question_id"])["status"] == "expired"
    with pytest.raises(ValueError, match="no longer waiting"):
        w.pi.ui_respond(c["id"], {"question_id": short["question_id"], "value": "x"})
    with pytest.raises(ValueError, match="Not this agent"):
        tools.ui_state("lead_other", asked["question_id"])
    # The researcher command goes through the bus and is the researcher's.
    from optimization_framework.contracts.commands import Command
    cancel = tools.ui_request(lead["id"], run["id"], "req_4", "editor", "Edit the query")
    w.commands.execute(Command(id="cancel_dialog", campaign_id=c["id"], expected_revision=w.store.get(c["id"], "campaign")["version"],
                               operation="agent.ui_respond", payload={"question_id": cancel["question_id"], "cancelled": True}))
    assert tools.ui_state(lead["id"], cancel["question_id"])["status"] == "cancelled"


def test_under_autopilot_a_dialog_is_cancelled_at_once(team):
    w, c, lead, run = team
    round_run = w.pi.enqueue(w.store.get(lead["id"], "agent_session"), "autopilot_round_1", NOTICE + "Autopilot round 1.", autopilot=True)
    w.store.put("agent_run", {**round_run, "status": "submitted"})
    answer = PiTools(w.pi).ui_request(lead["id"], round_run["id"], "req", "confirm", "Proceed?")
    assert answer["status"] == "cancelled" and not [q for q in w.store.list("agent_question") if q.get("kind") == "extension_dialog"]


def test_the_controller_still_asks_for_a_checkpoint_when_the_turn_ends_without_one(team):
    """The in-turn continuation lives in the harness's Balsamic extension; when it too ends without yield_work, the controller's
    pi_continue notice and its stall count stay as they were."""
    w, c, lead, run = team
    rid = run["id"]
    for index in range(3):
        w.pi._receive(lead["id"], {"runs": {rid: {"status": "completed", "result": {"text": "An answer in prose."}}}, "events": [], "cursor": 0})
        nudges = [r for r in w.store.list("agent_run") if r["id"].startswith("pi_continue_")]
        if index < 2:
            rid = nudges[-1]["id"]
            w.store.put("agent_run", {**w.store.get(rid, "agent_run"), "status": "submitted"})
    assert len(nudges) == 2 and w.store.get(lead["id"], "agent_session")["uncheckpointed_turns"] == 3
    assert any(q["id"].startswith("pi_stalled_") for q in w.store.list("agent_question", c["id"]))
