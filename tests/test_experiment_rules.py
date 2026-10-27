"""The experiment rules the operator keeps, runs hidden from the Experiments page, and the operator's own tools."""
import pytest

from optimization_framework.agents.experiments import suggest
from optimization_framework.campaigns.experiment_rules import classify, current
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import TrialInput

from test_page_agents import call, finish, submitted, wakes
from test_pi_agents import activated


def command(w, c, operation, payload, identity):
    return w.commands.execute(Command(id=identity, campaign_id=c['id'], expected_revision=w.store.get(c['id'], 'campaign')['version'],
                                      operation=operation, payload=payload))['outcome']


def run(w, c, status='completed', **values):
    task = w.current_tasks(c['id'])[0]
    trial = w.create_trial(TrialInput(campaign_id=c['id'], task_id=task['id'], algorithm='coordinate', max_steps=2, wall_seconds=5, **values))
    if status != 'queued':
        w.store.put('trial', {**w.store.get(trial['id'], 'trial'), 'status': status})
    return w.store.get(trial['id'], 'trial')


def test_the_rules_start_from_the_runtime_gate_and_change_by_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('GRATING_RUNTIME_GATE_SECONDS', '600')
    w, c, lead = activated(tmp_path, monkeypatch)
    rules = current(w.store, c['id'])
    assert (rules['revision'], rules['short_run_seconds'], rules['max_concurrent']) == (0, 600.0, None) and '{seed}' in rules['naming']
    saved = command(w, c, 'experiments.rules', {'max_concurrent': 2, 'short_run_seconds': 900, 'expected_revision': 0, 'rationale': 'GPU memory'}, 'r1')
    assert (saved['revision'], saved['max_concurrent'], saved['short_run_seconds'], saved['updated_by']) == (1, 2, 900, 'researcher')
    with pytest.raises(ValueError, match='changed'):
        command(w, c, 'experiments.rules', {'max_concurrent': 3, 'expected_revision': 0, 'rationale': 'stale'}, 'r2')
    assert command(w, c, 'experiments.rules', {'max_concurrent': 0, 'expected_revision': 1, 'rationale': 'No limit'}, 'r3')['max_concurrent'] is None
    # The lead reads them; the operator is told them in each turn's state block, and changes them under its own name.
    lead_run = submitted(w, w.pi.message(c['id'], {'message': 'What are the rules?'}, 'ask'))
    assert call(w, lead, lead_run, 'campaign_inspect', {}, 'inspect')['experiment_rules']['short_run_seconds'] == 900
    asked = submitted(w, w.pi.message(c['id'], {'message': 'Allow two runs at once.', 'page_agent': 'experiment_operator'}, 'op'))
    operator = w.store.get(asked['agent_id'], 'agent_session')
    from optimization_framework.agents.tools import PiTools
    state = PiTools(w.pi).turn_state(operator['id'], asked['id'])['text']
    assert 'revision 2' in state and 'Short runs are allotted less than 900 seconds' in state and 'expected improvement' not in state
    assert 'experiment rules' in PiTools(w.pi).manifest(operator['id'], asked['id'])['instructions'] and '900' not in PiTools(w.pi).manifest(operator['id'], asked['id'])['instructions']
    changed = call(w, operator, asked, 'campaign_command', {'operation': 'experiments.rules', 'request_key': 'two', 'guidance_revision': w.memory.state(c['id'])['guidance_revision'],
        'payload': {'max_concurrent': 2, 'expected_revision': 2, 'rationale': 'The researcher asked for two at once'}}, 'rules')
    assert changed['outcome']['max_concurrent'] == 2 and current(w.store, c['id'])['updated_by'] == 'manager' and changed['page'] == '#experiments/rules'


