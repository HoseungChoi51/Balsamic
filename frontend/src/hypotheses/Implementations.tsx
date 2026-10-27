/** The Implementations tab: each coding workspace as a card (what it is for, how it is going, and its history), and the
 *  library versions validated through commissions. Everything here comes from what the workspace recorded; nothing is guessed. */
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useRead } from '../api/queries';
import { Markdown } from '../chat/render/Markdown';
import { Empty, Failed, Kv, Loading, Pill, Section, when } from '../primitives/ui';
import { Meter } from '../primitives/charts';
import { formatHash } from '../router/routes';

export interface Checkpoint { at: string; summary: string; next_steps?: string; blocker?: string; question?: string; done?: string[]; remaining?: string[] }
export interface Tests { passed: number; failed: number; skipped?: number; command?: string }
export interface Report {
  verdict: 'ready' | 'ready_with_limits' | 'not_ready'; summary: string; tests: Tests; limitations: string[];
  methods: { method_id: string; hypothesis_id?: string | null; state: string; conformance: string; tests?: Tests | null; note?: string }[];
  next_actions: { owner: 'researcher' | 'lead' | 'validator'; action: string }[];
}
export interface Submission { id: string; commit: string; status: string; notes?: string; report?: Report | null; created_at: string;
  validation_outcome?: { status?: string; error?: string | null; findings?: Record<string, string>[] } }
