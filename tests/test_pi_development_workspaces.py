"""Durable native Pi coding workspace handoff and validation authority."""
import json
from pathlib import Path

import pytest

from optimization_framework.agents.development import DevelopmentWorkspaces
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace


class Driver:
    def __init__(self, root):
        self.directory = root
        self.cpu = 0
        self.prepared = 0
        self.started = 0
        self.paused = 0
        self.ignored = []

    def root(self, record):
        return self.directory / record['id']

    def name(self, record):
        return 'grating-' + record['id']

    def capability(self):
        return {'available': True}

    def prepare(self, record, brief, evidence):
        self.prepared += 1
        root = self.root(record)
        for name in ('incoming/commands', 'incoming/results', 'outgoing/events'):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / 'brief.md').write_text(brief)

    def start(self, record):
        self.started += 1
        return self.inspect(record)

    def inspect(self, record):
        return {'running': True, 'paused': bool(self.paused), 'port': 32768, 'pid': 1000}

    def cpu_seconds(self, state):
        return self.cpu

    def pause(self, record):
        self.paused += 1

    def stop(self, record):
        self.paused += 1

    def snapshot(self, record, commit, manifest_path):
        assert manifest_path == 'implementation-manifest.json'
        return ({'contract': 'optimizer_v1', 'entrypoint': 'optimizer:create_optimizer',
                 'files': [{'path': 'optimizer.py', 'content': 'def create_optimizer(*args): pass\n'}]},
                {'contract': 'optimizer_v1', 'entrypoint': 'optimizer:create_optimizer',
                 'files': ['optimizer.py'], 'dependencies': {}, 'test_summary': 'Development tests passed'}, self.ignored)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('GRATING_DEVELOPMENT_ENABLED', 'true')
    monkeypatch.setenv('GRATING_PI_PROVIDER', 'openai-codex')
    workspace = Workspace(tmp_path)
    campaign = workspace.create_campaign(CampaignInput(name='Development campaign', compute_budget_seconds=100,
        validation_reserve_seconds=10, implementation_compute_budget_seconds=30,
        tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    workspace.commands.execute(Command(id='activate-development', campaign_id=campaign['id'], expected_revision=1,
        operation='agent.activate', payload={'objective': 'Implement an optimizer'}))
    hypothesis = {'id': 'hypothesis_dev', 'campaign_id': campaign['id'], 'title': 'Test method',
                  'status': 'proposed', 'mechanism': 'A test implementation', 'algorithm': 'custom',
                  'algorithm_config': {}}
    workspace.store.put('hypothesis', hypothesis)
    driver = Driver(tmp_path / 'development')
    development = DevelopmentWorkspaces(workspace.pi, driver=driver)
    workspace.pi.development = development
    return workspace, campaign, development, driver


def outgoing(driver, record, identity, kind, payload):
    path = driver.root(record) / 'outgoing/events' / (identity + '.json')
    path.write_text(json.dumps({'type': kind, 'payload': payload}))


def test_persistent_workspace_receipts_and_replay(setup):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    request = {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement this method',
               'evidence_ids': [], 'request_key': 'request-one'}
    first = development.create(cid, request)
    second = development.create(cid, request)
    assert first['id'] == second['id']
    assert len(workspace.store.list('development_workspace', cid)) == 1
    development.sync(cid)
    assert driver.prepared == 1
    command_file = list((driver.root(first) / 'incoming/commands').glob('*.json'))
    assert len(command_file) == 1
    original_command = json.loads(command_file[0].read_text())
    assert original_command['operation'] == 'message'
    outgoing(driver, first, 'ready-event', 'ready', {'session_id': 'pi.jsonl', 'tools': ['bash', 'read', 'edit', 'write']})
    development.sync(cid)
    saved = development.get(cid, first['id'])
    assert saved['status'] == 'idle'
    assert saved['active_tools'] == ['bash', 'read', 'edit', 'write']
    assert development.events(cid, first['id'])['cursor'] == 2

    outgoing(driver, first, 'receipt-event', 'receipt', {'command_id': original_command['id'], 'status': 'accepted'})
    development.sync(cid)
    assert workspace.store.get(original_command['id'], 'development_command')['status'] == 'accepted'
    cursor = development.events(cid, first['id'])['cursor']
    outgoing(driver, first, 'receipt-event', 'receipt', {'command_id': original_command['id'], 'status': 'accepted'})
    development.sync(cid)
    assert development.events(cid, first['id'])['cursor'] == cursor
    restarted = DevelopmentWorkspaces(workspace.pi, driver=driver)
    assert restarted.get(cid, first['id'])['session_id'] == 'pi.jsonl'
    assert driver.prepared == 1


def test_questions_submissions_and_independent_validation_grant(setup, monkeypatch):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement',
                                       'request_key': 'create'})
    development.sync(cid)
    outgoing(driver, record, 'checkpoint', 'checkpoint', {'summary': 'Built the search module',
        'next_steps': 'Test seed replay', 'question': 'Should the seed be configurable?'})
    development.sync(cid)
    question = development.public(development.get(cid, record['id']))['questions'][0]
    answer = {'message': 'Yes, expose the seed.', 'mode': 'steer', 'request_key': 'answer', 'question_id': question['id']}
    development.message(cid, record['id'], answer)
    development.message(cid, record['id'], answer)
    assert workspace.store.get(question['id'], 'development_question')['status'] == 'answered'
    assert len([c for c in workspace.store.list('development_command', cid) if c['request_key'] == 'answer']) == 1

    commit = 'a' * 40
    outgoing(driver, record, 'submission-event', 'submission', {'commit': commit,
        'manifest_path': 'implementation-manifest.json', 'notes': 'Ready for independent checks'})
    development.sync(cid)
    submission = development.public(development.get(cid, record['id']))['submissions'][0]
    assert submission['commit'] == commit
    assert 'package' not in submission
    captured = {}
    def reserve(hypothesis_id, spec, **options):
        captured.update(hypothesis_id=hypothesis_id, spec=spec, **options)
        grant = {'id': 'grant_dev', 'campaign_id': cid, 'status': 'dispatching', 'compute_seconds': 0,
                 'request': {'compute_seconds': options['compute_seconds']}}
        workspace.store.put('implementation_grant', grant)
        return grant
    monkeypatch.setattr(workspace.implementations, 'reserve_commission', reserve)
    monkeypatch.setattr('optimization_framework.agents.capabilities.implementation_execution',
                        lambda: {'available': True})
    # The implementation module imports the capability function at invocation time.
    frozen = development.freeze_envelope(cid, record['id'], {'request_key': 'freeze',
        'spec': {'name': 'Test method', 'mechanism': 'Seeded search',
                 'acceptance_criteria': ['Seeded replay'], 'dependencies': {}}})
    assert frozen['checks'] == {'behavior': 0, 'mechanism': 0, 'diagnostic': 0}
    assert development.freeze_envelope(cid, record['id'], {'request_key': 'freeze',
        'spec': {'name': 'Test method', 'mechanism': 'Seeded search',
                 'acceptance_criteria': ['Seeded replay'], 'dependencies': {}}})['id'] == frozen['id']
    assert 'spec' not in development.public(development.get(cid, record['id']))['validation_envelopes'][0]
    result = development.validate(cid, record['id'], {'submission_id': submission['id'],
        'envelope_id': frozen['id'],
        'compute_seconds': 20, 'request_key': 'validate'})
    assert result['grant_id'] == 'grant_dev'
    assert captured['accounting_mode'] == 'execution_v1'
    assert captured['package']['files'][0]['content'].startswith('def create_optimizer')

    grant = workspace.store.get('grant_dev', 'implementation_grant')
    grant.update(status='failed', error='Independent check failed', attempts=[{'report': {'checks': [
        {'name': 'successful private reference', 'passed': True, 'detail': 'withheld expected design'},
        {'name': 'seed replay', 'passed': False, 'detail': 'replay diverged'}]},
        'review': {'findings': ['RNG state missing from checkpoint']}}])
    workspace.store.put('implementation_grant', grant)
    development.validation_feedback(development.get(cid, record['id']))
    saved = workspace.store.get(submission['id'], 'development_submission')
    assert saved['status'] == 'needs_revision'
    assert 'replay diverged' in json.dumps(saved['validation_outcome'])
    assert 'withheld expected design' not in json.dumps(saved['validation_outcome'])


