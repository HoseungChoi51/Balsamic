"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

It starts empty; the roadmap's N3 to N8 move MEENT's procedures, tools, estimators, racing ladder, references and legacy
hooks out of the core and into it.
"""
from optimization_framework.contracts.packs import ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS)
