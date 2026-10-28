"""Reuse first (roadmap L5, decision 27): the method list names each installed method's package and version; an agent's coding
workspace for proposals whose named method is installed and runs on a current task is refused with the binding to make instead;
binding an installed method and applying a strategy are reuse, which Explore allows; a library entry records the winner's code,
and applying it gives a proposal bound to the method."""
import pytest

from optimization_framework.agents.tools import PiTools
from optimization_framework.campaigns import mandates, method_catalog
from optimization_framework.contracts.commands import Command
from optimization_framework.optimizers import plugins

from test_pi_development_workspaces import TICKET, setup   # noqa: F401  (the fixture)


@pytest.fixture
def packaged(monkeypatch):
    """coordinate, as if it came from the installed package coordinate-search 0.2.0 rather than with Balsamic."""
    origin = plugins.installed.origin
    monkeypatch.setattr(plugins.installed, "origin", lambda method_id: {"entry_point": "coordinate", "distribution": "coordinate-search",
        "version": "0.2.0", "own": False} if method_id == "coordinate" else origin(method_id))


def proposal(workspace, cid, identity, algorithm="coordinate", **extra):
    workspace.store.put("hypothesis", {"id": identity, "campaign_id": cid, "title": identity, "status": "proposed", "mechanism": "m",
                                       "rationale": "r", "parent_ids": [], "algorithm": algorithm, "algorithm_config": {},
                                       "algorithm_chosen": True, **extra})


def test_the_method_list_names_each_package_and_version(setup, packaged):
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    row = next(row for row in method_catalog.catalog(workspace, cid)["methods"] if row["id"] == "coordinate")
    assert row["source"] == "library" and (row["package"]["name"], row["package"]["version"]) == ("coordinate-search", "0.2.0")
    listed = {row["id"]: row for row in PiTools(workspace.pi).methods(workspace.current_tasks(cid))}
    assert listed["coordinate"]["package"] == {"name": "coordinate-search", "version": "0.2.0"} and "package" not in listed["random"]


def test_a_workspace_for_a_proposal_whose_installed_method_runs_is_refused_with_the_binding_to_make(setup, packaged):
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    compute_consent.grant(workspace, {"id": "decision_go", "campaign_id": cid},
                          {"plan": "Implement", "wall_seconds": 3600, "worker_seconds": 600, "coding_workspaces": 2})
    request = {"hypothesis_id": "H1", "objective": "Implement", "request_key": "agent", "ticket": TICKET}
    with pytest.raises(ValueError) as refused:
        development.create(cid, request, actor="lead")
    assert "H1 names coordinate (package coordinate-search 0.2.0), which runs on task" in str(refused.value)
    assert "Bind it instead (implementation.bind_builtin" in str(refused.value) and "reuse needs no coding time" in str(refused.value)
    # A proposal naming a method the lab does not have opens one; so does the researcher, and a proposal already bound.
    proposal(workspace, cid, "H2", algorithm="custom")
    assert development.create(cid, {**request, "hypothesis_id": "H2"}, actor="lead")["id"]
    assert development.create(cid, {**request, "request_key": "mine"})["id"]


def test_under_explore_binding_an_installed_method_is_allowed_and_a_workspace_still_refused(setup):
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    assert mandates.CLASSES["implementation.bind_builtin"] == mandates.CLASSES["library.apply"] == "reuse"
    # A request with no mandate has Explore: reuse passes, a coding workspace does not.
    for operation in ("implementation.bind_builtin", "library.apply"):
        assert mandates.require(workspace, cid, None, mandates.classes_of(operation), what=operation) is None
    with pytest.raises(ValueError, match="no coding workspace, starts without it"):
        development.create(cid, {"hypothesis_id": "hypothesis_dev", "objective": "Implement", "request_key": "agent", "ticket": TICKET}, actor="lead")
    # A mandate recorded before L5 named no reuse class; it allows reuse still, and Answer never does.
    explore = mandates.grant(workspace, cid, "explore", root={"thread_id": "thread_old", "message_id": "message_old"})
    row = workspace.store.get(explore.id, "mandate")
    workspace.store.put("mandate", {**row, "classes": [name for name in row["classes"] if name != "reuse"]})
    assert mandates.require(workspace, cid, {"thread_id": "thread_old", "message_id": "message_old"}, {"reuse"}, what="Binding").id == explore.id
    assert "reuse" not in mandates.TEMPLATES["answer"]["classes"]


def test_a_published_entry_records_its_code_and_applying_it_gives_a_bound_proposal(setup, packaged):
    from balsamic.library.service import ApplyInput, apply, code_of
    workspace, campaign, development, driver = setup
    cid = campaign["id"]
    proposal(workspace, cid, "H1")
    assert code_of(workspace, workspace.store.get("H1", "hypothesis")) == {"package": "coordinate-search", "version": "0.2.0",
                                                                          "method": "coordinate", "library_version_id": None}
    assert code_of(workspace, {"algorithm": "random"}) is None
    entry = workspace.store.put_immutable("library_entry", {"id": "library_won", "kind": "positive", "origin_campaign_id": "elsewhere",
        "hypothesis_id": "h_won", "strategy": {"title": "Coordinate wins", "mechanism": "m", "algorithm": "coordinate", "algorithm_config": {}},
        "code": {"package": "coordinate-search", "version": "0.1.0", "method": "coordinate", "library_version_id": None},
        "signature": {"problem_id": "bounded_continuous"}, "evidence": {"best_score": 0.1}, "graph": {}, "notes": "", "published_by": "researcher",
        "created_at": "2026-10-28T00:00:00Z"}, "library.published")
    command = Command(id="apply_one", campaign_id=cid, operation="library.apply", expected_revision=1, payload={"entry_id": entry["id"]})
    outcome = apply(workspace, cid, ApplyInput(entry_id=entry["id"]), command=command, actor="researcher")
    assert "binding" in outcome, outcome.get("not_bound")
    applied = workspace.store.get(outcome["hypothesis_id"], "hypothesis")
    assert applied["builtin_binding_id"] == outcome["binding"]["binding_id"] and applied["executable"] is True
    assert "the lab runs 0.2.0" in outcome["binding"]["note"]
    # An entry whose method is not installed says so, and its proposal stays unbound.
    missing = workspace.store.put_immutable("library_entry", {**{key: value for key, value in entry.items() if key != "content_hash"},
        "id": "library_gone", "strategy": {**entry["strategy"], "algorithm": "bakery_dp"},
        "code": {"package": "bakery-search", "version": "0.2.0", "method": "bakery_dp", "library_version_id": None}}, "library.published")
    outcome = apply(workspace, cid, ApplyInput(entry_id=missing["id"]), command=command.model_copy(update={"id": "apply_two"}), actor="researcher")
    assert outcome["not_bound"].startswith("bakery_dp from package bakery-search 0.2.0 is not installed in this lab")
    assert not workspace.store.get(outcome["hypothesis_id"], "hypothesis").get("builtin_binding_id")