def test_optional_cpu_allowance_pauses_without_losing_session(setup):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement',
        'request_key': 'limit', 'cpu_budget_seconds': 10})
    development.sync(cid)
    driver.cpu = 8
    development.sync(cid)
    assert development.get(cid, record['id'])['budget_checkpoint_requested']
    driver.cpu = 10
    development.sync(cid)
    saved = development.get(cid, record['id'])
    assert saved['status'] == 'paused'
    assert saved['usage']['container_cpu_seconds'] == 10
    assert driver.paused == 1
    with pytest.raises(ValueError, match='exhausted'):
        development.control(cid, record['id'], {'action': 'resume', 'request_key': 'too-soon',
                                                'expected_revision': saved['control_revision']})


def test_while_workspaces_are_off_the_refusal_names_the_commission_and_the_switch(setup, monkeypatch):
    workspace, campaign, development, driver = setup
    monkeypatch.setenv('GRATING_DEVELOPMENT_ENABLED', 'false')
    with pytest.raises(ValueError, match='implementation.commission') as refused:
        development.create(campaign['id'], {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'off'})
    assert 'GRATING_DEVELOPMENT_ENABLED=true' in str(refused.value)
    assert 'docker build -t grating-implementation-workspace' in str(refused.value)
    assert development.view(campaign['id'])['disabled'] == str(refused.value)


