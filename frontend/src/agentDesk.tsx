import { useState } from 'react';
import { errorText } from './api';
import type { Json, State } from './api';
import { useCommand } from './commands';
import { AgentConversation, firstLine } from './piAgents';
import { currentStep, roleName, useAgentLive } from './agentLive';
import { ErrorNotice } from './ui';
import './agentDesk.css';

/** What each page agent does, said once before it is first asked. */
const work: Record<string, string> = {
  discussion_moderator: 'Runs review rounds: specialists and reviewers criticise the proposals you name, the proposals are revised, and you get a short synthesis.',
  experiment_operator: 'Designs, starts, watches, pauses, extends and stops runs within the campaign’s budget, and finds out why a run failed.',
  implementation_lead: 'Builds and checks optimizer and evaluator implementations in coding workspaces, and attaches them to proposals.',
};
const example: Record<string, string> = {
  discussion_moderator: 'For example: have H3 and H5 reviewed by two reviewers and a skeptic…',
  experiment_operator: 'For example: why did the last run fail?…',
  implementation_lead: 'For example: what would it take to implement H4?…',
};

/**
 * The agent in charge of this page: one line with what it is doing and its last word, which opens into its conversation.
 * It is asked here, or by the lead agent; it acts on nothing else.
 */
export function AgentDesk({ state, refresh, role }: { state: State; refresh: () => Promise<void>; role: string }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const command = useCommand(state.campaign);
  const agent: Json | undefined = (state.agent_runtime?.agents || []).find((item: Json) => item.role === role);
  const working = Boolean(agent && ['queued', 'running'].includes(agent.status));
  const live = useAgentLive(state.campaign?.id, working).find(row => row.agent_id === agent?.id);
  if (!state.campaign || !state.agent_runtime?.configuration?.enabled) return null;
  const name = roleName(role);
  const replies = agent ? state.messages.filter(message => message.agent_id === agent.id && message.role === 'assistant') : [];
  const questions = agent ? (state.agent_runtime.questions || []).filter((question: Json) => question.agent_id === agent.id).length : 0;
  const waiting = agent?.request_open && !working && agent.disposition?.disposition === 'waiting' ? agent.disposition.summary || '' : '';
  const status = !agent ? 'not asked yet' : working ? currentStep(live) || 'at work' : agent.status === 'paused' ? 'paused' : waiting ? 'waiting' : 'ready';
  async function control(action: 'pause' | 'resume' | 'stop') {
    if (!agent || busy) return;
    setBusy(true); setError('');
    try { await command('agent.control', { agent_id: agent.id, action, expected_control_revision: agent.control_revision }); await refresh(); }
    catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  return <section className={`agent-desk ${open ? 'open' : ''}`} aria-label={name}>
    <button type="button" className="agent-desk-line" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span className={`agent-desk-dot ${working ? 'working' : agent ? '' : 'new'}`} />
      <strong>{name}</strong><span className="agent-desk-status">{status}</span>
      {questions > 0 && <span className="agent-desk-question">{questions === 1 ? 'a question for you' : `${questions} questions for you`}</span>}
      <span className="agent-desk-last">{waiting || agent?.disposition?.summary || firstLine(replies.at(-1)?.content || '') || work[role]}</span>
      <span className="agent-desk-toggle">{open ? 'Close ▴' : 'Ask ▾'}</span>
    </button>
    {open && <div className="agent-desk-body">
      <AgentConversation state={state} refresh={refresh} role={role} agent={agent} target={{ page_agent: role }} live={live} working={working}
        waiting={waiting ? <div className="working-note waiting"><div className="working-head"><span className="working-dot" /><strong role="status">{name} is waiting</strong></div><p className="waiting-status">{waiting}</p></div> : null}
        waitingKey={waiting} placeholder={example[role]}
        intro={!agent || !state.messages.some(message => message.agent_id === agent.id) ? <p>{work[role]} It acts only when you or the lead agent ask.</p> : null} />
      {agent && <div className="agent-desk-controls">
        <button type="button" className="text-button" disabled={busy} onClick={() => void control(agent.status === 'paused' ? 'resume' : 'pause')}>{agent.status === 'paused' ? 'Resume' : 'Pause'}</button>
        <button type="button" className="text-button" disabled={busy || !working} onClick={() => void control('stop')}>Stop its current work</button>
      </div>}
      <ErrorNotice text={error} />
    </div>}
  </section>;
}
