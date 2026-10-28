/** The second reading of the researcher's words against the lead's charter (roadmap P4), as the pages show it (P5): each
 *  difference it found, settled by the researcher on the confirm card or the Charter tab: the charter is right, or the lead
 *  fixes it (problem_note.settle). */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSummary } from '../api/queries';
import { send } from '../commands/bus';
import { Pill } from '../primitives/ui';
import { track } from '../telemetry/events';

export interface Mismatch { id: string; quote: string; path: string; kind: 'missing' | 'different' | 'added' | string; explanation: string; verbatim?: boolean;
  settled?: { how: 'right' | 'ask_lead' | string; by: string; at: string; text?: string; carried_from?: number } | null }
export interface Reading { id: string; revision: number; status: string; model?: { provider?: string | null; model?: string | null } | null; mismatches?: Mismatch[]; error?: string | null }

const KIND_WORDS: Record<string, [string, string]> = {
  missing: ['left out', 'The charter leaves out what you said'], different: ['differs', 'The charter says otherwise'], added: ['added', 'The charter states what you did not say'] };
/** A refusal of the service, as the page shows it: its pointers to the Charter tab are for the agents, not for a page that is one. */
export const plainWhy = (text: string) => text.replace(/\s*\(#note\/charter\)/g, '');

/** Refresh what the quick path's actions change: the note (its reading and confirmation), the charter, and the gate. */
export function useRefresh(campaignId: string, charterId?: string | null) {
  const queryClient = useQueryClient();
  return () => Promise.all([['note', campaignId], ...(charterId ? [['charter', charterId]] : []), ['summary', campaignId], ['campaigns']]
    .map(queryKey => queryClient.invalidateQueries({ queryKey })));
}

/** What the second reading found, each difference settled by the researcher: the charter is right, or the lead fixes it. */
export function Differences({ campaignId, noteId, reading, threadId, live }: { campaignId: string; noteId: string; reading: Reading; threadId?: string | null; live: boolean }) {
  const summary = useSummary(campaignId);
  const refresh = useRefresh(campaignId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);   // the difference whose words to the lead are open
  const [text, setText] = useState('');
  const rows = reading.mismatches || [];
  const settle = async (id: string, how: 'right' | 'ask_lead') => {
    const version = summary.data?.campaign.version;
    if (version === undefined) return;
    setBusy(true); setError(null);
    try {
      await send({ operation: 'problem_note.settle', campaignId, expectedRevision: version, ...(threadId ? { origin: { thread_id: threadId } } : {}),
        payload: { note_id: noteId, revision: reading.revision, mismatches: { [id]: how }, ...(how === 'ask_lead' && text.trim() ? { text: text.trim() } : {}) } });
      track('note.settle', { how });
      setAsking(null); setText(''); await refresh();
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  const model = reading.model?.model ? `${reading.model.provider}/${reading.model.model}` : null;
  return <div className="col" style={{ gap: 6 }} data-testid="differences" data-revision={reading.revision}>
    <p className="small muted" style={{ margin: 0 }} data-testid="differences-lead">
      {rows.length ? <>A second reading of your words against revision {reading.revision} found {rows.length === 1 ? 'one difference' : `${rows.length} differences`}. Settle each before confirming: the charter is right as it stands, or the lead fixes it.</>
        : <>A second reading of your words against revision {reading.revision} found no difference.</>}
      {model ? <span className="faint"> Read by {model}, which saw only your words and the charter.</span> : null}</p>
    {rows.map(row => {
      const [label, title] = KIND_WORDS[row.kind] || [row.kind, row.kind];
      const settled = row.settled;
      return <article key={row.id} className={'finding ' + (settled ? 'answered' : 'blocking')} data-testid="difference" data-id={row.id} data-settled={settled?.how}>
        <div className="row wrap"><span className="finding-code" title={title}>{label}</span><code className="small">{row.path}</code><span className="grow">{row.explanation}</span>
          {settled?.how === 'right' ? <Pill tone="clear" title={settled.carried_from ? `You said so on the reading of revision ${settled.carried_from}, and the charter still says the same there` : `You said so${settled.at ? ' on ' + settled.at.slice(0, 16).replace('T', ' ') : ''}`}>
            the charter is right{settled.carried_from ? ` · from r${settled.carried_from}` : ''}</Pill>
            : settled?.how === 'ask_lead' ? <Pill tone="agent" title={settled.text ? `Your words to the lead: ${settled.text}` : 'The lead was asked to fix it'}>the lead is fixing it</Pill> : null}</div>
        {row.quote ? <div className="small muted" style={{ marginTop: 4 }}>Your words: “{row.quote}”{row.verbatim === false ? <span className="faint"> · not found word for word in what you said</span> : null}</div> : null}
        {!settled && live ? <div className="row wrap finding-actions">
          <button className="btn small" disabled={busy} onClick={() => settle(row.id, 'right')} data-testid="difference-right" title="Keep the charter as it is here; your word is recorded, and holds for a later reading while the charter says the same">The charter is right</button>
          <button className="btn small" disabled={busy} onClick={() => setAsking(asking === row.id ? null : row.id)} data-testid="difference-ask" title="The lead fixes the charter here from your words, and its next revision is read again">Ask the lead to fix it</button>
        </div> : null}
        {asking === row.id && !settled ? <div className="row" style={{ marginTop: 6 }}>
          <input className="grow" placeholder="What it should say, in your words (optional)" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="difference-text" />
          <button className="btn small primary" disabled={busy} onClick={() => settle(row.id, 'ask_lead')} data-testid="difference-send">Send to the lead</button></div> : null}
      </article>;
    })}
    {error ? <div className="pill bad" role="alert" data-testid="differences-error">{error}</div> : null}
  </div>;
}

