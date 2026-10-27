"""Whether an installed method meets the optimizer contract: the checks a library passes before it is used.

These are software checks, not a judgement of the algorithm: every proposal is a valid candidate of the problem,
the same seed gives the same proposals, a checkpoint restored into a fresh optimizer gives the same next proposal,
checkpoints and inspection are plain JSON, inspection stays small (it is recorded after every evaluation), and every
exported artifact has a kind the asset catalog holds. A method declared ``stochastic: False`` must give the same proposals
for seeds 0 and 7, since the assessment gate (decision 14) then counts one run per configuration. A method may finish on its own (no proposal: MethodFinished); the
same seed then finishes at the same step, and so does its restored checkpoint. Scores are synthetic; no evaluator runs.

``check_function`` checks a plain-function method (``optimizers/functions.py``) on the problem its instance resolves
to, so the evaluator it runs is the problem's own, a library's included: every candidate valid, the same candidates for
the same seed, a checkpoint that continues the same run, and a clean end, by returning or at the evaluation cap.
"""
from __future__ import annotations

import json
from typing import get_args

from optimization_framework.contracts.assets import AssetKind
from optimization_framework.execution.metrics import DIAGNOSTICS_BYTES
from optimization_framework.contracts.problems import Observation
from optimization_framework.contracts.base import content_hash
from .finish import MethodFinished
from .registry import create, stochastic


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
    finished, proposed = {}, {}
    for seed in seeds:
        first, second = make(seed), make(seed)
        proposed[seed] = []
        try:
            for step in range(steps):
                a, b = _next(first, instance), _next(second, instance)
                assert (a is None) == (b is None), f"seed {seed}, step {step}: the same seed finished in one replay and not the other"
                if a is None:
                    finished[seed] = step
                    break
                assert a[1] == b[1], f"seed {seed}, step {step}: the same seed gave different proposals"
                proposed[seed].append(a[1])
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
    deterministic = not stochastic(method, optimizer_plugins)
    if deterministic:
        _same_for_every_seed(proposed)
    return {"method": method, "seeds": list(seeds), "steps": steps, **({"finished_at_step": finished} if finished else {}),
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "JSON checkpoint and inspection", "bounded inspection",
                       "catalog export kinds", *(["declared deterministic"] if deterministic else [])]}


def _same_for_every_seed(proposed):
    """A method declared deterministic (stochastic: False) proposes the same for every seed."""
    (first, reference), *others = proposed.items()
    for seed, candidates in others:
        diverged = next((step for step, (a, b) in enumerate(zip(reference, candidates)) if a != b), None)
        if diverged is None and len(reference) != len(candidates):
            diverged = min(len(reference), len(candidates))
        assert diverged is None, (f"declared deterministic (stochastic: false), but seeds {first} and {seed} gave different proposals "
                                  f"at step {diverged + 1}; declare it stochastic, or draw nothing from the seed")


def _function_run(plugin, method_id, instance, parameters, seed, evaluations, evaluator, scores, cap, *, state=None, stop_at=None):
    """Drive one function method to its end, the cap or ``stop_at`` candidates; append to ``evaluations``.

    Scores come from ``evaluator`` once per distinct candidate (``scores``), so a replay compares what the method
    proposes, not the evaluator's noise. Returns how the run ended and, when stopped at ``stop_at``, its JSON checkpoint."""
    from optimization_framework.contracts.problems import Observation
    method = plugin.create(method_id, instance, dict(parameters), seed)
    checkpoint, ended = None, "cap"
    try:
        if state is not None:
            method.restore(state)
        while len(evaluations) < cap:
            if stop_at is not None and len(evaluations) == stop_at:
                checkpoint, ended = json.loads(json.dumps(method.checkpoint())), "checkpoint"
                break
            try:
                proposal = method.propose(1)[0]
            except MethodFinished:
                ended = "returned"
                break
            except Exception as exc:
                raise AssertionError(f"seed {seed}, evaluation {len(evaluations) + 1}: the method raised {type(exc).__name__}: {exc}") from exc
            try:
                candidate = instance.candidate_schema.canonicalize(proposal.candidate)
            except (TypeError, ValueError) as exc:
                raise AssertionError(f"seed {seed}, evaluation {len(evaluations) + 1}: an invalid candidate ({exc})") from None
            key = content_hash(candidate)
            if key not in scores:
                try:
                    scores[key] = evaluator.evaluate(candidate).objectives
                except Exception as exc:
                    raise AssertionError(f"seed {seed}, evaluation {len(evaluations) + 1}: the problem's evaluator failed "
                                         f"({type(exc).__name__}: {exc})") from exc
            evaluations.append(key)
            method.observe([Observation(id=f"conformance_{len(evaluations)}", experiment_id="conformance", attempt_id="conformance",
                request_id=f"conformance_{len(evaluations)}", proposal_id=proposal.id, candidate=candidate, status="ok",
                objectives=scores[key], fidelity=instance.fidelity, evaluator_identity=instance.evaluation_identity)])
    finally:
        method.close()
    assert getattr(method, "thread", None) is None or not method.thread.is_alive(), \
        f"seed {seed}: the method did not end after StopSearch (it must not catch BaseException)"
    return ended, checkpoint


def check_function(plugin, method_id, instance, *, seeds=(0, 7), max_evaluations=50, parameters=None, registry=None):
    """Run the checks for one plain-function method on one problem instance; raise AssertionError on the first failure."""
    if registry is None:
        from optimization_framework.evaluation.registry import problems as registry
    parameters = dict(parameters or {})
    evaluator, scores, ended, proposed = registry.evaluator(instance), {}, {}, {}
    for seed in seeds:
        first, second, continued = [], [], []
        ended[seed], _ = _function_run(plugin, method_id, instance, parameters, seed, first, evaluator, scores, max_evaluations)
        again, _ = _function_run(plugin, method_id, instance, parameters, seed, second, evaluator, scores, max_evaluations)
        diverged = next((step for step, (a, b) in enumerate(zip(first, second)) if a != b), None)
        assert diverged is None, f"seed {seed}: the same seed proposed a different candidate at evaluation {diverged + 1}"
        assert (len(first), ended[seed]) == (len(second), again), \
            f"seed {seed}: the same seed ended differently ({ended[seed]} after {len(first)}, then {again} after {len(second)})"
        if len(first) > 1:
            _, state = _function_run(plugin, method_id, instance, parameters, seed, continued, evaluator, scores, max_evaluations,
                                     stop_at=len(first) // 2)
            last, _ = _function_run(plugin, method_id, instance, parameters, seed, continued, evaluator, scores, max_evaluations, state=state)
            assert continued == first and last == ended[seed], \
                f"seed {seed}: continuing from the checkpoint at evaluation {len(first) // 2} did not give the same run"
        proposed[seed] = first
    listed = next((method for method in plugin.methods() if method["id"] == method_id), {})
    deterministic = listed.get("stochastic", True) is False
    if deterministic:
        _same_for_every_seed(proposed)
    return {"method": method_id, "seeds": list(seeds), "max_evaluations": max_evaluations,
            "ended": {str(seed): how for seed, how in ended.items()},
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "clean end", *(["declared deterministic"] if deterministic else [])]}
