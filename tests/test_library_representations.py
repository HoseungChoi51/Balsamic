"""A library's methods say which candidates they accept (roadmap C3): a method's own representations, else the library's
REPRESENTATIONS, else binary as before; a method left on that default says so when it does not fit a problem, and the
optimizer_v1 context names the dimension count `dimensions` beside the grating's `n_cells`."""
import textwrap
from pathlib import Path

import pytest

from optimization_framework.evaluation.registry import problems
from optimization_framework.optimizers.plugins import OptimizerPlugins
from optimization_framework.optimizers.registry import capability_reason, create, methods

LIBRARY = '''
import json
from optimization_framework.optimizers.packaged import PackagedPlugin

CONTEXTS = []


class Centre:
    """Propose the centre of the box (or all zeros), and remember the context it was created with."""
    def __init__(self, context):
        CONTEXTS.append(context)

    def initialize(self, problem, parameters, seed, assets):
        schema = problem["candidate_schema"]
        self.candidate = [(low + high) / 2 for low, high in schema["bounds"]] or [0] * schema["dimensions"]

    def propose(self, max_candidates=1):
        return [{"id": "p1", "candidate": self.candidate}]

    def observe(self, observations):
        pass

    def checkpoint(self):
        return json.dumps(self.candidate).encode()

    def restore(self, raw):
        self.candidate = json.loads(raw)

    def inspect(self):
        return {}


def create_optimizer(context):
    return Centre(context)


METHOD = {"module": __import__(__name__), "name": "Centre", "description": "Test library."}


class Undeclared(PackagedPlugin):
    METHODS = {"centre_undeclared": METHOD}


class Continuous(PackagedPlugin):
    REPRESENTATIONS = ["continuous"]
    METHODS = {"centre_continuous": METHOD, "centre_own": {**METHOD, "representations": ["discrete"]}}
'''


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    (tmp_path / "centre_library.py").write_text(textwrap.dedent(LIBRARY))
    monkeypatch.syspath_prepend(str(tmp_path))
    return OptimizerPlugins({"undeclared": "centre_library:Undeclared", "continuous": "centre_library:Continuous"})


def continuous():
    return problems.resolve("bounded_continuous", {"dimensions": 3})


def test_a_library_that_declares_representations_is_compatible_with_their_problems(plugins):
    listed = {method["id"]: method for method in methods(plugins)}
    assert listed["centre_continuous"]["representations"] == ["continuous"]
    assert listed["centre_own"]["representations"] == ["discrete"]   # a method's own declaration wins over the library's
    assert "representations_defaulted" not in listed["centre_continuous"]
    assert capability_reason("centre_continuous", continuous(), plugins) is None
    optimizer = create("centre_continuous", continuous(), {}, 0, 1, optimizer_plugins=plugins)
    assert len(optimizer.propose(1)[0].candidate) == 3


def test_a_method_on_the_binary_default_says_to_declare_representations(plugins):
    method = next(method for method in methods(plugins) if method["id"] == "centre_undeclared")
    assert method["representations"] == ["binary"] and method["representations_defaulted"] is True
    assert capability_reason("centre_undeclared", continuous(), plugins) == (
        "Centre requires binary candidates: the library declares no representations, so it is treated as binary; "
        "declare REPRESENTATIONS")
    assert capability_reason("centre_own", continuous(), plugins) == "Centre requires discrete candidates"
    with pytest.raises(ValueError, match="declare REPRESENTATIONS"):
        create("centre_undeclared", continuous(), {}, 0, 1, optimizer_plugins=plugins)


def test_the_context_names_the_dimension_count_dimensions_and_keeps_n_cells(plugins):
    import centre_library
    create("centre_continuous", continuous(), {}, 0, 1, optimizer_plugins=plugins)
    assert centre_library.CONTEXTS[-1]["dimensions"] == centre_library.CONTEXTS[-1]["n_cells"] == 3


def test_the_grating_library_methods_are_listed_as_before(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "libraries/grating-mask-search/src"))
    from grating_mask_search.plugin import GratingMaskSearchPlugin
    listed = GratingMaskSearchPlugin().methods()
    assert [method["id"] for method in listed] == ["cyclic_geometric_vnd", "conditional_mirror_search", "elite_spread_relinking"]
    for method in listed:
        assert method["representations"] == ["binary"] and method["representations_defaulted"] is True
        assert method["constraints"] is False
        assert method["problem_ids"] == ["meent_2d_dual_polarization_deflector"]
        assert method["parameters"] == {} and method["parameter_properties"] == {} and "module" not in method
