/** Experiments: short runs, long runs and checks, drafts, the rules; one run's log with its curve. The operator's desk lives here. */
import type { PageProps } from '../shell/StagePanel';
import { useExperiments, useRead } from '../api/queries';
import type { Trial } from '../api/types';
import { Empty, Failed, Kv, Loading, Pill, Section, duration, num, statusTone, when } from '../primitives/ui';
import { Curve } from '../primitives/charts';
import { formatHash, navigate } from '../router/routes';
import { useSelection } from '../stores/selection';
import { TraceOrigin } from '../evolution/TraceOrigin';
import { Markdown } from '../chat/render/Markdown';
import { PlanCard } from './PlanCard';
import type { ExperimentPlan } from '../api/types';
import { useState } from 'react';

const STATUS_WORDS: Record<string, string> = { stopped: 'stopped (by request, not failed)', failed: 'failed', completed: 'completed', running: 'running', queued: 'queued', paused: 'paused' };

function score(trial: Trial) {
  const result = (trial.result || trial.progress || {}) as Record<string, unknown>;
  return result.best_objective ?? result.best_efficiency ?? result.best_score ?? null;
}

export default function ExperimentsPage({ campaignId, route }: PageProps) {
  const experiments = useExperiments(campaignId);
  const selection = useSelection();
  if (experiments.isPending) return <Loading what="Loading experiments" />;
  if (experiments.error) return <Failed error={experiments.error} />;
  const data = experiments.data;
  if (route.id && !route.sub) return <ExperimentLog trialId={route.id} campaignId={campaignId} back={formatHash({ page: 'experiments' }, route.thread)} />;
  const sub = route.sub || 'runs';
  const tabs = [['runs', 'Runs'], ['checks', 'Checks'], ['drafts', 'Drafts'], ['rules', 'Rules']] as const;
  const table = (all: Trial[], title: string) => {
    const rows = all.filter(t => !t.hidden), hidden = all.length - rows.length;
    return (
    <Section title={`${title} (${rows.length}${hidden ? `, ${hidden} hidden` : ''})`}>
      {rows.length ? <table><thead><tr><th>Run</th><th>Algorithm</th><th>Status</th><th>Best</th><th>Evaluations</th><th>Time</th><th>Started</th></tr></thead><tbody>
        {rows.map(t => (
          <tr key={t.id} className={selection.id === t.id ? 'selected' : ''} data-record-id={t.id} style={{ cursor: 'pointer' }} onClick={() => { selection.select(t.id); navigate(formatHash({ page: 'experiments', id: t.id, sel: t.id }, route.thread)); }}>
            <td className="mono small">{t.id}</td><td>{t.algorithm}</td><td><Pill tone={statusTone(t.status)} title={STATUS_WORDS[t.status] || t.status}>{t.status}</Pill></td>
            <td>{num(score(t), 4)}</td><td>{num((t.result as Record<string, unknown> | undefined)?.evaluations ?? (t.progress as Record<string, unknown> | undefined)?.evaluations, 0)}</td><td>{duration(t.wall_seconds)}</td><td className="small faint">{when(t.created_at)}</td>
          </tr>))}
      </tbody></table> : <Empty>{hidden ? 'All hidden.' : 'None yet.'}</Empty>}
    </Section>
    );
  };
  return (
    <div className="col">
      <div className="stage-head"><h1>Experiments</h1></div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'experiments', sub: key === 'runs' ? null : key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {sub === 'runs' ? <>{table(data.long, 'Long runs')}{table(data.short, 'Short runs')}</> : null}
      {sub === 'checks' ? table(data.checks, 'Checks: validations, recipes, speed probes') : null}
      {sub === 'drafts' && route.id ? <DraftView draftId={route.id} thread={route.thread} back={formatHash({ page: 'experiments', sub: 'drafts' }, route.thread)} /> : null}
      {sub === 'drafts' ? <Section title={`Drafts (${data.drafts.length})`}>{data.drafts.length ? data.drafts.map(d => (
        <a key={String(d.id)} href={formatHash({ page: 'experiments', sub: 'drafts', id: String(d.id) }, route.thread)} className={'card row draft-row' + (route.id === d.id ? ' selected' : '')} data-testid="draft-row">
          <strong className="grow">{String(d.title || d.id)}</strong><Pill>{String(d.status || 'draft')}</Pill><span className="small faint">open the plan</span></a>))
        : <Empty>No draft waits to be started.</Empty>}</Section> : null}
      {sub === 'rules' ? <Section title="Experiment rules"><Kv rows={Object.entries(data.rules).filter(([k]) => !['id', 'campaign_id'].includes(k)).map(([k, v]) => [k.replaceAll('_', ' '), typeof v === 'object' ? JSON.stringify(v) : String(v)])} /><p className="why">The experiment operator changes these on request (experiments.rules).</p></Section> : null}
    </div>
  );
}

