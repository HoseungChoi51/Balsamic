/** The branch map: every thread as a lane with its summary card and activity strip; fork, switch, park, unpark, merge. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useSummary, useThreads } from '../api/queries';
import type { Thread } from '../api/types';
import { send } from '../commands/bus';
import { Empty, Failed, Loading, Pill, when } from '../primitives/ui';
import { formatHash } from '../router/routes';
import { track } from '../telemetry/events';

const GLYPH: Record<string, string> = { message: '•', strategy: '◆', run: '▶', decision: '✓', note: '✎', merge: '⤵', command: '·' };

export function ActivityStrip({ strip }: { strip: { glyph: string; at: string; who?: string; operation?: string }[] }) {
  if (!strip?.length) return <span className="faint small">no activity yet</span>;
  return <span className="mono small" title={strip.map(s => `${s.glyph}${s.operation ? ' ' + s.operation : ''} ${when(s.at)}`).join('\n')} aria-label="activity strip">
    {strip.map((s, i) => <span key={i} style={{ color: s.glyph === 'message' ? (s.who === 'you' ? 'var(--you)' : 'var(--agent)') : 'var(--ink-2)' }}>{GLYPH[s.glyph] || '·'}</span>)}</span>;
}

export function SummaryCard({ thread, current, route, onPark, onUnpark, onMerge }: { thread: Thread; current: boolean; route: PageProps['route']; onPark: (t: Thread) => void; onUnpark: (t: Thread) => void; onMerge: (t: Thread) => void }) {
  const summary = thread.summary;
  return (
    <article className={'card' + (current ? ' selected' : '')} data-testid="thread-card" data-thread-id={thread.id} data-status={thread.status}>
      <div className="row">
        <a href={formatHash({ page: route.page === 'branches' ? 'monitor' : route.page, sub: route.sub }, thread.id)} onClick={() => track('thread.switch', { from: 'map' })}><strong>{thread.title}</strong></a>
        <Pill tone={thread.status === 'active' ? 'clear' : thread.status === 'parked' ? 'attention' : ''}>{thread.status}</Pill>
        {thread.busy ? <Pill tone="agent">lead working</Pill> : null}{thread.queued ? <Pill>{thread.queued} queued</Pill> : null}{thread.unread ? <Pill tone="you">new reply</Pill> : null}
        <span className="grow" /><span className="small faint">{thread.message_count} turns · {when(thread.last_activity_at)}</span>
      </div>
      <div style={{ margin: '4px 0' }}><ActivityStrip strip={(thread.status === 'active' ? thread.strip : summary?.strip) || thread.strip || []} /></div>
      {summary ? <p className="small">{summary.text} <span className="faint">({summary.written_by === 'model' ? `summary by ${summary.model || 'the model'}` : 'activity only, no model call'}{summary.stale ? ', stale' : ''})</span></p>
        : <p className="small faint">No summary yet: one is written when the branch is parked or merged.</p>}
      {thread.parent_thread_id ? <p className="why">forked from {thread.parent_thread_id} at {thread.fork_message_id}</p> : null}
      <div className="row wrap">
        {thread.status === 'active' && thread.name !== 'main' ? <button className="btn small" onClick={() => onPark(thread)}>Park</button> : null}
        {thread.status === 'parked' ? <button className="btn small" onClick={() => onUnpark(thread)}>Take up again</button> : null}
        {thread.status !== 'merged' && thread.name !== 'main' ? <button className="btn small" onClick={() => onMerge(thread)}>Merge into…</button> : null}
        {thread.status === 'merged' ? <span className="small faint">merged into {thread.merged_into}</span> : null}
        <a className="btn quiet small" href={`/api/v1/threads/${thread.id}/export`} download data-testid="export-thread">Export</a>
      </div>
    </article>
  );
}

export default function BranchesPage({ campaignId, route }: PageProps) {
  const threads = useThreads(campaignId);
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const [mergingId, setMergingId] = useState<string | null>(null);
  const [into, setInto] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  if (threads.isPending) return <Loading />;
  if (threads.error) return <Failed error={threads.error} />;
  const rows = threads.data.threads;
  const merging = rows.find(t => t.id === mergingId) || null;
  const setMerging = (t: Thread | null) => setMergingId(t ? t.id : null);
  const version = summary.data?.campaign.version;
  const run = async (operation: string, payload: Record<string, unknown>, kind: string) => {
    if (version === undefined) return;
    setError(null);
    try { await send({ operation, campaignId, expectedRevision: version, payload, origin: { thread_id: route.thread } }); track(kind, {}); await queryClient.invalidateQueries({ queryKey: ['threads', campaignId] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const lanes = (parent: string | null, depth = 0): React.ReactNode[] => rows.filter(t => (t.parent_thread_id || null) === parent).flatMap(t => [
    <div key={t.id} style={{ marginLeft: depth * 22, borderLeft: depth ? '2px solid var(--line-2)' : 'none', paddingLeft: depth ? 10 : 0 }} className="lane">
      <SummaryCard thread={t} current={route.thread === t.id} route={route} onPark={th => run('thread.park', { thread_id: th.id }, 'thread.park')} onUnpark={th => run('thread.unpark', { thread_id: th.id }, 'thread.unpark')} onMerge={th => { setMerging(th); setInto(rows.find(r => r.id === th.parent_thread_id)?.id || rows[0].id); }} />
    </div>, ...lanes(t.id, depth + 1)]);
  return (
    <div className="col">
      <div className="stage-head"><h1>Branches</h1><span className="muted small">{rows.filter(t => t.status === 'active').length} active · {rows.filter(t => t.status === 'parked').length} parked · {rows.filter(t => t.status === 'merged').length} merged</span></div>
      {error ? <div className="pill bad">{error}</div> : null}
      {merging ? <div className="card" data-testid="merge-dialog"><h3>Merge “{merging.title}” into</h3>
        <select value={into} onChange={e => setInto(e.target.value)}>{rows.filter(t => t.id !== merging.id && t.status !== 'merged').map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select>
        <textarea style={{ width: '100%', minHeight: 70, marginTop: 6 }} placeholder="The merge note: what this branch concluded, as the request the lead reads in the target" value={note} onChange={e => setNote(e.target.value)} />
        <p className="why">{merging.merge_draft?.text ? 'Drafted by the lead from the branch; edit it as you like.' : merging.merge_draft ? 'The lead is drafting the note…' : 'Ask the lead to draft it from the branch, or write it yourself.'}</p>
        <div className="row wrap"><button className="btn small" onClick={() => run('thread.merge_draft', { thread_id: merging.id, into_thread_id: into }, 'thread.merge_draft')} data-testid="draft-note">Ask the lead for a draft</button>
          {merging.merge_draft?.text && merging.merge_draft.text !== note ? <button className="btn small" onClick={() => setNote(merging.merge_draft!.text!)} data-testid="use-draft">Use the draft</button> : null}
          <button className="btn primary small" disabled={!note.trim()} onClick={async () => { await run('thread.merge', { thread_id: merging.id, into_thread_id: into, note }, 'thread.merge'); setMerging(null); setNote(''); }}>Merge</button><button className="btn small" onClick={() => setMerging(null)}>Cancel</button></div></div> : null}
      {rows.length ? lanes(null) : <Empty>No thread yet.</Empty>}
    </div>
  );
}
