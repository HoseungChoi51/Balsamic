"""Host contract, checkpoint boundaries and truthful proof claims."""
import copy
import json

import pytest

pytest.importorskip('optimization_framework')
from optimization_framework.contracts.problems import Observation
from optimization_framework.evaluation.registry import ProblemRegistry
from optimization_framework.optimizers.conformance import check_function
from optimization_framework.optimizers.finish import MethodFinished
from single_oven_total_tardiness.adapter import problem_adapter, method_plugin
from single_oven_total_tardiness.objective import details


@pytest.fixture
def host():
    adapter = problem_adapter()
    declared = adapter.manifest()
    instance = adapter.resolve(declared.configuration, declared.fidelity)
    return adapter, instance, method_plugin()


def observation(instance, proposal, value, identity=None):
    return Observation(id='test', experiment_id='test', attempt_id='test', request_id='test',
        proposal_id=proposal.id, candidate=proposal.candidate, status='ok', objectives=value,
        fidelity=instance.fidelity, evaluator_identity=identity or instance.evaluation_identity)


@pytest.mark.parametrize('name', ['oven_subset_dp', 'oven_mdd'])
def test_seeded_lifecycle_checkpoints_and_final_inspection(host, name):
    adapter, instance, plugin = host
    make = lambda seed=0: plugin.create(name, instance, {}, seed)
    first = make()
    restored = make(7)
    restored.restore(json.loads(json.dumps(first.checkpoint())))
    proposal = first.propose(1)[0]
    assert restored.propose(1)[0].candidate == proposal.candidate
    pending = make()
    pending.restore(json.loads(json.dumps(first.checkpoint())))
    with pytest.raises(ValueError):
        pending.propose(1)
    result = adapter.evaluator(instance).evaluate(proposal.candidate)
    for optimizer in [first, restored, pending]:
        optimizer.observe([observation(instance, proposal, result.objectives)])
        with pytest.raises(MethodFinished):
            optimizer.propose(1)
        diagnostics = optimizer.inspect()
        assert diagnostics['elapsed_seconds'] >= 0
        assert diagnostics['evaluations'] == 1
        if name == 'oven_subset_dp':
            assert diagnostics['states'] == 256
            assert diagnostics['transitions'] == 1024
            assert diagnostics['bound'] == result.objectives['total_customer_wait']
            assert diagnostics['proved_optimal'] is True
        else:
            assert diagnostics['priority_calculations'] == 36
            assert 'proved_optimal' not in diagnostics
    done = make()
    done.restore(json.loads(json.dumps(first.checkpoint())))
    assert done.inspect() == first.inspect()
    with pytest.raises(MethodFinished):
        done.propose(1)
    wrong = first.checkpoint()
    wrong['identity'] = 'wrong'
    with pytest.raises(ValueError):
        done.restore(wrong)
    assert len(json.dumps(first.inspect())) < 16384
    assert check_function(plugin, name, instance, registry=ProblemRegistry().extended(adapter))


@pytest.mark.parametrize('identity', ['conformance', None])
def test_synthetic_observations_never_create_false_proof(host, identity):
    _, instance, plugin = host
    optimizer = plugin.create('oven_subset_dp', instance, {}, 0)
    proposal = optimizer.propose(1)[0]
    optimizer.observe([observation(instance, proposal, {'total_customer_wait': -999}, identity)])
    assert 'bound' not in optimizer.inspect()
    assert not optimizer.inspect().get('proved_optimal', False)


def test_host_evaluator_all_metrics_metadata_count_and_identity(host):
    adapter, instance, _ = host
    evaluator = adapter.evaluator(instance)
    for candidate in [[0] * 8, list(range(7)), [.25] + list(range(1, 8))]:
        with pytest.raises(ValueError):
            evaluator.evaluate(candidate)
        assert evaluator.evaluations == 0
    candidate = [6, 5, 7, 2, 3, 0, 1, 4]
    evaluated = evaluator.evaluate(candidate)
    expected, rows = details(adapter.problem(instance), candidate)
    assert evaluated.objectives == expected
    assert set(evaluated.objectives) == {instance.primary_objective.name, *(m.name for m in instance.extra_metrics)}
    assert evaluated.metadata['schedule'] == rows
    assert evaluated.metadata['start_clock_min'] == 360
    assert evaluated.metadata['metric_directions'] == {m.name: m.direction for m in instance.extra_metrics}
    assert all(v >= 0 for v in evaluated.objectives.values())
    assert evaluator.evaluations == 1
    checkpoint = json.loads(json.dumps(evaluator.checkpoint()))
    again = adapter.evaluator(instance)
    again.restore(checkpoint)
    assert again.evaluations == 1
    checkpoint['identity'] = 'other'
    with pytest.raises(ValueError):
        again.restore(checkpoint)
