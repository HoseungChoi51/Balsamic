"""MEENT's problem pack (decision 17): what the grating problems bring besides their evaluators.

It holds MEENT's procedures (``procedures/``, served only to campaigns on these problems) and the labels of a design's
cells (roadmap N3); N4 to N8 move MEENT's tools, estimators, racing ladder, references and legacy hooks out of the core and
into it.
"""
from optimization_framework.contracts.packs import PackPresentation, ProblemPack

PROBLEM_IDS = ["meent_grating", "meent_2d_dual_polarization_deflector"]


def pack() -> ProblemPack:
    return ProblemPack(package=__name__, problem_ids=PROBLEM_IDS, procedures="procedures",
                       presentation=PackPresentation(labels={"on_label": "silicon", "off_label": "air"}))