def test_a_workspace_runs_on_the_campaigns_model(setup):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    config = workspace.pi.configuration(cid)
    config['models'] = {'default': {'provider': 'centinels', 'model': 'gpt-6.1-sol', 'effort': None}, 'roles': {}}
    workspace.store.put('agent_campaign', config)
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'model'})
    assert record['model'] == {'provider': 'centinels', 'model': 'gpt-6.1-sol', 'effort': None}


def test_the_container_gets_the_campaigns_provider_only(tmp_path, monkeypatch):
    from optimization_framework.agents import development_runtime
    from optimization_framework.agents.development_runtime import DockerWorkspace
    auth, models = tmp_path / 'auth.json', tmp_path / 'models.json'
    auth.write_text(json.dumps({'centinels': {'type': 'api_key', 'key': 'router-key'}, 'openai-codex': {'type': 'oauth', 'access': 'codex-token'}}))
    models.write_text(json.dumps({'providers': {'centinels': {'baseUrl': 'https://8.8.8.8/v1', 'api': 'openai-completions'},
                                                'strixhalo': {'baseUrl': 'http://100.120.125.80:8084/v1', 'api': 'openai-completions'}}}))
    monkeypatch.setenv('GRATING_PI_AUTH_FILE', str(auth))
    monkeypatch.setenv('GRATING_PI_MODELS_FILE', str(models))
    driver = DockerWorkspace(tmp_path / 'development')
    record = {'id': 'development_one', 'model': {'provider': 'centinels', 'model': 'gpt-6.1-sol', 'effort': None}}
    root = driver.root(record)
    (root / 'incoming').mkdir(parents=True)
    driver.configure_pi(record, root)
    assert json.loads((root / 'incoming/auth.json').read_text()) == {'centinels': {'type': 'api_key', 'key': 'router-key'}}
    home = root / 'home/.pi/agent'
    assert json.loads((home / 'models.json').read_text()) == {'providers': {'centinels': {'baseUrl': 'https://8.8.8.8/v1', 'api': 'openai-completions'}}}
    settings = json.loads((home / 'settings.json').read_text())
    assert (settings['defaultProvider'], settings['defaultModel'], 'defaultThinkingLevel' in settings) == ('centinels', 'gpt-6.1-sol', False)

    commands = []
    monkeypatch.setattr(development_runtime, 'run', lambda args, **kwargs: commands.append(args) or '')
    monkeypatch.setattr(DockerWorkspace, 'inspect', lambda self, record: None)
    driver.start(record)
    assert {'PI_PROVIDER=centinels', 'PI_MODEL=gpt-6.1-sol', 'PI_THINKING='} <= set(commands[0])

    private = {'id': 'development_two', 'model': {'provider': 'strixhalo', 'model': 'local', 'effort': None}}
    with pytest.raises(ValueError, match='public addresses only'):
        driver.configure_pi(private, driver.root(private))