def test_finished_runs_can_be_hidden_and_shown_again_but_not_runs_at_work(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    done, failed, queued = run(w, c), run(w, c, 'failed'), run(w, c, 'queued')
    with pytest.raises(ValueError, match='Stop these runs'):
        command(w, c, 'trial.hide', {'trial_ids': [done['id'], queued['id']], 'reason': 'Superseded'}, 'h1')
    hidden = command(w, c, 'trial.hide', {'trial_ids': [done['id'], failed['id']], 'reason': 'Out of GPU memory; run again'}, 'h2')
    assert hidden['changed'] == [done['id'], failed['id']]
    record = w.store.get(failed['id'], 'trial')
    assert record['hidden']['reason'] == 'Out of GPU memory; run again' and record['hidden']['by'] == 'researcher' and record['status'] == 'failed'
    assert command(w, c, 'trial.hide', {'trial_ids': [done['id']], 'hidden': False}, 'h3')['changed'] == [done['id']]
    assert 'hidden' not in w.store.get(done['id'], 'trial')
    other = activated(tmp_path / 'other', monkeypatch)
    foreign = run(other[0], other[1])
    with pytest.raises(KeyError):
        command(w, c, 'trial.hide', {'trial_ids': [foreign['id']]}, 'h4')


def test_runs_are_listed_as_short_long_or_checks_and_a_continued_run_counts_whole():
    trials = [{'id': 'screen', 'wall_seconds': 300}, {'id': 'final', 'wall_seconds': 14400},
              {'id': 'first', 'wall_seconds': 599}, {'id': 'second', 'wall_seconds': 599, 'parent_trial_id': 'first'},
              {'id': 'check', 'wall_seconds': 900, 'recipe': {'recipe_id': 'x'}, 'parent_trial_id': 'final'},
              {'id': 'probe', 'wall_seconds': 300}, {'id': 'validation', 'wall_seconds': 120, 'algorithm': 'validate'}]
    assert classify(trials, 600, {'probe'}) == {'screen': 'short', 'final': 'long', 'first': 'long', 'second': 'long', 'check': 'check',
                                                 'probe': 'check', 'validation': 'check'}


def test_the_scheduler_holds_a_campaigns_runs_above_its_limit_and_never_holds_checks(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    running, waiting = run(w, c, 'running'), run(w, c, 'queued')
    trials = [running, waiting]
    assert not w._over_campaign_limit(waiting, trials, {})
    command(w, c, 'experiments.rules', {'max_concurrent': 1, 'expected_revision': 0, 'rationale': 'One at a time'}, 'one')
    assert w._over_campaign_limit(waiting, trials, {})
    probe = run(w, c, 'queued')
    w.store.put('runtime_profile', {'id': 'runtime_profile_x', 'campaign_id': c['id'], 'status': 'running', 'levels': [{'workers': 1, 'trial_ids': [probe['id']]}]})
    assert not w._over_campaign_limit(probe, trials + [probe], {})
    # Another campaign's runs do not count.
    other = activated(tmp_path / 'other', monkeypatch)
    assert not w._over_campaign_limit({**waiting, 'campaign_id': other[1]['id']}, trials, {})


def test_the_state_lists_each_runs_group_and_the_rules(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from balsamic.app import create_app
    monkeypatch.setenv('GRATING_LLM_DISABLED', 'true')
    app = create_app(tmp_path / 'workspace', start_workers=False)
    with TestClient(app) as client:
        w = app.state.workspace
        from optimization_framework.contracts.requests import CampaignInput, TaskInput
        c = w.create_campaign(CampaignInput(name='Rules', compute_budget_seconds=100000, validation_reserve_seconds=10,
            tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
        task = w.current_tasks(c['id'])[0]
        short = w.create_trial(TrialInput(campaign_id=c['id'], task_id=task['id'], algorithm='coordinate', max_steps=2, wall_seconds=60))
        long = w.create_trial(TrialInput(campaign_id=c['id'], task_id=task['id'], algorithm='coordinate', max_steps=2, wall_seconds=3600))
        page = client.get(f"/api/v1/campaigns/{c['id']}/experiments").json()
        kinds = {trial['id']: kind for kind in ('short', 'long', 'checks') for trial in page[kind]}
        assert kinds == {short['id']: 'short', long['id']: 'long'} and page['rules']['revision'] == 0


def test_the_operator_reads_progress_and_asks_for_settings(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    asked = submitted(w, w.pi.message(c['id'], {'message': 'How are the runs going?', 'page_agent': 'experiment_operator'}, 'op'))
    operator = w.store.get(asked['agent_id'], 'agent_session')
    finished = run(w, c, question='Screen · H1 · coordinate · seed 0\nWhy: a floor')
    waiting = run(w, c, 'queued', priority=5)
    hidden = run(w, c, 'failed')
    command(w, c, 'trial.hide', {'trial_ids': [hidden['id']], 'reason': 'Superseded'}, 'hide')
    progress = call(w, operator, asked, 'experiment_progress', {}, 'progress')
    assert [row['trial_id'] for row in progress['at_work']] == [waiting['id']] and progress['at_work'][0]['priority'] == 5
    assert [row['name'] for row in progress['recently_finished']] == ['Screen · H1 · coordinate · seed 0'] and progress['hidden'] == 1
    assert progress['worker_ceiling'] == w.max_workers and progress['at_work'][0]['kind'] == 'short'
    space = {'step': {'type': 'log', 'low': 1e-3, 'high': 1.0}, 'restarts': {'type': 'int', 'low': 1, 'high': 8}}
    spread = call(w, operator, asked, 'config_suggest', {'space': space, 'count': 3}, 'suggest')
    assert spread['method'] == 'space-filling' and len(spread['suggestions']) == 3
    assert all(1e-3 <= item['step'] <= 1 and isinstance(item['restarts'], int) for item in spread['suggestions'])
    # The lead reads progress itself (a status question is a read, not work for the operator); choosing settings stays the operator's.
    lead_run = submitted(w, w.pi.message(c['id'], {'message': 'How are the runs going?'}, 'lead'))
    assert call(w, lead, lead_run, 'experiment_progress', {}, 'lead_progress')['at_work'][0]['trial_id'] == waiting['id']
    with pytest.raises(ValueError, match='not available'):
        call(w, lead, lead_run, 'config_suggest', {'space': space}, 'nope')


def test_suggestions_spread_first_then_follow_the_scores():
    space = {'x': {'type': 'float', 'low': 0, 'high': 1}, 'kind': {'type': 'choice', 'choices': ['a', 'b']}}
    score = lambda config: -(config['x'] - 0.3) ** 2 + (0.2 if config['kind'] == 'b' else 0)
    observations = [{'config': config, 'score': score(config)} for config in suggest(space, [], count=6, seed=2)['suggestions']]
    assert suggest(space, [], count=6, seed=2) == suggest(space, [], count=6, seed=2)   # the same seed, the same spread
    for round in range(3):
        result = suggest(space, observations, count=2, seed=round)
        assert result['method'] == 'model' and all({'predicted', 'uncertainty'} <= set(item) for item in result['suggestions'])
        observations += [{'config': item['config'], 'score': score(item['config'])} for item in result['suggestions']]
    best = max(observations, key=lambda row: row['score'])['config']
    assert best['kind'] == 'b' and abs(best['x'] - 0.3) < 0.1
    with pytest.raises(ValueError, match='low < high'):
        suggest({'x': {'type': 'float', 'low': 1, 'high': 0}}, [])
    # Minimizing turns the same scores around.
    lowest = suggest({'x': {'type': 'float', 'low': 0, 'high': 1}}, [{'config': {'x': value / 10}, 'score': value} for value in range(10)],
                     count=1, maximize=False)['suggestions'][0]['config']['x']
    assert lowest < 0.3


def test_a_page_agents_question_to_the_lead_is_answered_back_without_touching_the_researchers_request(tmp_path, monkeypatch):
    from optimization_framework.agents.models import NOTICE
    w, c, lead = activated(tmp_path, monkeypatch)
    asked = submitted(w, w.pi.message(c['id'], {'message': 'Screen the three strategies.', 'page_agent': 'experiment_operator'}, 'op'))
    operator = w.store.get(asked['agent_id'], 'agent_session')
    sent = call(w, operator, asked, 'lead_ask', {'question': 'Why does H2 use a log-scaled step?'}, 'why')
    question = w.store.get(sent['run_id'], 'agent_run')
    assert question['agent_id'] == lead['id'] and question['asked_by'] == operator['id'] and question['input'].startswith(NOTICE)
    note = next(m for m in w.store.list('message') if m.get('from_agent_id') == operator['id'])
    assert (note['role'], note['agent_id'], note['content']) == ('agent', lead['id'], 'Why does H2 use a log-scaled step?')
    assert not w.pi.configuration(c['id'])['request_open']
    lead_turn = submitted(w, question)
    assert 'report' in call(w, lead, lead_turn, 'yield_work', {'disposition': 'complete', 'summary': 'Answered the operator'}, 'bare')['error']
    call(w, lead, lead_turn, 'yield_work', {'disposition': 'complete', 'summary': 'Answered the operator',
        'report': 'Its step spans three decades, so it is sampled on a log scale.'}, 'done')
    finish(w, lead, lead_turn, 'Let me answer.')
    answer = wakes(w, operator, 'lead_answer_')
    assert len(answer) == 1 and 'three decades' in answer[0]['input']
    reply = w.store.get('message_' + lead_turn['id'], 'message')
    assert reply['to_agent_id'] == operator['id'] and not w.pi.configuration(c['id'])['request_open']
    # Only page agents ask the lead this way.
    lead_run = submitted(w, w.pi.message(c['id'], {'message': 'Go on.'}, 'go'))
    with pytest.raises(ValueError, match='not available'):
        call(w, lead, lead_run, 'lead_ask', {'question': 'x'}, 'self')


def test_how_runs_are_presented_starts_from_the_problem_and_refuses_unreadable_choices(tmp_path, monkeypatch):
    from optimization_framework.campaigns.experiment_rules import default_presentation
    grid = {'definition_id': 'meent_2d_dual_polarization_deflector', 'candidate_schema': {'representation': 'binary', 'dimensions': 32768},
            'configuration': {'grid_x': 256, 'grid_y': 128}}
    shown = default_presentation(grid)
    assert shown['design']['render'] == 'mask' and (shown['design']['rows'], shown['design']['cols']) == (128, 256)
    assert shown['design']['on_label'] == 'silicon' and 'thumbnail' in shown['list_columns']
    assert default_presentation({'candidate_schema': {'representation': 'binary', 'dimensions': 64}})['design']['render'] == 'strip'
    assert default_presentation({'candidate_schema': {'representation': 'continuous', 'dimensions': 6}})['design']['render'] == 'table'
    assert default_presentation({'candidate_schema': {'representation': 'continuous', 'dimensions': 5000}})['design']['render'] == 'none'
    w, c, lead = activated(tmp_path, monkeypatch)
    rules = current(w.store, c['id'])
    assert rules['presentation_chosen'] is False and rules['presentation']['design']['render'] == 'table'   # the test problem has few values
    choice = {'list_columns': ['name', 'best', 'objectives'], 'entry_sections': ['curve', 'design'], 'design': {'render': 'table'},
              'rationale': 'The score curve matters most here'}
    saved = command(w, c, 'experiments.rules', {'presentation': choice, 'expected_revision': 0, 'rationale': 'Chosen with the lead'}, 'p1')
    assert saved['presentation_chosen'] and saved['presentation']['entry_sections'] == ['curve', 'design']
    assert saved['presentation']['rationale'] == 'The score curve matters most here'
    unexplained = command(w, c, 'experiments.rules', {'presentation': {**choice, 'rationale': ''}, 'expected_revision': 1, 'rationale': 'Asked the lead'}, 'p0')
    assert unexplained['presentation']['rationale'] == 'Asked the lead'
    with pytest.raises(ValueError, match='rows x cols'):
        command(w, c, 'experiments.rules', {'presentation': {**choice, 'design': {'render': 'mask', 'rows': 3, 'cols': 3}},
                                             'expected_revision': 2, 'rationale': 'x'}, 'p2')
    with pytest.raises(ValueError):
        command(w, c, 'experiments.rules', {'presentation': {**choice, 'entry_sections': ['html']}, 'expected_revision': 2, 'rationale': 'x'}, 'p3')


def test_a_runs_curve_is_read_as_a_few_columns_and_thinned(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from balsamic.app import create_app
    from optimization_framework.contracts.requests import CampaignInput, TaskInput
    monkeypatch.setenv('GRATING_LLM_DISABLED', 'true')
    app = create_app(tmp_path / 'workspace', start_workers=False)
    with TestClient(app) as client:
        w = app.state.workspace
        c = w.create_campaign(CampaignInput(name='Curve', compute_budget_seconds=1000, validation_reserve_seconds=10,
            tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
        trial = w.create_trial(TrialInput(campaign_id=c['id'], task_id=w.current_tasks(c['id'])[0]['id'], algorithm='coordinate', max_steps=2, wall_seconds=5))
        path = w.job_dir(trial['id']) / 'metrics.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps({'step': i, 'evaluations': i, 'best_objective': i / 1000, 'best_objectives': {'a': i}}) + '\n' for i in range(1, 1001)))
        rows = client.get(f"/api/v1/experiments/{trial['id']}/metrics", params={'fields': 'evaluations,best_objective', 'points': 50}).json()
        assert len(rows) == 50 and rows[0]['evaluations'] == 1 and rows[-1]['evaluations'] == 1000 and set(rows[0]) == {'evaluations', 'best_objective'}
