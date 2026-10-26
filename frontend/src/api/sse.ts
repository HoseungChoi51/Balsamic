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
  [/^panel\./, ['panels', 'panel', 'messages']],
];

const PROGRESS = /\.progress$/;
const PROGRESS_MS = 3000;

export type FrameListener = (frame: EventFrame) => void;

export function connectEvents(campaignId: string | null, queryClient: QueryClient, onFrame?: FrameListener) {
  const url = '/api/v1/events' + (campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '');
  const source = new EventSource(url);
  let pending = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let due = 0;
  const flush = () => {
    timer = null;
    const keys = [...pending]; pending = new Set();
    for (const key of keys) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  source.addEventListener('update', event => {
    let frame: EventFrame;
    try { frame = JSON.parse((event as MessageEvent).data); } catch { return; }
    onFrame?.(frame);
    const events = frame.events || [];
    // A running experiment reports progress every second or two: that refreshes the pages that show runs, at most every
    // PROGRESS_MS, and not every page; any other change refreshes the campaign's views within 300 ms.
    const progress = events.length > 0 && events.every(item => PROGRESS.test(item.kind));
    if (!progress) { pending.add('campaigns'); pending.add('summary'); pending.add('threads'); }
    for (const item of events) for (const [pattern, keys] of ROUTES) if (pattern.test(item.kind)) keys.forEach(key => pending.add(key));
    const at = Date.now() + (progress ? PROGRESS_MS : 300);
    if (timer && at < due) { clearTimeout(timer); timer = null; }
    if (!timer) { due = at; timer = setTimeout(flush, at - Date.now()); }
  });
  return () => { source.close(); if (timer) clearTimeout(timer); };
}
