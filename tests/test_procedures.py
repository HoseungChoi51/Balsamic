"""Procedures (harness plan, Phase 6): workflow instructions read on demand with procedure_read, a per-role catalog in the
static instructions, and a hint in the result of a workflow-starting call that came without its procedure."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent / "balsamic"))
from support import QUADRATIC, activate_team, command, submitted  # noqa: E402

from balsamic import procedures as module  # noqa: E402
from balsamic.procedures import COMMAND_HINTS, TOOL_HINTS, Procedures  # noqa: E402
from optimization_framework.agents.models import ROLES  # noqa: E402
from optimization_framework.agents.tools import EXTRA_TOOLS, PiTools  # noqa: E402

MAIN = "thread_main_demo"


@pytest.fixture
def team(tmp_path, monkeypatch):
    from balsamic.app import create_app
    monkeypatch.setenv("GRATING_LLM_DISABLED", "true")
    app = create_app(tmp_path / "workspace", start_workers=False)
    with TestClient(app) as client:
        workspace = app.state.workspace
        campaign = command(client, "campaign.create", "demo", {"name": "Demo", "objective": "Find a better optimizer", "tasks": [QUADRATIC],
                                                               "compute_budget_seconds": 600}, 0)["outcome"]["campaign"]
        lead = activate_team(client, workspace, campaign, monkeypatch)
        def turn(text):
            version = workspace.store.get("demo", "campaign")["version"]
            return submitted(workspace, "pi_run_" + command(client, "agent.message", "demo", {"message": text, "thread_id": MAIN}, version, origin={"thread_id": MAIN})["id"])
        yield SimpleNamespace(client=client, workspace=workspace, lead=lead, turn=turn, tools=PiTools(workspace.pi))


def test_every_procedure_is_a_valid_skill_for_real_roles_and_every_hint_names_one():
    catalog = Procedures()
    assert {"report-brief", "problem-formulation", "proposal-fields", "journal-cleanup", "recording-findings", "runtime-profiling",
            "implementation-supervision", "panels", "analysis-scripts"} <= set(catalog.items)
    # A problem's own procedures are in its pack (roadmap N3), not among the generic ones.
    assert not {"rcwa-convergence-check", "meent-problem-setup"} & set(catalog.items)
    for name, item in catalog.items.items():
        assert item["roles"] and item["roles"] <= set(ROLES), name
        assert len(item["description"]) <= 1024 and item["body"].startswith("# "), name
    assert set(TOOL_HINTS.values()) | set(COMMAND_HINTS.values()) <= set(catalog.items)
    assert catalog.catalog("lead") == sorted(catalog.catalog("lead")) and catalog.catalog("implementation_builder") == []   # retired (H8)


def test_the_lead_is_given_a_short_contract_and_its_catalog(team):
    run = team.turn("Hello")
    manifest = team.tools.manifest(team.lead["id"], run["id"])
    assert "Procedures: before you start one of these workflows, read its procedure with procedure_read." in manifest["instructions"]
    assert "- report-brief: " in manifest["instructions"] and "procedure_read" in {tool["name"] for tool in manifest["tools"]}
    # The workflow texts are no longer in every turn.
    assert "Proposal fields." not in manifest["instructions"] and "journal.compaction_request" not in manifest["instructions"]


def test_a_procedure_is_read_by_its_roles_only_whole_or_cut_and_the_read_is_receipted(team, monkeypatch, tmp_path):
    run = team.turn("Write a report on the runs.")
    read = team.tools.call(team.lead["id"], run["id"], "read", "procedure_read", {"name": "report-brief"})
    assert read["name"] == "report-brief" and read["text"].startswith("# Report brief") and read["files"] == []
    # The body named as a file, as models do (lead evals S4 and S7, live), is the body.
    for named in ("", "none", "SKILL.md"):
        assert team.tools.call(team.lead["id"], run["id"], "as_" + named, "procedure_read", {"name": "report-brief", "file": named})["text"] == read["text"]
    receipt = next(r for r in team.workspace.store.list("agent_tool_receipt", "demo") if r["tool"] == "procedure_read")
    assert receipt["run_id"] == run["id"] and receipt["result"]["name"] == "report-brief"
    # Another role's procedure, an unknown one, or a file it does not bundle: refused.
    assert "No procedure" in team.tools.call(team.lead["id"], run["id"], "nope", "procedure_read", {"name": "no-such-thing"})["error"]
    assert "has no file" in team.tools.call(team.lead["id"], run["id"], "file", "procedure_read", {"name": "report-brief", "file": "../SKILL.md"})["error"]
    child = team.tools.call(team.lead["id"], run["id"], "delegate", "delegate", {"role": "methodology_specialist", "objective": "Check", "request_key": "k"})
    child_run = submitted(team.workspace, child["run_id"])
    assert "No procedure" in team.tools.call(child["agent_id"], child_run["id"], "spec_read", "procedure_read", {"name": "report-brief"})["error"]
    assert team.tools.call(child["agent_id"], child_run["id"], "spec_scripts", "procedure_read", {"name": "analysis-scripts"})["name"] == "analysis-scripts"
    # A bundled reference is read by its path; a long body is cut at the cap.
    folder = tmp_path / "procedures" / "long-one"
    (folder / "references").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: long-one\ndescription: A long test procedure.\nmetadata:\n  roles: lead\n---\n\n# Long\n" + "x" * 100)
    (folder / "references" / "detail.md").write_text("Detail.")
    monkeypatch.setattr(module, "BODY_BYTES", 40)
    catalog = Procedures(tmp_path / "procedures")
    cut = catalog.read("lead", "long-one")
    assert len(cut["text"].encode()) == 40 and "Cut at 40 bytes" in cut["note"] and cut["files"] == ["references/detail.md"]
    assert catalog.read("lead", "long-one", "references/detail.md")["text"] == "Detail."


def test_a_workflow_started_without_its_procedure_is_told_once_per_run(team):
    run = team.turn("Record two proposals.")
    propose = lambda key, run_id=None: team.tools.call(team.lead["id"], run_id or run["id"], key, "campaign_command",
        {"operation": "hypothesis.create", "request_key": key, "payload": {"title": "Strategy " + key, "mechanism": "m", "rationale": "r"}})
    assert propose("first")["procedure"] == "proposal-fields"
    assert "procedure" not in propose("second"), "at most once per run"
    # A call that failed is not told; nor is a run that read the procedure first.
    assert "procedure" not in team.tools.call(team.lead["id"], run["id"], "bad", "campaign_command",
        {"operation": "hypothesis.create", "request_key": "bad", "payload": {}})
    later = team.turn("One more.")
    team.tools.call(team.lead["id"], later["id"], "read", "procedure_read", {"name": "proposal-fields"})
    assert "procedure" not in propose("third", later["id"])
    again = team.turn("And another.")
    assert propose("fourth", again["id"])["procedure"] == "proposal-fields", "a new run is told again"
    assert "procedure_read" in EXTRA_TOOLS and "lead" in EXTRA_TOOLS["procedure_read"]["roles"]


MEENT_PROCEDURES = ("meent-problem-setup", "rcwa-convergence-check")


def meent_campaign(team, monkeypatch, campaign_id="meent"):
    task = {"name": "Grating", "problem_id": "meent_grating", "configuration": {}}
    campaign = command(team.client, "campaign.create", campaign_id, {"name": "Grating", "objective": "Find a better grating", "tasks": [task],
                                                                     "compute_budget_seconds": 600}, 0)["outcome"]["campaign"]
    lead = activate_team(team.client, team.workspace, campaign, monkeypatch)
    version = team.workspace.store.get(campaign_id, "campaign")["version"]
    run = submitted(team.workspace, "pi_run_" + command(team.client, "agent.message", campaign_id, {"message": "Hello", "thread_id": "thread_main_" + campaign_id},
                                                       version, origin={"thread_id": "thread_main_" + campaign_id})["id"])
    return lead, run


def test_a_meent_campaign_is_given_its_packs_procedures_and_another_campaign_is_refused_them(team, monkeypatch):
    """Roadmap N3: MEENT's procedures come with its pack. The cached role catalogs stay generic; the state block of a MEENT
    campaign lists them, procedure_read serves them there only, and a bounded_continuous campaign neither sees nor reads them."""
    lead, run = meent_campaign(team, monkeypatch)
    manifest = team.tools.manifest(lead["id"], run["id"])
    assert not any(name in manifest["instructions"] for name in MEENT_PROCEDURES), "the static catalog stays generic"
    state = team.tools.turn_state(lead["id"], run["id"])["text"]
    assert "Procedures for this campaign's problem" in state and all(f"- {name}: " in state for name in MEENT_PROCEDURES)
    for name in MEENT_PROCEDURES:
        read = team.tools.call(lead["id"], run["id"], "read_" + name, "procedure_read", {"name": name})
        assert read["name"] == name and read["text"].startswith("# "), read
    # A specialist of the MEENT campaign has no other state, but is told of the procedures for its role.
    child = team.tools.call(lead["id"], run["id"], "delegate", "delegate", {"role": "empirical_assessor", "objective": "Check", "request_key": "k"})
    child_run = submitted(team.workspace, child["run_id"])
    assert "- rcwa-convergence-check: " in team.tools.turn_state(child["agent_id"], child_run["id"])["text"]
    assert team.tools.call(child["agent_id"], child_run["id"], "spec", "procedure_read", {"name": "rcwa-convergence-check"})["name"] == "rcwa-convergence-check"
    # The quadratic campaign: not listed, refused, and the specialists' state stays empty.
    plain = team.turn("Hello")
    assert "Procedures for this campaign's problem" not in team.tools.turn_state(team.lead["id"], plain["id"])["text"]
    for name in MEENT_PROCEDURES:
        assert "No procedure" in team.tools.call(team.lead["id"], plain["id"], "nope_" + name, "procedure_read", {"name": name})["error"]
    other = team.tools.call(team.lead["id"], plain["id"], "delegate", "delegate", {"role": "empirical_assessor", "objective": "Check", "request_key": "k"})
    assert team.tools.turn_state(other["agent_id"], submitted(team.workspace, other["run_id"])["id"])["text"] == ""


def test_a_pack_procedure_may_not_take_a_generic_procedure_s_name(team, tmp_path, monkeypatch):
    folder = tmp_path / "pack" / "report-brief"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: report-brief\ndescription: A clash.\nmetadata:\n  roles: lead\n---\n\n# Clash\n")
    monkeypatch.setattr(team.workspace.packs, "procedure_folders", lambda campaign_id: [tmp_path / "pack"])
    with pytest.raises(ValueError, match="has the name of a generic one"):
        team.workspace.procedures.campaign(team.workspace, "demo")
