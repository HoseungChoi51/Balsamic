/** The strategy evolution graph: the frontier table with interventions, the lineage forest, curves at matched cost, the races. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useMessages, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { useQuery } from '@tanstack/react-query';
import { scoped } from '../api/client';
import type { Evolution, LedgerRow } from '../api/evolution';
import { Empty, Failed, Kv, Loading, Pill, Section, duration, num, when } from '../primitives/ui';
import { Curve } from '../primitives/charts';
import { formatHash, navigate } from '../router/routes';
import { useSelection } from '../stores/selection';
import { intervene } from './Interventions';
import { LineageTree } from './LineageTree';
import { TraceOrigin } from './TraceOrigin';
import { track } from '../telemetry/events';

export const STAGE_TONE: Record<string, string> = { proposed: '', reviewed: '', screening: 'agent', extended: 'agent', finalist: 'clear', confirmed: 'clear', stopped: 'attention' };
export const STAGE_WORD: Record<string, string> = { stopped: 'stopped (a decision, not a failure)' };

export function useEvolution(campaignId: string | null, curves = false) {
  return useQuery<Evolution>({ queryKey: ['evolution', campaignId, curves], enabled: !!campaignId, staleTime: 5000, refetchOnWindowFocus: false,
    queryFn: ({ client }) => scoped<Evolution>(`/api/v1/campaigns/${campaignId}/evolution`, client.getQueryData<Evolution>(['evolution', campaignId, curves]), { progress: 'true', curves: curves ? 'true' : undefined }) });
}

export default function EvolutionPage({ campaignId, route }: PageProps) {
  const sub = route.sub || 'frontier';
  const evolution = useEvolution(campaignId, sub === 'curves');
  const summary = useSummary(campaignId);
  const messages = useMessages(route.thread);
  const queryClient = useQueryClient();
  const selection = useSelection();
  const [picked, setPicked] = useState<string[]>([]);
  const [trace, setTrace] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const tabs = [['frontier', 'Frontier'], ['lineage', 'Lineage'], ['curves', 'Curves'], ['races', 'Races']] as const;
  if (evolution.isPending) return <Loading what="Reading the graph" />;
  if (evolution.error) return <Failed error={evolution.error} />;
  const data = evolution.data;
  const rows = data.nodes;
  const version = summary.data?.campaign.version;
  const chosen = rows.filter(r => picked.includes(r.id));
  const act = async (label: string, run: () => Promise<unknown>) => {
    if (version === undefined) return;
    setError(null); setPending(label);
    try { await run(); setPicked([]); await queryClient.invalidateQueries({ queryKey: ['evolution'] }); await queryClient.invalidateQueries({ queryKey: ['hypotheses'] }); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setPending(null); }
  };
  return (
    <div className="col">
      <div className="stage-head"><h1>Evolution</h1><Pill title={data.stage.basis}>{data.stage.stage}</Pill>
        {data.progress ? <span className="muted small">best so far {num(data.progress.best_so_far, 4)} · {data.progress.live_trials.length} live runs · round {data.rounds}</span> : null}</div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'evolution', sub: key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {error ? <div className="pill bad">{error}</div> : null}
      {sub === 'frontier' ? <FrontierTable rows={rows} picked={picked} setPicked={setPicked} selectedId={selection.id} thread={route.thread} onTrace={setTrace}
        onOpen={id => { selection.select(id); navigate(formatHash({ page: 'hypotheses', id, sel: id }, route.thread)); }} /> : null}
      {sub === 'frontier' && chosen.length ? <InterventionBar rows={chosen} pending={pending} onStop={reason => act('stop', () => intervene(chosen, { kind: 'stop', reason }, campaignId, version!, route.thread))}
        onPromote={() => act('promote', () => intervene(chosen, { kind: 'promote' }, campaignId, version!, route.thread))}
        onAllocate={(seconds, rationale) => act('allocate', () => intervene(chosen, { kind: 'allocate', seconds, rationale }, campaignId, version!, route.thread))}
        onGenerate={(operation, count, note) => act('generate', () => intervene(chosen, { kind: 'generate', operation, count, note }, campaignId, version!, route.thread))}
        onDiscuss={() => act('discuss', async () => {
          const last = messages.data?.messages.filter(m => m.origin !== 'lab_event').at(-1);
          if (!route.thread || !last) throw new Error('Nothing to fork from yet: write to the lead first');
          const receipt = await send({ operation: 'thread.fork', campaignId, expectedRevision: version!, payload: { thread_id: route.thread, message_id: last.id, title: `Discuss ${chosen.map(r => r.label || r.title).join(', ').slice(0, 60)}`, anchors: chosen.map(r => r.id) }, origin: { thread_id: route.thread } });
          track('thread.fork', { from: 'frontier' });
          navigate(formatHash({ page: 'evolution', sub: 'frontier' }, (receipt.outcome.thread as { id: string }).id));
        })} /> : null}
      {sub === 'lineage' ? <LineageTree data={data} selectedId={selection.id} onSelect={id => selection.select(id)} onOpen={id => navigate(formatHash({ page: 'hypotheses', id, sel: id }, route.thread))} /> : null}
      {sub === 'curves' ? <Curves rows={rows} selectedId={selection.id} /> : null}
      {sub === 'races' ? <Races data={data} /> : null}
      {data.interventions.length ? <Section title="Recent interventions">{data.interventions.slice().reverse().map(i => <div key={String(i.id)} className="small row"><Pill tone={i.actor === 'autopilot' ? 'agent' : 'you'}>{String(i.actor)}</Pill><span className="grow">{(i.items as { operation: string }[]).map(x => x.operation).join(', ')} — {String(i.rationale || '')}</span><span className="faint">{when(i.created_at)}</span></div>)}</Section> : null}
      {trace ? <TraceOrigin recordId={trace} thread={route.thread} onClose={() => setTrace(null)} /> : null}
    </div>
  );
}

function FrontierTable({ rows, picked, setPicked, selectedId, onOpen, onTrace }: { rows: LedgerRow[]; picked: string[]; setPicked: (ids: string[]) => void; selectedId: string | null; thread: string | null; onOpen: (id: string) => void; onTrace: (id: string) => void }) {
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter(p => p !== id) : [...picked, id]);
  const sorted = rows.slice().sort((a, b) => (b.best.score ?? -Infinity) - (a.best.score ?? -Infinity));
  if (!rows.length) return <Empty>No strategy yet. Ask the lead for some in the conversation (/generate 3), and they appear here with their stage.</Empty>;
  return (
    <table data-testid="frontier">
      <thead><tr><th><input type="checkbox" aria-label="select all" checked={picked.length === rows.length} onChange={e => setPicked(e.target.checked ? rows.map(r => r.id) : [])} /></th><th>Strategy</th><th>Stage</th><th>Round</th><th>Best (measured)</th><th>Worker time</th><th>Rung</th><th>Review</th><th>Who</th><th></th></tr></thead>
      <tbody>{sorted.map(row => (
        <tr key={row.id} data-record-id={row.id} data-stage={row.stage} className={selectedId === row.id ? 'selected' : ''}>
          <td><input type="checkbox" aria-label={`select ${row.title}`} checked={picked.includes(row.id)} onChange={() => toggle(row.id)} /></td>
          <td><a href="#" onClick={e => { e.preventDefault(); onOpen(row.id); }}>{row.label ? <Pill>{row.label}</Pill> : null} {row.title}</a>{row.live_trials ? <Pill tone="agent"> {row.live_trials} live</Pill> : null}</td>
          <td><Pill tone={STAGE_TONE[row.stage]} title={row.stage === 'stopped' ? `Stopped: ${row.stop_reason || 'no reason recorded'}` : STAGE_WORD[row.stage] || row.stage}>{row.stage}</Pill></td>
          <td>{row.round ?? <span className="faint">–</span>}</td>
          <td>{num(row.best.score, 4)}{row.best.score != null ? <span className="faint small"> {row.best.source}</span> : null}</td>
          <td>{duration(row.worker_seconds)}<span className="faint small"> of {duration(row.allotted_seconds)}</span></td>
          <td>{row.highest_rung_seconds ? duration(row.highest_rung_seconds) : <span className="faint">–</span>}{row.race ? <span className="small faint"> · race {row.race.status}</span> : null}</td>
          <td>{row.review.verdict ? <Pill tone={row.review.verdict === 'test' ? 'clear' : 'attention'}>{row.review.verdict}</Pill> : <span className="faint small">{row.review.count ? `${row.review.count} notes` : 'none'}</span>}{!row.implementation_readiness.runnable ? <span className="why"> not runnable</span> : null}</td>
          <td>{row.autonomous ? <Pill tone="agent" title="Run by autopilot">autopilot</Pill> : row.actor === 'researcher' ? <Pill tone="you">You</Pill> : row.actor ? <Pill tone="agent">{row.actor}</Pill> : null}</td>
          <td><button className="btn quiet small" onClick={() => onTrace(row.id)} title="Trace origin">origin</button></td>
        </tr>))}</tbody>
    </table>
  );
}

function InterventionBar({ rows, pending, onStop, onPromote, onAllocate, onGenerate, onDiscuss }: { rows: LedgerRow[]; pending: string | null; onStop: (reason: string) => void; onPromote: () => void; onAllocate: (seconds: number, rationale: string) => void; onGenerate: (operation: 'hybrid' | 'revise' | 'diversify', count: number, note: string) => void; onDiscuss: () => void }) {
  const [mode, setMode] = useState<'stop' | 'allocate' | 'generate' | null>(null);
  const [text, setText] = useState('');
  const [seconds, setSeconds] = useState(600);
  const [count, setCount] = useState(2);
  const busy = !!pending;
  return (
    <div className="card" data-testid="interventions">
      <div className="row wrap"><strong>{rows.length} selected:</strong>
        <button className="btn small" disabled={busy} onClick={() => setMode('stop')}>Stop…</button>
        <button className="btn small" disabled={busy} onClick={onPromote}>Promote to finalist</button>
        <button className="btn small" disabled={busy} onClick={() => setMode('allocate')}>Allocate time…</button>
        <button className="btn small" disabled={busy} onClick={() => setMode('generate')}>{rows.length > 1 ? 'Hybrid of these…' : 'Revise…'}</button>
        <button className="btn quiet small" onClick={onDiscuss} title="Opens the conversation with these selected">Discuss</button>
        {pending ? <Pill tone="agent">{pending}…</Pill> : null}</div>
      {mode === 'stop' ? <div className="row" style={{ marginTop: 6 }}><input className="grow" placeholder="Why stop them (recorded on the graph)" value={text} onChange={e => setText(e.target.value)} data-testid="stop-reason" /><button className="btn primary small" disabled={!text.trim()} onClick={() => { onStop(text.trim()); setMode(null); setText(''); }}>Stop</button><button className="btn quiet small" onClick={() => setMode(null)}>cancel</button></div> : null}
      {mode === 'allocate' ? <div className="row" style={{ marginTop: 6 }}><input type="number" min={1} value={seconds} onChange={e => setSeconds(Number(e.target.value))} aria-label="seconds" style={{ width: 100 }} /><span className="small">s each</span><input className="grow" placeholder="Why (one line)" value={text} onChange={e => setText(e.target.value)} /><button className="btn primary small" disabled={!text.trim()} onClick={() => { onAllocate(seconds, text.trim()); setMode(null); setText(''); }}>Allocate</button><button className="btn quiet small" onClick={() => setMode(null)}>cancel</button></div> : null}
      {mode === 'generate' ? <div className="row" style={{ marginTop: 6 }}><input type="number" min={1} max={8} value={count} onChange={e => setCount(Number(e.target.value))} aria-label="count" style={{ width: 70 }} /><input className="grow" placeholder="A note for the lead (optional)" value={text} onChange={e => setText(e.target.value)} /><button className="btn primary small" onClick={() => { onGenerate(rows.length > 1 ? 'hybrid' : 'revise', count, text.trim()); setMode(null); setText(''); }}>{rows.length > 1 ? 'Generate hybrids' : 'Generate revisions'}</button><button className="btn quiet small" onClick={() => setMode(null)}>cancel</button></div> : null}
      <p className="why">All or nothing: one refused item undoes the batch. Each stop records its reason; stopped never reads as failed.</p>
    </div>
  );
}

function Curves({ rows, selectedId }: { rows: LedgerRow[]; selectedId: string | null }) {
  const withCurves = rows.filter(r => r.curve?.length);
  if (!withCurves.length) return <Empty>No measured curve yet. Curves are drawn from each strategy's best run, at matched evaluations.</Empty>;
  return <Section title="Score curves (measured, best run per strategy)">{withCurves.map(row => <div key={row.id} className={'card' + (selectedId === row.id ? ' selected' : '')} data-record-id={row.id}><div className="row"><strong className="grow">{row.label ? row.label + ' · ' : ''}{row.title}</strong><Pill tone={STAGE_TONE[row.stage]}>{row.stage}</Pill><span className="faint small">{row.curve!.length} points</span></div><Curve points={row.curve!} height={90} label={row.title} /></div>)}</Section>;
}

function Races({ data }: { data: Evolution }) {
  if (!data.races.length) return <Empty>No race yet. A race starts when several strategies are ready to be compared at matched cost over rungs.</Empty>;
  return <>{data.races.map(race => <Section key={race.id} title={`Race ${race.id}`} right={<Pill>{race.status}</Pill>}>
    <Kv rows={[['Elapsed', `${duration(race.elapsed_seconds)} of ${duration(race.total_seconds)}`], ['Worker seconds', `${duration(race.worker_seconds_spent)} of ${duration(race.worker_seconds_cap)} (measured)`], ['Running now', String(race.running_workers ?? 'unknown')]]} />
    <table><thead><tr><th>Configuration</th><th>Status</th><th>Mean score</th><th>Seeds</th><th>Rung</th><th>Maturity</th></tr></thead><tbody>{race.configurations.map(c => <tr key={c.id}><td>{c.id} <span className="faint small">{c.algorithm}</span></td><td><Pill>{c.status}</Pill></td><td>{num(c.mean_score, 4)}</td><td>{c.seeds}</td><td>{duration(c.rung_seconds)}</td><td className="small">{c.maturity.eligible ? 'eligible' : c.maturity.reasons.join('; ')}</td></tr>)}</tbody></table>
    {race.decisions.length ? <details><summary className="small">{race.decisions.length} decisions</summary>{race.decisions.slice(-10).reverse().map((d, i) => <div key={i} className="small">{d.action} {d.configuration_ids?.join(', ')} — {d.rationale} <span className="faint">{when(d.created_at)}</span></div>)}</details> : null}
  </Section>)}</>;
}
