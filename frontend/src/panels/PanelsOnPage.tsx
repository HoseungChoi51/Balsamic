/** The panels agents composed for the current page, above or below its fixed content. */
import { useRead } from '../api/queries';
import type { Panels } from '../api/types';
import { PanelView } from './PanelView';

export function PanelsOnPage({ campaignId, page, placement, threadId }: { campaignId: string; page: string; placement: 'top' | 'bottom'; threadId: string | null }) {
  const panels = useRead<Panels>(['panels', campaignId, page], `/api/v1/campaigns/${campaignId}/panels?page=${encodeURIComponent('#' + page)}`, { refetchInterval: 15000 });
  const rows = (panels.data?.panels || []).filter(p => (p.placement || 'bottom') === placement);
  if (!rows.length) return null;
  return <div className={'panels ' + placement} data-testid={`panels-${placement}`}>{rows.map(p => <PanelView key={p.id} panel={p} threadId={threadId} />)}</div>;
}
