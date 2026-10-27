/** One strategy: the card with its lineage, reviews, runs, race cell, implementation and provenance; Open in graph, Trace origin, Discuss. */
import { useState } from 'react';
import { useRead } from '../api/queries';
import { FAMILY, type HypothesisCard as Card } from '../api/evolution';
import { Failed, Kv, Loading, Pill, Section, duration, num, statusTone, when } from '../primitives/ui';
import { Markdown } from '../chat/render/Markdown';
import { Curve } from '../primitives/charts';
import { TraceOrigin } from '../evolution/TraceOrigin';
import { formatHash, navigate } from '../router/routes';
import { STAGE_TONE } from '../evolution/EvolutionPage';

export function HypothesisCard({ id, thread, back, onDiscuss }: { id: string; thread: string | null; back: string; onDiscuss?: (id: string, title: string) => void }) {
  const card = useRead<Card>(['hypothesis', id], `/api/v1/hypotheses/${id}`, { refetchInterval: 8000 });
  const [trace, setTrace] = useState(false);
  if (card.isPending) return <Loading what="Loading the strategy" />;
  if (card.error) return <Failed error={card.error} />;
  const { hypothesis: h, ledger_row: row, parents, children, reviews, trials, implementation, race_cells, rounds } = card.data;
  const title = String(h.title);
  return (
    <article className="card selected" data-testid="hypothesis-card" data-record-id={id}>
      <div className="row wrap"><a href={back} className="small">← All</a>{row?.label ? <Pill>{row.label}</Pill> : null}<h2 className="grow">{title}</h2>
        {row ? <Pill tone={STAGE_TONE[row.stage]} title={row.stop_reason || row.stage}>{row.stage}</Pill> : null}<Pill tone={statusTone(String(h.status))}>{String(h.status)}</Pill>
        {row?.autonomous ? <Pill tone="agent">autopilot</Pill> : null}</div>
      <div className="row wrap" style={{ margin: '6px 0' }}>
        <button className="btn small" onClick={() => navigate(formatHash({ page: 'evolution', sub: 'lineage', sel: id }, thread))} data-testid="open-in-graph">Open in graph</button>
        <button className="btn small" onClick={() => setTrace(true)} data-testid="trace-origin-button">Trace origin</button>
        {onDiscuss ? <button className="btn small" onClick={() => onDiscuss(id, title)} data-testid="discuss">Discuss in a branch</button> : null}
      </div>
      {row?.stop_reason ? <p className="pill attention">Stopped: {row.stop_reason}</p> : null}
      <Kv rows={[['Family', h.family ? FAMILY[String(h.family)] || String(h.family) : 'not stated'], ['Algorithm', h.algorithm === 'unchosen' ? 'none chosen yet: it cannot run until one is' : String(h.algorithm || 'none yet')], ['Origin', `${String(h.origin || 'unknown')}${row?.actor ? ` (${row.actor})` : ''}`], ['Round', row?.round ?? 'unassigned'],
        ['Parents', parents.length ? parents.map(p => <a key={p.id} href={formatHash({ page: 'hypotheses', id: p.id, sel: p.id }, thread)}>{p.title} </a>) : 'root'],
        ['Children', children.length ? children.map(c => <a key={c.id} href={formatHash({ page: 'hypotheses', id: c.id, sel: c.id }, thread)}>{c.title} </a>) : 'none'],
        ['Best (measured)', row ? num(row.best.score, 5) : 'unknown'], ['Worker time', row ? <>{duration(row.worker_seconds)} of {duration(row.allotted_seconds)}</> : 'unknown'],
        ['Review', <Approval h={h} thread={thread} review={row?.review} />],
        ['Implementation', implementation.runnable ? 'runnable' : `not runnable: ${implementation.reason || implementation.state || 'unknown'}`],
        ['Race', race_cells ? `${race_cells.race_id} · ${race_cells.configuration_id} · ${race_cells.status}${race_cells.latest_decision ? ` · last: ${race_cells.latest_decision.action}` : ''}` : 'not in a race'],
        ['Confirmation', row?.confirmation ? `${row.confirmation.status}${row.confirmation.promising != null ? (row.confirmation.promising ? ', promising' : ', not promising') : ''}` : 'none']]} />
      <h3 style={{ marginTop: 8 }}>Mechanism</h3><Markdown text={String(h.mechanism || '(none)')} thread={thread} />
      <h3>Rationale</h3><Markdown text={String(h.rationale || '(none)')} thread={thread} />
      {row?.curve?.length ? <><h3>Best run's curve</h3><Curve points={row.curve} height={90} label={title} /></> : null}
      <h3>Runs ({trials.length})</h3>
      {trials.length ? <table><thead><tr><th>Run</th><th>Status</th><th>Seed</th><th>Time</th><th>Started</th></tr></thead><tbody>{trials.map(t => <tr key={t.id}><td><a href={formatHash({ page: 'experiments', id: t.id }, thread)} className="mono small">{t.id}</a>{t.race_phase ? <Pill> {t.race_phase}</Pill> : null}</td><td><Pill tone={statusTone(t.status)}>{t.status}</Pill></td><td>{t.seed}</td><td>{duration(t.execution_seconds)} of {duration(t.wall_seconds)}</td><td className="small faint">{when(t.created_at)}</td></tr>)}</tbody></table> : <p className="faint small">No run yet.</p>}
      <h3>Reviews ({reviews.length})</h3>
      {reviews.length ? reviews.map(r => <div key={r.id} className="card"><div className="row"><Pill tone="agent">{r.author}</Pill>{r.verdict ? <Pill tone={r.verdict === 'test' ? 'clear' : 'attention'}>{r.verdict}</Pill> : null}<span className="faint small">{when(r.created_at)}</span></div><Markdown text={r.text} thread={thread} /></div>) : <p className="faint small">No review yet.</p>}
      {rounds.length ? <><h3>Review rounds</h3>{rounds.map((r, i) => <details key={i} className="card"><summary className="small">{String(r.title || r.question || `round ${i + 1}`)}</summary><pre>{JSON.stringify(r, null, 1).slice(0, 3000)}</pre></details>)}</> : null}
      <details><summary className="small">Record</summary><pre>{JSON.stringify(h, null, 1).slice(0, 6000)}</pre></details>
      {trace ? <TraceOrigin recordId={id} thread={thread} onClose={() => setTrace(false)} /> : null}
    </article>
  );
}

export function Section_({ title, children }: { title: string; children: React.ReactNode }) { return <Section title={title}>{children}</Section>; }

/** Why the proposal needs no concept review: the researcher's message that asked for it, the go-ahead of a plan that named it, or both. */
function Approval({ h, thread, review }: { h: Record<string, unknown>; thread: string | null; review?: { readiness: { state: string } } }) {
  const asked = h.requested_by as { thread_id: string; message_id: string } | undefined;
  const approved = h.approved_by as { decision_id: string } | undefined;
  if (!asked && !approved) return <>{review ? review.readiness.state.replaceAll('_', ' ') : 'not required'}</>;
  return <span className="row wrap" style={{ gap: 6 }}>
    {asked ? <span data-testid="asked-for"><Pill tone="clear">asked for</Pill> <a href={formatHash({ page: 'chat', sel: asked.message_id }, asked.thread_id)}>your message</a></span> : null}
    {approved ? <span data-testid="approved"><Pill tone="clear">approved</Pill> <a href={formatHash({ page: 'inbox', id: approved.decision_id }, thread)}>your go-ahead</a></span> : null}
    <span className="faint small">no concept review needed</span></span>;
}
