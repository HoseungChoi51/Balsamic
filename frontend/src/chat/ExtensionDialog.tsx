/** A dialog an extension of an agent's session opened (select, confirm, input, editor). The agent waits inside its tool call;
 *  the answer goes back to it with agent.ui_respond, not into a new turn. Unanswered, it is cancelled at its deadline. */
import { useState } from 'react';
import type { Question } from '../api/types';
import { send } from '../commands/bus';
import { Pill, when } from '../primitives/ui';

interface Dialog { method: 'select' | 'confirm' | 'input' | 'editor'; title: string; message?: string; options?: string[]; placeholder?: string; prefill?: string }

export const isExtensionDialog = (question: Question) => question.kind === 'extension_dialog';

export function ExtensionDialog({ question, campaignId, version, who, onDone }: { question: Question; campaignId: string; version?: number; who: string; onDone?: () => unknown }) {
  const dialog = question.dialog as Dialog;
  const [text, setText] = useState(dialog.prefill || '');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const respond = async (payload: { value?: string | boolean; cancelled?: boolean }) => {
    if (version === undefined) { setError('The campaign is still loading'); return; }
    setSending(true); setError(null);
    try { await send({ operation: 'agent.ui_respond', campaignId, expectedRevision: version, payload: { question_id: question.id, ...payload } }); await onDone?.(); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setSending(false); }
  };
  const deadline = typeof question.deadline_at === 'number' ? new Date(question.deadline_at * 1000).toISOString() : null;
  return (
    <article className="card" data-testid="extension-dialog">
      <div className="row"><Pill tone="agent">{who} asks, through an extension</Pill><span className="faint small grow">{when(question.created_at)}</span>
        {deadline ? <span className="faint small" title="Unanswered, the dialog is cancelled then and the agent goes on without it">cancelled {when(deadline)}</span> : null}</div>
      <p><strong>{dialog.title}</strong></p>
      {dialog.message ? <p className="small">{dialog.message}</p> : null}
      {dialog.method === 'select' ? <div className="row wrap">{(dialog.options || []).map(option =>
        <button key={option} className="btn small" disabled={sending} onClick={() => respond({ value: option })}>{option}</button>)}</div> : null}
      {dialog.method === 'confirm' ? <div className="row"><button className="btn small" disabled={sending} onClick={() => respond({ value: true })}>Yes</button>
        <button className="btn small" disabled={sending} onClick={() => respond({ value: false })}>No</button></div> : null}
      {dialog.method === 'input' || dialog.method === 'editor' ? <form className="row" onSubmit={e => { e.preventDefault(); void respond({ value: text }); }}>
        {dialog.method === 'input' ? <input className="grow" value={text} placeholder={dialog.placeholder || ''} onChange={e => setText(e.target.value)} data-testid="extension-dialog-input" />
          : <textarea className="grow" rows={6} value={text} onChange={e => setText(e.target.value)} data-testid="extension-dialog-input" />}
        <button className="btn small" type="submit" disabled={sending}>Send</button></form> : null}
      <div className="row"><button className="btn quiet small" disabled={sending} onClick={() => respond({ cancelled: true })}>Cancel the dialog</button></div>
      {error ? <div className="pill bad">{error}</div> : null}
    </article>
  );
}
