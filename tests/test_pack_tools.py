"""Pack tools (roadmap N4): the mask tools are MEENT's, offered only to agents of campaigns on MEENT's problems."""
import pytest

from optimization_framework.agents.tools import EXTRA_TOOLS, PACK_OPERATIONS, ROLE_OPERATIONS, PiTools
from optimization_framework.contracts.commands import Command
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.execution.service import Workspace

from test_page_agents import call, guidance, submitted


def campaign(w, problem_id, name):
    created = w.create_campaign(CampaignInput(name=name, compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name=name, problem_id=problem_id, configuration={})]))
    w.commands.execute(Command(id='start_' + created['id'], campaign_id=created['id'], expected_revision=1, operation='agent.activate', payload={}))
    return created


def agents(w, c):
    """The lead and the experiment operator of a campaign, each with a run and the tools of its manifest."""
    tools = PiTools(w.pi)
    lead = w.store.get(w.pi.configuration(c['id'])['lead_id'], 'agent_session')
    lead_run = submitted(w, w.pi.message(c['id'], {'message': 'Wait for my next message.'}, 'ask_lead_' + c['id']))
    run = submitted(w, w.pi.message(c['id'], {'message': 'Wait for my next message.', 'page_agent': 'experiment_operator'}, 'ask_operator_' + c['id']))
    operator = w.store.get(run['agent_id'], 'agent_session')
    manifest = lambda agent, run: {tool['name']: tool for tool in tools.manifest(agent['id'], run['id'])['tools']}
    return (lead, lead_run, manifest(lead, lead_run)), (operator, run, manifest(operator, run))


def operations(manifest):
    return set(manifest['campaign_command']['input_schema']['properties']['operation']['enum'])


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv('GRATING_LLM_ENABLED', 'true')
    monkeypatch.setenv('GRATING_LLM_DISABLED', 'false')
    monkeypatch.setenv('GRATING_PI_PROVIDER', 'openai-codex')
    w = Workspace(tmp_path)
    return w, campaign(w, 'meent_grating', 'Grating'), campaign(w, 'bounded_continuous', 'Quadratic')


def test_a_meent_campaigns_operator_has_both_tools_and_its_lead_asks_the_operator(lab):
    w, meent, _ = lab
    (lead, lead_run, lead_tools), (operator, run, operator_tools) = agents(w, meent)
    assert 'mask_create' in operator_tools and 'mask_create' in lead_tools
    assert operations(operator_tools) == ROLE_OPERATIONS['experiment_operator'] | {'fixed_mask.run'}
    assert 'fixed_mask.run' not in operations(lead_tools)
    assert EXTRA_TOOLS['mask_create']['pack'] == PACK_OPERATIONS['fixed_mask.run']['pack'] == 'dqn_meent.pack'
    # The lead's own call is routed to the operator, as for the pages' other work.
    refused = call(w, lead, lead_run, 'campaign_command', {'operation': 'fixed_mask.run', 'payload': {}, 'request_key': 'f'}, 'lead_fixed')
    assert refused['executed'] is False and 'experiment operator' in refused['error']
    tools = PiTools(w.pi)
    assert tools.capabilities(lead)['fixed_mask_diagnostics'] == 'the experiment operator (fixed_mask.run)'
    assert tools.capabilities(operator)['fixed_mask_diagnostics'] == 'fixed_mask.run'
    # The tool makes a full-sized design, saved as a mask artifact with its receipt.
    task = w.current_tasks(meent['id'])[0]
    made = call(w, operator, run, 'mask_create', {'task_id': task['id'], 'pattern': 'seeded_random', 'seed': 3}, 'mask')
    artifact = w.store.get(made['artifact_id'], 'agent_artifact')
    assert artifact['kind'] == 'mask' and len(artifact['content']['mask']) == made['dimensions'] == 64
    assert w.store.get_entry(made['artifact_id']) and any(r['tool'] == 'mask_create' for r in w.store.list('agent_tool_receipt', meent['id']))
    # The operator's command reaches the pack's handler, which queues a job of the same kind as before (without MEENT
    # installed, the handler's own check refuses the evaluator, so the command got that far).
    queued = call(w, operator, run, 'campaign_command', {'operation': 'fixed_mask.run', 'request_key': 'fixed', 'guidance_revision': guidance(w, meent),
        'payload': {'task_id': task['id'], 'mask_artifact_ids': [artifact['id']], 'fidelities': [{}], 'wall_seconds': 5,
                    'rationale': 'Check a known design'}}, 'fixed')
    if not w.evaluators.readiness(task)['runnable']:
        assert queued['error'] == 'The selected evaluator is not runnable', queued
        return
    assert 'error' not in queued, queued
    job, = w.store.list('fixed_mask_job', meent['id'])
    assert job['status'] == 'queued' and job['fixtures'][0]['artifact_id'] == artifact['id']