function ExperimentLog({ trialId, campaignId, back }: { trialId: string; campaignId: string; back: string }) {
  const record = useRead<{ trial: Trial; chain_trial_ids: string[]; validations: Record<string, unknown>[]; race: { race_id: string } | null }>(['experiment', trialId], `/api/v1/experiments/${trialId}`, { refetchInterval: 5000 });
  const [trace, setTrace] = useState(false);
  const metrics = useRead<Record<string, unknown>[]>(['metrics', trialId], `/api/v1/experiments/${trialId}/metrics?points=200`, { refetchInterval: 5000 });
  const logs = useRead<{ text: string }>(['logs', trialId], `/api/v1/experiments/${trialId}/logs`, { refetchInterval: 10000 });
  if (record.isPending) return <Loading what="Loading the run" />;
  if (record.error) return <Failed error={record.error} />;
  const trial = record.data.trial;
  const points = (metrics.data || []).map((row, i) => ({ x: Number(row.evaluations ?? row.step ?? i), y: Number(row.best_objective ?? row.best_efficiency ?? row.best ?? row.score ?? NaN) })).filter(p => Number.isFinite(p.y));
  return (
    <div className="col">
      <div className="stage-head"><a href={back} className="small">← Experiments</a><h1 className="mono">{trialId}</h1><Pill tone={statusTone(trial.status)}>{STATUS_WORDS[trial.status] || trial.status}</Pill>
        <button className="btn small" onClick={() => setTrace(true)} data-testid="trace-origin-button">Trace origin</button>
        {trial.hypothesis_id ? <a className="btn small" href={`#evolution/lineage?sel=${trial.hypothesis_id}`}>Open in graph</a> : null}</div>
      {trace ? <TraceOrigin recordId={trialId} thread={null} onClose={() => setTrace(false)} /> : null}
      <Section title="Run"><Kv rows={[['Algorithm', trial.algorithm], ['Kind', record.data.chain_trial_ids.length > 1 ? 'one run continued over ' + record.data.chain_trial_ids.length + ' parts' : 'single run'], ['Task', String(trial.task_id)], ['Seed', String(trial.seed ?? '')], ['Budget', <>{num(trial.max_steps, 0)} evaluations, {duration(trial.wall_seconds)}</>],
        ['Best (measured)', num(score(trial), 5)], ['Chain', record.data.chain_trial_ids.length > 1 ? record.data.chain_trial_ids.join(' → ') : 'single run'], ['Race', record.data.race ? record.data.race.race_id : 'not in a race'],
        ['Hypothesis', trial.hypothesis_id ? String(trial.hypothesis_id) : <span className="faint">none</span>], ['Campaign', campaignId]]} /></Section>
      <Section title="Score curve" right={<span className="small faint">{points.length} points, measured</span>}><Curve points={points} label="best score over evaluations" /></Section>
      <Section title="Checks">{record.data.validations.length ? record.data.validations.map(v => <div key={String(v.id)} className="row small"><Pill>{String(v.verdict || v.status)}</Pill><span>{String(v.kind || v.recipe_id || '')}</span></div>) : <Empty>No validation ran on this run.</Empty>}</Section>
      <Section title="Worker log (tail)"><pre style={{ maxHeight: 300 }}>{logs.data?.text || '(empty)'}</pre></Section>
    </div>
  );
}

/** A draft is an experiment plan: what it asks, whether it can start and what blocks it, and the plan computed from the records. */
function DraftView({ draftId, thread, back }: { draftId: string; thread: string | null; back: string }) {
  type Blocker = { code: string; message: string };
  const draft = useRead<{ draft: Record<string, unknown> & { procedure: Record<string, unknown>; title: string; revision: number }; readiness: { ready: boolean; blockers: Blocker[]; waiting_for?: Blocker[] }; plan: ExperimentPlan }>(['draft', draftId], `/api/v1/drafts/${draftId}`);
  if (draft.isPending) return <Loading what="Loading the plan" />;
  if (draft.error) return <Failed error={draft.error} />;
  const { procedure } = draft.data.draft;
  const { readiness, plan } = draft.data;
  return (
    <article className="card" data-testid="draft-view">
      <div className="row"><h2 className="grow">{draft.data.draft.title}</h2><span className="faint small">revision {draft.data.draft.revision}</span><a className="btn quiet small" href={back}>Close</a></div>
      {procedure.question ? <Markdown text={String(procedure.question)} thread={thread} /> : <p className="faint small">The draft does not say what it asks.</p>}
      {readiness.ready ? <p><Pill tone="clear">ready to start</Pill></p> : (
        <div data-testid="draft-blockers"><Pill tone="attention">cannot start yet</Pill>
          <ul className="small">{readiness.blockers.map(blocker => <li key={blocker.code}>{blocker.message}</li>)}</ul></div>)}
      <PlanCard plan={plan} />
    </article>
  );
}