def test_a_specification_must_state_what_it_cites(setup):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    artifact = 'artifact_pi_tool_86f8269f855f5ffdb0b6c927c295bc7c'
    workspace.store.put('agent_artifact', {'id': artifact, 'campaign_id': cid, 'content': 'R4-A: the normative mechanism'})
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'cite'})
    spec = {'name': 'Test method', 'mechanism': f'Freeze {artifact} verbatim', 'acceptance_criteria': ['Seeded replay'],
            'dependencies': {}, 'provenance': [{'id': artifact}]}
    # The test designer sees the specification alone: an id it cannot read is refused before any model call.
    with pytest.raises(ValueError, match=f'campaign records \\({artifact}\\).*cannot read'):
        development.freeze_envelope(cid, record['id'], {'request_key': 'cited', 'spec': spec})
    with pytest.raises(ValueError, match='cannot read'):
        workspace.implementations.reserve_commission('hypothesis_dev', spec, compute_seconds=10, idempotency_key='cited')
    # Stated in full, with the record cited in provenance (and an id that names no record left alone), it is accepted.
    spec['mechanism'] = 'R4-A: the normative mechanism, written out; pi_tool_86f8269f855f5ffdb0b6c927c295bc7c'
    assert development.freeze_envelope(cid, record['id'], {'request_key': 'stated', 'spec': spec})['id']


def test_an_agent_opens_a_coding_workspace_only_with_the_researchers_go_ahead(setup):
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    workspace.store.put('hypothesis', {'id': 'hypothesis_other', 'campaign_id': cid, 'title': 'Other method', 'status': 'proposed',
                                       'mechanism': 'Another', 'algorithm': 'custom', 'algorithm_config': {}})
    request = {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'agent'}
    with pytest.raises(ValueError, match='approval.request with kind compute'):
        development.create(cid, request, actor='lead')
    compute_consent.grant(workspace, {'id': 'decision_go', 'campaign_id': cid},
                          {'plan': 'Implement the method', 'wall_seconds': 3600, 'worker_seconds': 600, 'coding_workspaces': 1})
    assert development.create(cid, request, actor='lead')['id']
    with pytest.raises(ValueError, match='0 coding workspaces for "Implement the method"'):
        development.create(cid, {**request, 'hypothesis_id': 'hypothesis_other'}, actor='lead')
    assert development.create(cid, {**request, 'hypothesis_id': 'hypothesis_other'})['id']   # the researcher's own


def test_a_go_ahead_for_named_proposals_opens_workspaces_only_for_them(setup):
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    workspace.store.put('hypothesis', {'id': 'hypothesis_other', 'campaign_id': cid, 'title': 'Other method', 'status': 'proposed',
                                       'mechanism': 'Another', 'algorithm': 'custom', 'algorithm_config': {}})
    consent = compute_consent.grant(workspace, {'id': 'decision_go', 'campaign_id': cid}, {'plan': 'Implement the first method',
        'wall_seconds': 3600, 'worker_seconds': 600, 'coding_workspaces': 2, 'hypothesis_ids': ['hypothesis_dev']})
    request = {'hypothesis_id': 'hypothesis_other', 'objective': 'Implement', 'request_key': 'agent'}
    with pytest.raises(ValueError, match='No approved plan covers work for hypothesis_other'):
        development.create(cid, request, actor='lead')
    with pytest.raises(ValueError, match='No approved plan covers work for hypothesis_dev, hypothesis_other'):
        development.create(cid, {**request, 'hypothesis_id': 'hypothesis_dev', 'hypothesis_ids': ['hypothesis_other']}, actor='lead')
    record = development.create(cid, {**request, 'hypothesis_id': 'hypothesis_dev'}, actor='lead')
    saved = workspace.store.get(consent['id'], 'compute_consent')
    assert record['consent']['id'] == consent['id'] and saved['workspace_ids'] == [record['id']] and saved['used_workspaces'] == 1


