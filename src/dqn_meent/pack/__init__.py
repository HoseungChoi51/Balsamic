"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

It holds MEENT's agent tools and commands (N4, ``tools.py``); the roadmap's N3 and N5 to N8 move its procedures,
estimators, racing ladder, references and legacy hooks out of the core and into it.
"""
from optimization_framework.contracts.packs import PackTools, ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS,
                       # N4: the test-design tool and fixed-design evaluations (tools.py).
                       tools=PackTools(agent_tools=[f"{__name__}.tools:register_agent_tools"],
                                       operations=[f"{__name__}.tools:register_operations"]))
