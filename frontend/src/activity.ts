import type { Json, State } from './api';

const atWork = (agent: Json) => ['queued', 'running'].includes(agent.status);

/** What is running in the campaign now, by the page that shows it. */
export function campaignActivity(state: State) {
  const team: Json[] = state.agent_runtime?.agents || [];
  return {
    experiments: state.trials.filter(trial => ['queued', 'running', 'pausing'].includes(trial.status)).length,
    // The moderator, the specialists and the reviewers: the agents whose work is on the Hypotheses page.
    reviewing: team.some(agent => atWork(agent) && !['lead', 'experiment_operator', 'results_analyst'].includes(agent.role) && !agent.role.startsWith('implementation_')),
    operating: team.some(agent => atWork(agent) && agent.role === 'experiment_operator'),
    implementing: team.some(agent => atWork(agent) && agent.role.startsWith('implementation_')),
    writing: (state.report_writer_jobs || []).some((job: Json) => ['running', 'awaiting_focus'].includes(job.status)),
    decisions: state.decisions.filter(decision => decision.status === 'pending').length,
  };
}
