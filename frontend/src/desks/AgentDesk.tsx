/** The desk of the agent in charge of a page: its conversation with you, and a line to write to it. Requests only; it starts nothing else.
 *  Docked at the bottom of its page, or filling the chat column while the lead's chat is detached. */
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRead, useSummary } from '../api/queries';
import type { Message, Question } from '../api/types';
import { ExtensionDialog } from '../chat/ExtensionDialog';
import { send } from '../commands/bus';
import { Composer } from '../chat/Composer';
import { Markdown } from '../chat/render/Markdown';
import { Pill, statusTone, when } from '../primitives/ui';
import catalog from '../router/pages.json';
import type { Route } from '../router/routes';

const NAMES: Record<string, string> = { discussion_moderator: 'Discussion moderator', experiment_operator: 'Experiment operator', implementation_lead: 'Implementation lead', resource_planner: 'Resource planner' };
const AGENTS = catalog.agents as Record<string, string>;
const DOCK_OPEN = 'balsamic.deskOpen';

/** The page agent whose page the route shows: the most specific address wins (hypotheses/implementations before hypotheses). */
export function deskRole(route: Pick<Route, 'page' | 'sub'>): string | null {
  const address = route.sub ? `${route.page}/${route.sub}` : route.page;
  const exact = Object.entries(AGENTS).find(([, page]) => page === address);
  if (exact) return exact[0];
  const byPage = Object.entries(AGENTS).find(([, page]) => page === route.page);
  return byPage ? byPage[0] : null;
}

interface Desk { role: string; page: string; agent: { id: string; status: string; activity?: string; model?: string } | null; messages: Message[]; truncated: boolean; dialogs?: Question[] }

export function DeskPanel({ campaignId, role, mode }: { campaignId: string; role: string; mode: 'docked' | 'column' }) {
  const queryClient = useQueryClient();
  const summary = useSummary(campaignId);
  const desk = useRead<Desk>(['desk', campaignId, role], `/api/v1/campaigns/${campaignId}/desks/${role}`, { refetchInterval: 5000 });
  const team = useRead<{ configuration: { enabled: boolean } | null }>(['agents', campaignId], `/api/v1/campaigns/${campaignId}/agents`);
  const [open, setOpen] = useState(() => { try { return mode === 'column' || localStorage.getItem(DOCK_OPEN) === '1'; } catch { return mode === 'column'; } });
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { if (mode === 'docked') { try { localStorage.setItem(DOCK_OPEN, open ? '1' : '0'); } catch { /* private mode */ } } }, [open, mode]);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [desk.data?.messages.length, open]);
  const agent = desk.data?.agent;
  const enabled = !!team.data?.configuration?.enabled;
  const name = NAMES[role] || role.replaceAll('_', ' ');
  const busy = agent?.status === 'running' || agent?.status === 'queued';
  const ask = async (text: string) => {
    const campaign = summary.data?.campaign; if (!campaign) throw new Error('The campaign is still loading');
    if (!enabled) await send({ operation: 'agent.activate', campaignId, expectedRevision: campaign.version, payload: {} });
    await send({ operation: 'agent.message', campaignId, expectedRevision: campaign.version, payload: { page_agent: role, message: text } });
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['desk', campaignId, role] }), queryClient.invalidateQueries({ queryKey: ['agents', campaignId] })]);
  };
  const messages = desk.data?.messages || [];
  return (
    <section className={'desk ' + mode + (open ? ' open' : '')} data-testid={`desk-${role}`} data-mode={mode} aria-label={`${name} desk`}>
      <header className="desk-head" onClick={mode === 'docked' ? () => setOpen(o => !o) : undefined} role={mode === 'docked' ? 'button' : undefined} data-testid="desk-head">
        <span className="desk-dot" data-busy={busy ? '1' : undefined} />
        <strong className="grow">{name}</strong>
        {agent ? <Pill tone={statusTone(agent.status)}>{agent.status}</Pill> : <Pill>not started</Pill>}
        {messages.length ? <span className="faint small">{messages.length} turn{messages.length === 1 ? '' : 's'}</span> : null}
        {mode === 'docked' ? <span className="faint small">{open ? '▾' : '▴'}</span> : null}
      </header>
      {open ? <>
        <div className="desk-turns" ref={scroller}>
          {messages.length ? messages.map(m => <article key={m.id} className={'turn ' + (m.role === 'user' ? 'user' : 'agent')} data-testid="desk-turn">
            <div className="meta"><Pill tone={m.role === 'user' ? 'you' : 'agent'}>{m.role === 'user' ? 'You' : name}</Pill><span>{when(m.created_at)}</span></div>
            <Markdown text={m.content} thread={null} />
          </article>) : <p className="small muted">{agent?.activity || `The ${name.toLowerCase()} takes requests from you here and from the lead, and acts on nothing else.`}</p>}
        </div>
        {(desk.data?.dialogs || []).map(q => <ExtensionDialog key={q.id} question={q} campaignId={campaignId} version={summary.data?.campaign?.version} who={`The ${name.toLowerCase()}`}
          onDone={() => queryClient.invalidateQueries({ queryKey: ['desk', campaignId, role] })} />)}
        <Composer onSend={ask} placeholder={`Ask the ${name.toLowerCase()}…`} testId="desk-composer" />
      </> : null}
    </section>
  );
}

/** Kept for pages that still embed a desk inline. */
export function AgentDesk({ campaignId, role }: { campaignId: string; role: string }) {
  return <DeskPanel campaignId={campaignId} role={role} mode="docked" />;
}
