/** The desk of the agent in charge of a page: its state, and a line to write to it. Requests only; it starts nothing else. */
import { useQueryClient } from '@tanstack/react-query';
import { useRead, useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Composer } from '../chat/Composer';
import { Pill, statusTone } from '../primitives/ui';

const NAMES: Record<string, string> = { discussion_moderator: 'Discussion moderator', experiment_operator: 'Experiment operator', implementation_lead: 'Implementation lead', resource_planner: 'Resource planner' };

export function AgentDesk({ campaignId, role }: { campaignId: string; role: string }) {
  const queryClient = useQueryClient();
  const summary = useSummary(campaignId);
  const team = useRead<{ configuration: { enabled: boolean } | null; agents: { id: string; role: string; status: string; activity?: string; model?: string }[] }>(['agents', campaignId], `/api/v1/campaigns/${campaignId}/agents`);
  const agent = team.data?.agents.find(a => a.role === role);
  const enabled = !!team.data?.configuration?.enabled;
  const ask = async (text: string) => {
    const campaign = summary.data?.campaign; if (!campaign) throw new Error('The campaign is still loading');
    if (!enabled) await send({ operation: 'agent.activate', campaignId, expectedRevision: campaign.version, payload: {} });
    await send({ operation: 'agent.message', campaignId, expectedRevision: campaign.version, payload: { page_agent: role, message: text } });
    await queryClient.invalidateQueries({ queryKey: ['agents', campaignId] });
  };
  return (
    <details className="card" data-testid={`desk-${role}`}>
      <summary className="row"><strong className="grow">{NAMES[role] || role}</strong>{agent ? <Pill tone={statusTone(agent.status)}>{agent.status}</Pill> : <Pill>not started</Pill>}</summary>
      <p className="small muted">{agent?.activity || 'Takes requests from you and from the lead on this page, and acts on nothing else.'}</p>
      <Composer onSend={ask} placeholder={`Ask the ${(NAMES[role] || role).toLowerCase()}…`} />
    </details>
  );
}