export interface Outcome { state: string; verdict?: string; submission_id?: string; commit?: string; at: string; reason?: string }
export interface Workspace {
  id: string; campaign_id: string; title: string; hypothesis_id: string; hypothesis_ids?: string[]; status: string; desired_status: string; created_at: string;
  started_at?: string; last_activity_at?: string; cpu_budget_seconds?: number | null; usage?: { container_cpu_seconds?: number };
  error?: string; activity?: string; checkpoints?: Checkpoint[]; last_error_at?: string | null; ide_url?: string;
  opened_by?: { actor?: string; role?: string }; questions?: { id: string; question: string }[];
  phase?: string; tests?: Tests; estimate?: { remaining_minutes: number; given_at: string; source: string };
  outcome?: Outcome | null; finished_at?: string | null; submissions?: Submission[];
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
export const VERDICT: Record<string, [string, string]> = { ready: ['ready', 'clear'], ready_with_limits: ['ready, with limits', 'attention'],
  not_ready: ['not ready', 'bad'], unreported: ['no delivery report', ''] };
const OUTCOME: Record<string, [string, string]> = { delivered: ['delivered', 'clear'], validating: ['being validated', 'agent'], validated: ['validated', 'clear'],
  needs_revision: ['needs revision', 'bad'], stopped: ['stopped', ''], failed: ['failed', 'bad'] };
const OWNER: Record<string, string> = { researcher: 'You', lead: 'The lead', validator: 'Independent validation' };
export const testsText = (t?: Tests | null) => t ? `${t.passed} passed, ${t.failed} failed${t.skipped ? `, ${t.skipped} skipped` : ''}` : '';
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
      <Algorithms campaignId={campaignId} thread={route.thread} labels={labels} />
      {workspaces.length ? <h2 style={{ margin: '12px 0 6px' }}>Coding workspaces</h2> : null}
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
        {w.phase && live ? <Pill tone="agent" title="The phase the coding agent gave at its latest checkpoint">{w.phase}</Pill> : null}
        <Pill tone={tone} live={w.status === 'running'}>{label}</Pill>
        {w.outcome ? <Pill tone={(OUTCOME[w.outcome.state] || [])[1]} title={`Latest result, ${new Date(w.outcome.at).toLocaleString()}`}>{(OUTCOME[w.outcome.state] || [w.outcome.state])[0]}</Pill> : null}
        {w.ide_url ? <a className="btn small quiet" href={w.ide_url} target="_blank" rel="noreferrer" title="The workspace's editor and terminal">Open the editor</a> : null}
      </div>
      <Kv rows={[
        ['For', <span className="row wrap" style={{ gap: 4 }}>{proposals.map(id => <a key={id} className="chip" href={formatHash({ page: 'hypotheses', id, sel: id }, thread)}>{labels[id] || id.slice(0, 18)}</a>)}</span>],
        ['Opened', `${new Date(w.created_at).toLocaleString()}${w.opened_by?.role ? ` by the ${w.opened_by.role.replaceAll('_', ' ')}` : ''}${w.desired_status === 'running' ? ` · open for ${minutes(opened)}` : ''}`],
        ['Last activity', w.last_activity_at ? when(w.last_activity_at) : <span className="faint">none yet</span>],
        ...(estimate(w) ? [['Estimate', estimate(w)] as [string, React.ReactNode]] : []),
        ...(w.tests ? [['Tests', <span>{testsText(w.tests)} <span className="faint small">at the latest checkpoint</span></span>] as [string, React.ReactNode]] : []),
        ['CPU', w.cpu_budget_seconds ? <div style={{ maxWidth: 260 }}><Meter total={w.cpu_budget_seconds} segments={[{ value: used, tone: used >= w.cpu_budget_seconds ? 'bad' : 'info', title: `${used.toFixed(0)} s used` }]} label="CPU used of the allowance" />
          <span className="small faint">{used.toFixed(0)} of {w.cpu_budget_seconds.toFixed(0)} s</span></div> : <span className="small">{used.toFixed(0)} s, no allowance set</span>],
      ]} />
      {w.error ? <div className="callout attention small" role="alert" data-testid="workspace-error">{w.error}</div> : null}
      {w.questions?.length ? <div className="callout attention small" data-testid="workspace-question"><strong>The coding agent asks:</strong> {w.questions[0].question}</div> : null}
      {w.outcome ? <OutcomeBox workspace={w} labels={labels} thread={thread} /> : null}
      {latest ? <div className="small" data-testid="workspace-checkpoint" style={{ marginTop: 6 }}>
        <span className="faint">Latest checkpoint, {when(latest.at)}:</span>
        <Markdown text={latest.summary} thread={thread} className="md small" />
        {latest.next_steps ? <div className="faint">Next: {latest.next_steps}</div> : null}
        {latest.blocker ? <div className="pill warn" style={{ whiteSpace: 'normal' }}>Blocker: {latest.blocker}</div> : null}
        {latest.remaining?.length ? <div className="faint">Remaining: {latest.remaining.join('; ')}</div> : null}
      </div> : null}
      <MessageAgent workspace={w} />
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

/** The coding agent's own estimate, said as its own; once its time has passed with no newer one, that is said instead. */
function estimate(w: Workspace) {
  const e = w.estimate;
  if (!e || (w.outcome && w.outcome.at > e.given_at)) return null;
  const due = new Date(e.given_at).getTime() + e.remaining_minutes * 60_000;
  return <span data-testid="workspace-estimate">{due > Date.now()
    ? <>about {Math.max(1, Math.round((due - Date.now()) / 60_000))} min left<span className="faint small">: the coding agent's estimate at {clock(e.given_at)}</span></>
    : <span className="faint">the coding agent's estimate at {clock(e.given_at)} ({Math.round(e.remaining_minutes)} min) has passed; it has given no newer one</span>}</span>;
}

/** The latest result: a delivery with the coding agent's verdict, a validation's result, or a failure. */
function OutcomeBox({ workspace: w, labels, thread }: { workspace: Workspace; labels: Record<string, string>; thread: string | null }) {
  const o = w.outcome!;
  const submission = w.submissions?.find(s => s.id === o.submission_id);
  const report = submission?.report;
  const [verdict, tone] = VERDICT[o.verdict || 'unreported'] || [o.verdict, ''];
  return (
    <div className="outcome" data-testid="workspace-outcome" data-state={o.state} data-verdict={o.verdict || ''}>
      <div className="row wrap">
        <strong className="grow">{o.state === 'failed' ? 'Failed' : o.state === 'stopped' ? 'Stopped' : `Delivered commit ${o.commit?.slice(0, 7)}`}
          <span className="faint small"> · {new Date(o.at).toLocaleString()}</span></strong>
        {o.commit ? <Pill tone={tone} title="The coding agent's own judgement of what it delivered">{verdict}</Pill> : null}
      </div>
      {o.state === 'failed' ? <p className="small">{o.reason}</p> : null}
      {o.state === 'validated' ? <p className="small">Independent validation passed.</p> : null}
      {o.state === 'needs_revision' ? <div className="small"><p>Independent validation found problems{submission?.validation_outcome?.error ? `: ${submission.validation_outcome.error}` : '.'}</p>
        {submission?.validation_outcome?.findings?.length ? <ul>{submission.validation_outcome.findings.slice(0, 10).map((f, i) => <li key={i}>{f.detail || f.review || f.check}</li>)}</ul> : null}</div> : null}
      {report ? <>
        <Markdown text={report.summary} thread={thread} className="md small" />
        <table className="small" data-testid="outcome-methods"><thead><tr><th>Method</th><th>Proposal</th><th>State</th><th>Conformance</th><th>Tests</th></tr></thead>
          <tbody>{report.methods.map(m => <tr key={m.method_id}><td className="mono">{m.method_id}</td>
            <td>{m.hypothesis_id ? <a className="chip" href={formatHash({ page: 'hypotheses', id: m.hypothesis_id, sel: m.hypothesis_id }, thread)}>{labels[m.hypothesis_id] || m.hypothesis_id.slice(0, 18)}</a> : <span className="faint">—</span>}</td>
            <td><Pill tone={m.state === 'implemented' ? 'clear' : 'attention'}>{m.state.replace('_', ' ')}</Pill></td>
            <td><Pill tone={m.conformance === 'passed' ? 'clear' : m.conformance === 'failed' ? 'bad' : 'attention'}>{m.conformance.replace('_', ' ')}</Pill></td>
            <td>{testsText(m.tests)}</td></tr>)}</tbody></table>
        <p className="small">Tests: {testsText(report.tests)}{report.tests.command ? <> · <code>{report.tests.command}</code></> : null}</p>
        {report.limitations.length ? <div className="small" data-testid="outcome-limitations"><strong>Limitations</strong><ul>{report.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></div> : null}
        {report.next_actions.length ? <div className="small" data-testid="outcome-next"><strong>Next</strong><ul>{report.next_actions.map((a, i) =>
          <li key={i}><Pill tone={a.owner === 'researcher' ? 'you' : 'agent'}>{OWNER[a.owner]}</Pill> {a.action}</li>)}</ul></div> : null}
      </> : submission ? <details className="small"><summary>No delivery report (sent before the coding agent's tools asked for one); its notes</summary>
        <Markdown text={submission.notes || '(none)'} thread={thread} className="md small" /></details> : null}
    </div>
  );
}


/** A word to the coding agent: the researcher's instruction takes precedence over the lead's. */
function MessageAgent({ workspace: w }: { workspace: Workspace }) {
  const [text, setText] = useState('');
  const [state, setState] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const send = async () => {
    if (!text.trim()) return;
    setState('sending');
    try {
      await api(`/api/campaigns/${w.campaign_id}/implementation-workspaces/${w.id}/messages`, { method: 'POST',
        body: JSON.stringify({ message: text.trim(), mode: 'steer', request_key: `researcher-${Date.now()}` }) });
      setText(''); setState('sent: the coding agent reads it at its next step');
      await queryClient.invalidateQueries({ queryKey: ['timeline', w.id] });
    } catch (e) { setState(String((e as Error).message || e)); }
  };
  return (
    <div className="row" style={{ marginTop: 6 }}>
      <input className="grow" placeholder="Message the coding agent (yours takes precedence over the lead's)" value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') void send(); }} data-testid="workspace-message" />
      <button className="btn small" disabled={!text.trim() || state === 'sending'} onClick={() => void send()}>Send</button>
      {state && state !== 'sending' ? <span className="small faint">{state}</span> : null}
    </div>
  );
}

interface MethodRow {
  id: string; name: string; source: 'bundled' | 'library' | 'submitted'; state: string; reported?: boolean; verdict?: string;
  package?: { name?: string | null; version?: string | null; commit?: string | null; install_id?: string | null } | null;
  workspace_id?: string | null; submission_id?: string | null;
  tasks: { task_id: string; runnable: boolean; reason: string | null }[];
  proposals: { hypothesis_id: string; bound: boolean; default: boolean }[];
  next_action: { owner: string; text: string } | null;
}
interface Catalog { tasks: { id: string; name: string; problem_id?: string; blocker: string | null }[]; methods: MethodRow[];
  building: { workspace_id: string; title: string; phase?: string | null; hypothesis_ids: string[] }[]; other: { id: string; name: string; source: string; reason: string | null }[]; other_count: number }

const METHOD_STATE: Record<string, [string, string]> = { runnable: ['can run', 'clear'], not_installed: ['delivered, not installed', 'attention'],
  needs_revision: ['needs revision', 'bad'], incompatible: ['cannot run here', 'bad'], legacy: ['not installable', ''] };

/** Which algorithms this campaign can run, and why the others cannot, with the next step and who takes it. */
function Algorithms({ campaignId, thread, labels }: { campaignId: string; thread: string | null; labels: Record<string, string> }) {
  const view = useRead<Catalog>(['methods', campaignId], `/api/v1/campaigns/${campaignId}/methods`, { refetchInterval: 30000 });
  if (view.isPending) return <Loading what="Reading which algorithms can run" />;
  if (view.error) return <Failed error={view.error} />;
  const { tasks, methods, building, other, other_count } = view.data;
  const chip = (id: string) => <a key={id} className="chip" href={formatHash({ page: 'hypotheses', id, sel: id }, thread)}>{labels[id] || id.slice(0, 18)}</a>;
  // Bundled methods nothing here uses are folded away; what proposals use, and libraries, come first.
  const shown = methods.filter(m => m.source !== 'bundled' || m.proposals.length || m.state !== 'runnable');
  const spare = methods.filter(m => !shown.includes(m));
  const where = (m: MethodRow) => m.source === 'bundled' ? 'bundled with Balsamic'
    : m.source === 'library' ? `library ${m.package?.name || ''} ${m.package?.version || ''}`.trim()
    : `${m.package?.name ? `library ${m.package.name}, ` : ''}delivered in commit ${(m.package?.commit || '').slice(0, 7)}${m.reported === false ? ' (method ids not reported)' : ''}`;
  return (
    <Section title="Algorithms" right={<span className="small faint">what this campaign can run, and why the others cannot</span>}>
      <div data-testid="algorithms">
        {tasks.filter(t => t.blocker).map(t => <div key={t.id} className="callout attention small" data-testid="task-blocker">
          <strong>{t.name}</strong> cannot run any method yet: {t.blocker}</div>)}
        {building.map(b => <div key={b.workspace_id} className="row small wrap" data-testid="algorithm-building">
          <Pill tone="agent" live>being built</Pill><a href={formatHash({ page: 'hypotheses', sub: 'implementations', id: b.workspace_id }, thread)}>{b.title}</a>
          {b.phase ? <span className="faint">({b.phase})</span> : null}<span className="faint">for</span>{b.hypothesis_ids.map(chip)}</div>)}
        {shown.length ? <table className="small" data-testid="algorithm-table"><thead><tr><th>Method</th><th>From</th><th>Can it run?</th><th>Proposals</th><th>Next</th></tr></thead>
          <tbody>{shown.map(m => { const [label, tone] = METHOD_STATE[m.state] || [m.state, '']; const reason = m.tasks.find(t => t.reason)?.reason;
            return <tr key={`${m.source}-${m.id}`} data-testid="algorithm" data-method={m.id} data-state={m.state}>
              <td><span className="mono">{m.id}</span>{m.name !== m.id ? <div className="faint">{m.name}</div> : null}</td>
              <td>{m.workspace_id ? <a href={formatHash({ page: 'hypotheses', sub: 'implementations', id: m.workspace_id }, thread)}>{where(m)}</a> : where(m)}</td>
              <td><Pill tone={tone} title={reason || undefined}>{label}</Pill>{m.state !== 'runnable' && reason ? <div className="faint">{reason}</div> : null}</td>
              <td><span className="row wrap" style={{ gap: 4 }}>{m.proposals.map(p => <span key={p.hypothesis_id} title={p.bound ? (p.default ? 'runs it as the default method' : 'runs it') : 'built for it, not bound yet'}>
                {chip(p.hypothesis_id)}{p.bound ? null : <span className="faint"> (not bound)</span>}</span>)}</span></td>
              <td>{m.next_action ? <><Pill tone={m.next_action.owner === 'researcher' ? 'you' : 'agent'}>{OWNER[m.next_action.owner] || m.next_action.owner}</Pill> {m.next_action.text}</> : null}</td>
            </tr>; })}</tbody></table> : <Empty>No method that matters here yet.</Empty>}
        {spare.length ? <details className="small"><summary>{spare.length} more bundled methods that can run here</summary>
          <p className="mono">{spare.map(m => m.id).join(', ')}</p></details> : null}
        {other_count ? <details className="small"><summary>{other_count} methods that cannot run here, or are procedures rather than search methods</summary>
          <ul>{other.map(o => <li key={o.id}><span className="mono">{o.id}</span>: <span className="faint">{o.reason}</span></li>)}</ul></details> : null}
      </div>
    </Section>
  );
}
