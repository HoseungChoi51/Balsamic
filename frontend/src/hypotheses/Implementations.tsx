/** The Implementations tab: each coding workspace as a card (what it is for, how it is going, and its history), and the
 *  library versions validated through commissions. Everything here comes from what the workspace recorded; nothing is guessed. */
import { useEffect, useRef, useState } from 'react';
import { useRead } from '../api/queries';
import { Markdown } from '../chat/render/Markdown';
import { Empty, Failed, Kv, Loading, Pill, Section, when } from '../primitives/ui';
import { Meter } from '../primitives/charts';
import { formatHash } from '../router/routes';

export interface Checkpoint { at: string; summary: string; next_steps?: string; blocker?: string; question?: string }
export interface Workspace {
  id: string; campaign_id: string; title: string; hypothesis_id: string; hypothesis_ids?: string[]; status: string; desired_status: string; created_at: string;
  started_at?: string; last_activity_at?: string; cpu_budget_seconds?: number | null; usage?: { container_cpu_seconds?: number };
  error?: string; activity?: string; checkpoints?: Checkpoint[]; last_error_at?: string | null; ide_url?: string;
  opened_by?: { actor?: string; role?: string }; questions?: { id: string; question: string }[];
}
interface Entry { at: string; kind: string; title: string; detail: string; tone: string; ref: string | null; items: string[] }
interface Timeline { entries: Entry[]; next_before: string | null }

/** Working means the coding agent is busy; waiting means it settled and waits for input; the rest say themselves. */
const STATUS: Record<string, [string, string]> = {
  queued: ['starting', 'agent'], starting: ['starting', 'agent'], resuming: ['resuming', 'agent'], running: ['working', 'agent'],
  idle: ['waiting for input', ''], pausing: ['pausing', 'attention'], paused: ['paused', 'attention'], stopping: ['stopping', 'attention'],
  stopped: ['stopped', ''], blocked: ['blocked', 'bad'],
};
export const LIVE = new Set(['queued', 'starting', 'resuming', 'running', 'pausing', 'stopping']);
const TONE: Record<string, string> = { ok: 'good', warn: 'warn', attention: 'warn', bad: 'bad', info: 'info', you: 'you', agent: 'agent' };
const minutes = (ms: number) => ms < 90_000 ? `${Math.round(ms / 1000)} s` : ms < 5_400_000 ? `${Math.round(ms / 60_000)} min` : `${(ms / 3_600_000).toFixed(1)} h`;

export function Implementations({ campaignId, route, labels }: { campaignId: string; route: { thread: string | null; id: string | null }; labels: Record<string, string> }) {
  const view = useRead<{ enabled: boolean; disabled?: string; workspaces: Workspace[] }>(['implementation-workspaces', campaignId],
    `/api/campaigns/${campaignId}/implementation-workspaces`, { refetchInterval: 30000 });
  const catalog = useRead<{ versions: Record<string, unknown>[] }>(['implementations', campaignId], `/api/v1/implementations?campaign_id=${campaignId}`);
  if (view.isPending) return <Loading />;
  if (view.error) return <Failed error={view.error} />;
  const workspaces = [...view.data.workspaces].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const versions = catalog.data?.versions || [];
  return (
    <>
      {workspaces.length ? workspaces.map(w => <WorkspaceCard key={w.id} workspace={w} thread={route.thread} labels={labels} focused={route.id === w.id} />)
        : <Empty>{view.data.enabled ? 'No coding workspace yet. The implementation lead opens one, with your go-ahead, when a proposal needs code.'
          : view.data.disabled || 'Coding workspaces are off.'}</Empty>}
      {versions.length ? <Section title={`Validated library versions (${versions.length})`}>
        <table><thead><tr><th>Version</th><th>Name</th><th>Status</th><th>Validated</th></tr></thead><tbody>{versions.map(v =>
          <tr key={String(v.id)}><td className="mono small">{String(v.id)}</td><td>{String(v.name || (v.spec as { name?: string } | undefined)?.name || '')}</td>
            <td><Pill>{String(v.status || '')}</Pill></td><td className="small">{String(v.validated_at || v.validation_level || '')}</td></tr>)}</tbody></table>
      </Section> : null}
    </>
  );
}

