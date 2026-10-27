/** Above the chat, the mandate the thread's current request works under (roadmap R7): its template, what is left of its envelope and
 * its deadline, with Close for the researcher; then any other mandate still in force from an earlier request in this thread. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useThreadMandate } from '../api/queries';
import type { MandateView } from '../api/types';
import { send } from '../commands/bus';
import { duration, Pill } from '../primitives/ui';

const GRANTED: Record<MandateView['granted'], string> = { message: 'granted with your message', card: 'approved by you', automatic: 'granted automatically' };

function left(mandate: MandateView) {
  const terms = [`${String(duration(mandate.left.worker_seconds))} of worker time`];
  if (mandate.envelope.coding_workspaces) terms.push(`${mandate.left.coding_workspaces} coding workspace${mandate.left.coding_workspaces === 1 ? '' : 's'}`);
  if (mandate.left.model_usd != null) terms.push(`$${mandate.left.model_usd.toFixed(2)} of model spend`);
  return terms.join(', ');
}

function deadline(at: string | null) {
  if (!at) return 'no deadline';
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? `deadline ${at}` : `deadline ${date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
}

export function MandateBar({ campaignId, threadId, version }: { campaignId: string; threadId: string; version?: number }) {
  const mandate = useThreadMandate(threadId);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const data = mandate.data;
  const rows = data ? [...(data.current ? [{ view: data.current, current: true }] : []), ...data.others.map(view => ({ view, current: false }))] : [];
  if (!rows.length) return null;
  const close = async (view: MandateView) => {
    if (version === undefined) return;
    setError(null); setClosing(view.id);
    try {
      await send({ operation: 'mandate.close', campaignId, expectedRevision: version, payload: { mandate_id: view.id, reason: 'Closed by the researcher in the chat' }, origin: { thread_id: threadId } });
      await queryClient.invalidateQueries({ queryKey: ['mandate', threadId] });
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setClosing(null); }
  };
  return (
    <div className="mandate-bar" data-testid="mandate-bar">
      {rows.map(({ view, current }) => {
        const ended = view.status !== 'active';
        return (
          <div key={view.id} className="mandate-row" data-testid={current ? 'mandate-current' : 'mandate-other'} data-status={view.status} title={view.plan || view.summary}>
            <Pill tone={ended ? 'attention' : view.template === 'screen' || view.template === 'run_campaign' ? 'you' : ''}>{view.label}</Pill>
            <span className="grow">{current ? (view.standing ? 'Standing mandate' : 'This request') : 'An earlier request'}
              {ended ? ` · ${view.status === 'closed' ? `closed${view.closed_by === 'researcher' ? ' by you' : ''}` : view.status === 'exhausted' ? 'envelope spent' : 'time is up'}: new work is refused`
                : ` · left: ${left(view)} · ${deadline(view.deadline_at)}`}
              {view.hypothesis_ids.length ? ` · for ${view.hypothesis_ids.join(', ')}` : ''} · <span className="faint">{GRANTED[view.granted]}</span></span>
            {view.closable ? <button className="btn quiet small" disabled={closing === view.id || version === undefined} onClick={() => void close(view)} data-testid="mandate-close"
              title="Close this mandate: the agents start no new work under it; work already running goes on">Close</button> : null}
          </div>
        );
      })}
      {error ? <span className="pill bad">{error}</span> : null}
    </div>
  );
}
