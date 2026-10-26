/** What waits in the inbox, in front of the researcher on every page until they acknowledge it: opening the inbox is not
 * acknowledging. An item raised again or revised comes back (its key changes). */
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useInbox } from '../api/queries';
import type { InboxItem } from '../api/types';
import { formatHash, type Route } from '../router/routes';

const KIND: Record<string, string> = { decision: 'Decision', issue: 'Issue', question: 'Question from the lead', closed: 'Closed by the lead' };
const TITLE = document.title;

export async function acknowledge(campaignId: string, items: InboxItem[], refresh: () => unknown) {
  if (!items.length) return;
  await api(`/api/v1/campaigns/${campaignId}/inbox/acknowledge`, { method: 'POST', body: JSON.stringify({ keys: items.map(item => item.key) }) });
  await refresh();
}

export function InboxNotice({ campaignId, route }: { campaignId: string | null; route: Route }) {
  const inbox = useInbox(campaignId);
  const queryClient = useQueryClient();
  const items = inbox.data?.unacknowledged || [];
  useEffect(() => { document.title = items.length ? `(${items.length}) ${TITLE}` : TITLE; }, [items.length]);
  if (!campaignId || !items.length) return null;
  const [first, ...rest] = items;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['inbox', campaignId] });
  return (
    <div className="inbox-notice" role="status" aria-live="polite" data-testid="inbox-notice">
      <strong className="nowrap">{items.length === 1 ? 'New in your inbox' : `${items.length} new in your inbox`}</strong>
      <span className="grow notice-text"><span className="faint">{KIND[first.kind] || first.kind}:</span> {first.title}{rest.length ? <span className="faint"> · and {rest.length} more</span> : null}</span>
      {route.page !== 'inbox' ? <a className="btn small primary" href={formatHash({ page: 'inbox' }, route.thread)} data-testid="open-inbox">Open the inbox</a> : null}
      <button className="btn small" onClick={() => void acknowledge(campaignId, items, refresh)} title="Mark these as seen; what needs your answer stays in the inbox" data-testid="acknowledge-all">Got it</button>
    </div>
  );
}
