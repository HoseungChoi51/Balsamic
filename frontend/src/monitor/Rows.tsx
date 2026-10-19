import type { Monitor } from '../api/types';
import { Kv, Pill, duration, num } from '../primitives/ui';

export function Rows({ monitor }: { monitor: Monitor }) {
  const { problem, budget, compute, agents, needs_you } = monitor.rows;
  const worker = (budget.worker || {}) as Record<string, unknown>;
  const llm = budget.llm as Record<string, unknown>;
  const admission = (compute.admission || null) as Record<string, unknown> | null;
  return (
    <div className="col" data-testid="monitor-rows">
      <div className="card"><h3>Problem</h3><Kv rows={[['Campaign', String(problem.name)], ['Tasks', String(problem.tasks)]]} /></div>
      <div className="card"><h3>Budget</h3>
        <Kv rows={[
          ['Worker time', worker.unavailable ? <span className="faint">{String(worker.unavailable)}</span> : <>{duration(worker.allocated_seconds ?? worker.used_seconds)} of {duration(worker.budget_seconds ?? worker.compute_budget_seconds)} allocated (measured)</>],
          ['Model spend', <>{num(llm.agent_charged_usd, 2, ' $')} charged{llm.cap_usd != null ? <> of {num(llm.cap_usd, 2, ' $')}</> : null}{Number(llm.implementation_committed_usd) ? <>, {num(llm.implementation_committed_usd, 2, ' $')} committed to implementations</> : null}</>],
        ]} />
      </div>
      <div className="card"><h3>Compute</h3>
        <Kv rows={[['Runs now', `${compute.busy} of ${compute.limit} workers`], ['Level', compute.level ? String(compute.level) : <span className="faint">unknown</span>],
          ['Waiting', admission ? String((admission.waiting as unknown[] | undefined)?.length ?? 0) : <span className="faint">admission not reported</span>]]} />
      </div>
      <div className="card"><h3>Agents</h3><div className="row"><Pill tone={agents.active ? 'agent' : ''}>{String(agents.status)}</Pill><span className="small">{String(agents.headline || '')}</span></div></div>
      <div className="card"><h3>Needs you</h3><Kv rows={[['Decisions', String(needs_you.decisions)], ['Issues', String(needs_you.issues)], ['Questions', String(needs_you.questions)]]} /></div>
    </div>
  );
}
