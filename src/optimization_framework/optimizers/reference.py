"""Evaluate one explicitly bound solution without performing a search move."""
from copy import deepcopy


class FixedSolution:
    def __init__(self, candidate):
        self.candidate = list(candidate)
        self.count = 0

    def ask(self):
        if self.count:
            raise ValueError("The declared reference evaluation contains exactly one candidate")
        return self.candidate.copy()

    def tell(self, candidate, score):
        self.count += 1

    def diagnostics(self):
        return {"reference_evaluations": self.count}

    def state_dict(self):
        return {"count": self.count, "candidate": deepcopy(self.candidate)}

    def load_state_dict(self, state):
        if state["candidate"] != self.candidate or state["count"] not in (0, 1):
            raise ValueError("Reference checkpoint differs from its declared input")
        self.count = state["count"]


class Replay:
    """Evaluate the listed candidates once each, in order: how a changed evaluator is compared with recorded results."""

    def __init__(self, candidates):
        self.candidates = [list(candidate) for candidate in candidates]
        self.count = 0

    def ask(self):
        if self.count >= len(self.candidates):
            raise ValueError("Every listed candidate has been evaluated")
        return self.candidates[self.count].copy()

    def tell(self, candidate, score):
        self.count += 1

    def diagnostics(self):
        return {"replayed_evaluations": self.count}

    def state_dict(self):
        return {"count": self.count}

    def load_state_dict(self, state):
        if not 0 <= state["count"] <= len(self.candidates):
            raise ValueError("Replay checkpoint differs from its listed candidates")
        self.count = state["count"]
