"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

N3 to N8 move MEENT's procedures, tools, estimators, racing ladder, references and legacy hooks out of the core and into
it. Its cost section (N11) keeps MEENT an oracle problem compared on worker-seconds: the RCWA solver is the expensive
evaluator a method reaches only through ``evaluate``.
"""
from optimization_framework.contracts.packs import PackCost, ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS, cost=PackCost(access="oracle", cost_axis="worker_seconds"))
