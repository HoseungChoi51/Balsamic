"""Local search over orders: swap and insertion moves, first improvement, random restarts after a plateau."""
from __future__ import annotations

import math

import numpy as np


def moves(n):
    """Every swap (i < j), then every insertion that moves item i to position j with |i − j| ≥ 2
    (an adjacent insertion is the same order as an adjacent swap)."""
    swaps = [("swap", i, j) for i in range(n) for j in range(i + 1, n)]
    return swaps + [("insert", i, j) for i in range(n) for j in range(n) if abs(i - j) >= 2]


def apply(order, move):
    kind, i, j = move
    order = list(order)
    if kind == "swap":
        order[i], order[j] = order[j], order[i]
    else:
        order.insert(j, order.pop(i))
    return order


class SwapSearch:
    """First-improvement local search from a random order. The current order's neighbours are tried in a seeded random
    order; the first that improves it becomes the current order. After `restarts_after` evaluations without improving the
    current order (by default a whole neighbourhood, so at a local optimum) the search restarts from a new random order."""

    def __init__(self, dimensions, seed, config=None):
        config = dict(config or {})
        self.n = int(dimensions)
        self.moves = moves(self.n)
        self.restarts_after = config.get("restarts_after", max(1, len(self.moves)))
        if type(self.restarts_after) is not int or self.restarts_after < 1:
            raise ValueError("restarts_after must be a positive integer")
        self.rng = np.random.default_rng(seed)
        self.current = None
        self.current_score = None
        self.remaining = []
        self.stagnation = 0
        self.restarts = 0
        self.pending_restart = False
        self.count = 0
        self.best = None
        self.best_score = None

    def ask(self):
        self.pending_restart = self.current is None or not self.remaining or self.stagnation >= self.restarts_after
        if self.pending_restart:
            if self.current is not None:
                self.restarts += 1
            return self.rng.permutation(self.n)
        return np.asarray(apply(self.current, self.moves[self.remaining.pop()]))

    def tell(self, candidate, utility):
        if not math.isfinite(utility):
            raise FloatingPointError("Optimizer received a nonfinite objective")
        candidate = [int(item) for item in candidate]
        self.count += 1
        if self.best_score is None or utility > self.best_score:
            self.best, self.best_score = candidate, float(utility)
        if self.pending_restart or utility > self.current_score:
            self.current, self.current_score = candidate, float(utility)
            self.remaining = self.rng.permutation(len(self.moves)).tolist()
            self.stagnation = 0
        else:
            self.stagnation += 1

    def diagnostics(self):
        return {"restarts": self.restarts, "stagnation": self.stagnation, "neighbourhood": len(self.moves)}

    def state_dict(self):
        """Plain JSON: the generator's state, the current and best orders and the untried neighbours."""
        return {"rng": self.rng.bit_generator.state, "current": self.current, "current_score": self.current_score,
                "remaining": list(self.remaining), "stagnation": self.stagnation, "restarts": self.restarts,
                "pending_restart": self.pending_restart, "count": self.count, "best": self.best, "best_score": self.best_score}

    def load_state_dict(self, state):
        if state["current"] is not None and sorted(state["current"]) != list(range(self.n)):
            raise ValueError("Swap search checkpoint is not an order of this instance's items")
        self.rng.bit_generator.state = state["rng"]
        for key in ("current", "current_score", "stagnation", "restarts", "pending_restart", "count", "best", "best_score"):
            setattr(self, key, state[key])
        self.remaining = list(state["remaining"])
