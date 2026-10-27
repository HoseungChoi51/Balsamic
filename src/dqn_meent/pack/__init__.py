"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

The roadmap's N3 to N8 move MEENT's procedures, tools, estimators, racing ladder, references and legacy hooks out of the
core and into it. N7 moved the legacy hooks: ``legacy.problem`` resolves old records stored without a problem, and
``legacy.runtime`` adds MEENT's version to the legacy runtime identity.
"""
from optimization_framework.contracts.packs import ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS,
                       legacy={"problem": f"{__name__}.legacy:problem", "runtime": f"{__name__}.legacy:runtime"})
