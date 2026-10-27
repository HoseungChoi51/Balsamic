/** Resolves the route to a campaign and a thread (the bare address is the home page), keeps the SSE connection and telemetry context, and renders the shell.
 * An address without a thread names no campaign: its pages show nothing of any campaign, whichever was opened last; only one opened
 * from a campaign in this tab (an old address, a link written without a thread) stays in that campaign. */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Shell } from './shell/Shell';
import { HomePage } from './home/HomePage';
import { parseHash, formatHash, navigate } from './router/routes';
import { useThread, useWorkspace } from './api/queries';
import { connectEvents } from './api/sse';
import { setWorkspaceId } from './api/client';
import { setTelemetryContext, track } from './telemetry/events';
import { SelectionProvider } from './stores/selection';

const subscribeHash = (fn: () => void) => { window.addEventListener('hashchange', fn); return () => window.removeEventListener('hashchange', fn); };

export default function App() {
  const hash = useSyncExternalStore(subscribeHash, () => location.hash, () => '');
  const route = parseHash(hash);
  const queryClient = useQueryClient();
  const workspace = useWorkspace();
  const thread = useThread(route.thread);
  const campaignId = thread.data?.campaign_id ?? (route.thread ? null : null);

  useEffect(() => { if (workspace.data) setWorkspaceId(workspace.data.workspace_id); }, [workspace.data]);
  // An old address is rewritten to its current page, so the bar shows where the link led.
  useEffect(() => { if (hash && route.raw !== hash && !route.thread) { const canonical = route.raw; if (canonical !== hash) navigate(canonical); } }, [hash, route.raw, route.thread]);
  // The campaign open in this tab; the new-campaign and home pages choose none, so a page opened from them shows no campaign.
  const open = useRef<string | null>(null);
  useEffect(() => {
    if (route.page === 'new' || route.page === 'home') open.current = null;
    else if (route.thread) open.current = route.thread;
    else if (open.current) navigate(formatHash(route, open.current));
  }, [route.raw]);   // eslint-disable-line react-hooks/exhaustive-deps
  // An unknown thread (removed campaign, stale link) falls back to the same page without a campaign.
  useEffect(() => { if (route.thread && thread.error) { open.current = null; navigate(formatHash({ page: route.page, sub: route.sub }, null)); } }, [route, thread.error]);
  useEffect(() => { if (!campaignId) return; return connectEvents(campaignId, queryClient); }, [campaignId, queryClient]);
  useEffect(() => {
    setTelemetryContext({ campaign_id: campaignId, thread_id: route.thread, page: route.page + (route.sub ? '/' + route.sub : '') });
    track('page.open', { page: route.page, sub: route.sub, has_id: !!route.id });
  }, [campaignId, route.thread, route.page, route.sub, route.id]);

  if (route.page === 'home') return <HomePage />;
  return (
    <SelectionProvider route={route}>
      <Shell route={route} campaignId={route.page === 'new' ? null : campaignId} threadId={route.page === 'new' ? null : route.thread} />
    </SelectionProvider>
  );
}
