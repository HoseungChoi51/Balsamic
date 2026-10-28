"""Real host contract on synthetic instances only: no adapter/evaluator required."""
import json
from importlib import metadata
import pytest
from optimization_framework.contracts.problems import CandidateSchema, Objective, ProblemInstance, Observation
from optimization_framework.optimizers.conformance import check
from optimization_framework.optimizers.plugins import OptimizerPlugins
from single_oven_total_tardiness.plugin import Plugin

IDS = list(Plugin.METHODS)


def instance():
    return ProblemInstance(definition_id='synthetic_only', definition_version='1', evaluator_id='not_registered',
        evaluator_version='1', configuration={}, candidate_schema=CandidateSchema(representation='permutation', dimensions=3),
        primary_objective=Objective(name='tardiness', direction='minimize'),
        public_descriptor={'processing': [0, 2, 3], 'due': [-1, 3, 4]}, scientific_identity='tiny_synthetic_fixture')


def observation(p, value):
    return Observation(id='o', experiment_id='test', attempt_id='test', request_id='test', proposal_id=p.id,
                       candidate=p.candidate, status='ok', objectives={'tardiness': value}, evaluator_identity='synthetic')


@pytest.mark.parametrize('method', IDS)
def test_host_conformance(method):
    plugins = OptimizerPlugins({'synthetic_scheduling': 'single_oven_total_tardiness.plugin:Plugin'})
    result = check(method, instance(), seeds=(0, 7, 19), steps=12, optimizer_plugins=plugins)
    assert 'valid candidates' in result['checks']


@pytest.mark.parametrize('method', IDS)
def test_outstanding_restore_and_sequential(method):
    plugin, inst = Plugin(), instance()
    a, b = [plugin.create(method, inst, {}, 7) for _ in range(2)]
    p = a.propose(1)[0]
    assert inst.candidate_schema.canonicalize(p.candidate) == p.candidate
    with pytest.raises(ValueError): a.propose(1)
    b.restore(json.loads(json.dumps(a.checkpoint())))
    for obj in (a, b): obj.observe([observation(p, 10)])
    assert a.checkpoint() == b.checkpoint()
    if method == 'swap_insert_restarts':
        assert a.optimizer.search.current_score == -10  # minimizing sign
        p = a.propose(1)[0]; a.observe([observation(p, 11)])
        assert a.optimizer.search.current_score == -10
        p = a.propose(1)[0]; a.observe([observation(p, 9)])
        assert a.optimizer.search.current_score == -9
    else:
        assert a.optimizer.propose(1) == []


def test_packaging_discovery():
    entry = next(e for e in metadata.entry_points(group='optimization_framework.optimizers') if e.name == 'single_oven_total_tardiness')
    assert entry.load()().methods() == Plugin().methods()
    assert metadata.version('single-oven-total-tardiness') == '0.2.1'
    assert not [e for e in metadata.entry_points(group='optimization_framework.problems') if e.name == 'single_oven_total_tardiness']
    plugins = OptimizerPlugins()
    assert set(IDS) <= {m['id'] for m in plugins.methods()}
