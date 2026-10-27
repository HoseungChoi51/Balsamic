"""MEENT's adaptive-race values: the RCWA fidelity ladder, its ceiling, and how a solve's memory grows with the orders."""
from __future__ import annotations

# The reviewed default validation ladder, cheapest first; a race validates its finalists above the search truncation.
LADDER = [{"rcwa_order_x": x, "rcwa_order_y": y} for x, y in ((10, 5), (12, 6), (14, 7))]
LIMIT = {"rcwa_order_x": 34, "rcwa_order_y": 17}
# With nothing higher on the ladder, validate this far above the search fidelity (capped at the limit).
STEP = {"rcwa_order_x": 4, "rcwa_order_y": 2}
# The race's memory plan also forecasts these orders, beside the ones its protocol declares.
MEMORY_CHECKS = [{"rcwa_order_x": x, "rcwa_order_y": x // 2} for x in (22, 26, 30, 34)]
PREFERRED = ["motif_surgery", "flrl_ppo_residual", "flrl_autograd_adam", "flrl_lsf_random"]


def harmonics(fidelity):
    return (2 * fidelity["rcwa_order_x"] + 1) * (2 * fidelity["rcwa_order_y"] + 1)


def growth(target, reference):
    """How a worker's peak memory grows from `reference` to `target`: dense N x N matrices in the harmonic count."""
    return (harmonics(target) / harmonics(reference)) ** 2
