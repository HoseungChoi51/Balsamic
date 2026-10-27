"""A campaign's tasks adopt the problem an installed library provides for its charter's declared problem (roadmap E4): new
tasks compiled from the charter replace the declared ones, the old ones are superseded and never rebound, one campaign version
and one study for the adoption, and an immutable record links the old evaluator requirement to the install."""
import pytest

from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, CampaignUpdate
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace
from test_problem_charter import installed, reactor
from test_mandates import granted


def library_install(workspace, cid, identity="library_install_reactor", **fields):
    return workspace.store.put("library_install", {"id": identity, "campaign_id": cid, "workspace_id": "development_reactor",
        "submission_id": "submission_reactor", "commit": "abc1234def", "package": "reactor-lab", "version": "0.2.0",
        "path": "libraries/reactor-lab", "entry_points": {}, "problem_entry_points": {"flow_reactor_yield": "reactor_lab:Problem"},
        "actor": "researcher", "status": "installed", "methods_added": [], "missing_methods": [], "problems_added": ["flow_reactor_yield"],
        "missing_problems": [], **fields})


@pytest.fixture
def declared(tmp_path):
    """A campaign made from a charter that declares flow_reactor_yield, before any library provides it."""
    workspace = Workspace(tmp_path)
    confirmed = workspace.charters.confirm(workspace.charters.create(reactor(), source={"kind": "test"})["id"])
    campaign = workspace.create_campaign(CampaignInput(name="Reactor", charter=confirmed["charter"], compute_budget_seconds=600,
                                                       validation_reserve_seconds=0))
    return workspace, campaign["id"]


@pytest.fixture
def provided(monkeypatch):
    """The library that provides flow_reactor_yield, installed in the lab's registry."""
    registry = installed(reactor(), distribution="reactor-lab")
    monkeypatch.setitem(problems._loaders, "flow_reactor_yield", registry._loaders["flow_reactor_yield"])
    monkeypatch.delitem(problems._adapters, "flow_reactor_yield", raising=False)


def adopt(workspace, cid, identity, install_id="library_install_reactor", actor="researcher"):
    campaign = workspace.store.get(cid, "campaign")
    extra = {}
    if actor == "manager":
        extra = {"expected_guidance_revision": workspace.memory.state(cid)["guidance_revision"],
                 "expected_authority_hash": workspace.commands.authority_hash(campaign)}
    return workspace.commands.execute(Command(id=identity, campaign_id=cid, expected_revision=campaign["version"],
        operation="campaign.adopt_problem", payload={"install_id": install_id}, **extra), actor=actor)


def test_adopting_creates_a_provided_task_supersedes_the_declared_one_and_bumps_the_version_once(declared, provided):
    workspace, cid = declared
    before = workspace.store.get(cid, "campaign")
    old, = workspace.current_tasks(cid)
    assert old["evaluator_manifest"]["id"] == "flow_reactor_yield" and old["evaluator_requirement_id"]
    install = library_install(workspace, cid)
    receipt = adopt(workspace, cid, "adopt_reactor")
    outcome = receipt["outcome"]
    assert receipt["actor"] == "researcher" and outcome["problem_id"] == "flow_reactor_yield"
    (row,) = outcome["adopted"]
    assert row["old_task_id"] == old["id"] and row["new_task_id"] != old["id"]
    # One campaign version and one new study for the adoption.
    after = workspace.store.get(cid, "campaign")
    assert after["version"] == before["version"] + 1 == outcome["campaign_version"]
    assert after["active_study_id"] == outcome["study_id"] != before["active_study_id"]
    study = workspace.store.get(outcome["study_id"], "study")
    assert study["parent_study_id"] == before["active_study_id"]
    # The new task runs the installed problem and names what provides it.
    task, = workspace.current_tasks(cid)
    assert task["id"] == row["new_task_id"] and task["name"] == old["name"]
    assert task["problem_id"] == "flow_reactor_yield" and task.get("evaluator_manifest") is None and not task.get("evaluator_requirement_id")
    assert task["configuration"] == old["configuration"] and task["fidelity"] == old["fidelity"]
    assert task["problem"]["primary_objective"]["name"] == "isolated_yield" and task["charter_version"] == after["version"]
    assert task["provided_by"] == {"package": "reactor-lab", "version": "0.2.0", "commit": "abc1234def",
                                   "submission_id": "submission_reactor", "install_id": install["id"]}
    # The old task is kept as it was, never rebound: superseded by the new one.
    superseded = workspace.store.get(old["id"], "task")
    assert superseded["superseded_by_task_id"] == task["id"] and superseded["archived"]
    assert superseded["evaluator_manifest"] == old["evaluator_manifest"] and superseded["evaluator_requirement_id"] == old["evaluator_requirement_id"]
    # An immutable record links the old evaluator requirement to the install.
    satisfaction = workspace.store.get(row["satisfaction_id"], "evaluator_requirement_satisfaction")
    assert satisfaction["requirement_id"] == old["evaluator_requirement_id"] and satisfaction["install_id"] == install["id"]
    assert satisfaction["task_id"] == old["id"] and satisfaction["new_task_id"] == task["id"] and satisfaction["authority"] == "researcher"
    assert satisfaction["content_hash"]
    # The installed task needs no commissioned evaluator.
    assert workspace.evaluators.binding(task) is None and "requires a validated evaluator" not in str(workspace.evaluators.readiness(task, wait=False))


