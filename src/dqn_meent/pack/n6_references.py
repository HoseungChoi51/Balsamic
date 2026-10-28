"""N6: the FLRL authors' code (jLabKAIST/flrl), mounted into the coding workspaces of MEENT campaigns only.

It is taken from GRATING_FLRL_REFERENCE, else from a checkout beside this repository; without either, no reference.
"""
from pathlib import Path

from optimization_framework.contracts.packs import PackReference

FLRL = PackReference(name="flrl", environment="GRATING_FLRL_REFERENCE",
                     default=str(Path(__file__).resolve().parents[3].parent / "flrl"))

CONTRIBUTION = {"references": [FLRL.model_dump()]}