def test_the_history_of_a_workspace_reads_newest_first_from_what_it_recorded(setup, monkeypatch):
    from optimization_framework.agents.development_timeline import timeline
    from optimization_framework.campaigns import compute_consent
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    workspace.store.put('hypothesis', {'id': 'hypothesis_two', 'campaign_id': cid, 'title': 'Second method', 'status': 'proposed',
                                       'mechanism': 'Another', 'algorithm': 'custom', 'algorithm_config': {}})
    compute_consent.grant(workspace, {'id': 'decision_go', 'campaign_id': cid},
                          {'plan': 'Build both methods in one library', 'wall_seconds': 1200, 'worker_seconds': 300, 'coding_workspaces': 1})
    # Who opened it, under which go-ahead, for which proposals.
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'hypothesis_ids': ['hypothesis_two'], 'objective': 'Implement both',
                                       'request_key': 'history'}, actor='lead', opener={'agent_id': 'agent_impl', 'role': 'implementation_lead'})
    assert record['hypothesis_ids'] == ['hypothesis_dev', 'hypothesis_two'] and record['consent']['decision_id'] == 'decision_go'
    assert record['opened_by'] == {'actor': 'lead', 'agent_id': 'agent_impl', 'role': 'implementation_lead'}
    with pytest.raises(ValueError, match='No proposal hypothesis_missing'):
        development.create(cid, {'hypothesis_id': 'hypothesis_two', 'hypothesis_ids': ['hypothesis_missing'], 'objective': 'x', 'request_key': 'bad'})
    development.sync(cid)
    for key, kind, payload in [('e1', 'agent_start', {}), ('e2', 'tool', {'tool': 'bash', 'error': False, 'output': 'ok'}),
            ('e3', 'tool', {'tool': 'bash', 'error': True, 'output': 'collected 4 items\nFAILED tests/test_seed.py::test_replay\n\nCommand exited with code 1'}),
            ('e4', 'message', {'role': 'assistant', 'text': 'Both methods pass their tests.'}), ('e5', 'agent_settled', {}),
            ('e6', 'checkpoint', {'summary': 'Built both methods', 'blocker': 'The evaluator is not commissioned'}),
            ('e7', 'receipt', {'command_id': 'development_command_missing', 'status': 'accepted'})]:
        outgoing(driver, record, key, kind, payload)
    development.sync(cid)
    # A host that cannot run the workspace, then can again: both stay in its history.
    monkeypatch.setattr(driver, 'start', lambda record: (_ for _ in ()).throw(ValueError('Docker is not running')))
    development.sync(cid)
    monkeypatch.setattr(driver, 'start', lambda record: driver.inspect(record))
    development.sync(cid)
    saved = development.public(development.get(cid, record['id']))
    assert saved['started_at'] and saved['updated_at'] and saved['last_error_at']
    assert [c['summary'] for c in saved['checkpoints']] == ['Built both methods']
    entries = timeline(workspace.store, development.get(cid, record['id']))['entries']
    assert entries == sorted(entries, key=lambda e: e['at'], reverse=True)
    opened = entries[-1]
    assert opened['title'] == 'Opened by the implementation lead under your go-ahead' and 'Build both methods in one library' in opened['detail']
    work = next(e for e in entries if e['kind'] == 'work')
    assert work['title'].startswith('Worked') and work['title'].endswith('2 tool calls · 1 failed') and work['detail'] == 'Both methods pass their tests.'
    assert work['items'] == ['bash: FAILED tests/test_seed.py::test_replay (exit 1)']
    checkpoint = next(e for e in entries if e['kind'] == 'checkpoint')
    assert checkpoint['tone'] == 'warn' and 'Blocker: The evaluator is not commissioned' in checkpoint['detail']
    assert [e['kind'] for e in entries if e['tone'] in {'bad', 'ok'} and e['kind'] in {'blocked', 'recovered'}] == ['recovered', 'blocked']
    assert next(e for e in entries if e['kind'] == 'refused')['tone'] == 'warn'
    assert any(e['kind'] == 'instruction' and e['title'] == 'The lead wrote to the coding agent' for e in entries)
    page = timeline(workspace.store, development.get(cid, record['id']), limit=2)
    assert len(page['entries']) == 2 and timeline(workspace.store, development.get(cid, record['id']), before=page['next_before'])['entries'][0]['at'] <= page['next_before']


