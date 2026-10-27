"""Problem packs (roadmap N2): a problem declares what it brings besides its evaluator, and campaigns get their problems' packs."""
import pytest

from optimization_benchmarks.problems import ContinuousProblem
from optimization_framework.contracts.packs import PackReference, PackTools, ProblemPack
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.evaluation.registry import ProblemRegistry, problems
from optimization_framework.execution.service import Workspace


@pytest.fixture
def fixture_package(tmp_path, monkeypatch):
    """An installed package holding a pack: a hooks module and a procedures folder."""
    root = tmp_path / "site" / "pack_fixture"
    (root / "procedures").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "hooks.py").write_text("def register(workspace):\n    return None\n")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    return "pack_fixture"


def packed_problem(name="packed_quadratic", **pack):
    class Packed(ContinuousProblem):
        def describe(self):
            return super().describe().model_copy(update={"id": name})

        def pack(self):
            return ProblemPack(**{"package": "pack_fixture", "problem_ids": [name], "procedures": "procedures",
                                  "tools": PackTools(operations=["pack_fixture.hooks:register"]), **pack})
    return Packed()


def registry_with(*adapters):
    registry = ProblemRegistry()
    for adapter in adapters:
        registry.register(adapter.describe().id, lambda adapter=adapter: lambda: adapter)
    return registry


def test_an_installed_problem_with_a_pack_is_listed_and_one_without_is_not(fixture_package):
    registry = registry_with(packed_problem(), ContinuousProblem())
    packs = registry.packs()
    assert list(packs) == ["packed_quadratic"]
    assert packs["packed_quadratic"].procedures == "procedures"
    assert registry.pack("bounded_continuous") is None


def test_meent_problems_share_one_pack_and_the_benchmarks_declare_none():
    meent = problems.pack("meent_grating")
    assert meent is not None and meent == problems.pack("meent_2d_dual_polarization_deflector")
    assert meent.package == "dqn_meent.pack"
    assert set(meent.problem_ids) == {"meent_grating", "meent_2d_dual_polarization_deflector"}
    assert problems.pack("bounded_continuous") is None


@pytest.mark.parametrize("pack, refusal", [
    ({"tools": PackTools(operations=["pack_fixture.absent:register"])}, "modules are not installed: pack_fixture.absent:register"),
    ({"legacy": {"migrate": "no_such_package.legacy:migrate"}}, "no_such_package.legacy:migrate"),
    ({"procedures": "absent"}, "folders are missing from pack_fixture: absent"),
    ({"references": [PackReference(name="paper", folder="absent")]}, "folders are missing"),
    ({"package": "no_such_package"}, "not an installed package"),
    ({"problem_ids": ["someone_else"]}, "not for itself"),
])
def test_a_pack_naming_what_is_not_there_is_refused_at_load_with_the_problem_id(fixture_package, pack, refusal):
    registry = registry_with(packed_problem(**pack))
    with pytest.raises(ValueError, match="Problem 'packed_quadratic'") as error:
        registry.pack("packed_quadratic")
    assert refusal in str(error.value)
    with pytest.raises(ValueError, match="packed_quadratic"):
        registry.packs()


def test_a_reference_kept_outside_the_package_is_not_checked_at_load(fixture_package):
    registry = registry_with(packed_problem(references=[PackReference(name="flrl", environment="PACK_FIXTURE_REFERENCE")]))
    assert registry.pack("packed_quadratic").references[0].environment == "PACK_FIXTURE_REFERENCE"


@pytest.mark.parametrize("pack", [
    {"package": "x", "problem_ids": []},
    {"package": "x", "problem_ids": ["a"], "procedures": "../outside"},
    {"package": "x", "problem_ids": ["a"], "procedures": "/absolute"},
    {"package": "x", "problem_ids": ["a"], "tools": {"agent_tools": ["not a hook"]}},
    {"package": "x", "problem_ids": ["a"], "references": [{"name": "paper"}]},
    {"package": "x", "problem_ids": ["a"], "legacy": {"migrate": "not a hook"}},
    {"package": "x", "problem_ids": ["a", "a"]},
    {"package": "x", "problem_ids": ["a"], "unknown": 1},
])
def test_a_malformed_manifest_is_refused_by_the_contract(pack):
    with pytest.raises(ValueError):
        ProblemPack.model_validate(pack)


def test_a_campaign_gets_the_packs_of_its_tasks_problems_and_no_other(tmp_path, monkeypatch, fixture_package):
    adapter = packed_problem()
    monkeypatch.setitem(problems._loaders, "packed_quadratic", lambda: lambda: adapter)
    monkeypatch.setitem(problems._adapters, "packed_quadratic", adapter)
    monkeypatch.setattr(problems, "_packs", {})
    workspace = Workspace(tmp_path / "lab")
    packed = workspace.create_campaign(CampaignInput(name="Packed", tasks=[
        TaskInput(name="One", problem_id="packed_quadratic"), TaskInput(name="Two", problem_id="packed_quadratic"),
        TaskInput(name="Plain", problem_id="bounded_continuous")]))
    plain = workspace.create_campaign(CampaignInput(name="Plain", tasks=[TaskInput(name="Quadratic", problem_id="bounded_continuous")]))
    assert workspace.packs.for_campaign(packed["id"]) == [adapter.pack()]
    assert workspace.packs.for_campaign(plain["id"]) == []
