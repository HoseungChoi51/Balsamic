/** The strategy library: winners of earlier campaigns, ranked by how well their problem signature fits this campaign; Apply makes a root inspired by one. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useRead, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Empty, Failed, Kv, Loading, Pill, Section, duration, num, when } from '../primitives/ui';
import { formatHash, navigate } from '../router/routes';
import { useEvolution } from '../evolution/EvolutionPage';

interface Entry { id: string; origin_campaign_id: string; hypothesis_id: string; strategy: { title: string; mechanism?: string; algorithm?: string }; signature: { problem_id: string | null; objective?: { name?: string; direction?: string }; representation?: string };
  evidence: { best_score: number | null; best_basis?: string | null; worker_seconds?: number; seeds_won?: number | null; confirmation_protocol_id?: string | null; fidelity?: Fidelity }; notes?: string; created_at: string }
interface Fidelity { state: string; trial_id?: string | null; checks: { recipe_id: string; state: string; validation_result_id?: string | null; waiver_id?: string | null }[] }
interface Search { signature: { problem_id: string | null; basis?: string }; entries: { entry: Entry; match: { score: number; reasons: string[] } }[] }

/** Whether the entry's score held at higher fidelity when it was published (roadmap V3), with the result or waiver it rests on. */
function fidelityText(fidelity?: Fidelity) {
  if (!fidelity) return 'not recorded (published before fidelity checks)';
  if (fidelity.state === 'not_required') return 'not required for this problem';
  const checks = fidelity.checks.map(c => `${c.recipe_id}${c.validation_result_id ? ` (${c.validation_result_id})` : ''}${c.waiver_id ? `, waiver ${c.waiver_id}` : ''}`).join('; ');
  return `${fidelity.state === 'waived' ? 'waived by the researcher' : fidelity.state.replace('_', ' ')}: ${checks}`;
}

export default function LibraryPage({ campaignId, route, threadId }: PageProps) {
  const [q, setQ] = useState('');
  const results = useRead<Search>(['library', campaignId, q], `/api/v1/library?campaign_id=${campaignId}&q=${encodeURIComponent(q)}`);
  const summary = useSummary(campaignId);
  const evolution = useEvolution(campaignId);
  const queryClient = useQueryClient();
  const [applying, setApplying] = useState<Entry | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const version = summary.data?.campaign.version;
  const apply = async () => {
    if (!applying || version === undefined) return;
    setError(null);
    try {
      const receipt = await send({ operation: 'library.apply', campaignId, expectedRevision: version, payload: { entry_id: applying.id, note }, origin: { thread_id: threadId } });
      setApplying(null); setNote('');
      await queryClient.invalidateQueries({ queryKey: ['hypotheses'] }); await queryClient.invalidateQueries({ queryKey: ['evolution'] });
      navigate(formatHash({ page: 'hypotheses', id: String(receipt.outcome.hypothesis_id), sel: String(receipt.outcome.hypothesis_id) }, threadId));
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  const publish = async (hypothesisId: string) => {
    if (version === undefined) return;
    setError(null);
    try { await send({ operation: 'library.publish', campaignId, expectedRevision: version, payload: { hypothesis_id: hypothesisId }, origin: { thread_id: threadId } }); await queryClient.invalidateQueries({ queryKey: ['library'] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const candidates = (evolution.data?.nodes || []).filter(n => (n.finalist || n.confirmation?.promising) && !(n as unknown as { library_entry_id?: string }).library_entry_id);
  return (
    <div className="col">
      <div className="stage-head"><h1>Library</h1><input placeholder="Search strategies" value={q} onChange={e => setQ(e.target.value)} data-testid="library-search" /></div>
      {error ? <div className="pill bad">{error}</div> : null}
      {results.isPending ? <Loading /> : results.error ? <Failed error={results.error} /> : (
        <Section title={`Strategies for this problem (${results.data.entries.length})`} right={<span className="small faint">{results.data.signature.problem_id ? `matched on ${results.data.signature.basis}` : 'no problem instance yet to match on'}</span>}>
          {results.data.entries.length ? results.data.entries.map(({ entry, match }) => (
            <article key={entry.id} className="card" data-testid="library-entry" data-record-id={entry.id}>
              <div className="row wrap"><strong className="grow">{entry.strategy.title}</strong><Pill tone={match.score >= 5 ? 'clear' : match.score >= 3 ? 'agent' : ''} title={match.reasons.join('; ') || 'no shared signature'}>fit {match.score}</Pill>
                <span className="small faint">from {entry.origin_campaign_id} · {when(entry.created_at)}</span></div>
              <p className="small muted">{(entry.strategy.mechanism || '').slice(0, 240)}</p>
              <Kv rows={[['Algorithm', entry.strategy.algorithm || 'none'], ['Problem', `${entry.signature.problem_id || 'unknown'} · ${entry.signature.objective?.name || ''} ${entry.signature.objective?.direction || ''} · ${entry.signature.representation || ''}`],
                ['Evidence', <>{num(entry.evidence.best_score, 4)} best ({entry.evidence.best_basis || 'basis unknown'}), {duration(entry.evidence.worker_seconds)} of worker time{entry.evidence.seeds_won != null ? `, ${entry.evidence.seeds_won} seeds won` : ''}{entry.evidence.confirmation_protocol_id ? ', confirmed' : ', not confirmed'}</>],
                ['Fidelity', fidelityText(entry.evidence.fidelity)],
                ['Why it fits', match.reasons.join('; ') || 'nothing in common with this problem']]} />
              <div className="row"><button className="btn small" onClick={() => { setApplying(entry); setNote(''); }} data-testid="apply">Apply here…</button></div>
            </article>)) : <Empty>No library entry yet. Publish a finalist or a confirmed strategy from this campaign below, or from an earlier campaign of the same problem.</Empty>}
        </Section>)}
      {applying ? <div className="card" data-testid="apply-dialog"><h3>Apply “{applying.strategy.title}”</h3>
        <p className="small muted">A new root strategy in this campaign, inspired by the entry; the fit is written into its rationale and it is reviewed like any other.</p>
        <textarea style={{ width: '100%', minHeight: 60 }} placeholder="A note for the record (optional)" value={note} onChange={e => setNote(e.target.value)} />
        <div className="row"><button className="btn primary small" onClick={apply}>Apply</button><button className="btn small" onClick={() => setApplying(null)}>Cancel</button></div></div> : null}
      <Section title="Publish from this campaign">
        {candidates.length ? candidates.map(n => <div key={n.id} className="row small card"><span className="grow">{n.label ? n.label + ' · ' : ''}{n.title} <Pill>{n.stage}</Pill> best {num(n.best.score, 4)}</span><button className="btn small" onClick={() => publish(n.id)} data-testid="publish">Publish</button></div>)
          : <p className="faint small">A finalist, or a strategy whose confirmation was promising, can be published. None waits.</p>}
      </Section>
      <p className="why">Entries are immutable records with the strategy, the problem signature and the evidence links; see <a href={formatHash({ page: 'evolution', sub: 'frontier' }, route.thread)}>the frontier</a> to promote finalists.</p>
    </div>
  );
}
