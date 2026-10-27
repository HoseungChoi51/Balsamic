/** An experiment plan as the researcher reads it before approving: per run what it searches, its speed and the disk use of
 * each output file measured on an earlier run of the same problem, and what ends it. Computed by the workspace
 * (campaigns/experiment_plan.py), never written by an agent; what was not measured says so. */
import type { ExperimentPlan } from '../api/types';
import { Kv, duration } from '../primitives/ui';

export function bytes(value: number | null | undefined) {
  if (value === null || value === undefined) return 'not measured';
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} kB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(value < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

export function PlanCard({ plan }: { plan: ExperimentPlan }) {
  const { totals } = plan;
  return (
    <div className="plan" data-testid="plan-card">
      {plan.warnings.length ? <ul className="plan-warnings" data-testid="plan-warnings">{plan.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul> : null}
      {plan.runs.map((run, index) => (
        <section key={index} className="plan-run">
          <div className="row"><strong className="grow">{run.label}</strong>
            <span className="faint small">{run.seeds.length === 1 ? `seed ${run.seeds[0]}` : `${run.seeds.length} runs, seeds ${run.seeds.join(', ')}`}{run.device ? ` · ${run.device}` : ''}</span></div>
          <Kv rows={[
            ['Problem', `${run.task || run.task_id}${run.design ? ` (${run.design})` : ''}`],
            ['Each run', <>{duration(run.wall_seconds)}{run.max_evaluations ? `, at most ${run.max_evaluations.toLocaleString()} evaluations` : ''}</>],
            ['Speed', run.speed.seconds_per_evaluation !== null ? `${run.speed.seconds_per_evaluation.toFixed(run.speed.seconds_per_evaluation < 1 ? 2 : 1)} s per evaluation, ${run.speed.basis}` : run.speed.basis],
            ['Evaluations', run.evaluations.expected !== null ? `about ${run.evaluations.expected.toLocaleString()} per run, ended by ${run.evaluations.ends_by}` : 'unknown'],
            ['Writes', run.disk_bytes !== null ? `about ${bytes(run.disk_bytes)} per run` : 'not measured'],
          ]} />
          {run.outputs.length ? (
            <table className="small plan-outputs"><tbody>
              {run.outputs.map(output => <tr key={output.file}><td className="mono">{output.file}</td><td>{output.what}</td><td className="num">{bytes(output.bytes)}</td></tr>)}
              {run.other_bytes ? <tr><td className="mono">other files</td><td>frozen code, checkpoints, outputs</td><td className="num">{bytes(run.other_bytes)}</td></tr> : null}
            </tbody></table>) : null}
        </section>
      ))}
      <p className="small muted">In all: {totals.runs} run{totals.runs === 1 ? '' : 's'}, {duration(totals.worker_seconds)} of worker time
        {totals.disk_bytes !== null ? `, about ${bytes(totals.disk_bytes)} on disk` : ''}{totals.max_workers ? `; at most ${totals.max_workers} runs go at once on this server` : ''}.</p>
    </div>
  );
}
