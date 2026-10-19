/** The strategy evolution graph (M2): frontier, lineage, curves, races. Until then: what is known from hypotheses and runs. */
import type { PageProps } from '../shell/StagePanel';
import { useExperiments, useHypotheses } from '../api/queries';
import { Empty, Failed, Loading, Pill, Section, num, statusTone } from '../primitives/ui';
import { formatHash } from '../router/routes';

export default function EvolutionPage({ campaignId, route }: PageProps) {
  const hypotheses = useHypotheses(campaignId);
  const experiments = useExperiments(campaignId);
  const sub = route.sub || 'frontier';
  const tabs = [['frontier', 'Frontier'], ['lineage', 'Lineage'], ['curves', 'Curves'], ['races', 'Races']] as const;
  if (hypotheses.isPending || experiments.isPending) return <Loading />;
  if (hypotheses.error || experiments.error) return <Failed error={hypotheses.error || experiments.error} />;
  const trials = [...experiments.data.long, ...experiments.data.short];
  const rows = hypotheses.data.hypotheses.map(h => {
    const mine = trials.filter(t => t.hypothesis_id === h.id);
    const best = mine.map(t => Number(((t.result || t.progress || {}) as Record<string, unknown>).best_objective ?? NaN)).filter(Number.isFinite);
    return { h, runs: mine.length, best: best.length ? Math.max(...best) : null };
  });
  return (
    <div className="col">
      <div className="stage-head"><h1>Evolution</h1><span className="muted small">frontier v0: the full graph (stages, lineage, interventions) arrives with M2</span></div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'evolution', sub: key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {sub === 'frontier' ? <Section title="Frontier">{rows.length ? <table><thead><tr><th>Strategy</th><th>Status</th><th>Runs</th><th>Best (measured)</th></tr></thead><tbody>{rows.map(({ h, runs, best }) => <tr key={h.id} data-record-id={h.id}><td>{h.title}</td><td><Pill tone={statusTone(h.status)}>{h.status}</Pill></td><td>{runs}</td><td>{num(best, 4)}</td></tr>)}</tbody></table> : <Empty>No strategy yet.</Empty>}</Section> : null}
      {sub !== 'frontier' ? <Empty>The {sub} view arrives with milestone M2.</Empty> : null}
    </div>
  );
}
