"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

It holds MEENT's agent tools and commands (N4, ``tools.py``) and the FLRL reference for coding workspaces (N6); the
roadmap's N3, N5, N7 and N8 move its procedures, estimators, racing ladder and legacy hooks out of the core and into it.
"""
from pathlib import Path

from optimization_framework.contracts.packs import PackReference, PackTools, ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]
# The FLRL authors' code (jLabKAIST/flrl): GRATING_FLRL_REFERENCE, else a checkout beside this repository.
FLRL = PackReference(name="flrl", environment="GRATING_FLRL_REFERENCE",
                     default=str(Path(__file__).resolve().parents[3].parent / "flrl"),
                     description="the FLRL authors' reference code for the grating problems")


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS, references=[FLRL],
                       # N4: the test-design tool and fixed-design evaluations (tools.py).
                       tools=PackTools(agent_tools=[f"{__name__}.tools:register_agent_tools"],
                                       operations=[f"{__name__}.tools:register_operations"]))