REPORT = {'verdict': 'ready_with_limits', 'summary': 'Both methods work.',
          'methods': [{'method_id': 'bakery_adjacent', 'hypothesis_id': 'hypothesis_dev', 'state': 'implemented',
                       'tests': {'passed': 12, 'failed': 0}, 'conformance': 'passed'}],
          'tests': {'passed': 32, 'failed': 0, 'skipped': 0, 'command': 'pytest libraries/bakery'},
          'limitations': ['The evaluator is not commissioned'], 'next_actions': [{'owner': 'researcher', 'action': 'Install the library'}]}


def refusal(driver, record, key):
    return json.loads((driver.root(record) / 'incoming/results' / (key + '.json')).read_text()).get('error', '')


def test_progress_and_the_delivery_report_are_the_coding_agents_own_and_say_how_it_went(setup):
    from balsamic.monitor.rows import inbox_view, acknowledge
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'report'})
    development.sync(cid)
    # A checkpoint's progress: the phase, the tests and its own estimate; a value it got wrong is left out, not the checkpoint.
    outgoing(driver, record, 'c1', 'checkpoint', {'summary': 'Testing', 'phase': 'testing', 'eta_minutes': 8,
                                                  'tests': {'passed': 30, 'failed': 2}, 'done': ['core'], 'remaining': ['seed replay']})
    outgoing(driver, record, 'c2', 'checkpoint', {'summary': 'Still testing', 'phase': 'coding', 'tests': {'passed': 'many'}})
    development.sync(cid)
    saved = development.public(development.get(cid, record['id']))
    assert saved['phase'] == 'testing' and saved['tests'] == {'passed': 30, 'failed': 2, 'skipped': 0}
    assert saved['estimate']['remaining_minutes'] == 8 and saved['estimate']['source'] == 'coding agent'
    assert saved['checkpoints'][0]['remaining'] == ['seed replay'] and saved['outcome'] is None
    # A report that contradicts itself is refused, naming what to fix; nothing is recorded.
    commit = 'b' * 40
    for key, report, says in [('r1', {**REPORT, 'verdict': 'ready'}, 'verdict ready allows no limitations'),
                              ('r2', {**REPORT, 'limitations': []}, 'needs the limitations listed'),
                              ('r3', {**REPORT, 'verdict': 'not_ready', 'next_actions': []}, 'not_ready needs next_actions'),
                              ('r4', {**REPORT, 'methods': [{**REPORT['methods'][0], 'hypothesis_id': 'hypothesis_elsewhere'}]}, 'methods[0].hypothesis_id')]:
        outgoing(driver, record, key, 'submission', {'commit': commit, 'manifest_path': 'implementation-manifest.json', 'report': report})
        development.sync(cid)
        assert says in refusal(driver, record, key)
    assert workspace.store.list('development_submission', cid) == []
    outgoing(driver, record, 'r5', 'submission', {'commit': commit, 'manifest_path': 'implementation-manifest.json', 'report': REPORT})
    development.sync(cid)
    submission = workspace.store.list('development_submission', cid)[0]
    assert submission['report']['verdict'] == 'ready_with_limits' and 'schema_version' not in json.dumps(submission['report'])
    outcome = development.public(development.get(cid, record['id']))['outcome']
    assert (outcome['state'], outcome['verdict'], outcome['submission_id']) == ('delivered', 'ready_with_limits', submission['id'])
    lead_notice = next(r for r in workspace.store.list('agent_run', cid) if submission['id'] in r['input'])
    assert "verdict: ready with limits; next: researcher: Install the library" in lead_notice['input']
    # The delivery is news in the inbox until acknowledged; the next result brings it back.
    [item] = [i for i in inbox_view(workspace, cid)['unacknowledged'] if i['kind'] == 'implementation']
    assert item['title'] == 'Implementation delivered: Test method: ready, with limits, 32 passed, 0 failed'
    acknowledge(workspace, cid, [item['key']])
    assert not [i for i in inbox_view(workspace, cid)['unacknowledged'] if i['kind'] == 'implementation']
    workspace.store.put('development_submission', {**submission, 'status': 'validated', 'validated_at': '2026-10-27T04:00:00+00:00'})
    [item] = [i for i in inbox_view(workspace, cid)['unacknowledged'] if i['kind'] == 'implementation']
    assert item['title'] == 'Implementation validated: Test method'


