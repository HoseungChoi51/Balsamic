/** The strategy library: winners of earlier campaigns, and methods assessed and stopped there (roadmap K4), ranked by how well their problem signature fits this campaign; Apply makes a root inspired by one. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useRead, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Empty, Failed, Kv, Loading, Pill, Section, duration, num, when } from '../primitives/ui';
import { formatHash, navigate } from '../router/routes';
import { useEvolution } from '../evolution/EvolutionPage';

interface Entry { id: string; kind?: 'positive' | 'negative'; origin_campaign_id: string; hypothesis_id: string; strategy: { title: string; mechanism?: string; algorithm?: string }; signature: { problem_id: string | null; objective?: { name?: string; direction?: string }; representation?: string };
  evidence: { best_score: number | null; best_basis?: string | null; worker_seconds?: number; seeds_won?: number | null; confirmation_protocol_id?: string | null; fidelity?: Fidelity; evidence_ids?: string[] }; notes?: string; created_at: string;
  stop?: { outcome: string; words: string; reason?: string | null; evidence_ids: string[]; by?: string | null }; assessment?: { basis: 'adequate' | 'waiver' | 'not required'; words?: string; waiver_id?: string; configurations_run?: { configuration_hash: string; seeds: number[] }[] } }
interface Fidelity { state: string; trial_id?: string | null; checks: { recipe_id: string; state: string; validation_result_id?: string | null; waiver_id?: string | null }[] }
interface Row { entry: Entry; match: { score: number; reasons: string[] }; kind?: 'positive' | 'negative'; label?: string | null }
interface Search { signature: { problem_id: string | null; basis?: string }; entries: Row[] }
interface Stopped { stop?: { outcome: string; words: string } | null; assessment?: { adequate: boolean; words: string } }

// Stops that judge the method: a strategy stopped with one of these may be published as a negative entry (K4).
const JUDGEMENTS = new Set(['configuration_unpromising', 'adequately_assessed_deprioritized', 'implementation_invalid', 'assumptions_incompatible']);
const PERFORMANCE = new Set(['configuration_unpromising', 'adequately_assessed_deprioritized']);

/** How a negative entry's method was tried before it was stopped. */
function assessmentText(entry: Entry) {
  const a = entry.assessment;
  if (!a || a.basis === 'not required') return 'not required for this outcome';
  const runs = a.configurations_run?.length ? ` · ${a.configurations_run.map(c => `${c.configuration_hash.slice(0, 6)} on seeds ${c.seeds.join(', ')}`).join('; ')}` : '';
  return `${a.words || ''} (${a.basis === 'waiver' ? `fewer runs, waived by the researcher${a.waiver_id ? ` (${a.waiver_id})` : ''}` : 'adequate'})${runs}`;
}

