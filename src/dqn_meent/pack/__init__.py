"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

It holds MEENT's agent tools and commands (N4, ``tools.py``), its RCWA memory planner (N5, ``memory.py``) and the
race's fidelity ladder (N5, ``racing.py``); the roadmap's N3 and N6 to N8 move its procedures, references and legacy hooks
out of the core and into it. The memory planner and the ladder are keyed on the 2D problem's RCWA orders, so a race or
forecast on a task with another fidelity does not use them.
"""
from optimization_framework.contracts.packs import PackEstimators, PackRacing, PackTools, ProblemPack

from . import racing

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS,
                       # N4: the test-design tool and fixed-design evaluations (tools.py).
                       tools=PackTools(agent_tools=[f"{__name__}.tools:register_agent_tools"],
                                       operations=[f"{__name__}.tools:register_operations"]),
                       estimators=PackEstimators(memory=f"{__name__}.memory:estimate"),
                       racing=PackRacing(ladder=racing.LADDER, limit=racing.LIMIT, step=racing.STEP,
                                         memory_checks=racing.MEMORY_CHECKS, cost_model=f"{__name__}.racing:growth",
                                         preferred_methods=racing.PREFERRED))
