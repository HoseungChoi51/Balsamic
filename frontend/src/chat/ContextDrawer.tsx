/** The context chip and drawer: what the lead sees in this thread, by layer, with pins and exclusions. */
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRead, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Failed, Kv, Loading, Pill } from '../primitives/ui';
import { track } from '../telemetry/events';

interface Layer { items?: { id: string; kind: string | null; title: string; bytes?: number; status?: string | null; revision?: unknown; excluded?: boolean }[]; bytes?: number;
  entries_since_fork?: number; summary_entries?: number; compactions?: number; leaf_entry_id?: string | null; measured?: boolean; basis?: string }
interface Context { thread_id: string; layers: { project: Layer; branch: Layer; live: Layer }; pinned_ids: string[]; excluded_ids: string[]; lab_events_since_last_turn: number }

const kb = (bytes: unknown) => typeof bytes === 'number' ? `${(bytes / 1024).toFixed(1)} KiB` : 'unknown';

export function ContextChip({ threadId, onOpen }: { threadId: string; onOpen: () => void }) {
  const context = useRead<Context>(['context', threadId], `/api/v1/threads/${threadId}/context`, { staleTime: 10000 });
  const data = context.data;
  const total = data ? (data.layers.project.bytes || 0) + (typeof data.layers.branch.bytes === 'number' ? data.layers.branch.bytes : 0) : null;
  return <button className="btn control" data-testid="context-chip" title="Open what the lead sees in this thread" onClick={() => { track('context.open', {}); onOpen(); }}>
    Context{total != null ? ` ${kb(total)}` : ''}{data?.pinned_ids.length ? ` · ${data.pinned_ids.length} pinned` : ''}{data?.lab_events_since_last_turn ? ` · ${data.lab_events_since_last_turn} lab events` : ''}</button>;
}

export function ContextDrawer({ threadId, campaignId, onClose }: { threadId: string; campaignId: string; onClose: () => void }) {
  const context = useRead<Context>(['context', threadId], `/api/v1/threads/${threadId}/context`, { staleTime: 5000 });
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const [recordId, setRecordId] = useState('');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  const pin = async (id: string, excluded: boolean, pinned = true) => {
    const campaign = summary.data?.campaign; if (!campaign) return;
    setError(null);
    try {
      await send({ operation: 'thread.pin', campaignId, expectedRevision: campaign.version, payload: { thread_id: threadId, record_id: id, pinned, excluded }, origin: { thread_id: threadId } });
      track(excluded ? 'context.exclude' : 'context.pin', { kind: id.split('_')[0] });
      await queryClient.invalidateQueries({ queryKey: ['context', threadId] });
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  if (context.isPending) return <aside className="drawer"><Loading /></aside>;
  if (context.error) return <aside className="drawer"><Failed error={context.error} /></aside>;
  const { layers } = context.data;
  return (
    <aside className="drawer" data-testid="context-drawer" aria-label="Context">
      <div className="row" style={{ marginBottom: 10 }}><h2 className="grow">What the lead sees here</h2><button className="btn quiet small" onClick={onClose}>Close</button></div>
      <section className="card"><h3>Project layer <span className="faint small">{kb(layers.project.bytes)}</span></h3>
        <p className="small muted">The problem, the tasks, the charter and your guidance: in every turn, in every thread.</p>
        <Kv rows={(layers.project.items || []).map(item => [item.kind || '', <>{item.title} <span className="faint">{kb(item.bytes)}</span></>])} /></section>
      <section className="card"><h3>Branch layer <span className="faint small">{kb(layers.branch.bytes)}</span></h3>
        <p className="small muted">{layers.branch.measured ? 'Measured by the harness from this branch\'s leaf.' : 'Estimated from the saved messages; the harness has not reported this branch yet.'}</p>
        <Kv rows={[['Entries since fork', String(layers.branch.entries_since_fork ?? 'unknown')], ['Branch summaries', String(layers.branch.summary_entries ?? 'unknown')], ['Compactions', String(layers.branch.compactions ?? 'none reported')], ['Leaf', layers.branch.leaf_entry_id || <span className="faint">no turn yet</span>]]} /></section>
      <section className="card"><h3>Live layer</h3>
        <p className="small muted">Records this thread keeps in view (pinned) or out of it (excluded); the lead reads their current state each turn.</p>
        {(layers.live.items || []).length ? (layers.live.items || []).map(item => <div key={item.id} className="row small" data-testid="context-item">
          <Pill tone={item.excluded ? 'bad' : 'clear'}>{item.excluded ? 'excluded' : 'pinned'}</Pill><span className="grow">{item.title} <span className="faint mono">{item.id}</span>{item.status ? <> · {item.status}</> : null}</span>
          {item.excluded ? <button className="btn small" onClick={() => pin(item.id, false)}>Pin</button> : <button className="btn small" onClick={() => pin(item.id, true)}>Exclude</button>}
          <button className="btn quiet small" onClick={() => pin(item.id, false, false)}>Forget</button></div>) : <div className="faint small">Nothing pinned or excluded.</div>}
        <form className="row" style={{ marginTop: 8 }} onSubmit={e => { e.preventDefault(); if (recordId.trim()) { void pin(recordId.trim(), false); setRecordId(''); } }}>
          <input className="grow" placeholder="record id to pin (hypothesis_…, trial_…)" value={recordId} onChange={e => setRecordId(e.target.value)} data-testid="pin-input" /><button className="btn small" type="submit">Pin</button></form>
        {error ? <div className="pill bad">{error}</div> : null}</section>
      <p className="why">Lab events since the last turn: {context.data.lab_events_since_last_turn}. A forgotten report? Tell us: <button className="btn quiet small" onClick={() => track('context.forgot_report', {})}>it forgot something</button></p>
    </aside>
  );
}
