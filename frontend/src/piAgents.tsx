import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { errorText } from './api';
import type { State, Json } from './api';
import { useCommand } from './commands';
import { ErrorNotice, Icon, sendOnEnter } from './ui';
import { TextContent } from './textContent';
import { WorkingNote, agentPage, currentStep, roleName, useAgentLive } from './agentLive';
import type { LiveAgent } from './agentLive';
import { stageNames } from './reports';

/** A message that asks an agent for something: the researcher's, or the lead agent's to an agent in charge of a page. */
const isRequest = (message: Json) => message.role === 'user' || message.role === 'lead' || message.role === 'agent';

/** A reply from a turn the platform started, which ended with the work still running: a progress note. */
function progressNote(message: Json): boolean {
  return !isRequest(message) && message.turn === 'notice' && (message.disposition == null || message.disposition === 'waiting');
}

type ChatEntry = { message: Json } | { notes: Json[] };
/**
 * The conversation with superseded progress notes gathered. A note is folded only when the agent wrote again right after it.
 * So these always stay: the agent's first reply after a request (it may be the answer), the note a request answered
 * (it may have asked something), and the newest message.
 */
function chatEntries(messages: Json[]): ChatEntry[] {
  const entries: ChatEntry[] = [];
  let unanswered = false;
  messages.forEach((message, index) => {
    const next = messages[index + 1];
    const note = !unanswered && progressNote(message) && Boolean(next) && !isRequest(next);
    unanswered = isRequest(message);
    const last = entries.at(-1);
    if (note && last && 'notes' in last) last.notes.push(message);
    else entries.push(note ? { notes: [message] } : { message });
  });
  return entries;
}

