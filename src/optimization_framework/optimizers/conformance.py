"""Whether an installed method meets the optimizer contract: the checks a library passes before it is used.

These are software checks, not a judgement of the algorithm: every proposal is a valid candidate of the problem,
the same seed gives the same proposals, a checkpoint restored into a fresh optimizer gives the same next proposal,
checkpoints and inspection are plain JSON, inspection stays small (it is recorded after every evaluation), and every
exported artifact has a kind the asset catalog holds. A method may finish on its own (no proposal: MethodFinished); the
same seed then finishes at the same step, and so does its restored checkpoint. Scores are synthetic; no evaluator runs.
"""
from __future__ import annotations

import json
from typing import get_args

from optimization_framework.contracts.assets import AssetKind
from optimization_framework.execution.metrics import DIAGNOSTICS_BYTES
from optimization_framework.contracts.problems import Observation
from .finish import MethodFinished
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


def _next(optimizer, instance):
    """The next proposal and its canonical candidate, or None when the method has finished."""
    try:
        proposal = optimizer.propose(1)[0]
    except MethodFinished:
        return None
    return proposal, instance.candidate_schema.canonicalize(proposal.candidate)


def check(method, instance, *, seeds=(0, 7), steps=6, parameters=None, optimizer_plugins=None):
    """Run the contract checks for one method on one problem instance; raise AssertionError on the first failure."""
    parameters = dict(parameters or {})
    make = lambda seed: create(method, instance, parameters, seed, steps + 2, optimizer_plugins=optimizer_plugins)
    finished = {}
    for seed in seeds:
        first, second = make(seed), make(seed)
        try:
            for step in range(steps):
                a, b = _next(first, instance), _next(second, instance)
                assert (a is None) == (b is None), f"seed {seed}, step {step}: the same seed finished in one replay and not the other"
                if a is None:
                    finished[seed] = step
                    break
                assert a[1] == b[1], f"seed {seed}, step {step}: the same seed gave different proposals"
                _observe(first, instance, a[0], a[1], step)
                _observe(second, instance, b[0], a[1], step)
            shown = len(json.dumps(first.inspect()))
            assert shown <= DIAGNOSTICS_BYTES, (f"seed {seed}: inspect() returns {shown:,} bytes; the host records it after every evaluation, "
                                                f"so keep it under {DIAGNOSTICS_BYTES:,} (counters, a recent tail, no designs)")
            for item in first.export_artifacts() if hasattr(first, "export_artifacts") else []:
                assert isinstance(item, dict) and "data" in item, f"seed {seed}: an export is not a dict with data"
                assert item.get("kind") in get_args(AssetKind), \
                    f"seed {seed}: export kind {item.get('kind')!r} is not one the asset catalog holds ({', '.join(get_args(AssetKind))})"
            state = json.loads(json.dumps(first.checkpoint()))
            expected = _next(first, instance)
            restored = make(seed)
            try:
                restored.restore(state)
                again = _next(restored, instance)
                assert (again and again[1]) == (expected and expected[1]), f"seed {seed}: a restored checkpoint changed the next proposal"
            finally:
                restored.close()
        finally:
            first.close()
            second.close()
    return {"method": method, "seeds": list(seeds), "steps": steps, **({"finished_at_step": finished} if finished else {}),
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "JSON checkpoint and inspection", "bounded inspection", "catalog export kinds"]}