def test_a_submission_without_a_report_is_delivered_unreported_and_a_long_blocked_host_is_a_failure(setup, monkeypatch):
    from optimization_framework.agents import development as module
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'old'})
    development.sync(cid)
    monkeypatch.setattr(driver, 'start', lambda record: (_ for _ in ()).throw(ValueError('Docker is not running')))
    development.sync(cid)
    assert development.public(development.get(cid, record['id']))['outcome'] is None   # blocked, not yet failed
    saved = development.get(cid, record['id'])
    workspace.store.put('development_workspace', {**saved, 'blocked_since': '2026-10-27T00:00:00+00:00'})
    failed = development.public(development.get(cid, record['id']))['outcome']
    assert failed['state'] == 'failed' and 'Docker is not running' in failed['reason']
    monkeypatch.setattr(driver, 'start', lambda record: driver.inspect(record))
    development.sync(cid)
    assert 'blocked_since' not in development.get(cid, record['id'])
    outgoing(driver, record, 'old-submit', 'submission', {'commit': 'c' * 40, 'manifest_path': 'implementation-manifest.json', 'notes': 'Done'})
    development.sync(cid)
    assert development.public(development.get(cid, record['id']))['outcome']['verdict'] == 'unreported'


def test_each_validation_of_a_submission_has_its_result_recorded(setup, monkeypatch):
    workspace, campaign, development, driver = setup
    cid = campaign['id']
    record = development.create(cid, {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'twice'})
    development.sync(cid)
    outgoing(driver, record, 's', 'submission', {'commit': 'd' * 40, 'manifest_path': 'implementation-manifest.json', 'report': REPORT})
    development.sync(cid)
    submission = workspace.store.list('development_submission', cid)[0]
    grants = iter(['grant_one', 'grant_two'])
    def reserve(hypothesis_id, spec, **options):
        return workspace.store.put('implementation_grant', {'id': next(grants), 'campaign_id': cid, 'status': 'dispatching', 'compute_seconds': 0})
    monkeypatch.setattr(workspace.implementations, 'reserve_commission', reserve)
    monkeypatch.setattr('optimization_framework.agents.capabilities.implementation_execution', lambda: {'available': True})
    request = {'submission_id': submission['id'], 'spec': {'name': 'Test method', 'mechanism': 'Seeded search', 'acceptance_criteria': ['Seeded replay'], 'dependencies': {}},
               'compute_seconds': 20}
    def finish(grant_id, status):
        workspace.store.put('implementation_grant', {**workspace.store.get(grant_id, 'implementation_grant'), 'status': status,
                                                    'finished_at': '2026-10-27T05:00:00+00:00', 'attempts': []})
        development.validation_feedback(development.get(cid, record['id']))
    development.validate(cid, record['id'], {**request, 'request_key': 'first'})
    finish('grant_one', 'failed')
    assert workspace.store.get(submission['id'], 'development_submission')['status'] == 'needs_revision'
    development.validate(cid, record['id'], {**request, 'request_key': 'second'})
    assert workspace.store.get(submission['id'], 'development_submission')['status'] == 'validating'
    finish('grant_two', 'completed')
    saved = workspace.store.get(submission['id'], 'development_submission')
    assert saved['status'] == 'validated' and saved['validation_outcome']['id'] == 'grant_two' and saved['validated_at'] == '2026-10-27T05:00:00+00:00'
    told = [c for c in workspace.store.list('development_command', cid) if c['request_key'].startswith('validation-feedback-')]
    assert len(told) == 2   # the coding agent hears each result once
    # A result left unrecorded before this fix (feedback_sent from the first run) is corrected without waking the agent.
    workspace.store.put('development_submission', {**saved, 'status': 'validating', 'grant_id': 'grant_one', 'feedback_sent': True})
    development.validation_feedback(development.get(cid, record['id']))
    assert workspace.store.get(submission['id'], 'development_submission')['status'] == 'needs_revision'
    assert len([c for c in workspace.store.list('development_command', cid) if c['request_key'].startswith('validation-feedback-')]) == 2
