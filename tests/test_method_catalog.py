"""Which methods a campaign can run and why the others cannot: installed (bundled or a library), delivered by a coding
workspace and not installed, being built; proposal readiness says the same."""
import pytest

from optimization_framework.campaigns.method_catalog import catalog, unavailable
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace
from optimization_framework.optimizers import plugins
from optimization_framework.optimizers.registry import capability_reason


@pytest.fixture
def campaign(tmp_path):
    workspace = Workspace(tmp_path)
    record = workspace.create_campaign(CampaignInput(name='Catalog', compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    return workspace, record['id']


def proposal(workspace, cid, identity, algorithm='custom', chosen=True):
    return workspace.store.put('hypothesis', {'id': identity, 'campaign_id': cid, 'title': identity, 'status': 'proposed', 'mechanism': 'm',
                                              'algorithm': algorithm, 'algorithm_config': {}, 'algorithm_chosen': chosen})


def submission(workspace, cid, identity, hypothesis_ids, *, methods=None, files=('libraries/bakery/pyproject.toml',), status='submitted'):
    report = {'verdict': 'ready', 'summary': 's', 'tests': {'passed': 1, 'failed': 0, 'skipped': 0, 'command': ''}, 'limitations': [],
              'next_actions': [], 'methods': [{'method_id': m, 'hypothesis_id': h, 'state': 'implemented', 'conformance': 'passed'}
                                              for m, h in methods]} if methods else None
    return workspace.store.put('development_submission', {'id': identity, 'campaign_id': cid, 'workspace_id': 'development_' + identity,
        'hypothesis_id': hypothesis_ids[0], 'hypothesis_ids': hypothesis_ids, 'commit': 'a' * 40, 'status': status, 'report': report,
        'manifest': {'entrypoint': 'bakery.plugin:create', 'files': list(files)}, 'created_at': '2026-10-27T03:00:00+00:00'})


def test_a_method_bound_to_a_problem_says_which_problem_it_runs_on(campaign):
    workspace, cid = campaign
    task = workspace.current_tasks(cid)[0]
    if plugins.installed.get('conditional_mirror_search') is None:
        pytest.skip('grating-mask-search is not installed here')
    reason = capability_reason('conditional_mirror_search', task['problem'])
    assert 'runs only on meent_2d' in reason and "this task's problem is bounded_continuous" in reason


def test_readiness_names_the_installed_library_and_a_method_left_at_the_default(campaign, monkeypatch):
    workspace, cid = campaign
    library = proposal(workspace, cid, 'hypothesis_lib', 'random')
    monkeypatch.setattr(plugins.installed, 'origin', lambda name: {'entry_point': 'bakery', 'distribution': 'bakery-search', 'version': '0.2.0', 'own': False}
                        if name == 'random' else None)
    ready = workspace.implementations.readiness(library)
    assert ready['runnable'] and ready['reason'] == 'Installed library bakery-search 0.2.0 provides random.' and ready['validation_level'] == 'installed_library'
    default = workspace.implementations.readiness(proposal(workspace, cid, 'hypothesis_default', 'random', chosen=False))
    assert default['default_method'] and 'no method of its own was chosen' in default['reason']


def test_a_proposal_a_workspace_serves_is_building_then_delivered_then_installed(campaign):
    workspace, cid = campaign
    h = proposal(workspace, cid, 'hypothesis_dp')
    workspace.store.put('development_workspace', {'id': 'development_open', 'campaign_id': cid, 'hypothesis_id': 'hypothesis_other',
        'hypothesis_ids': ['hypothesis_other', 'hypothesis_dp'], 'desired_status': 'running', 'status': 'running', 'phase': 'testing', 'created_at': 'x'})
    assert workspace.implementations.readiness(h)['reason'] == 'Being built in a coding workspace (testing).'
    submission(workspace, cid, 'one', ['hypothesis_other', 'hypothesis_dp'], methods=[('bakery_dp', 'hypothesis_dp')])
    delivered = workspace.implementations.readiness(h)
    assert delivered['state'] == 'submitted_not_installed' and 'install it on the Implementations page' in delivered['reason']
    submission(workspace, cid, 'one', ['hypothesis_other', 'hypothesis_dp'], methods=[('random', 'hypothesis_dp')])   # its method is installed now
    installed = workspace.implementations.readiness(h)
    assert installed['state'] == 'installed_not_bound' and 'implementation.bind_builtin' in installed['reason']


def test_the_catalog_lists_what_runs_what_waits_to_be_installed_and_why_the_rest_cannot(campaign):
    workspace, cid = campaign
    proposal(workspace, cid, 'hypothesis_random', 'random')
    proposal(workspace, cid, 'hypothesis_dp')
    submission(workspace, cid, 'lib', ['hypothesis_dp'], methods=[('bakery_dp', 'hypothesis_dp')])
    submission(workspace, cid, 'old', ['hypothesis_dp'], files=('h12_optimizer.py',))
    view = catalog(workspace, cid)
    assert [t['blocker'] for t in view['tasks']] == [None]
    rows = {row['id']: row for row in view['methods']}
    assert rows['random']['state'] == 'runnable' and rows['random']['source'] == 'bundled'
    assert rows['random']['proposals'] == [{'hypothesis_id': 'hypothesis_random', 'bound': True, 'default': False}]
    dp = rows['bakery_dp']
    assert (dp['source'], dp['state'], dp['package']['name']) == ('submitted', 'not_installed', 'bakery')
    assert dp['next_action'] == {'owner': 'researcher', 'text': 'Install the library on this page'}
    assert rows['bakery.plugin:create']['state'] == 'legacy' and rows['bakery.plugin:create']['reported'] is False
    assert all(row['id'] != 'replay' for row in view['methods']) and any(o['id'] == 'replay' and 'not a search method' in o['reason'] for o in view['other'])
    agents = unavailable(workspace, cid)
    assert [m['id'] for m in agents['methods']] == ['bakery_dp', 'bakery.plugin:create'] and agents['tasks_blocked'] == []
