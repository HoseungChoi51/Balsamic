"""The moderator's synthesis of a review round is compared with the reviewers' verdicts (roadmap T2): a standing or a status
against them is recorded with against_tally and the reviews it overrides, and a round with reviewers closes only with one."""
from optimization_framework.agents.discussions import view
from optimization_framework.agents.models import NOTICE
from optimization_framework.campaigns.proposals import hypothesis_revision, overridden, status_overridden, tally

from test_page_agents import call, finish, guidance, submitted, wakes
from test_pi_agents import activated
from test_mandates import granted


def proposal(w, c, identity, **extra):
    record = {'id': identity, 'campaign_id': c['id'], 'title': identity.upper(), 'mechanism': 'One step', 'requires_concept_review': True,
              'status': 'proposed', 'status_revision': 0, 'created_at': '2026-10-27T00:00:00+00:00', **extra}
    w.store.put('hypothesis', record)
    return record


def review(w, moderator, run, hypothesis, verdict, key):
    """A reviewer the moderator asks records its verdict on the exact revision and finishes."""
    asked = call(w, moderator, run, 'delegate', {'role': 'proposal_reviewer', 'objective': f'Review {hypothesis["id"]}.', 'request_key': key}, key)
    reviewer = w.store.get(asked['agent_id'], 'agent_session')
    reviewer_run = submitted(w, w.store.get(asked['run_id'], 'agent_run'))
    recorded = call(w, reviewer, reviewer_run, 'proposal_review', {'hypothesis_id': hypothesis['id'], 'hypothesis_hash': hypothesis_revision(hypothesis),
        'verdict': verdict, 'rationale': f'{verdict} because of the mechanism.', 'suggested_tests': ['A matched baseline']}, key + '_verdict')
    finish(w, reviewer, reviewer_run, verdict)
    return recorded['review_id']


def moderator_round(tmp_path, monkeypatch):
    w, c, lead = activated(tmp_path, monkeypatch)
    lead_run = submitted(w, w.pi.message(c['id'], {'message': 'Have H1 and H2 reviewed.'}, 'request'))
    sent = call(w, lead, lead_run, 'page_agent_message', {'page_agent': 'discussion_moderator', 'message': 'Review H1 and H2.'}, 'ask')
    moderator = w.store.get(sent['agent_id'], 'agent_session')
    return w, c, lead, moderator, submitted(w, w.store.get(sent['run_id'], 'agent_run'))


def test_a_standing_against_the_tally_is_saved_with_the_reviews_it_overrides(tmp_path, monkeypatch):
    w, c, lead, moderator, run = moderator_round(tmp_path, monkeypatch)
    h1, h2 = proposal(w, c, 'h1'), proposal(w, c, 'h2')
    rejected = review(w, moderator, run, h1, 'reject', 'r1')
    passed = review(w, moderator, run, h2, 'test', 'r2')
    saved = call(w, moderator, run, 'review_synthesis', {'summary': 'Both stand.', 'proposals': [
        {'hypothesis_id': 'h1', 'standing': 'stands', 'reason': 'The mechanism is sound.'},
        {'hypothesis_id': 'h2', 'standing': 'stands', 'review_ids': [passed], 'reason': 'The reviewer said test.'}]}, 'first')
    assert saved['against_tally'] == [{'hypothesis_id': 'h1', 'standing': 'stands', 'overrides': [rejected]}] and saved['omitted'] == []
    artifact = w.store.get(saved['synthesis_id'], 'agent_artifact')
    first, second = artifact['content']['proposals']
    assert artifact['kind'] == 'review_synthesis' and artifact['content']['against_tally'] == 1
    assert first['against_tally'] is True and first['overrides'] == [rejected] and first['tally'] == {'test': 0, 'revise': 0, 'reject': 1}
    assert 'against_tally' not in second and second['review_ids'] == [passed]
    # One that matches the tally is saved without it; a proposal reviewed in the round and left out is named.
    matching = call(w, moderator, run, 'review_synthesis', {'summary': 'H1 is rejected.', 'proposals': [
        {'hypothesis_id': 'h1', 'standing': 'rejected', 'review_ids': [rejected], 'reason': 'The reviewer rejected it.'}]}, 'second')
    assert matching['against_tally'] == [] and matching['omitted'] == ['h2']
    # A verdict that is not a reviewer's, and a proposal named twice, are refused before anything is saved.
    refused = call(w, moderator, run, 'review_synthesis', {'summary': 'x', 'proposals': [
        {'hypothesis_id': 'h1', 'standing': 'rejected', 'review_ids': [saved['synthesis_id']], 'reason': 'x'}]}, 'bad_review')
    assert refused['executed'] is False and "reviewer's verdict" in refused['error']
    twice = call(w, moderator, run, 'review_synthesis', {'summary': 'x', 'proposals': [
        {'hypothesis_id': 'h1', 'standing': 'rejected', 'reason': 'x'}, {'hypothesis_id': 'h1', 'standing': 'stands', 'reason': 'x'}]}, 'twice')
    assert twice['executed'] is False and 'named twice' in twice['error']


