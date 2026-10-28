"""The discussions page is assembled from what the agents saved: rounds, replies, verdicts and the lead's responses."""
from fastapi.testclient import TestClient

from optimization_framework.agents.discussions import view
from optimization_framework.agents.models import NOTICE
from optimization_framework.agents.tools import PiTools
from balsamic.app import create_app
from optimization_framework.contracts.base import content_hash
from optimization_framework.contracts.requests import CampaignInput, TaskInput
from optimization_framework.campaigns.proposals import hypothesis_revision
from test_pi_agents import invoke, prepared   # noqa: F401  (the fixture)


def finish(workspace, agent_id, run_id, text, summary=None):
    """A turn ends at the harness: its closing summary, if any, was saved by yield_work during the turn."""
    run = workspace.store.get(run_id, 'agent_run')
    workspace.store.put('agent_run', {**run, 'status': 'submitted', **({'disposition': {'disposition': 'complete', 'summary': summary}} if summary else {})})
    workspace.pi._receive(agent_id, {'runs': {run_id: {'status': 'completed', 'result': {'text': text}}}, 'events': [], 'cursor': 0})


def test_rounds_replies_verdicts_and_the_leads_response_are_read_from_saved_records(prepared):
    w, c, lead, first = prepared
    tools = PiTools(w.pi)
    assert view(w, c['id']) == {'rounds': [], 'earlier_rounds': 0, 'proposals': [], 'unreviewed_proposals': 0}
    original = {'id': 'h6', 'campaign_id': c['id'], 'title': 'H6 — Autograd Adam', 'mechanism': 'Adam on the relaxed score',
                'requires_concept_review': True, 'status': 'proposed', 'created_at': '2026-10-13T15:00:00+00:00'}
    w.store.put('hypothesis', original)
    w.store.put('hypothesis', {'id': 'h1', 'campaign_id': c['id'], 'title': 'H1 — never reviewed', 'mechanism': 'none', 'created_at': '2026-10-13T15:00:01+00:00'})

    # Round 1: two assistants asked in the researcher's turn.
    specialist = invoke(prepared, 'delegate', {'role': 'methodology_specialist', 'objective': 'Propose strategies for the deflector.', 'request_key': 'ideas'}, 'd1')
    reviewer = invoke(prepared, 'delegate', {'role': 'proposal_reviewer', 'objective': 'Review H6 for a short run.', 'request_key': 'review', 'hypothesis_id': 'h6'}, 'd2')
    saved = invoke(prepared, 'artifact_save', {'title': 'Consolidated picks', 'kind': 'analysis', 'content': 'Lead picks H6.'}, 'd3')
    review_run = w.store.get(reviewer['run_id'], 'agent_run'); w.store.put('agent_run', {**review_run, 'status': 'submitted'})
    verdict = tools.call(reviewer['agent_id'], reviewer['run_id'], 'v1', 'proposal_review', {'hypothesis_id': 'h6', 'hypothesis_hash': hypothesis_revision(original),
        'verdict': 'revise', 'rationale': 'The Adam schedule is not pinned.', 'required_changes': ['Pin reference_epochs'], 'suggested_tests': ['Matched budget against ES']})
    note = tools.call(reviewer['agent_id'], reviewer['run_id'], 'v2', 'artifact_save', {'title': 'Review notes', 'kind': 'review', 'content': {'scope': 'short runs'}})
    finish(w, specialist['agent_id'], specialist['run_id'], 'Five strategies, in full.', 'Proposed five strategies.')
    finish(w, reviewer['agent_id'], reviewer['run_id'], 'H6 needs its schedule pinned.', 'H6: revise.')

    # The reviewer's answer wakes the lead; in that turn it answers, revises H6 and asks for a second review: round 2.
    woken = 'pi_child_result_' + content_hash(reviewer['run_id'])[:28]
    w.store.put('agent_run', {**w.store.get(woken, 'agent_run'), 'status': 'submitted', 'disposition': {'disposition': 'waiting', 'summary': 'Revised H6; re-review asked.'}})
    revision = {**original, 'id': 'h6b', 'title': 'H6 — Autograd Adam, schedule pinned', 'parent_ids': ['h6'], 'reviews': [], 'created_at': '2026-10-13T16:00:00+00:00', 'status': 'finalist'}
    w.store.put('hypothesis', revision)
    second = tools.call(lead['id'], woken, 'd4', 'delegate', {'role': 'proposal_reviewer', 'objective': 'Re-review the revised H6.', 'request_key': 'again', 'hypothesis_id': 'h6b'})
    w.pi._receive(lead['id'], {'runs': {woken: {'status': 'completed', 'result': {'text': 'I pinned the schedule and asked for a second review.'}}}, 'events': [], 'cursor': 0})
    again = w.store.get(second['run_id'], 'agent_run'); w.store.put('agent_run', {**again, 'status': 'submitted'})
    tools.call(second['agent_id'], second['run_id'], 'v3', 'proposal_review', {'hypothesis_id': 'h6b', 'hypothesis_hash': hypothesis_revision(w.store.get('h6b', 'hypothesis')),
        'verdict': 'test', 'rationale': 'Pinned now.', 'suggested_tests': ['Three seeds']})

    result = view(w, c['id'])
    newest, oldest = result['rounds']
    assert (oldest['number'], oldest['trigger']) == (1, {'kind': 'request', 'text': first['input']})
    assert [person['role'] for person in oldest['assistants']] == ['methodology_specialist', 'proposal_reviewer']
    assert [doc['title'] for doc in oldest['owner_documents']] == ['Consolidated picks'] and oldest['owner_documents'][0]['id'] == saved['artifact_id']
    asked, reviewed = oldest['assistants']
    assert asked['assignment'] == 'Propose strategies for the deflector.' and asked['verdicts'] == []
    turn = asked['turns'][0]
    assert (turn['kind'], turn['asked'], turn['summary'], turn['reply']) == ('assignment', None, 'Proposed five strategies.', 'Five strategies, in full.')
    assert [(item['title'], item['verdict'], item['required_changes'], item['artifact_id']) for item in reviewed['verdicts']] == [
        ('H6 — Autograd Adam', 'revise', ['Pin reference_epochs'], verdict['review_id'])]
    assert [(doc['kind'], doc['title'], doc['id']) for doc in reviewed['documents']] == [('review', 'Review notes', note['artifact_id'])]
    # The lead's response is matched to the reply that woke it.
    response = reviewed['turns'][0]['response']
    assert (response['run_id'], response['summary'], response['text']) == (woken, 'Revised H6; re-review asked.', 'I pinned the schedule and asked for a second review.')
    # Round 2 continues round 1 and is still in progress.
    assert (newest['number'], newest['trigger'], newest['active']) == (2, {'kind': 'continued', 'round': 1}, True)
    pending = newest['assistants'][0]
    assert pending['assignment'] == 'Re-review the revised H6.' and [item['verdict'] for item in pending['verdicts']] == ['test']
    assert [(turn['kind'], turn['reply'], turn['summary'], turn['response']) for turn in pending['turns']] == [('assignment', '', None, None)]
    # How the proposal fared: its revisions in order, each verdict with its round. The unreviewed one is counted, and listed for the graph.
    assert result['unreviewed_proposals'] == 1
    assert [(proposal['id'], proposal['status'], proposal['reviewed']) for proposal in result['proposals']] == [('h6b', 'finalist', True), ('h1', None, False)]
    assert [revision['parent_ids'] for revision in result['proposals'][0]['revisions']] == [[], ['h6']]
    assert [[(item['verdict'], item['round']) for item in revision['verdicts']] for revision in result['proposals'][0]['revisions']] == [[('revise', 1)], [('test', 2)]]
    # Put in by hand here, as the researcher would: no agent's turn created them.
    assert {(revision['created_in_round'], revision['created_by']) for proposal in result['proposals'] for revision in proposal['revisions']} == {(None, None)}

    # A reviewer answers once (roadmap T1): a message to it is refused.
    refused = tools.call(lead['id'], first['id'], 'm0', 'agent_message', {'agent_id': second['agent_id'], 'message': 'Also check the seeds.'})
    assert 'answers once; delegate again' in refused['error']
    # A message the lead sends an assistant while it works is shown as added to its assignment.
    checker = tools.call(lead['id'], first['id'], 'd5', 'delegate', {'role': 'methodology_specialist', 'objective': 'Check the seeds of H6.', 'request_key': 'seeds'})
    extra = tools.call(lead['id'], first['id'], 'm1', 'agent_message', {'agent_id': checker['agent_id'], 'message': 'Also check the seeds.'})
    w.pi._receive(checker['agent_id'], {'runs': {extra['id']: {'status': 'completed', 'result': {'delivery': 'steering_queued'}}}, 'events': [], 'cursor': 0})
    follow = view(w, c['id'])['rounds'][1]['assistants'][2]['turns']
    assert [(turn['kind'], turn['asked'], turn['delivered_while_working'], turn['response']) for turn in follow] == [
        ('assignment', None, False, None), ('follow_up', 'Also check the seeds.', True, None)]

    # Another campaign sees none of it, and the page's endpoint serves the same view.
    other = w.create_campaign(CampaignInput(name='Other', compute_budget_seconds=100, validation_reserve_seconds=10,
        tasks=[TaskInput(name='Quadratic', problem_id='bounded_continuous', configuration={})]))
    assert view(w, other['id'])['rounds'] == []
    client = TestClient(create_app(w.directory))
    served = client.get(f"/api/v1/campaigns/{c['id']}/discussions").json()
    assert [round['number'] for round in served['rounds']] == [2, 1]
    assert client.get('/api/v1/campaigns/campaign_unknown/discussions').status_code == 404


