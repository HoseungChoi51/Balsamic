"""This library's methods as Balsamic optimizer plug-ins (entry point in pyproject.toml); see docs/optimizer-plugins.md."""
from optimization_framework.optimizers.packaged import PackagedPlugin

from . import conditional_mirror_search, cyclic_geometric_vnd, elite_spread_relinking

PROBLEMS = ["meent_2d_dual_polarization_deflector"]


class GratingMaskSearchPlugin(PackagedPlugin):
    METHODS = {
        "cyclic_geometric_vnd": {"module": cyclic_geometric_vnd, "name": "Cyclic geometric VND", "problem_ids": PROBLEMS,
            "description": "Cyclic variable-neighborhood descent with geometric displacement on the full 128x256 mask: "
                           "coarse random starts, then square XOR, rectangle rotation and paired XOR moves (docs/cyclic_geometric_vnd.md)."},
        "conditional_mirror_search": {"module": conditional_mirror_search, "name": "Frozen-batch conditional mirror search",
            "problem_ids": PROBLEMS,
            "description": "Frozen-batch conditional mirror search with bounded active windows: per-tile probabilities updated "
                           "from paired background/opposite-arm scores (docs/conditional_mirror_search.txt)."},
        "elite_spread_relinking": {"module": elite_spread_relinking, "name": "Elite-spread relinking", "problem_ids": PROBLEMS,
            "description": "Elite-plus-spread archive relinking on full binary masks: path relinking between archive parents "
                           "along a disagreement corridor, with local moves and coarse draws on stalls (docs/elite_spread_relinking.md)."},
    }
