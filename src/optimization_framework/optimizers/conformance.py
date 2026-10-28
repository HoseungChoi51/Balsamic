"""Whether an installed method meets the optimizer contract: the checks a library passes before it is used.

These are software checks, not a judgement of the algorithm: every proposal is a valid candidate of the problem,
the same seed gives the same proposals, a checkpoint restored into a fresh optimizer gives the same next proposal,
checkpoints and inspection are plain JSON, inspection stays small (it is recorded after every evaluation), and every
exported artifact has a kind the asset catalog holds. A method may finish on its own (no proposal: MethodFinished); the
same seed then finishes at the same step, and so does its restored checkpoint. A method that reports a ``bound`` (N13)
reports one its own best does not beat. Scores are synthetic; no evaluator runs.

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


def _bound_holds(optimizer, instance, best, where):
    """A reported bound is a value no feasible candidate beats, so the method's own best must not beat it (N13)."""
    from optimization_framework.analysis.optimality import beats, claim_of
    bound = claim_of(optimizer.inspect()).get("best_bound")
    if bound is not None and best is not None:
        assert not beats(instance.primary_objective, best, bound), (f"{where}: the method reports bound {bound:g}, which its own best "
            f"({best:g}) beats; a bound is a value no feasible candidate can beat in the objective's direction")


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
    objective = instance.primary_objective
    for seed in seeds:
        first, second = make(seed), make(seed)
        best = None
        try:
            for step in range(steps):
                a, b = _next(first, instance), _next(second, instance)
                assert (a is None) == (b is None), f"seed {seed}, step {step}: the same seed finished in one replay and not the other"
                if a is None:
                    finished[seed] = step
                    _bound_holds(first, instance, best, f"seed {seed}, at its finish")
                    break
                assert a[1] == b[1], f"seed {seed}, step {step}: the same seed gave different proposals"
                _observe(first, instance, a[0], a[1], step)
                _observe(second, instance, b[0], a[1], step)
                best = _score(a[1], step) if objective.better(_score(a[1], step), best) else best
                _bound_holds(first, instance, best, f"seed {seed}, step {step}")
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
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "JSON checkpoint and inspection", "bounded inspection",
                       "catalog export kinds", "bounds its own best does not beat"]}


def _function_run(plugin, method_id, instance, parameters, seed, evaluations, evaluator, scores, cap, *, state=None, stop_at=None):
    """Drive one function method to its end, the cap or ``stop_at`` candidates; append to ``evaluations``.

    Scores come from ``evaluator`` once per distinct candidate (``scores``), so a replay compares what the method
    proposes, not the evaluator's noise. Returns how the run ended and, when stopped at ``stop_at``, its JSON checkpoint."""
    from optimization_framework.contracts.problems import Observation
    method = plugin.create(method_id, instance, dict(parameters), seed)
    checkpoint, ended = None, "cap"
    from optimization_framework.analysis.optimality import beats, claim_of
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
                bound, name = claim_of(method.inspect()).get("best_bound"), instance.primary_objective.name
                values = [scores[key][name] for key in evaluations if name in scores[key]]
                best = max(values, key=instance.primary_objective.utility) if values else None
                assert bound is None or best is None or not beats(instance.primary_objective, best, bound), (f"seed {seed}: the method "
                    f"returned bound {bound:g}, which its own best ({best:g}) beats; a bound is a value no feasible candidate can beat")
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
    evaluator, scores, ended = registry.evaluator(instance), {}, {}
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
    return {"method": method_id, "seeds": list(seeds), "max_evaluations": max_evaluations,
            "ended": {str(seed): how for seed, how in ended.items()},
            "checks": ["valid candidates", "seeded replay", "checkpoint continuation", "clean end", "bounds its own best does not beat"]}
