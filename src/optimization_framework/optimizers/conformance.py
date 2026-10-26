"""Whether an installed method meets the optimizer contract: the checks a library passes before it is used.

These are software checks, not a judgement of the algorithm: every proposal is a valid candidate of the problem,
the same seed gives the same proposals, a checkpoint restored into a fresh optimizer gives the same next proposal,
checkpoints and inspection are plain JSON, and every exported artifact has a kind the asset catalog holds. Scores are
synthetic; no evaluator runs.
"""
from __future__ import annotations

import json
from typing import get_args

from optimization_framework.contracts.assets import AssetKind
from optimization_framework.contracts.problems import Observation
from .registry import create


def _score(candidate, step):
    """A deterministic synthetic score in [0, 1] that depends on the candidate."""
    return ((sum(int(value) for value in candidate) if isinstance(candidate, list) else 0) * 7 + step * 13) % 101 / 100


def _observe(optimizer, instance, proposal, candidate, step):
    score = _score(candidate, step)
    objectives = {instance.primary_objective.name: score, **{metric.name: score for metric in instance.extra_metrics}}
    optimizer.observe([Observation(id=f"conformance_{step}", experiment_id="conformance", attempt_id="conformance",
        request_id=f"conformance_{step}", proposal_id=proposal.id, candidate=candidate, status="ok",
        objectives=objectives, fidelity=instance.fidelity, evaluator_identity="conformance")])


def check(method, instance, *, seeds=(0, 7), steps=6, parameters=None, optimizer_plugins=None):
    """Run the contract checks for one method on one problem instance; raise AssertionError on the first failure."""
    parameters = dict(parameters or {})
    make = lambda seed: create(method, instance, parameters, seed, steps + 2, optimizer_plugins=optimizer_plugins)
    for seed in seeds:
        first, second = make(seed), make(seed)
        try:
            for step in range(steps):
                a, b = first.propose(1)[0], second.propose(1)[0]
                candidate = instance.candidate_schema.canonicalize(a.candidate)
                assert candidate == instance.candidate_schema.canonicalize(b.candidate), f"seed {seed}, step {step}: the same seed gave different proposals"
                _observe(first, instance, a, candidate, step)
                _observe(second, instance, b, candidate, step)
            json.dumps(first.inspect())
            for item in first.export_artifacts() if hasattr(first, "export_artifacts") else []:
                assert isinstance(item, dict) and "data" in item, f"seed {seed}: an export is not a dict with data"
                assert item.get("kind") in get_args(AssetKind), \
                    f"seed {seed}: export kind {item.get('kind')!r} is not one the asset catalog holds ({', '.join(get_args(AssetKind))})"
            state = json.loads(json.dumps(first.checkpoint()))
            expected = instance.candidate_schema.canonicalize(first.propose(1)[0].candidate)
            restored = make(seed)
            try:
                restored.restore(state)
                assert instance.candidate_schema.canonicalize(restored.propose(1)[0].candidate) == expected, \
                    f"seed {seed}: a restored checkpoint changed the next proposal"
            finally:
                restored.close()
        finally:
            first.close()
            second.close()
    return {"method": method, "seeds": list(seeds), "steps": steps,
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "JSON checkpoint and inspection", "catalog export kinds"]}