def test_a_platform_notice_to_an_assistant_is_not_shown_as_an_exchange(prepared):
    w, c, lead, first = prepared
    child = invoke(prepared, 'delegate', {'role': 'results_analyst', 'objective': 'Summarise the runs.', 'request_key': 'summary'}, 'd1')
    w.pi.enqueue(w.store.get(child['agent_id'], 'agent_session'), 'pi_recover_x', NOTICE + 'Assignment was interrupted by a harness restart.')
    turns = view(w, c['id'])['rounds'][0]['assistants'][0]['turns']
    assert [turn['kind'] for turn in turns] == ['assignment']


def test_every_page_the_lead_may_link_exists_in_the_application():
    import json
    from pathlib import Path
    from optimization_framework.agents.tools import COMMAND_PAGES, PAGES
    catalog = json.loads((Path(__file__).parents[1] / 'frontend/src/router/pages.json').read_text())
    pages = catalog['pages']
    assert {'hypotheses', 'experiments', 'inbox', 'monitor', 'files'} <= set(catalog['rail']) <= set(pages)
    for link in [link for link, *_ in PAGES] + list(COMMAND_PAGES.values()):
        assert link.startswith('#'), link
        page, _, sub = link[1:].partition('/')
        assert page in pages, link
        assert not sub or sub in (pages[page].get('subs') or {}), link
    assert '#hypotheses/implementations' in COMMAND_PAGES.values() and '#inbox' in COMMAND_PAGES.values()


def test_a_proposal_names_the_round_whose_turn_created_it(prepared):
    w, c, lead, first = prepared
    invoke(prepared, 'delegate', {'role': 'methodology_specialist', 'objective': 'Propose strategies.', 'request_key': 'ideas'}, 'd1')
    created = invoke(prepared, 'campaign_command', {'operation': 'hypothesis.create', 'request_key': 'floor', 'guidance_revision': w.memory.state(c['id'])['guidance_revision'],
        'payload': {'title': 'Random designs as a floor', 'algorithm': 'random', 'mechanism': 'Independent random designs.', 'rationale': 'A floor to beat.'}}, 'h')
    by_hand = {'id': 'h_by_hand', 'campaign_id': c['id'], 'title': 'Written by the researcher', 'mechanism': 'x', 'created_at': '2026-10-13T15:00:00+00:00'}
    w.store.put('hypothesis', by_hand)
    revisions = {revision['id']: revision for proposal in view(w, c['id'])['proposals'] for revision in proposal['revisions']}
    made = revisions[created['outcome']['hypothesis_id']]
    assert (made['created_in_round'], made['created_by']) == (1, 'lead')
    assert (revisions['h_by_hand']['created_in_round'], revisions['h_by_hand']['created_by']) == (None, None)