def test_a_campaign_on_another_problem_has_neither_tool_even_after_a_meent_campaign_registered_them(lab):
    w, meent, other = lab
    agents(w, meent)   # the pack's hooks have run in this workspace
    assert 'mask_create' in EXTRA_TOOLS
    (lead, lead_run, lead_tools), (operator, run, operator_tools) = agents(w, other)
    assert 'mask_create' not in lead_tools and 'mask_create' not in operator_tools
    assert operations(operator_tools) == ROLE_OPERATIONS['experiment_operator']
    assert 'fixed_mask.run' not in operations(lead_tools)
    assert 'fixed_mask_diagnostics' not in PiTools(w.pi).capabilities(operator)
    assert 'validation.run' in PiTools(w.pi).capabilities(lead)['fixed_design_check']
    task = w.current_tasks(other['id'])[0]
    with pytest.raises(ValueError, match='not available to this assignment'):
        call(w, operator, run, 'mask_create', {'task_id': task['id'], 'pattern': 'zeros'}, 'mask')
    assert not w.store.list('agent_artifact', other['id'])
    # Nobody runs the command here, the researcher included: the bus names the pack it comes with.
    with pytest.raises(ValueError, match='problem pack dqn_meent.pack'):
        w.commands.execute(Command(id='researcher_fixed', campaign_id=other['id'], expected_revision=w.store.get(other['id'], 'campaign')['version'],
            operation='fixed_mask.run', payload={'task_id': task['id'], 'mask_artifact_ids': ['m'], 'fidelities': [{}], 'rationale': 'x'}))
    assert not w.store.list('fixed_mask_job', other['id'])


def test_a_fresh_workspace_without_a_meent_campaign_refuses_the_command(tmp_path):
    w = Workspace(tmp_path)
    c = w.create_campaign(CampaignInput(name='Quadratic', compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    with pytest.raises(ValueError):
        w.commands.execute(Command(id='fixed', campaign_id=c['id'], expected_revision=1, operation='fixed_mask.run',
            payload={'task_id': 't', 'mask_artifact_ids': ['m'], 'fidelities': [{}], 'rationale': 'x'}))
    assert 'fixed_mask.run' not in w.commands.handlers and not w.store.list('fixed_mask_job')


def test_old_fixed_mask_records_still_render_in_a_campaign_without_the_pack(lab):
    w, _, other = lab
    (lead, lead_run, _), _ = agents(w, other)
    w.store.put('fixed_mask_job', {'id': 'fixed_old', 'campaign_id': other['id'], 'status': 'completed', 'wall_seconds': 10,
        'execution_seconds': 4, 'report_id': 'report_fixed_old', 'scope': 'Development evaluator diagnostics', 'identity': 'frozen'})
    w.store.put_immutable('fixed_mask_report', {'id': 'report_fixed_old', 'campaign_id': other['id'], 'job_id': 'fixed_old',
        'checks': [{'mask_artifact_id': 'uniform', 'repeat': 0, 'observation': {'objectives': {'efficiency': 0.5}}}], 'completed': True})
    for identity in ('fixed_old', 'report_fixed_old'):
        read = call(w, lead, lead_run, 'evidence_read', {'record_id': identity}, 'read_' + identity)
        assert 'error' not in read and read['campaign_id'] == other['id'], read
    found = call(w, lead, lead_run, 'evidence_search', {'query': 'fixed_old'}, 'search')
    assert {'fixed_old', 'report_fixed_old'} <= {row['id'] for row in found['records']}
    # Its compute still counts against the campaign's budget.
    from optimization_framework.execution.resources import ResourceLedger
    assert ResourceLedger(w.store).assessment(other['id'])['actual_seconds'] == 4