function signatureText(entry: Entry) {
  return `${entry.signature.problem_id || 'unknown'} · ${entry.signature.objective?.name || ''} ${entry.signature.objective?.direction || ''} · ${entry.signature.representation || ''}`;
}

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
  const publish = async (hypothesisId: string, kind: 'positive' | 'negative' = 'positive') => {
    if (version === undefined) return;
    setError(null);
    try { await send({ operation: 'library.publish', campaignId, expectedRevision: version, payload: { hypothesis_id: hypothesisId, ...(kind === 'negative' ? { kind } : {}) }, origin: { thread_id: threadId } }); await queryClient.invalidateQueries({ queryKey: ['library'] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const published = (n: object) => Boolean((n as { library_entry_id?: string }).library_entry_id);
  const candidates = (evolution.data?.nodes || []).filter(n => (n.finalist || n.confirmation?.promising) && !published(n));
  const stoppedCandidates = (evolution.data?.nodes || []).filter(n => n.stop && JUDGEMENTS.has(n.stop.outcome) && !published(n));
  const rows = results.data?.entries || [];
  const won = rows.filter(r => (r.kind || r.entry.kind || 'positive') === 'positive');
  const stopped = rows.filter(r => (r.kind || r.entry.kind) === 'negative');
  const card = ({ entry, match, label }: Row) => {
    const negative = (entry.kind || 'positive') === 'negative';
    return (
      <article key={entry.id} className="card" data-testid="library-entry" data-kind={negative ? 'negative' : 'positive'} data-record-id={entry.id}>
        <div className="row wrap"><strong className="grow">{entry.strategy.title}</strong>
          {negative ? <Pill tone="attention" title="Another campaign tried this method fairly and stopped it; read why before trying it again">{label || 'assessed and stopped'}</Pill> : null}
          <Pill tone={match.score >= 5 ? 'clear' : match.score >= 3 ? 'agent' : ''} title={match.reasons.join('; ') || 'no shared signature'}>fit {match.score}</Pill>
          <span className="small faint">from {entry.origin_campaign_id} · {when(entry.created_at)}</span></div>
        <p className="small muted">{(entry.strategy.mechanism || '').slice(0, 240)}</p>
        <Kv rows={negative ? [['Algorithm', entry.strategy.algorithm || 'none'], ['Assessed on', signatureText(entry)],
          ['Stopped as', <>{entry.stop?.words || 'no outcome recorded'}{entry.stop?.reason ? `: ${entry.stop.reason}` : ''}{entry.stop?.by ? ` (${entry.stop.by})` : ''}</>],
          ['Assessment', assessmentText(entry)],
          ['Evidence', <>{num(entry.evidence.best_score, 4)} best as measured, {duration(entry.evidence.worker_seconds)} of worker time{entry.stop?.evidence_ids?.length ? `; rests on ${entry.stop.evidence_ids.join(', ')}` : ''}</>],
          ['Why it fits', match.reasons.join('; ') || 'nothing in common with this problem']]
          : [['Algorithm', entry.strategy.algorithm || 'none'], ['Problem', signatureText(entry)],
          ['Evidence', <>{num(entry.evidence.best_score, 4)} best ({entry.evidence.best_basis || 'basis unknown'}), {duration(entry.evidence.worker_seconds)} of worker time{entry.evidence.seeds_won != null ? `, ${entry.evidence.seeds_won} seeds won` : ''}{entry.evidence.confirmation_protocol_id ? ', confirmed' : ', not confirmed'}</>],
          ['Fidelity', fidelityText(entry.evidence.fidelity)],
          ['Why it fits', match.reasons.join('; ') || 'nothing in common with this problem']]} />
        <div className="row"><button className="btn small" onClick={() => { setApplying(entry); setNote(''); }} data-testid="apply">Apply here…</button></div>
      </article>);
  };
  return (
    <div className="col">
      <div className="stage-head"><h1>Library</h1><input placeholder="Search strategies" value={q} onChange={e => setQ(e.target.value)} data-testid="library-search" /></div>
      {error ? <div className="pill bad">{error}</div> : null}
      {results.isPending ? <Loading /> : results.error ? <Failed error={results.error} /> : (
        <>
          <Section title={`Strategies that won (${won.length})`} right={<span className="small faint">{results.data.signature.problem_id ? `matched on ${results.data.signature.basis}` : 'no problem instance yet to match on'}</span>}>
            {won.length ? won.map(card) : <Empty>No winning strategy in the library yet. Publish a finalist or a confirmed strategy from this campaign below, or from an earlier campaign of the same problem.</Empty>}
          </Section>
          <Section title={`Assessed and stopped (${stopped.length})`}>
            {stopped.length ? stopped.map(card) : <p className="faint small">No method has been assessed and stopped here yet. A strategy stopped as configuration unpromising or deprioritized after a fair assessment, or as an invalid implementation or incompatible assumptions, can be published below.</p>}
          </Section>
        </>)}
      {applying ? <div className="card" data-testid="apply-dialog"><h3>Apply “{applying.strategy.title}”</h3>
        <p className="small muted">A new root strategy in this campaign, inspired by the entry; the fit is written into its rationale and it is reviewed like any other.</p>
        <textarea style={{ width: '100%', minHeight: 60 }} placeholder="A note for the record (optional)" value={note} onChange={e => setNote(e.target.value)} />
        <div className="row"><button className="btn primary small" onClick={apply}>Apply</button><button className="btn small" onClick={() => setApplying(null)}>Cancel</button></div></div> : null}
      <Section title="Publish from this campaign">
        {candidates.length || stoppedCandidates.length ? candidates.map(n => <div key={n.id} className="row small card"><span className="grow">{n.label ? n.label + ' · ' : ''}{n.title} <Pill>{n.stage}</Pill> best {num(n.best.score, 4)}</span><button className="btn small" onClick={() => publish(n.id)} data-testid="publish">Publish</button></div>)
          : <p className="faint small">A finalist, a strategy whose confirmation was promising, or one stopped after a fair assessment can be published. None waits.</p>}
        {stoppedCandidates.map(n => { const a = (n as unknown as Stopped).assessment; return (
          <div key={n.id} className="row small card" data-testid="negative-candidate"><span className="grow">{n.label ? n.label + ' · ' : ''}{n.title} <Pill tone="attention">stopped: {n.stop!.words}</Pill>
            {PERFORMANCE.has(n.stop!.outcome) && a ? <span className="faint"> · {a.words}{a.adequate ? '' : ' (below the minimums: needs your waiver)'}</span> : null}</span>
            <button className="btn small" onClick={() => publish(n.id, 'negative')} data-testid="publish-negative">Publish as assessed and stopped</button></div>); })}
      </Section>
      <p className="why">Entries are immutable records with the strategy, the problem signature and the evidence links. An assessed-and-stopped entry says where a method was tried fairly and stopped, and why; it is not a verdict on the method elsewhere; see <a href={formatHash({ page: 'evolution', sub: 'frontier' }, route.thread)}>the frontier</a> to promote finalists.</p>
    </div>
  );
}
