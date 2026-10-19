/** One SSE connection per campaign; each frame names the record kinds that changed, and the pages that show them refetch. */
import type { QueryClient } from '@tanstack/react-query';
import type { EventFrame } from './types';

// Event kind prefix -> query keys to refetch. Everything also refreshes the campaign list and the summary.
const ROUTES: [RegExp, string[]][] = [
  [/^(message|thread|agent)\./, ['threads', 'messages', 'agents']],
  [/^(trial|experiment|draft|validation|runtime|worker|effect)\./, ['experiments', 'monitor']],
  [/^(hypothesis|finding|review|discussion|intervention)\./, ['hypotheses', 'evolution']],
  [/^(decision|manager\.issue|agent\.question|approval)/, ['inbox', 'monitor']],
  [/^(asset|report|bundle|source|artifact)\./, ['files']],
  [/^(study|race|confirmation|nomination|finalist)\./, ['evolution', 'experiments']],
  [/^(campaign|charter|problem_note|note)\./, ['summary', 'note', 'campaigns']],
  [/^(resources|workers|cost|llm)\./, ['monitor', 'resources']],
];

export type FrameListener = (frame: EventFrame) => void;

export function connectEvents(campaignId: string | null, queryClient: QueryClient, onFrame?: FrameListener) {
  const url = '/api/v1/events' + (campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '');
  const source = new EventSource(url);
  let pending = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = () => {
    timer = null;
    const keys = [...pending]; pending = new Set();
    for (const key of keys) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  source.addEventListener('update', event => {
    let frame: EventFrame;
    try { frame = JSON.parse((event as MessageEvent).data); } catch { return; }
    onFrame?.(frame);
    pending.add('campaigns'); pending.add('summary'); pending.add('threads');
    for (const item of frame.events || []) for (const [pattern, keys] of ROUTES) if (pattern.test(item.kind)) keys.forEach(key => pending.add(key));
    if (!timer) timer = setTimeout(flush, 300);
  });
  return () => { source.close(); if (timer) clearTimeout(timer); };
}
