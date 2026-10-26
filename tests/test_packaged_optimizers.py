"""A library built to the optimizer_v1 package contract runs in-process as a plug-in method, and the contract checks
catch an optimizer that breaks seeded replay or checkpoint continuation, or exports a kind the asset catalog does not hold."""
import json
import random
import textwrap

import pytest

from optimization_framework.evaluation.registry import problems
from optimization_framework.optimizers import conformance
from optimization_framework.optimizers.plugins import OptimizerPlugins
from optimization_framework.optimizers.registry import create

LIBRARY = '''
import json, random
from optimization_framework.optimizers.packaged import PackagedPlugin


class Flip:
    """Flip one random bit of the best candidate seen; RANDOM_RESTORE breaks checkpoint continuation on purpose."""
    def __init__(self, context):
        self.context = context

    def initialize(self, problem, parameters, seed, assets):
        self.n = problem["candidate_schema"]["dimensions"]
        self.rng = random.Random(seed)
        self.best, self.best_score, self.count = [0] * self.n, None, 0

    def propose(self, max_candidates=1):
        candidate = list(self.best)
        candidate[self.rng.randrange(self.n)] ^= 1
        self.count += 1
        return [{"id": f"p{self.count}", "candidate": candidate}]

    def observe(self, observations):
        for observation in observations:
            score = next(iter(observation["objectives"].values()))
            if self.best_score is None or score > self.best_score:
                self.best, self.best_score = observation["candidate"], score

    def checkpoint(self):
        return json.dumps({"best": self.best, "score": self.best_score, "count": self.count, "rng": self.rng.getstate()}).encode()

    def restore(self, raw):
        state = json.loads(raw)
        self.best, self.best_score, self.count = state["best"], state["score"], state["count"]
        rng = state["rng"]
        self.rng.setstate((rng[0], tuple(rng[1]), rng[2]))
        if RANDOM_RESTORE:
            self.rng.seed()

    def inspect(self):
        return {"best_score": self.best_score, "proposals": self.count, **({"history": [self.best] * self.count} if HISTORY else {})}

    def export_artifacts(self):
        return [{"kind": EXPORT_KIND, "media_type": "application/json", "data": {"candidate": self.best}}]


RANDOM_RESTORE = False
EXPORT_KIND = "solution"
HISTORY = False


def create_optimizer(context):
    return Flip(context)


class Plugin(PackagedPlugin):
    METHODS = {"flip": {"module": __import__(__name__), "name": "One-bit flip", "description": "Test library."}}
'''


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    (tmp_path / "flip_library.py").write_text(textwrap.dedent(LIBRARY))
    monkeypatch.syspath_prepend(str(tmp_path))
    return OptimizerPlugins({"flip": "flip_library:Plugin"})


def instance():
    return problems.get("meent_grating").implementation_fixture({}, 16)


def test_a_packaged_library_method_runs_and_checkpoints_through_the_registry(plugins):
    optimizer = create("flip", instance(), {}, 3, 10, optimizer_plugins=plugins)
    proposal = optimizer.propose(1)[0]
    assert len(proposal.candidate) == 16 and set(proposal.candidate) <= {0, 1}
    state = json.loads(json.dumps(optimizer.checkpoint()))
    assert state["contract"] == "optimizer_v1" and state["pending"][0]["id"] == proposal.id
    with pytest.raises(ValueError, match="Observe the outstanding batch"):
        optimizer.propose(1)


def test_the_contract_checks_pass_a_sound_method_and_catch_a_broken_restore(plugins, monkeypatch):
    assert conformance.check("flip", instance(), optimizer_plugins=plugins)["method"] == "flip"
    import flip_library
    monkeypatch.setattr(flip_library, "RANDOM_RESTORE", True)
    random.seed(1)
    with pytest.raises(AssertionError, match="restored checkpoint changed the next proposal"):
        conformance.check("flip", instance(), optimizer_plugins=plugins)
    monkeypatch.setattr(flip_library, "RANDOM_RESTORE", False)
    monkeypatch.setattr(flip_library, "EXPORT_KIND", "flip_best")
    with pytest.raises(AssertionError, match="export kind 'flip_best' is not one the asset catalog holds"):
        conformance.check("flip", instance(), optimizer_plugins=plugins)
    monkeypatch.setattr(flip_library, "EXPORT_KIND", "solution")
    monkeypatch.setattr(flip_library, "HISTORY", True)   # every design seen, reported on every inspection
    big = problems.get("meent_grating").implementation_fixture({}, 1024)
    with pytest.raises(AssertionError, match="the host records it after every evaluation"):
        conformance.check("flip", big, optimizer_plugins=plugins)


def test_a_progress_record_carries_bounded_diagnostics():
    from optimization_framework.execution.metrics import DIAGNOSTICS_BYTES, bounded_diagnostics
    small = {"counters": {"requests": 3}, "events": ["a", "b"]}
    assert bounded_diagnostics(small) == small
    shown = bounded_diagnostics({"counters": {"requests": 3}, "events": ["event"] * 20000, "best": {"mask": [1] * 40000}})
    assert shown["counters"] == {"requests": 3} and set(shown["events"]) == {"omitted_bytes"} and shown["best"]["omitted_bytes"] > DIAGNOSTICS_BYTES