def test_adopting_the_same_install_again_changes_nothing(declared, provided):
    workspace, cid = declared
    library_install(workspace, cid)
    first = adopt(workspace, cid, "adopt_reactor")["outcome"]
    tasks, campaign = workspace.store.list("task", cid), workspace.store.get(cid, "campaign")
    again = adopt(workspace, cid, "adopt_reactor_again")["outcome"]
    assert again["adopted"] == [] and again["campaign_version"] == first["campaign_version"] and again["study_id"] == first["study_id"]
    assert workspace.store.list("task", cid) == tasks and workspace.store.get(cid, "campaign") == campaign
    assert len(workspace.store.list("evaluator_requirement_satisfaction", cid)) == 1
    # Called directly, as Balsamic's own step will, it changes nothing either.
    assert workspace.adopt_library_problem(cid, "library_install_reactor")["adopted"] == []


def test_a_superseded_task_is_not_current_and_revising_the_charter_later_still_works(declared, provided):
    workspace, cid = declared
    old, = workspace.current_tasks(cid)
    library_install(workspace, cid)
    new_id = adopt(workspace, cid, "adopt_reactor")["outcome"]["adopted"][0]["new_task_id"]
    assert [task["id"] for task in workspace.current_tasks(cid)] == [new_id]
    # current_tasks leaves a superseded task out even where it was not archived (as a record written by another path).
    workspace.store.put("task", {**workspace.store.get(old["id"], "task"), "archived": False})
    assert [task["id"] for task in workspace.current_tasks(cid)] == [new_id]
    workspace.store.put("task", {**workspace.store.get(old["id"], "task"), "archived": True})
    # A later revision of the charter compiles against the current tasks; the superseded declared one is not re-validated.
    charter = workspace.store.get(cid, "campaign")["charter"]
    workspace.charters.edit(charter["id"], [{"op": "set", "path": "quantities.pressure_bar.value", "value": 8.0}])
    second = workspace.charters.confirm(charter["id"])
    workspace.update_campaign(cid, CampaignUpdate(charter=second["charter"]))
    task, = workspace.current_tasks(cid)
    assert task["problem_id"] == "flow_reactor_yield" and task["configuration"]["pressure_bar"] == 8.0 and not task.get("evaluator_manifest")


def test_the_lead_can_adopt_and_an_install_that_does_not_provide_the_problem_is_refused(declared, provided):
    workspace, cid = declared
    workspace.store.put("campaign", {**workspace.store.get(cid, "campaign"), "autonomy": "delegated"})
    library_install(workspace, cid, "library_install_other", problem_entry_points={"other_problem": "x:Y"}, problems_added=["other_problem"])
    library_install(workspace, cid, "library_install_failed", status="failed")
    with pytest.raises(ValueError, match="reactor-lab does not provide the problem the campaign's charter declares \\(flow_reactor_yield\\)"):
        adopt(workspace, cid, "adopt_other", "library_install_other")
    with pytest.raises(ValueError, match="is failed, not installed"):
        adopt(workspace, cid, "adopt_failed", "library_install_failed")
    library_install(workspace, cid)
    granted(workspace, cid, "screen")   # adopting is implement work: the lead's request needs a Screen mandate (R3)
    receipt = adopt(workspace, cid, "lead_adopts", actor="manager")
    assert receipt["actor"] == "manager" and len(receipt["outcome"]["adopted"]) == 1


def test_without_the_library_in_the_registry_nothing_is_adopted(declared):
    workspace, cid = declared
    library_install(workspace, cid)
    with pytest.raises(ValueError, match="still compiles flow_reactor_yield as a declared problem"):
        adopt(workspace, cid, "adopt_unseen")
    assert workspace.store.get(cid, "campaign")["version"] == 1 and workspace.current_tasks(cid)[0]["evaluator_manifest"]
