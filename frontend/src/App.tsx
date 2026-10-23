/** Resolves the route to a campaign and a thread (the bare address is the home page), keeps the SSE connection and telemetry context, and renders the shell. */
import { useEffect, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Shell } from './shell/Shell';
import { HomePage } from './home/HomePage';
import { parseHash, formatHash, lastThread, navigate, rememberThread } from './router/routes';
import { useCampaigns, useThread, useWorkspace } from './api/queries';
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
  const campaigns = useCampaigns();
  const thread = useThread(route.thread);
  const campaignId = thread.data?.campaign_id ?? (route.thread ? null : null);

  useEffect(() => { if (workspace.data) setWorkspaceId(workspace.data.workspace_id); }, [workspace.data]);
  // An old address is rewritten to its current page, so the bar shows where the link led.
  useEffect(() => { if (hash && route.raw !== hash && !route.thread) { const canonical = route.raw; if (canonical !== hash) navigate(canonical); } }, [hash, route.raw, route.thread]);
  // A thread-less address opens the last thread, or the newest campaign's main thread.
  useEffect(() => {
    if (route.page === 'new' || route.page === 'home' || route.thread || !campaigns.data) return;
    const remembered = lastThread();
    const rows = campaigns.data;
    const target = (remembered && rows.some(c => c.active_thread_id === remembered || remembered.endsWith('_' + c.id)) ? remembered : null) || rows.at(-1)?.active_thread_id || null;
    if (target) navigate(formatHash(route, target));
    else if (!rows.length) navigate('#new');
  }, [route, campaigns.data]);
  // An unknown thread (removed campaign, stale link) falls back to the campaign list.
  useEffect(() => { if (route.thread && thread.error) { rememberThread(null); navigate(formatHash({ page: route.page, sub: route.sub }, null)); } }, [route, thread.error]);
  useEffect(() => { if (route.thread && thread.data) rememberThread(route.thread); }, [route.thread, thread.data]);
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