function WorkspaceCard({ workspace: w, thread, labels, focused }: { workspace: Workspace; thread: string | null; labels: Record<string, string>; focused: boolean }) {
  const card = useRef<HTMLElement>(null);
  useEffect(() => { if (focused) card.current?.scrollIntoView({ block: 'start' }); }, [focused]);
  const [label, tone] = STATUS[w.status] || [w.status, ''];
  const live = LIVE.has(w.status);
  const used = w.usage?.container_cpu_seconds ?? 0;
  const proposals = w.hypothesis_ids?.length ? w.hypothesis_ids : [w.hypothesis_id];
  const latest = w.checkpoints?.at(-1);
  const opened = Date.now() - new Date(w.created_at).getTime();
  return (
    <article className="card workspace-card" ref={card} data-testid="workspace-card" data-workspace={w.id} data-status={w.status}>
      <div className="row wrap" style={{ marginBottom: 6 }}>
        <h2 className="grow" style={{ margin: 0 }}>{w.title}</h2>
        <Pill tone={tone} live={w.status === 'running'}>{label}</Pill>
        {w.ide_url ? <a className="btn small quiet" href={w.ide_url} target="_blank" rel="noreferrer" title="The workspace's editor and terminal">Open the editor</a> : null}
      </div>
      <Kv rows={[
        ['For', <span className="row wrap" style={{ gap: 4 }}>{proposals.map(id => <a key={id} className="chip" href={formatHash({ page: 'hypotheses', id, sel: id }, thread)}>{labels[id] || id.slice(0, 18)}</a>)}</span>],
        ['Opened', `${new Date(w.created_at).toLocaleString()}${w.opened_by?.role ? ` by the ${w.opened_by.role.replaceAll('_', ' ')}` : ''}${w.desired_status === 'running' ? ` · open for ${minutes(opened)}` : ''}`],
        ['Last activity', w.last_activity_at ? when(w.last_activity_at) : <span className="faint">none yet</span>],
        ['CPU', w.cpu_budget_seconds ? <div style={{ maxWidth: 260 }}><Meter total={w.cpu_budget_seconds} segments={[{ value: used, tone: used >= w.cpu_budget_seconds ? 'bad' : 'info', title: `${used.toFixed(0)} s used` }]} label="CPU used of the allowance" />
          <span className="small faint">{used.toFixed(0)} of {w.cpu_budget_seconds.toFixed(0)} s</span></div> : <span className="small">{used.toFixed(0)} s, no allowance set</span>],
      ]} />
      {w.error ? <div className="callout attention small" role="alert" data-testid="workspace-error">{w.error}</div> : null}
      {w.questions?.length ? <div className="callout attention small" data-testid="workspace-question"><strong>The coding agent asks:</strong> {w.questions[0].question}</div> : null}
      {latest ? <div className="small" data-testid="workspace-checkpoint" style={{ marginTop: 6 }}>
        <span className="faint">Latest checkpoint, {when(latest.at)}:</span>
        <Markdown text={latest.summary} thread={thread} className="md small" />
        {latest.next_steps ? <div className="faint">Next: {latest.next_steps}</div> : null}
        {latest.blocker ? <div className="pill warn" style={{ whiteSpace: 'normal' }}>Blocker: {latest.blocker}</div> : null}
      </div> : null}
      <History workspace={w} live={live} open={focused} />
    </article>
  );
}

function History({ workspace: w, live, open: initial }: { workspace: Workspace; live: boolean; open: boolean }) {
  const [open, setOpen] = useState(initial);
  const [older, setOlder] = useState<Entry[]>([]);
  const [before, setBefore] = useState<string | null | undefined>(undefined);   // undefined: no older page loaded yet
  const page = useRead<Timeline>(['timeline', w.id], open ? `/api/campaigns/${encodeURIComponent(w.campaign_id)}/implementation-workspaces/${w.id}/timeline?limit=60` : null,
    { refetchInterval: open && live ? 10000 : undefined });
  const entries = [...(page.data?.entries || []), ...older];
  const more = before === undefined ? page.data?.next_before ?? null : before;
  const loadOlder = async () => {
    if (!more) return;
    const response = await fetch(`/api/campaigns/${encodeURIComponent(w.campaign_id)}/implementation-workspaces/${w.id}/timeline?limit=60&before=${encodeURIComponent(more)}`);
    const next = await response.json() as Timeline;
    setOlder(rows => [...rows, ...next.entries]); setBefore(next.next_before);
  };
  return (
    <details className="history" open={open} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)} data-testid="workspace-history">
      <summary className="small">History{page.data ? ` (${entries.length}${more ? '+' : ''})` : ''}{w.last_error_at ? <span className="faint"> · last error {when(w.last_error_at)}</span> : null}</summary>
      {page.isPending && open ? <Loading what="Reading the history" /> : null}
      <ol className="timeline">
        {entries.map((e, i) => <li key={`${e.at}-${i}`} className={TONE[e.tone] || ''} data-kind={e.kind} data-testid="history-entry">
          <div className="row small"><span className="faint mono" title={e.at}>{new Date(e.at).toLocaleTimeString()}</span><strong className="grow">{e.title}</strong></div>
          {e.detail || e.items.length ? <details className="small"><summary className="faint">details</summary>
            {e.detail ? <Markdown text={e.detail} thread={null} className="md small" /> : null}
            {e.items.length ? <ul className="mono small">{e.items.map((item, j) => <li key={j}>{item}</li>)}</ul> : null}</details> : null}
        </li>)}
      </ol>
      {more ? <button className="btn small quiet" onClick={() => void loadOlder()} data-testid="history-older">Load older</button> : null}
    </details>
  );
}
