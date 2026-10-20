/** Hypotheses: every proposal with its stage and reviews; the generating chips of a round in progress; the review rounds; the implementations. */
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useHypotheses, useMessages, useRead, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Empty, Failed, Loading, Pill, Section, statusTone, when } from '../primitives/ui';
import { formatHash, navigate } from '../router/routes';
import { useSelection } from '../stores/selection';
import { AgentDesk } from '../desks/AgentDesk';
import { HypothesisCard } from './HypothesisCard';
import { useEvolution, STAGE_TONE } from '../evolution/EvolutionPage';
import { track } from '../telemetry/events';

export default function HypothesesPage({ campaignId, route, threadId }: PageProps) {
  const hypotheses = useHypotheses(campaignId);
  const evolution = useEvolution(campaignId);
  const messages = useMessages(threadId);
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const selection = useSelection();
  if (hypotheses.isPending) return <Loading what="Loading hypotheses" />;
  if (hypotheses.error) return <Failed error={hypotheses.error} />;
  const data = hypotheses.data;
  const stages = Object.fromEntries((evolution.data?.nodes || []).map(n => [n.id, n]));
  const labels = Object.fromEntries(data.aliases.map(a => [a.record_id, a.label]));
  const sub = route.sub || 'list';
  const tabs = [['list', 'Proposals'], ['rounds', 'Review rounds'], ['implementations', 'Implementations']] as const;
  const placeholders = messages.data?.placeholders || [];
  const generating = placeholders.length ? { pending: placeholders.filter(p => p.status === 'pending').length, total: placeholders.length } : null;
  const discuss = async (id: string, title: string) => {
    const campaign = summary.data?.campaign; const last = messages.data?.messages.filter(m => m.origin !== 'lab_event').at(-1);
    if (!campaign || !threadId || !last) return;
    const receipt = await send({ operation: 'thread.fork', campaignId, expectedRevision: campaign.version, payload: { thread_id: threadId, message_id: last.id, title: `Discuss ${labels[id] || title.slice(0, 40)}`, anchors: [id] }, origin: { thread_id: threadId } });
    track('thread.fork', { from: 'card' });
    await queryClient.invalidateQueries({ queryKey: ['threads', campaignId] });
    navigate(formatHash({ page: 'hypotheses', id, sel: id }, (receipt.outcome.thread as { id: string }).id));
  };
  return (
    <div className="col">
      <div className="stage-head"><h1>Hypotheses</h1><span className="muted small">{data.hypotheses.length} proposals</span>
        {generating ? <Pill tone="agent" title="A round the lead is recording">{generating.total - generating.pending} of {generating.total} ready</Pill> : null}</div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'hypotheses', sub: key === 'list' ? null : key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {route.id && !route.sub ? <HypothesisCard id={route.id} thread={route.thread} back={formatHash({ page: 'hypotheses' }, route.thread)} onDiscuss={discuss} /> : null}
      {sub === 'list' && !route.id ? (data.hypotheses.length || generating ? <>
        {data.hypotheses.map(h => { const node = stages[h.id]; return (
          <article key={h.id} className={'card' + (selection.id === h.id ? ' selected' : '')} data-record-id={h.id} data-testid="hypothesis" style={{ cursor: 'pointer' }}
            onClick={() => { selection.select(h.id); navigate(formatHash({ page: 'hypotheses', id: h.id, sel: h.id }, route.thread)); }}>
            <div className="row wrap"><Pill>{labels[h.id] || h.id.slice(0, 14)}</Pill><strong className="grow">{h.title}{h.short_title ? <span className="faint small" style={{ marginLeft: 8, fontWeight: 400 }}>{h.short_title}</span> : null}</strong>
              {node ? <Pill tone={STAGE_TONE[node.stage]} title={node.stop_reason || node.stage}>{node.stage}</Pill> : <Pill tone={statusTone(h.status)}>{h.status}</Pill>}
              {h.readiness ? <Pill tone={h.readiness.eligible ? 'clear' : 'attention'} title={h.readiness.reason}>{h.readiness.state.replaceAll('_', ' ')}</Pill> : null}
              {node?.autonomous ? <Pill tone="agent">autopilot</Pill> : null}</div>
            <p className="small muted">{(h.mechanism || '').slice(0, 240)}</p>
            <div className="row small faint"><span>{h.algorithm ? <>{h.algorithm}{h.algorithm_chosen === false ? <span className="pill attention" style={{ marginLeft: 6 }} title="The default search lane was recorded because none was chosen; the lead can set it with hypothesis.edit">default, not chosen</span> : null}</> : 'no executable algorithm yet'}</span><span>· {h.reviews?.length || 0} reviews</span><span>· round {node?.round ?? '–'}</span><span>· {when(h.created_at)}</span></div>
          </article>); })}
        {placeholders.filter(p => p.status === 'pending').map(p => <div key={p.id} className="card" data-testid="placeholder"><div className="row"><Pill tone="agent">generating</Pill><span className="faint">{p.id}: the lead is recording this strategy</span></div></div>)}
      </> : <Empty>No proposal yet. Ask the lead for hypotheses in the conversation (/generate 3); each lands here with its mechanism, its stage and its review.</Empty>) : null}
      {sub === 'rounds' ? <Rounds rounds={data.rounds} /> : null}
      {sub === 'implementations' ? <Implementations campaignId={campaignId} /> : null}
      <AgentDesk campaignId={campaignId} role={sub === 'implementations' ? 'implementation_lead' : 'discussion_moderator'} />
    </div>
  );
}

function Rounds({ rounds }: { rounds: Record<string, unknown> }) {
  const list = (rounds.rounds || []) as Record<string, unknown>[];
  if (!list.length) return <Empty>No review round yet. The discussion moderator runs rounds when asked (/review H01).</Empty>;
  return <>{list.map((r, i) => <Section key={String(r.number || i)} title={`Round ${String(r.number || i + 1)}`}>
    <p className="small muted">{String((r.trigger as { text?: string })?.text || (r.trigger as { kind?: string })?.kind || '')}</p>
    {((r.people || r.assistants || []) as Record<string, unknown>[]).map((p, j) => <div key={j} className="small row"><Pill tone="agent">{String(p.role)}</Pill><span className="grow">{String(p.verdict || p.status || '')}</span></div>)}
    <details><summary className="small">details</summary><pre>{JSON.stringify(r, null, 1).slice(0, 4000)}</pre></details>
  </Section>)}</>;
}

function Implementations({ campaignId }: { campaignId: string }) {
  const catalog = useRead<{ versions: Record<string, unknown>[] }>(['implementations', campaignId], `/api/v1/implementations?campaign_id=${campaignId}`);
  if (catalog.isPending) return <Loading />;
  if (catalog.error) return <Failed error={catalog.error} />;
  const versions = catalog.data.versions || [];
  return <Section title={`Implementations (${versions.length})`}>{versions.length ? <table><thead><tr><th>Version</th><th>Name</th><th>Status</th><th>Validated</th></tr></thead><tbody>{versions.map(v => <tr key={String(v.id)}><td className="mono small">{String(v.id)}</td><td>{String(v.name || (v.spec as Record<string, unknown>)?.name || '')}</td><td><Pill tone={statusTone(String(v.status))}>{String(v.status)}</Pill></td><td>{String(v.validation_status || v.validated || 'unknown')}</td></tr>)}</tbody></table> : <Empty>No implementation yet. The implementation lead builds and validates code on request.</Empty>}</Section>;
}
