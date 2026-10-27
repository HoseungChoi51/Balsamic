/** The draft the setup conversation fills, with Change and Create; the conversation itself is in the chat column. */
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { api } from '../api/client';
import { Kv, Pill, Section, duration, num } from '../primitives/ui';
import { navigate } from '../router/routes';
import { track } from '../telemetry/events';
import { useSetup } from './SetupChat';

export default function NewCampaign({ route }: PageProps) {
  const setupId = route.id;
  const setup = useSetup(setupId);
  const queryClient = useQueryClient();
  const d = (setup.data?.draft || {}) as Record<string, unknown>;
  const auto = (d.autopilot || null) as { enabled?: boolean; compute_cap_seconds?: number } | null;
  const field = setup.data?.step?.field;
  const edit = async (name: string) => { if (!setupId) return; const next = await api(`/api/v1/setup/${setupId}/edit`, { method: 'POST', body: JSON.stringify({ field: name }) }); queryClient.setQueryData(['setup', setupId], next); };
  const create = async () => {
    if (!setupId) return;
    const created = await api<{ campaign_id: string; thread_id: string }>(`/api/v1/setup/${setupId}/create`, { method: 'POST' });
    track('setup.create', {}); await queryClient.invalidateQueries({ queryKey: ['campaigns'] });
    navigate(`#t/${created.thread_id}/${d.problem_id ? 'hypotheses' : 'note'}`);
  };
  const row = (label: string, name: string, value: React.ReactNode) => [<span key={name} className="row"><span className="grow">{label}</span>{field === name ? <Pill tone="you">asking</Pill> : setupId && setup.data?.status === 'asking' ? <button className="btn quiet small" onClick={() => edit(name)} data-testid={`edit-${name}`}>change</button> : null}</span>, value] as [React.ReactNode, React.ReactNode];
  const complete = setup.data && (setup.data.step?.field === 'ready' || setup.data.status === 'ready');
  return (
    <div className="col">
      <div className="stage-head"><h1>New campaign</h1>{setup.data ? <Pill>{setup.data.status === 'created' ? 'created' : complete ? 'ready to create' : 'in conversation'}</Pill> : null}</div>
      <Section title="The draft, as the conversation fills it">
        <p className="small muted">Answer in the chat on the left: pick a choice or type. Every field can be changed before the campaign is created; only the name is required to be yours.</p>
        <Kv rows={[row('Name', 'name', d.name ? <>{String(d.name)} <span className="faint mono small">{String(d.identity)}</span></> : <span className="faint">not yet</span>),
          row('Question', 'objective', d.objective === undefined || d.objective === null ? <span className="faint">not yet</span> : d.objective ? String(d.objective) : <span className="muted">to be formulated with the lead</span>),
          row('Problem', 'problem', Array.isArray(d.decided) && (d.decided as string[]).includes('problem_id') ? (d.problem_id ? String(d.problem_id) : <span className="muted">formulate first</span>) : <span className="faint">not yet</span>),
          row('Budgets', 'budget', d.compute_budget_seconds != null ? <>{duration(d.compute_budget_seconds)} of worker time · {num(d.llm_budget_usd, 2, ' $')} · runs up to {duration(d.delegated_trial_seconds)}</> : <span className="faint">not yet</span>),
          row('Delegation', 'autonomy', d.autonomy ? String(d.autonomy) : <span className="faint">not yet</span>),
          row('Autopilot', 'autopilot', auto ? (auto.enabled ? `on, cap ${duration(auto.compute_cap_seconds)}` : 'off') : <span className="faint">not yet</span>)]} />
        <div className="row" style={{ marginTop: 8 }}><button className="btn primary" disabled={!complete || setup.data?.status === 'created'} onClick={create} data-testid="create-campaign">Create campaign</button>
          {!complete ? <span className="why">Finish the conversation first; the assistant asks what is still open.</span> : null}</div>
      </Section>
      <p className="why">Autopilot is off unless chosen; limits can be raised later only by you. The setup conversation becomes the first turns of the campaign's main thread.</p>
    </div>
  );
}
