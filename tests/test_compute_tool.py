"""The compute tool (roadmap K1): arithmetic over literals and recorded values, on the charter's expression evaluator, with a
receipt that names each input's source."""
import builtins

import pytest

from optimization_framework.agents.roles import ROLE_BRIEFS, SPECIALIST_CONTRACT
from optimization_framework.agents.tools import INSTRUCTIONS, PiTools, step_label
from optimization_framework.contracts.requests import CampaignInput, TaskInput, TrialInput

from test_page_agents import call, submitted
from test_pi_agents import activated


def finished_trial(w, c, best=0.82, campaign_id=None):
    task = w.current_tasks(campaign_id or c['id'])[0]
    trial = w.create_trial(TrialInput(campaign_id=campaign_id or c['id'], task_id=task['id'], algorithm='coordinate', max_steps=2, wall_seconds=5))
    w.store.put('trial', {**w.store.get(trial['id'], 'trial'), 'status': 'completed', 'best_objective': best,
                          'summary': {'evaluations': [10, 32768]}})
    return w.store.get(trial['id'], 'trial')


def lead_turn(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    return w, c, lead, submitted(w, w.pi.message(c['id'], {'message': 'How far is the best run from 1?'}, 'ask'))


def receipt(w, agent, run, call_id):
    from optimization_framework.contracts.base import content_hash
    return w.store.get("pi_tool_" + content_hash([agent['id'], run['id'], call_id])[:32], 'agent_tool_receipt')


def test_compute_with_literals_with_a_recorded_value_and_with_both(tmp_path, monkeypatch):
    w, c, lead, run = lead_turn(tmp_path, monkeypatch)
    trial = finished_trial(w, c)
    # Part J's case: a mutation rate of 0.005 is 163.84 times 1/n for 32,768 cells, not "about 1/n".
    literal = call(w, lead, run, 'compute', {'expression': 'rate / (1 / n)', 'values': {'rate': 0.005, 'n': 32768}}, 'literal')
    assert literal['value'] == pytest.approx(163.84) and literal['expression'] == 'rate / (1 / n)'
    assert literal['inputs'] == [{'name': 'rate', 'value': 0.005, 'record_id': None, 'pointer': None},
                                 {'name': 'n', 'value': 32768, 'record_id': None, 'pointer': None}]
    recorded = call(w, lead, run, 'compute', {'expression': '1 - best', 'values': {'best': {'record_id': trial['id'], 'pointer': '/best_objective'}}}, 'recorded')
    assert recorded['value'] == pytest.approx(0.18)
    assert recorded['inputs'] == [{'name': 'best', 'value': 0.82, 'record_id': trial['id'], 'pointer': '/best_objective'}]
    both = call(w, lead, run, 'compute', {'expression': 'rate * cells', 'values': {
        'rate': 0.005, 'cells': {'record_id': trial['id'], 'pointer': '/summary/evaluations/1'}}}, 'both')
    assert both['value'] == pytest.approx(163.84)
    assert {item['name']: (item['record_id'], item['pointer']) for item in both['inputs']} == {
        'rate': (None, None), 'cells': (trial['id'], '/summary/evaluations/1')}
    # The call's receipt is the computation: the expression, each input with its source, and the value.
    kept = receipt(w, lead, run, 'both')
    assert kept['tool'] == 'compute' and kept['result'] == both and both['receipt_id'] == kept['id']


def test_a_value_from_outside_the_campaign_or_not_a_number_is_refused(tmp_path, monkeypatch):
    w, c, lead, run = lead_turn(tmp_path, monkeypatch)
    trial = finished_trial(w, c)
    other = w.create_campaign(CampaignInput(name='Another campaign', compute_budget_seconds=100, validation_reserve_seconds=10,
                                            tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    foreign = finished_trial(w, c, best=0.99, campaign_id=other['id'])
    refused = call(w, lead, run, 'compute', {'expression': 'x', 'values': {'x': {'record_id': foreign['id'], 'pointer': '/best_objective'}}}, 'foreign')
    assert refused['executed'] is False and 'not readable within this campaign' in refused['error']
    for name, pointer, reason in (('missing', '/no_such_field', 'does not name a field'), ('text', '/status', 'not a number'),
                                  ('flag', '/summary', 'not a number')):
        result = call(w, lead, run, 'compute', {'expression': 'x + 1', 'values': {'x': {'record_id': trial['id'], 'pointer': pointer}}}, name)
        assert result['executed'] is False and reason in result['error'], result
    unused = call(w, lead, run, 'compute', {'expression': 'a + 1', 'values': {'a': 1, 'b': 2}}, 'unused')
    assert unused['executed'] is False and 'b' in unused['error']
    flag = call(w, lead, run, 'compute', {'expression': 'a + 1', 'values': {'a': True}}, 'boolean')
    assert flag['executed'] is False
    many = call(w, lead, run, 'compute', {'expression': 'a0', 'values': {f'a{i}': i for i in range(51)}}, 'many')
    assert many['executed'] is False


def test_an_expression_over_the_evaluators_bounds_is_refused_with_its_text_and_nothing_reaches_eval(tmp_path, monkeypatch):
    w, c, lead, run = lead_turn(tmp_path, monkeypatch)
    evaluated, original = [], builtins.eval
    def watched(source, *args, **kwargs):
        evaluated.append(source)
        return original(source, *args, **kwargs)
    monkeypatch.setattr(builtins, 'eval', watched)
    for call_id, expression, text in (('long', '1 + ' * 400 + '1', 'longer than 1000 characters'),
                                      ('import', "__import__('os').system('true')", 'unknown function'),
                                      ('attribute', 'x.real', "'Attribute' is not allowed"),
                                      ('unknown', 'y * 2', 'unknown name y'),
                                      ('zero', 'x / 0', 'division by zero')):
        result = call(w, lead, run, 'compute', {'expression': expression, 'values': {'x': 2} if 'x' in expression else {}}, call_id)
        assert result['executed'] is False and text in result['error'], (call_id, result)
        assert not any(isinstance(source, str) and expression in source for source in evaluated), call_id
    assert call(w, lead, run, 'compute', {'expression': 'sqrt(x) + pi', 'values': {'x': 16}}, 'fine')['value'] == pytest.approx(4 + 3.141592653589793)


def test_compute_goes_to_the_lead_the_page_agents_and_the_specialists_that_list_it(tmp_path, monkeypatch):
    w, c, lead, run = lead_turn(tmp_path, monkeypatch)
    tools = PiTools(w.pi)
    assert 'compute' in tools.names(lead)
    for role in ('discussion_moderator', 'experiment_operator', 'implementation_lead', 'resource_planner'):
        asked = submitted(w, w.pi.message(c['id'], {'message': 'Wait.', 'page_agent': role}, 'page_' + role))
        assert 'compute' in tools.names(w.store.get(asked['agent_id'], 'agent_session')), role
    listed = {role for role, brief in ROLE_BRIEFS.items() if 'compute' in brief['tools']}
    assert listed == {'results_analyst', 'empirical_assessor', 'methodology_specialist', 'skeptical_domain_analyst'}
    for role in ROLE_BRIEFS:
        assert ('compute' in tools.names({'role': role})) == (role in listed), role
    builder = w.pi.create_agent(c['id'], 'implementation_builder', 'Build', 'builder_compute', parent_id=lead['id'], grant_id='grant_compute')
    assert 'compute' not in tools.names(builder)
    # One sentence for the agents, and a label for the chat.
    flat = lambda text: ' '.join(text.split())
    assert 'Derive a number with compute or a script, never mental arithmetic' in flat(INSTRUCTIONS)
    assert 'compute or a script, never from mental arithmetic' in flat(SPECIALIST_CONTRACT)
    assert step_label('compute', {'expression': 'a / b'}) == 'Computing a number'
