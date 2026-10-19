/** Hypotheses: every proposal with its mechanism, reviews and status; the review rounds; the implementations. */
import type { PageProps } from '../shell/StagePanel';
import { useHypotheses, useRead } from '../api/queries';
import type { Hypothesis } from '../api/types';
import { Empty, Failed, Kv, Loading, Pill, Section, statusTone, when } from '../primitives/ui';
import { formatHash, navigate } from '../router/routes';
import { useSelection } from '../stores/selection';
import { AgentDesk } from '../desks/AgentDesk';
import { Markdown } from '../chat/render/Markdown';

export default function HypothesesPage({ campaignId, route }: PageProps) {
  const hypotheses = useHypotheses(campaignId);
  const selection = useSelection();
  if (hypotheses.isPending) return <Loading what="Loading hypotheses" />;
  if (hypotheses.error) return <Failed error={hypotheses.error} />;
  const data = hypotheses.data;
  const labels = Object.fromEntries(data.aliases.map(a => [a.record_id, a.label]));
  const sub = route.sub || 'list';
  const tabs = [['list', 'Proposals'], ['rounds', 'Review rounds'], ['implementations', 'Implementations']] as const;
  const selected = route.id ? data.hypotheses.find(h => h.id === route.id) : null;
  return (
    <div className="col">
      <div className="stage-head"><h1>Hypotheses</h1><span className="muted small">{data.hypotheses.length} proposals</span></div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'hypotheses', sub: key === 'list' ? null : key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {selected ? <HypothesisCard hypothesis={selected} label={labels[selected.id]} thread={route.thread} back={formatHash({ page: 'hypotheses' }, route.thread)} /> : null}
      {sub === 'list' && !selected ? (data.hypotheses.length ? data.hypotheses.map(h => (
        <article key={h.id} className={'card' + (selection.id === h.id ? ' selected' : '')} data-record-id={h.id} data-testid="hypothesis" style={{ cursor: 'pointer' }}
          onClick={() => { selection.select(h.id); navigate(formatHash({ page: 'hypotheses', id: h.id, sel: h.id }, route.thread)); }}>
          <div className="row"><Pill>{labels[h.id] || h.id.slice(0, 14)}</Pill><strong className="grow">{h.title}</strong><Pill tone={statusTone(h.status)}>{h.status}</Pill>
            {h.readiness ? <Pill tone={h.readiness.eligible ? 'clear' : 'attention'} title={h.readiness.reason}>{h.readiness.state.replaceAll('_', ' ')}</Pill> : null}</div>
          <p className="small muted">{(h.mechanism || '').slice(0, 240)}</p>
          <div className="row small faint"><span>{h.algorithm || 'no executable algorithm yet'}</span><span>· {h.reviews?.length || 0} reviews</span><span>· {h.origin || 'origin unknown'}</span><span>· {when(h.created_at)}</span></div>
        </article>)) : <Empty>No proposal yet. Ask the lead for hypotheses in the conversation; each lands here with its mechanism and review.</Empty>) : null}
      {sub === 'rounds' ? <Rounds rounds={data.rounds} /> : null}
      {sub === 'implementations' ? <Implementations campaignId={campaignId} /> : null}
      <AgentDesk campaignId={campaignId} role={sub === 'implementations' ? 'implementation_lead' : 'discussion_moderator'} />
    </div>
  );
}

function HypothesisCard({ hypothesis: h, label, thread, back }: { hypothesis: Hypothesis; label?: string; thread: string | null; back: string }) {
  return (
    <article className="card selected" data-testid="hypothesis-card">
      <div className="row"><a href={back} className="small">← All</a><Pill>{label || h.id}</Pill><h2 className="grow">{h.title}</h2><Pill tone={statusTone(h.status)}>{h.status}</Pill></div>
      <Kv rows={[['Algorithm', h.algorithm || 'none yet'], ['Origin', h.origin || 'unknown'], ['Parents', h.parent_ids?.length ? h.parent_ids.join(', ') : 'root'], ['Readiness', h.readiness ? `${h.readiness.state}: ${h.readiness.reason || ''}` : 'not assessed']]} />
      <h3 style={{ marginTop: 8 }}>Mechanism</h3><Markdown text={h.mechanism || '(none)'} thread={thread} />
      <h3>Rationale</h3><Markdown text={h.rationale || '(none)'} thread={thread} />
      <h3>Reviews ({h.reviews?.length || 0})</h3>
      {h.reviews?.length ? h.reviews.map(r => <div key={r.id} className="card"><div className="row"><Pill tone="agent">{r.author}</Pill>{r.verdict ? <Pill tone={r.verdict === 'test' ? 'clear' : 'attention'}>{r.verdict}</Pill> : null}<span className="faint small">{when(r.created_at)}</span></div><Markdown text={r.text} thread={thread} /></div>) : <Empty>No review yet.</Empty>}
    </article>
  );
}

function Rounds({ rounds }: { rounds: Record<string, unknown> }) {
  const list = (rounds.rounds || rounds.discussions || []) as Record<string, unknown>[];
  if (!list.length) return <Empty>No review round yet. The discussion moderator runs rounds when asked.</Empty>;
  return <>{list.map((r, i) => <Section key={String(r.id || i)} title={String(r.title || r.question || `Round ${i + 1}`)}><pre style={{ maxHeight: 280 }}>{JSON.stringify(r, null, 1).slice(0, 4000)}</pre></Section>)}</>;
}

function Implementations({ campaignId }: { campaignId: string }) {
  const catalog = useRead<{ versions: Record<string, unknown>[]; candidates?: Record<string, Record<string, unknown>> }>(['implementations', campaignId], `/api/v1/implementations?campaign_id=${campaignId}`);
  if (catalog.isPending) return <Loading />;
  if (catalog.error) return <Failed error={catalog.error} />;
  const versions = catalog.data.versions || [];
  return <Section title={`Implementations (${versions.length})`}>{versions.length ? <table><thead><tr><th>Version</th><th>Name</th><th>Status</th><th>Validated</th></tr></thead><tbody>{versions.map(v => <tr key={String(v.id)}><td className="mono small">{String(v.id)}</td><td>{String(v.name || (v.spec as Record<string, unknown>)?.name || '')}</td><td><Pill tone={statusTone(String(v.status))}>{String(v.status)}</Pill></td><td>{String(v.validation_status || v.validated || 'unknown')}</td></tr>)}</tbody></table> : <Empty>No implementation yet. The implementation lead builds and validates code on request.</Empty>}</Section>;
}