def test_a_round_with_reviewers_completes_only_with_a_synthesis_and_the_leads_notice_carries_it(tmp_path, monkeypatch):
    w, c, lead, moderator, run = moderator_round(tmp_path, monkeypatch)
    h1 = proposal(w, c, 'h1')
    rejected = review(w, moderator, run, h1, 'reject', 'r1')
    # The moderator's turn that asked ends waiting; the reviewer's answer wakes it, and that turn closes the round.
    call(w, moderator, run, 'yield_work', {'disposition': 'waiting', 'summary': 'A reviewer is reading H1.'}, 'waiting')
    finish(w, moderator, run, 'A reviewer is reading H1.')
    run = submitted(w, wakes(w, moderator, 'pi_child_result_')[0])
    close = {'disposition': 'complete', 'summary': 'Reviewed', 'report': 'H1 was rejected. See [Review rounds](#hypotheses/rounds).'}
    refused = call(w, moderator, run, 'yield_work', close, 'early')
    assert refused['executed'] is False and 'review_synthesis' in refused['error']
    saved = call(w, moderator, run, 'review_synthesis', {'summary': 'H1 stands.', 'proposals': [
        {'hypothesis_id': 'h1', 'standing': 'stands', 'reason': 'The objection is minor.'}]}, 'synthesis')
    assert call(w, moderator, run, 'yield_work', close, 'done')['saved']
    finish(w, moderator, run, close['report'])
    notice = wakes(w, lead, 'pi_child_result_')[0]['input']
    assert notice.startswith(NOTICE) and saved['synthesis_id'] in notice and 'H1 stands, over ' + rejected in notice
    # The Review rounds view shows the synthesis beside the moderator's words, with its tally and the badge.
    shown = view(w, c['id'])['rounds'][0]
    assert shown['owner'] == 'discussion_moderator' and shown['synthesis']['id'] == saved['synthesis_id']
    entry = shown['synthesis']['proposals'][0]
    assert entry['against_tally'] is True and entry['tally']['reject'] == 1 and entry['overrides'] == [rejected]
    # A new request that asks no reviewer needs no synthesis.
    again = submitted(w, w.pi.message(c['id'], {'message': 'Which proposals stand?', 'page_agent': 'discussion_moderator'}, 'again'))
    assert call(w, moderator, again, 'yield_work', {**close, 'report': 'H1 stands.'}, 'answer')['saved']


def test_a_status_against_the_tally_is_flagged_not_refused(tmp_path, monkeypatch):
    w, c, lead, moderator, run = moderator_round(tmp_path, monkeypatch)
    granted(w, c['id'])   # setting a status is decide work, which needs a mandate beyond Explore (R3)
    h1, h2 = proposal(w, c, 'h1'), proposal(w, c, 'h2')
    passed = review(w, moderator, run, h1, 'test', 'r1')
    objection = review(w, moderator, run, h2, 'revise', 'r2')
    def status(identity, value, key):
        # An agent's stop names a typed outcome and the records it rests on (V1); a proposal that never ran cannot be stopped
        # as inferior (V2), so the stop concludes its assumptions do not hold.
        stop = {'stop_reason': 'Not worth it', 'outcome': 'assumptions_incompatible', 'evidence_ids': [passed]} if value == 'archived' else {}
        return call(w, moderator, run, 'campaign_command', {'operation': 'hypothesis.status', 'request_key': key, 'guidance_revision': guidance(w, c),
            'payload': {'hypothesis_id': identity, 'status': value, 'expected_status_revision': 0, **stop}}, key)
    archived = status('h1', 'archived', 'archive')
    assert archived['status'] == 'completed' and w.store.get('h1', 'hypothesis')['status'] == 'archived'
    assert archived['against_tally'] == {'hypothesis_id': 'h1', 'status': 'archived', 'overrides': [passed]}
    investigating = status('h2', 'investigating', 'investigate')
    assert investigating['against_tally']['overrides'] == [objection]
    # The receipts keep the flag, and the round shows it.
    flags = view(w, c['id'])['rounds'][0]['status_flags']
    assert [(flag['hypothesis_id'], flag['status']) for flag in flags] == [('h1', 'archived'), ('h2', 'investigating')]
    # A status that agrees with the verdicts carries no flag.
    h3 = proposal(w, c, 'h3')
    review(w, moderator, run, h3, 'test', 'r3')
    assert 'against_tally' not in status('h3', 'investigating', 'agree')


def test_each_standing_is_held_by_its_rule():
    counted = lambda **verdicts: {'test': 0, 'revise': 0, 'reject': 0, **{v: list(verdicts.values()).count(v) for v in set(verdicts.values())},
                                  'verdicts': verdicts}
    assert overridden(counted(a='test'), 'stands') is None and overridden(counted(a='test', b='revise'), 'stands') == ['b']
    assert overridden(counted(a='reject'), 'rejected') is None and overridden(counted(a='test'), 'rejected') == ['a']
    assert overridden(counted(a='test'), 'rejected', stopped=True) is None
    assert overridden(counted(a='revise'), 'revise') is None and overridden(counted(a='reject'), 'revise') is None
    assert overridden(counted(a='test'), 'revise') == ['a'] and overridden(counted(a='test'), 'revise', revised=True) is None
    assert overridden(counted(), 'revise') == [] and overridden(counted(a='reject'), 'undecided') is None
    assert status_overridden(counted(), 'archived') is None and status_overridden(counted(a='test', b='reject'), 'archived') is None
    assert status_overridden(counted(a='test'), 'archived') == ['a'] and status_overridden(counted(a='reject'), 'investigating') == ['a']


def test_the_tally_counts_each_reviewers_latest_verdict_on_the_exact_revision(tmp_path, monkeypatch):
    w, c, lead, moderator, run = moderator_round(tmp_path, monkeypatch)
    h1 = proposal(w, c, 'h1')
    first = review(w, moderator, run, h1, 'reject', 'r1')
    second = review(w, moderator, run, h1, 'test', 'r2')
    assert tally(w.store, h1)['verdicts'] == {first: 'reject', second: 'test'}
    # A changed revision has no verdicts of its own yet.
    assert tally(w.store, {**h1, 'mechanism': 'Two steps'})['verdicts'] == {}
