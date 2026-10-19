import type { Message } from '../api/types';
import { Markdown } from './render/Markdown';
import { Pill, when } from '../primitives/ui';

const ORIGIN_LABEL: Record<string, string> = { researcher: 'You', lead: 'Lead', page_agent: 'Agent', autopilot: 'Autopilot', lab_event: 'Lab', manager_system: 'Lab', pi: 'Lead' };

export function Turn({ message, thread, aliases, onFork, onEdit }: { message: Message; thread: string | null; aliases?: Record<string, string>; onFork?: (message: Message) => void; onEdit?: (message: Message) => void }) {
  const user = message.role === 'user' && message.origin !== 'lab_event';
  const lab = message.origin === 'lab_event' || message.origin === 'manager_system' || !!message.issue_id;
  const who = user ? 'You' : ORIGIN_LABEL[String(message.origin)] || (message.role === 'assistant' ? 'Lead' : message.role);
  return (
    <article className={'turn ' + (user ? 'user' : lab ? 'lab' : 'agent')} data-message-id={message.id} data-testid="turn">
      <div className="meta">
        <Pill tone={user ? 'you' : lab ? '' : 'agent'}>{who}</Pill>
        <span>{when(message.created_at)}</span>
        {message.refs?.length ? <span className="faint">· {message.refs.length} refs</span> : null}
        {message.merge_of_thread_id ? <Pill>merged branch</Pill> : null}
        {message.edited_from_message_id ? <Pill title="An edited resend; the original stays in the parent thread">edited</Pill> : null}
        {onFork && !lab ? <button className="btn quiet small" onClick={() => onFork(message)} title="Start a branch of the conversation from this message" data-testid="fork-here">Fork here</button> : null}
        {onEdit && user ? <button className="btn quiet small" onClick={() => onEdit(message)} title="Edit and resend as a new branch" data-testid="edit-resend">Edit</button> : null}
      </div>
      {lab ? <div>{message.content}</div> : <Markdown text={message.content} thread={thread} aliases={aliases} />}
    </article>
  );
}
