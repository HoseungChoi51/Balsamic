"""N5: MEENT's memory estimator and the adaptive race's fidelity ladder (their code is ``memory.py`` and ``racing.py``).

Both are keyed on the 2D problem's RCWA orders, so a race or forecast on a task with another fidelity does not use them.
"""
from . import racing

PACKAGE = __package__

CONTRIBUTION = {
    "estimators": {"memory": f"{PACKAGE}.memory:estimate"},
    "racing": {"ladder": racing.LADDER, "limit": racing.LIMIT, "step": racing.STEP, "memory_checks": racing.MEMORY_CHECKS,
               "cost_model": f"{PACKAGE}.racing:growth", "preferred_methods": racing.PREFERRED},
}
