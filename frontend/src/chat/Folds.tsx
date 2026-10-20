/** Earlier exchanges folded under a one-sentence title; the last two stay open. An exchange is a researcher message and the replies before the next one. */
import { useState, type ReactNode } from 'react';
import type { Message } from '../api/types';

const OPEN_TAIL = 2;

export interface Exchange { id: string; question: Message | null; messages: Message[] }

export function exchangesOf(messages: Message[]): Exchange[] {
  const out: Exchange[] = [];
  for (const message of messages) {
    if (message.role === 'user' && message.origin !== 'lab_event') out.push({ id: message.id, question: message, messages: [message] });
    else if (out.length) out[out.length - 1].messages.push(message);
    else out.push({ id: 'lead-' + message.id, question: null, messages: [message] });
  }
  return out;
}

export function foldTitle(exchange: Exchange): string {
  const given = exchange.question?.fold_title;
  if (given) return given;
  const text = (exchange.question?.content || exchange.messages[0]?.content || '').replace(/\s+/g, ' ').trim();
  const sentence = text.split(/(?<=[.?!])\s/)[0] || text;
  return sentence.length > 110 ? sentence.slice(0, 110).replace(/\s+\S*$/, '') + '…' : sentence;
}

export function Folds({ messages, render }: { messages: Message[]; render: (message: Message) => ReactNode }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [all, setAll] = useState<boolean | null>(null);
  const exchanges = exchangesOf(messages);
  const folded = Math.max(0, exchanges.length - OPEN_TAIL);
  const isOpen = (exchange: Exchange, index: number) => index >= folded || (all ?? open[exchange.id] ?? false);
  const foldedCount = exchanges.slice(0, folded).filter((e, i) => !isOpen(e, i)).length;
  return (
    <>
      {folded ? <div className="fold-bar small" data-testid="fold-bar">
        <span className="faint">{foldedCount ? `${foldedCount} earlier exchange${foldedCount === 1 ? '' : 's'} folded` : `${folded} earlier exchange${folded === 1 ? '' : 's'}`}</span>
        <button className="btn quiet small" onClick={() => { setAll(foldedCount ? true : false); setOpen({}); }} data-testid="fold-all">{foldedCount ? 'Expand all' : 'Fold all'}</button>
      </div> : null}
      {exchanges.map((exchange, index) => index >= folded ? exchange.messages.map(render) : (
        <details key={exchange.id} className="fold" open={isOpen(exchange, index)} data-testid="fold" data-exchange-id={exchange.id}
          onToggle={e => { const next = (e.currentTarget as HTMLDetailsElement).open; setOpen(o => ({ ...o, [exchange.id]: next })); if (all !== null && next !== all) setAll(null); }}>
          <summary><span className="fold-title">{foldTitle(exchange)}</span><span className="faint small"> · {exchange.messages.length} turn{exchange.messages.length === 1 ? '' : 's'}</span></summary>
          {isOpen(exchange, index) ? exchange.messages.map(render) : null}
        </details>
      ))}
    </>
  );
}
