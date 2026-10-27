"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

The roadmap's N3 to N8 move MEENT's procedures, tools, estimators, racing ladder, references and legacy hooks out of the
core and into it. N5 has moved the RCWA memory planner (`memory.py`) and the race's fidelity ladder (`racing.py`); both
are keyed on the 2D problem's RCWA orders, so a race or forecast on a task with another fidelity does not use them.
"""
from optimization_framework.contracts.packs import PackEstimators, PackRacing, ProblemPack

from . import racing

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS,
                       estimators=PackEstimators(memory=f"{__name__}.memory:estimate"),
                       racing=PackRacing(ladder=racing.LADDER, limit=racing.LIMIT, step=racing.STEP,
                                         memory_checks=racing.MEMORY_CHECKS, cost_model=f"{__name__}.racing:growth",
                                         preferred_methods=racing.PREFERRED))
