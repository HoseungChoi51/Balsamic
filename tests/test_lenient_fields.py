"""Unknown fields reported, not refused, at the agent boundaries (roadmap B6, decision 5)."""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from balsamic.app import create_app

from optimization_framework.agents import development_runtime
from optimization_framework.agents.development import submission_manifest
from optimization_framework.contracts.requests import CampaignInput, TaskInput

from test_experiment_rules import activated, call, submitted
from test_pi_development_workspaces import outgoing, setup  # noqa: F401 (a fixture)

MANIFEST = {'contract': 'optimizer_v1', 'entrypoint': 'optimizer:create_optimizer', 'files': ['libraries/bakery/optimizer.py']}


def test_a_manifest_with_an_unknown_field_is_accepted_and_reports_it_ignored():
    manifest, ignored = submission_manifest(json.dumps({**MANIFEST, 'description': 'Two bakery searches'}), [])
    assert ignored == ['description'] and manifest.files == ['libraries/bakery/optimizer.py']


def test_a_near_miss_in_the_manifest_is_refused_with_the_field_it_meant():
    with pytest.raises(ValueError, match='did you mean files'):
        submission_manifest(json.dumps({'file': ['libraries/bakery/optimizer.py']}), [])


def test_nested_objects_of_the_manifest_stay_strict():
    with pytest.raises(ValueError):
        submission_manifest(json.dumps({**MANIFEST, 'dependencies': {'numpy': {'version': '2.0'}}}), [])


def test_without_a_manifest_one_is_derived_from_the_commits_single_library():
    manifest, ignored = submission_manifest(None, ['libraries/bakery/pyproject.toml', 'libraries/bakery/bakery/plugin.py'])
    assert (manifest.contract, manifest.entrypoint, ignored) == ('optimizer_v1', 'optimizer:create_optimizer', [])
    assert manifest.files == ['libraries/bakery/bakery/plugin.py', 'libraries/bakery/pyproject.toml']
    for tracked, named in (([], 'no library'), (['libraries/a/x.py', 'libraries/b/y.py'], '2 libraries')):
        with pytest.raises(ValueError, match=named):
            submission_manifest(None, tracked)


def git_repository(path, files):
    path.mkdir()
    for name, content in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(content)
    for args in (['init', '-q'], ['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'library']):
        subprocess.run(['git', '-C', str(path), *args], check=True)
    return subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize('manifest', [{**MANIFEST, 'description': 'ignored'}, None])
def test_the_workspace_snapshot_reads_a_lenient_or_derived_manifest_from_the_commit(tmp_path, monkeypatch, manifest):
    files = {'libraries/bakery/optimizer.py': 'def create_optimizer(context): pass\n'}
    if manifest:
        files['implementation-manifest.json'] = json.dumps(manifest)
    commit = git_repository(tmp_path / 'repo', files)
    def run(args, timeout=45, cwd=None):   # the container's git, on the host repository
        assert args[:2] == ['docker', 'exec'] and args[5:8] == ['git', '--no-replace-objects', '-C']
        return development_runtime.subprocess.run(['git', '-C', str(tmp_path / 'repo'), *args[9:]], check=True, capture_output=True, text=True).stdout
    monkeypatch.setattr(development_runtime, 'run', run)
    package, saved, ignored = development_runtime.DockerWorkspace(tmp_path).snapshot({'id': 'w'}, commit, 'implementation-manifest.json')
    assert saved['files'] == ['libraries/bakery/optimizer.py'] and package['files'][0]['content'].startswith('def create_optimizer')
    assert ignored == (['description'] if manifest else [])


def test_the_coding_agent_is_told_which_manifest_fields_were_ignored(setup):
    workspace, campaign, development, driver = setup
    record = development.create(campaign['id'], {'hypothesis_id': 'hypothesis_dev', 'objective': 'Implement', 'request_key': 'lenient'})
    development.sync(campaign['id'])
    driver.ignored = ['description']
    outgoing(driver, record, 'submit', 'submission', {'commit': 'b' * 40, 'manifest_path': 'implementation-manifest.json'})
    development.sync(campaign['id'])
    result = json.loads((driver.root(record) / 'incoming/results/submit.json').read_text())
    assert result['submission_id'].startswith('development_submission_') and result['ignored_fields'] == ['description']


def test_an_agent_command_drops_an_unknown_field_and_lists_it_but_refuses_a_near_miss(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    asked = submitted(w, w.pi.message(c['id'], {'message': 'Allow two runs at once.', 'page_agent': 'experiment_operator'}, 'op'))
    operator = w.store.get(asked['agent_id'], 'agent_session')
    guidance = w.memory.state(c['id'])['guidance_revision']
    task = w.current_tasks(c['id'])[0]
    refused = call(w, operator, asked, 'campaign_command', {'operation': 'trial.create', 'request_key': 'short', 'guidance_revision': guidance,
        'payload': {'task_id': task['id'], 'algorithm': 'coordinate', 'max_steps': 2, 'wall_secs': 10}}, 'misspelled')
    assert refused['executed'] is False and 'did you mean wall_seconds' in refused['error'] and not w.store.list('trial', c['id'])
    args = {'operation': 'experiments.rules', 'request_key': 'two', 'guidance_revision': guidance,
            'payload': {'max_concurrent': 2, 'expected_revision': 0, 'rationale': 'The researcher asked', 'note': 'two at once'}}
    changed = call(w, operator, asked, 'campaign_command', args, 'rules')
    assert changed['outcome']['max_concurrent'] == 2 and changed['ignored_fields'] == ['note']
    receipt = w.store.get(changed['id'], 'work_command')
    assert receipt['ignored_fields'] == ['note'] and 'note' not in receipt['request']['payload']
    # The same request again is the same command, and still says what it ignored.
    assert call(w, operator, asked, 'campaign_command', args, 'rules_again')['ignored_fields'] == ['note']


def test_the_researchers_http_api_still_refuses_an_extra_field(tmp_path, monkeypatch):
    monkeypatch.setenv('GRATING_LLM_DISABLED', 'true')
    app = create_app(tmp_path, start_workers=False)
    workspace = app.state.workspace
    campaign = workspace.create_campaign(CampaignInput(name='Strict API', compute_budget_seconds=200, validation_reserve_seconds=0,
        tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    task = workspace.current_tasks(campaign['id'])[0]
    with TestClient(app) as client:
        sent = client.post('/api/v1/commands', json={'id': 'strict', 'campaign_id': campaign['id'], 'operation': 'trial.create',
            'expected_revision': campaign['version'], 'payload': {'task_id': task['id'], 'algorithm': 'coordinate', 'wall_seconds': 10,
                                                                  'max_steps': 2, 'note': 'extra'}})
    assert sent.status_code >= 400 and 'note' in sent.text and not workspace.store.list('trial', campaign['id'])
