import type { Monitor } from '../api/types';
import { Kv, Pill, duration, num } from '../primitives/ui';

export function Rows({ monitor }: { monitor: Monitor }) {
  const { problem, budget, compute, agents, needs_you } = monitor.rows;
  const worker = (budget.worker || {}) as Record<string, unknown>;
  const llm = budget.llm as Record<string, unknown>;
  const autopilot = (monitor.rows as unknown as { autopilot?: Record<string, unknown> }).autopilot;
  return (
    <div className="col" data-testid="monitor-rows">
      <div className="card"><h3>Problem</h3><Kv rows={[['Campaign', String(problem.name)], ['Tasks', String(problem.tasks)]]} /></div>
      <div className="card"><h3>Budget</h3>
        <Kv rows={[
          ['Worker time', worker.unavailable ? <span className="faint">{String(worker.unavailable)}</span> : <>{duration(worker.actual_seconds)} used, {duration(worker.allocated_seconds)} allocated of {duration(worker.budget_seconds)} (measured)</>],
          ['Forecast', worker.forecast_seconds != null ? <>{duration(worker.forecast_seconds)} <span className="faint">forecast: {String(worker.forecast_basis)}</span></> : <span className="faint">unknown</span>],
          ['Model spend', <>{num(llm.agent_charged_usd, 2, ' $')} charged{llm.cap_usd != null ? <> of {num(llm.cap_usd, 2, ' $')}</> : null}{Number(llm.implementation_committed_usd) ? <>, {num(llm.implementation_committed_usd, 2, ' $')} committed to implementations</> : null}</>],
        ]} />
      </div>
      <div className="card"><h3>Compute</h3>
        <Kv rows={[['Runs now', `${compute.busy} of ${compute.limit} workers`], ['Queued', compute.queued != null ? String(compute.queued) : <span className="faint">admission not reported</span>], ['Level', compute.level ? String(compute.level) : <span className="faint">unknown</span>],
          ['GPU', gpu(compute.gpu as Record<string, unknown> | undefined)]]} />
      </div>
      <div className="card"><h3>Agents</h3><div className="row"><Pill tone={agents.active ? 'agent' : ''}>{String(agents.status)}</Pill><span className="small">{String(agents.headline || '')}</span></div></div>
      <div className="card"><h3>Autopilot</h3>{autopilot?.enabled ? <Kv rows={[['State', String(autopilot.reason)], ['Spent of cap', `${duration(autopilot.spent_seconds)} of ${duration((autopilot.settings as Record<string, unknown>)?.compute_cap_seconds)}`], ['Rounds', String(autopilot.rounds_completed)]]} /> : <p className="small muted">Off: the lead acts on your requests.</p>}</div>
      <div className="card"><h3>Needs you</h3><Kv rows={[['Decisions', String(needs_you.decisions)], ['Issues', String(needs_you.issues)], ['Questions', String(needs_you.questions)]]} /></div>
    </div>
  );
}

function gpu(row: Record<string, unknown> | undefined) {
  if (!row || !row.reported) return <span className="faint">{String(row?.basis || 'not reported')}</span>;
  if (!row.measured) return <span className="faint">{String(row.devices)} device(s), {String(row.basis)}</span>;
  return <>{row.busy ? 'busy' : 'idle'} · {String(row.utilization_percent)} % · {(Number(row.memory_used_bytes) / 2 ** 30).toFixed(1)} of {(Number(row.memory_total_bytes) / 2 ** 30).toFixed(1)} GiB <span className="faint">({String(row.basis)})</span></>;
}
