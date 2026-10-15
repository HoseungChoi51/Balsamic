import { useState } from 'react';
import { activeStatuses, best, objectiveValue, seconds } from './api';
import type { Json, State } from './api';
import { api, errorText } from './api';
import { Badge, ErrorNotice, Modal, Panel } from './ui';
import { CharterSummary } from './problemSetup';
import type { WorkspaceActions } from './views';
import { CharterHistory } from './views';
import { EvaluatorRequest } from './evaluatorForms';
import type { Task } from './api';
import { ReadableText } from './readableText';
import { campaignActivity } from './activity';
import { ManagerIssues } from './implementations';

type Props = { state: State; actions: WorkspaceActions };


export function GeneralOverview({ state, actions }: Props) {
  const active = state.trials.filter(t => activeStatuses.includes(t.status)), now = campaignActivity(state);
  const issues = (state.manager_issues || []).filter((issue: Json) => issue.status === 'pending').length;
  return <>
    <div className="page-heading"><div><span className="eyebrow">Research campaign</span><h1>{state.campaign?.name}</h1><ReadableText text={state.campaign?.objective} preview={2} />
      <a className="overview-problem-link" href="#problem">The problem in full</a></div></div>
    <Panel title="Now"><div className="overview-activity"><ul className="overview-now">
      {now.decisions > 0 && <li><a href="#decisions">{now.decisions} {now.decisions === 1 ? 'decision waits' : 'decisions wait'} for you</a></li>}
      {now.experiments > 0 && <li><a href="#experiments">{now.experiments} {now.experiments === 1 ? 'experiment' : 'experiments'} running</a></li>}
      {now.reviewing && <li><a href="#hypotheses/rounds">Agents are reviewing proposals</a></li>}
      {now.implementing && <li><a href="#implementations">An implementation is being built</a></li>}
      {now.writing && <li><a href="#reports">A report is being written</a></li>}
      {!now.decisions && !now.experiments && !now.reviewing && !now.implementing && !now.writing && <li>Nothing is running.</li>}
    </ul>
      <p>{active.length} active experiments · {state.hypotheses.length} proposals · {state.trials.length} experiments in all</p>
      <p>{seconds(state.budget?.spent_seconds || 0)} of {seconds(state.campaign?.compute_budget_seconds)} compute{state.campaign?.llm_budget_usd ? ` · $${Number(state.budget?.llm_spent_usd ?? state.campaign.llm_used_usd ?? 0).toFixed(2)} of $${Number(state.campaign.llm_budget_usd).toFixed(2)} for models` : ''}</p></div></Panel>
    <Panel title="Objective by problem instance"><div className="configuration-grid">{state.tasks.map(task => {
      const objective = task.problem?.primary_objective;
      const measured = state.trials.filter(t => t.task_id === task.id && !t.diagnostic_grant_id && !t.recipe && best(t) !== undefined);
      const values = measured.map(t => best(t)!);
      const value = values.length ? (objective?.direction === 'minimize' ? Math.min(...values) : Math.max(...values)) : undefined;
      return <article className="configuration-card" key={task.id}><h3>{task.name}</h3><p>{objective?.direction} {objective?.name}</p>
        <strong>{objectiveValue(value, objective)}</strong><p>{objective?.units}</p><span className="help-text">Best observed value · validation evidence is separate</span></article>;
    })}</div></Panel>
    {issues > 0 && <details className="overview-issues"><summary>{issues} open {issues === 1 ? 'issue' : 'issues'}: failed experiments and blocked operations</summary>
      <ManagerIssues state={state} refresh={actions.refresh} discuss={message => void actions.research(message, 'discuss')} /></details>}
  </>;
}

export function GeneralProblem({ state, actions }: Props) {
  const [selected, setSelected] = useState<Json | null>(null);
  const [commissioning, setCommissioning] = useState<Task | null>(null);
  const [history, setHistory] = useState(false), [error, setError] = useState('');
  const charter = state.campaign?.charter;
  // The problem is revised through its charter; a campaign made before charters gets one from its instances.
  async function revise() {
    try { location.hash = `new/${charter ? charter.id : (await api('/api/v1/problem-charters/for-campaign', { campaign_id: state.campaign!.id })).id}`; }
    catch (e) { setError(errorText(e)); }
  }
  return <><div className="page-heading"><div><span className="eyebrow">Problem</span><h1>A shared definition of success.</h1>
    {state.campaign?.research_question ? <><h2 className="problem-question-label">Research question</h2><ReadableText text={state.campaign.research_question} /></> : !charter && <ReadableText text={state.campaign?.objective} />}</div>
    <div className="inline-actions"><button className="button secondary" onClick={() => setHistory(true)}>Revision history</button>
      <button className="button secondary" onClick={() => actions.campaign(true)}>Campaign settings</button>
      <button className="button primary" onClick={() => void revise()}>Revise the problem</button></div></div>
    <ErrorNotice text={error} />
    {charter && <CharterSummary charterId={charter.id} onRevise={() => void revise()} />}
    <Panel title="Problem instances"><div className="configuration-grid">{state.tasks.map(task => <article className="configuration-card" key={task.id}>
      <div className="row-between"><Badge>{task.split}</Badge><span>{task.problem?.candidate_schema.representation}</span></div><h3>{task.name}</h3>
      <p>{task.problem?.primary_objective.direction} <strong>{task.problem?.primary_objective.name}</strong> · {task.problem?.primary_objective.units}</p>
      <p>{task.problem?.candidate_schema.dimensions} dimensions · {task.problem?.candidate_schema.constraints?.length || 0} explicit constraints</p>
      {task.evaluator_readiness && <p className={task.evaluator_readiness.runnable ? 'help-text' : 'callout amber'}>{task.evaluator_readiness.reason}</p>}
      <div className="inline-actions"><button className="button small secondary" onClick={() => setSelected(task)}>Inspect definition</button>
        {task.evaluator_manifest && !task.evaluator_version_id && <button className="button small secondary" onClick={() => setCommissioning(task)}>Build or reuse evaluator</button>}
        {task.evaluator_version_id && task.evaluator_readiness?.state !== 'ready' && <button className="button small secondary" onClick={() => actions.navigate('validation')}>Review evaluator evidence</button>}</div></article>)}</div></Panel>
    <p className="help-text">The studies that froze this problem's scope are on <a href="#studies">Studies</a>.</p>
    {selected && <Modal title={selected.name} description="Resolved scientific definition, feasibility constraints, and evaluator fidelity." onClose={() => setSelected(null)}>
      <pre>{JSON.stringify(selected.problem, null, 2)}</pre></Modal>}
    {history && state.campaign && <CharterHistory campaignId={state.campaign.id} onClose={() => setHistory(false)} />}
    {commissioning && <EvaluatorRequest task={commissioning} state={state} onClose={() => setCommissioning(null)} onDone={() => { void actions.refresh(); }} />}</>;
}

