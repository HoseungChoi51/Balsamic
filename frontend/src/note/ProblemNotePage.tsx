/** The problem note (M1): objective, knobs, observables, noise, constraints, confounders, open questions; the charter it becomes. */
import type { PageProps } from '../shell/StagePanel';
import { useSummary } from '../api/queries';
import { Empty, Failed, Kv, Loading, Section } from '../primitives/ui';
import { Markdown } from '../chat/render/Markdown';

export default function ProblemNotePage({ campaignId, route }: PageProps) {
  const summary = useSummary(campaignId);
  if (summary.isPending) return <Loading />;
  if (summary.error) return <Failed error={summary.error} />;
  const { campaign, tasks, charter } = summary.data;
  return (
    <div className="col">
      <div className="stage-head"><h1>Problem note</h1></div>
      <Section title="Objective"><Markdown text={campaign.objective || '(no objective yet)'} thread={route.thread} /></Section>
      {tasks.length ? <Section title={`Problem instances (${tasks.length})`}>{tasks.map(t => <div key={String(t.id)} className="card"><Kv rows={[['Task', String(t.name)], ['Problem', String(t.problem_id || (t.problem as Record<string, unknown>)?.definition_id || '')], ['Split', String(t.split || 'development')]]} /></div>)}</Section>
        : <Empty>No problem instance yet. Describe the problem to the lead in the conversation; the structured note (knobs, observables, noise, constraints, confounders, open questions), its annotations and Adopt arrive with milestone M1.</Empty>}
      {charter ? <Section title="Charter"><Kv rows={[['Version', String(charter.version)], ['Recorded', String(charter.created_at || '')]]} /></Section> : null}
    </div>
  );
}