export function firstLine(text: string): string { return (text || '').replace(/[*_`#>|]/g, '').split('\n').find(line => line.trim())?.trim() || ''; }

/** The agent's closing text of a turn, with the lines it wrote beside earlier tool calls folded; whole when an earlier text is the substance. */
export function turnParts(message: Json): { earlier: string[]; final: string } | null {
  const parts: string[] = Array.isArray(message.parts) ? message.parts : [];
  if (parts.length < 2) return null;
  const final = parts.at(-1)!, earlier = parts.slice(0, -1);
  return Math.max(...earlier.map(part => part.length)) > Math.max(400, 3 * final.length) ? null : { earlier, final };
}

/** Who wrote a message, as the conversation shows it: an exchange between two agents names both. */
function author(message: Json, speaker: string, names: Record<string, string>): string {
  if (message.role === 'user') return 'You';
  if (message.role === 'lead') return 'Lead agent';
  if (message.role === 'agent') return `${names[message.from_agent_id] || 'An agent'}, to the lead agent`;
  return message.to_agent_id ? `${speaker}, to the ${(names[message.to_agent_id] || 'agent').toLowerCase()}` : speaker;
}

function ChatMessage({ message, speaker, names = {} }: { message: Json; speaker: string; names?: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  const split = isRequest(message) ? null : turnParts(message);
  return <article className={`message ${message.role === 'user' ? 'user' : 'assistant'} ${message.role === 'agent' || message.to_agent_id ? 'between-agents' : ''}`}><div className="message-meta"><span>{author(message, speaker, names)}</span></div>
    {split && <div className="turn-notes">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '▾' : '▸'} {split.earlier.length} earlier {split.earlier.length === 1 ? 'note' : 'notes'} from this turn</button>
      {open && split.earlier.map((part, index) => <TextContent key={index} text={part} />)}
    </div>}
    <TextContent text={split ? split.final : message.content} /></article>;
}

/** Progress notes the agent has since superseded, folded into one line that opens on a click. */
function ProgressNotes({ notes, speaker, names }: { notes: Json[]; speaker: string; names: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  return <div className="progress-notes">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
      <strong>{open ? '▾' : '▸'} {notes.length} progress {notes.length === 1 ? 'note' : 'notes'}</strong>
      {!open && <span>latest: {firstLine(notes.at(-1)!.content)}</span>}
    </button>
    {open && notes.map(note => <ChatMessage message={note} key={note.id} speaker={speaker} names={names} />)}
  </div>;
}

/**
 * A conversation with one agent: its messages, with superseded notes folded; what it is doing while it works (temporary);
 * the questions it asked; and a box to write to it. Used by the lead agent's chat and by the agents in charge of pages.
 */
export function AgentConversation({ state, refresh, role, agent, target, live, working, waiting, waitingKey, intro, footer, placeholder }: {
  state: State; refresh: () => Promise<void>; role: string; agent?: Json;
  /** Added to every message sent: the agent it is for. */
  target: Json;
  live?: LiveAgent; working: boolean; waiting?: ReactNode; waitingKey?: string; intro?: ReactNode; footer?: ReactNode; placeholder: string;
}) {
  const command = useCommand(state.campaign);
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [question, setQuestion] = useState<string | null>(null);
  const name = roleName(role);
  // Its own conversation, and what it asked the lead and was answered (lead_ask).
  const messages = agent ? state.messages.filter(m => m.agent_id === agent.id || m.from_agent_id === agent.id || m.to_agent_id === agent.id) : [];
  const names: Record<string, string> = Object.fromEntries((state.agent_runtime?.agents || []).map((item: Json) => [item.id, roleName(item.role)]));
  const entries = chatEntries(messages);
  // A question saved without its agent is the lead's: only the lead asked the researcher before page agents existed.
  const questions: Json[] = agent ? (state.agent_runtime?.questions || []).filter((q: Json) => q.agent_id === agent.id || role === 'lead' && !q.agent_id) : [];
  const scrollArea = useRef<HTMLDivElement>(null), followLatest = useRef(true), box = useRef<HTMLTextAreaElement>(null);
  const lastMessage = messages.at(-1);
  const showLatest = () => {
    const area = scrollArea.current;
    if (area && followLatest.current) area.scrollTop = area.scrollHeight;
  };
  useLayoutEffect(() => {
    showLatest();
    // Formatted text and late fonts can still change the height after this render.
    const frame = requestAnimationFrame(showLatest);
    return () => cancelAnimationFrame(frame);
  }, [messages.length, lastMessage?.id, lastMessage?.content, working, live?.updated_at, waitingKey]);
  useEffect(() => {
    void document.fonts?.ready.then(showLatest);
    // The history's own height changes when a question above the message box appears, grows or goes: stay at the newest message.
    const area = scrollArea.current;
    if (!area || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => showLatest());
    observer.observe(area);
    return () => observer.disconnect();
  }, []);
  useEffect(() => { if (question && !questions.some(q => q.id === question)) setQuestion(null); }, [questions.map(q => q.id).join()]);
  async function send(event: FormEvent) {
    event.preventDefault(); if (!message.trim() || busy) return;
    setBusy(true); setError('');
    try {
      await command('agent.message', { message, mode: 'steer', ...target, ...(question ? { question_id: question } : {}) });
      followLatest.current = true; setMessage(''); setQuestion(null);
      try { await refresh(); } catch { /* Saved already. */ }
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  return <>
    <div className="research-body research-messages" ref={scrollArea} tabIndex={0} role="region" aria-label={`${name} message history`} onScroll={event => {
      const area = event.currentTarget;
      followLatest.current = area.scrollHeight - area.scrollTop - area.clientHeight < 48;
    }}>{intro}
      {entries.map(entry => 'notes' in entry
        ? <ProgressNotes key={entry.notes[0].id} notes={entry.notes} speaker={name} names={names} />
        : <ChatMessage key={entry.message.id} message={entry.message} speaker={entry.message.to_agent_id && entry.message.agent_id !== agent?.id ? 'Lead agent' : name} names={names} />)}
      {working && <WorkingNote agent={live} role={role} />}
      {!working && waiting}
      {footer}
    </div>
    {questions.map(item => <AgentQuestion key={item.id} name={name} item={item} answering={question === item.id}
      onAnswer={() => { setQuestion(question === item.id ? null : item.id); box.current?.focus(); }}
      onDismiss={async () => { setError(''); try { await command('agent.question_dismiss', { question_id: item.id }); await refresh(); } catch (failure) { setError(errorText(failure)); } }} />)}
    <form className="research-composer" onSubmit={send}><label className="sr-only" htmlFor={`message-${role}`}>{question ? `Your answer to the ${name.toLowerCase()}` : `Message to the ${name.toLowerCase()}`}</label>
      <textarea id={`message-${role}`} ref={box} rows={3} value={message} onChange={event => setMessage(event.target.value)} placeholder={question ? 'Your answer…' : placeholder} onKeyDown={sendOnEnter} />
      <div className="composer-footer"><span>Enter to send · Shift+Enter for a new line</span><button className="send-button" disabled={busy || !message.trim()} aria-label={question ? `Send answer to the ${name.toLowerCase()}` : `Send message to the ${name.toLowerCase()}`}><Icon name="send" size={17} /></button></div>
      <ErrorNotice text={error} /></form>
  </>;
}

/** A question an agent asked the researcher, kept above the message box until it is answered or set aside. Long ones open on a click. */
function AgentQuestion({ name, item, answering, onAnswer, onDismiss }: { name: string; item: Json; answering: boolean; onAnswer: () => void; onDismiss: () => Promise<void> }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const long = (item.question || '').length > 280;
  return <article className={`agent-question ${answering ? 'answering' : ''}`}>
    <strong>{name} asks you</strong>
    <div className={long && !open ? 'agent-question-text clipped' : 'agent-question-text'}><TextContent text={item.question} /></div>
    {long && <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Show less' : 'Show the whole question'}</button>}
    {item.reason && <details><summary>Why it asks</summary><TextContent text={item.reason} /></details>}
    <div className="agent-question-actions">
      <button type="button" className="button small secondary" aria-pressed={answering} onClick={onAnswer}>{answering ? 'Write a message instead' : 'Answer this question'}</button>
      <button type="button" className="text-button" disabled={busy} title="Set the question aside without answering; no agent is woken"
        onClick={() => { setBusy(true); void onDismiss().finally(() => setBusy(false)); }}>Dismiss</button>
    </div>
  </article>;
}

/** The lead agent's status, as one word for the chat's header. */
function leadStatus(state: State, lead?: Json): string {
  const config = state.agent_runtime?.configuration;
  if (!config?.provider?.configured) return 'needs sign-in';
  if (config.status === 'paused' || config.status === 'stopped') return config.status;
  if (lead && ['queued', 'running'].includes(lead.status)) return 'at work';
  return config.request_open ? 'waiting' : 'ready';
}

export function PiConversation({ state, refresh, onClose }: { state: State; refresh: () => Promise<void>; onClose: () => void }) {
  const team: Json[] = state.agent_runtime?.agents || [];
  const lead = team.find((agent: Json) => agent.role === 'lead');
  const atWork = team.filter(agent => ['queued', 'running'].includes(agent.status));
  const live = useAgentLive(state.campaign?.id, atWork.length > 0);
  const leadWorking = Boolean(lead && atWork.includes(lead)), leadLive = live.find(agent => agent.agent_id === lead?.id);
  const requestOpen = Boolean(state.agent_runtime?.configuration?.request_open);
  const assistants = atWork.filter(agent => agent.role !== 'lead');
  const experiments = state.trials.filter(trial => ['queued', 'running', 'pausing'].includes(trial.status)).length;
  const report = (state.report_writer_jobs || []).find((job: Json) => ['running', 'awaiting_focus'].includes(job.status));
  const waitingStatus = lead?.disposition?.disposition === 'waiting' ? lead.disposition.summary : '';
  const page = (agent: Json) => agentPage(agent.role) || (agent.role.startsWith('implementation_') ? 'implementations' : 'hypotheses/rounds');
  const status = leadStatus(state, lead);
  const waiting = requestOpen && (assistants.length > 0 || experiments > 0 || report || waitingStatus) && <div className="working-note waiting" aria-label="What the lead agent is waiting for">
    <div className="working-head"><span className="working-dot" /><strong role="status">Lead agent is waiting</strong></div>
    {waitingStatus && <p className="waiting-status">{waitingStatus}</p>}
    <ul className="waiting-on">
      {assistants.length > 0 && <li>{assistants.length} {assistants.length === 1 ? 'agent' : 'agents'} at work
        {assistants.slice(0, 4).map(agent => <small key={agent.id}><a href={`#${page(agent)}`}>{roleName(agent.role)}</a>: {currentStep(live.find(row => row.agent_id === agent.id)) || 'at work'}</small>)}</li>}
      {experiments > 0 && <li>{experiments} {experiments === 1 ? 'experiment' : 'experiments'} running · <a href="#experiments">Experiments</a></li>}
      {report && <li>{report.status === 'running' ? `A report is being written: ${(stageNames[(report.stage || '').split('_')[0]] || 'preparing the draft').toLowerCase()}` : 'The report writer asks about the focus'} · <a href="#reports">Reports</a></li>}
    </ul>
  </div>;
  return <aside className="research-panel pi-conversation" aria-label="Lead agent conversation" onClick={event => {
    // A link to a page of the application: where this panel covers the page, close it so the page shows.
    if ((event.target as HTMLElement).closest('a[href^="#"]') && window.innerWidth <= 1250) onClose();
  }}>
    <div className="research-header"><div className="assistant-mark"><Icon name="spark" /></div><div><h2>Lead agent</h2>
      <a className="model-settings-link" href="#agents" title="The agent team, its controls and models">{status} · {lead?.model || 'Agents'}</a></div>
      <button className="icon-button" aria-label="Close research panel" onClick={onClose}><Icon name="close" /></button></div>
    <AgentConversation state={state} refresh={refresh} role="lead" agent={lead} target={{}} live={leadLive} working={leadWorking}
      waiting={waiting || null} waitingKey={`${requestOpen}:${assistants.length}:${experiments}:${report?.stage}:${waitingStatus}`}
      intro={<>{!state.agent_runtime?.configuration.provider?.configured && <p>The model provider needs a sign-in: see <a href="#agents">Agents</a>. Your messages stay queued.</p>}
        {!lead || !state.messages.some(m => m.agent_id === lead.id) ? <p>The lead agent is waiting for your first message. It starts nothing until you ask for it.</p> : null}</>}
      footer={<p><a href="#notebook/conversation">Earlier campaign discussions</a></p>}
      placeholder="Tell the lead agent what to do next…" />
  </aside>;
}
