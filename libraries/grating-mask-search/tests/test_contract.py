"""The optimizer contract, checked through Balsamic on the problem these methods are for (no solver runs)."""
import pytest

from optimization_framework.evaluation.registry import problems
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.plugins import OptimizerPlugins


def instance():
    example = next(e for e in problems.examples() if e["id"] == "flrl_2d_deflector_1050nm_75deg")["instances"][0]
    return problems.get(example["problem_id"]).resolve(example["configuration"], example["fidelity"])


@pytest.mark.parametrize("method", ["cyclic_geometric_vnd", "conditional_mirror_search", "elite_spread_relinking"])
def test_method_meets_the_optimizer_contract(method):
    plugins = OptimizerPlugins({"grating_mask_search": "grating_mask_search.plugin:GratingMaskSearchPlugin"})
    assert conformance.check(method, instance(), optimizer_plugins=plugins)["checks"]
