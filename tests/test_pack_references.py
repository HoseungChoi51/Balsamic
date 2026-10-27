"""Pack references for coding workspaces (roadmap N6): a workspace gets the reference material of its campaign's packs
only, and its brief names only what it got."""
import json
import subprocess

import pytest

from optimization_framework.agents.development import DevelopmentWorkspaces, references_brief
from optimization_framework.agents.development_runtime import DockerWorkspace
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.packs import PackReference, ProblemPack
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.evaluation.packs import reference_source
from optimization_framework.evaluation.registry import problems
from optimization_framework.execution.service import Workspace

from test_pi_development_workspaces import Driver


@pytest.fixture
def flrl(tmp_path, monkeypatch):
    """A Git checkout standing in for the FLRL authors' repository, named by GRATING_FLRL_REFERENCE."""
    source = tmp_path / "flrl"
    (source / "flrl").mkdir(parents=True)
    (source / "flrl/agent.py").write_text("ACTIONS = 4\n")
    (source / "untracked.txt").write_text("not committed\n")
    git = ["git", "-C", str(source), "-c", "user.email=t@example.org", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run([*git, "add", "flrl/agent.py"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "reference"], check=True)
    monkeypatch.setenv("GRATING_FLRL_REFERENCE", str(source))
    monkeypatch.delenv("GRATING_PAPER_REFERENCE", raising=False)
    return source


def campaign(workspace, task):
    created = workspace.create_campaign(CampaignInput(name="References", compute_budget_seconds=100, validation_reserve_seconds=10,
                                                      implementation_compute_budget_seconds=30, tasks=[task]))
    workspace.commands.execute(Command(id="activate-" + created["id"], campaign_id=created["id"], expected_revision=1,
                                       operation="agent.activate", payload={"objective": "Implement an optimizer"}))
    workspace.store.put("hypothesis", {"id": "hypothesis_" + created["id"], "campaign_id": created["id"], "title": "Test method",
                                       "status": "proposed", "mechanism": "A test implementation", "algorithm": "custom",
                                       "algorithm_config": {}})
    return created


def opened(tmp_path, monkeypatch, task):
    """A coding workspace prepared for a one-task campaign: what the driver got, and the brief."""
    monkeypatch.setenv("GRATING_DEVELOPMENT_ENABLED", "true")
    monkeypatch.setenv("GRATING_PI_PROVIDER", "openai-codex")
    workspace = Workspace(tmp_path / "lab")
    created = campaign(workspace, task)
    driver = Driver(tmp_path / "development")
    development = DevelopmentWorkspaces(workspace.pi, driver=driver)
    workspace.pi.development = development
    record = development.create(created["id"], {"hypothesis_id": "hypothesis_" + created["id"], "objective": "Implement",
                                                "request_key": "open"})
    development.sync(created["id"])
    return driver.references, (driver.root(record) / "brief.md").read_text()


MEENT = TaskInput(name="Small grating", physics={"n_cells": 4, "fourier_order": 1})
PLAIN = TaskInput(name="Quadratic", problem_id="bounded_continuous", configuration={})


def test_meent_s_pack_names_the_flrl_reference_and_the_benchmarks_name_none():
    reference = problems.pack("meent_grating").references
    assert [(r.name, r.environment) for r in reference] == [("flrl", "GRATING_FLRL_REFERENCE")]
    assert problems.pack("bounded_continuous") is None


def test_a_meent_workspace_gets_references_flrl_and_its_brief_names_it(tmp_path, monkeypatch, flrl):
    references, brief = opened(tmp_path, monkeypatch, MEENT)
    assert [(r["name"], r["source"], r["package"]) for r in references] == [("flrl", str(flrl), "dqn_meent.pack")]
    assert "## References" in brief and "`/references/flrl`: the FLRL authors' reference code" in brief


def test_a_bounded_continuous_workspace_gets_no_references_and_its_brief_names_none(tmp_path, monkeypatch, flrl):
    references, brief = opened(tmp_path, monkeypatch, PLAIN)
    assert references == []
    assert "/references" not in brief and "flrl" not in brief.lower()


def test_a_meent_workspace_without_the_flrl_checkout_gets_none_and_its_brief_names_none(tmp_path, monkeypatch):
    monkeypatch.setenv("GRATING_FLRL_REFERENCE", str(tmp_path / "absent"))
    monkeypatch.delenv("GRATING_PAPER_REFERENCE", raising=False)
    references, brief = opened(tmp_path, monkeypatch, MEENT)
    assert references == [] and "/references" not in brief


def test_the_supplied_paper_is_named_only_when_there_is_one():
    assert references_brief([]) == ""
    assert "`/references/paper.txt` and `/references/paper.pdf`" in references_brief([], paper=True)
    unnamed = references_brief([{"name": "tables", "package": "pack_fixture", "description": ""}])
    assert "`/references/tables`: reference material from the pack_fixture problem pack" in unnamed


def prepared_root(tmp_path, record):
    """A workspace root whose repository already exists, so prepare() copies references without starting Docker."""
    driver = DockerWorkspace(tmp_path / "development")
    root = driver.root(record)
    (root / "work/git").mkdir(parents=True)
    (root / "work/repo/.git").mkdir(parents=True)
    return driver, root


def test_prepare_mounts_a_checkout_s_committed_tree_with_its_commit(tmp_path, flrl):
    record = {"id": "development_one"}
    driver, root = prepared_root(tmp_path, record)
    driver.prepare(record, "# Brief", [], references=[{"name": "flrl", "source": str(flrl)}])
    assert (root / "references/flrl/flrl/agent.py").read_text() == "ACTIONS = 4\n"
    assert not (root / "references/flrl/untracked.txt").exists()
    head = subprocess.run(["git", "-C", str(flrl), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    assert (root / "references/flrl.commit").read_text() == head
    driver.prepare(record, "# Brief", [], references=[{"name": "flrl", "source": str(flrl)}])   # recovery keeps the copy
    assert sorted(p.name for p in (root / "references").iterdir()) == ["flrl", "flrl.commit"]


def test_prepare_mounts_nothing_without_references(tmp_path, flrl):
    record = {"id": "development_two"}
    driver, root = prepared_root(tmp_path, record)
    driver.prepare(record, "# Brief", [])
    assert list((root / "references").iterdir()) == []
    assert json.loads((root / "work/repo/.campaign/evidence.json").read_text()) == []


def test_a_reference_in_the_pack_s_package_is_copied_as_it_is(tmp_path, monkeypatch):
    package = tmp_path / "site/pack_fixture"
    (package / "tables").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "tables/orders.csv").write_text("order,error\n1,0.1\n")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    pack = ProblemPack(package="pack_fixture", problem_ids=["packed"], references=[PackReference(name="tables", folder="tables")])
    source = reference_source(pack, pack.references[0])
    assert source == package / "tables"
    record = {"id": "development_three"}
    driver, root = prepared_root(tmp_path, record)
    driver.prepare(record, "# Brief", [], references=[{"name": "tables", "source": str(source)}])
    assert (root / "references/tables/orders.csv").read_text() == "order,error\n1,0.1\n"
    assert not (root / "references/tables.commit").exists()


def test_an_environment_reference_falls_back_to_its_default_and_is_absent_without_either(tmp_path, monkeypatch):
    monkeypatch.delenv("PACK_FIXTURE_REFERENCE", raising=False)
    (tmp_path / "beside").mkdir()
    pack = ProblemPack(package="dqn_meent.pack", problem_ids=["packed"], references=[
        PackReference(name="beside", environment="PACK_FIXTURE_REFERENCE", default=str(tmp_path / "beside")),
        PackReference(name="nowhere", environment="PACK_FIXTURE_REFERENCE")])
    assert reference_source(pack, pack.references[0]) == tmp_path / "beside"
    assert reference_source(pack, pack.references[1]) is None
    monkeypatch.setenv("PACK_FIXTURE_REFERENCE", str(tmp_path))
    assert reference_source(pack, pack.references[0]) == tmp_path


@pytest.mark.parametrize("reference", [
    {"name": "flrl", "folder": "flrl", "default": "/srv/flrl"},
    {"name": "flrl", "environment": "PACK_FIXTURE_REFERENCE", "default": "relative/flrl"},
])
def test_a_default_is_an_absolute_path_beside_an_environment_variable(reference):
    with pytest.raises(ValueError, match="default"):
        PackReference.model_validate(reference)
