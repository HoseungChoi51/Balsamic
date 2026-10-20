import { useEffect, useState } from 'react';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { StagePanel } from './StagePanel';
import { ThreadChat } from '../chat/ThreadChat';
import { SetupChat } from '../setup/SetupChat';
import { MonitorDrawer } from '../monitor/MonitorDrawer';
import { IterationProgress } from '../evolution/IterationProgress';
import { SearchPalette } from './SearchPalette';
import { CHAT_WINDOW, RAIL, chatChannel, formatHash, isDetachedWindow, navigate, withThread } from '../router/routes';
import { useCampaigns, useMonitor, useSummary, useWorkspace } from '../api/queries';
import type { Route } from '../router/routes';

const WIDE = 'balsamic.panelWide';
const DETACHED = 'balsamic.chatDetached';

export function Shell({ route, campaignId, threadId }: { route: Route; campaignId: string | null; threadId: string | null }) {
  const workspace = useWorkspace();
  const campaigns = useCampaigns();
  const summary = useSummary(campaignId);
  const monitor = useMonitor(campaignId);
  const [wide, setWide] = useState(() => { try { return localStorage.getItem(WIDE) === '1'; } catch { return false; } });
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [detached, setDetached] = useState(() => { try { return localStorage.getItem(DETACHED) === '1'; } catch { return false; } });
  const chatOnly = route.page === 'chat';
  useEffect(() => { try { localStorage.setItem(DETACHED, detached ? '1' : '0'); } catch { /* private mode */ } }, [detached]);
  // The main window follows the detached chat's page links and notices when that window closes; the detached window closes on reattach.
  useEffect(() => {
    const channel = chatChannel();
    if (!channel) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type: string; hash?: string };
      if (chatOnly) { if (data.type === 'reattach') window.close(); return; }
      if (data.type === 'navigate' && data.hash) navigate(withThread(data.hash, threadId));
      if (data.type === 'closed') setDetached(false);
      if (data.type === 'opened') setDetached(true);
    };
    channel.addEventListener('message', onMessage);
    return () => channel.removeEventListener('message', onMessage);
  }, [chatOnly, threadId]);
  useEffect(() => {
    if (!chatOnly) return;
    chatChannel()?.postMessage({ type: 'opened' });
    const bye = () => chatChannel()?.postMessage({ type: 'closed' });
    window.addEventListener('pagehide', bye);
    return () => window.removeEventListener('pagehide', bye);
  }, [chatOnly]);
  const detach = () => {
    if (detached) { chatChannel()?.postMessage({ type: 'reattach' }); setDetached(false); return; }
    const opened = window.open(formatHash({ page: 'chat' }, threadId), CHAT_WINDOW, 'width=560,height=860,menubar=no,toolbar=no,location=no');
    if (opened) setDetached(true);
  };
  useEffect(() => {
    let pendingG = false;
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest('input, textarea, select, [contenteditable]');
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(p => !p); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'g') { pendingG = true; setTimeout(() => { pendingG = false; }, 900); return; }
      if (pendingG) {
        const page = ({ n: 'note', h: 'hypotheses', e: 'experiments', v: 'evolution', f: 'files', i: 'inbox', m: 'monitor', l: 'library', b: 'branches' } as Record<string, string>)[e.key];
        pendingG = false;
        if (page && RAIL.includes(page as typeof RAIL[number])) navigate(formatHash({ page: page as 'monitor' }, threadId));
        return;
      }
      if (e.key === '?') setPalette(true);
      if (e.key === 'Escape') { setPalette(false); setDrawer(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [threadId]);
  useEffect(() => { try { localStorage.setItem(WIDE, wide ? '1' : '0'); } catch { /* private mode */ } }, [wide]);
  useEffect(() => { setDrawer(false); }, [campaignId]);
  if (chatOnly) {
    const current = (campaigns.data || []).find(c => c.active_thread_id === threadId || (threadId || '').endsWith('_' + c.id));
    return (
      <div className="shell detached" data-testid="shell-detached">
        <header className="topbar"><span className="brand">Balsamic</span><span className="small faint grow">{current?.name || ''} · chat</span>
          <button className="btn quiet small" onClick={() => { chatChannel()?.postMessage({ type: 'closed' }); window.close(); }} data-testid="reattach">Reattach</button></header>
        {campaignId && threadId ? <ThreadChat campaignId={campaignId} threadId={threadId} route={route} /> : <div className="chat" />}
      </div>
    );
  }
  const hideChat = detached && !isDetachedWindow();
  return (
    <div className="shell" data-testid="shell">
      <TopBar route={route} campaigns={campaigns.data || []} campaignId={campaignId} monitor={monitor.data} workspace={workspace.data}
        onSearch={() => setPalette(true)} onMonitor={() => setDrawer(open => !open)} wide={wide} onWide={() => setWide(w => !w)} version={summary.data?.campaign.version} />
      {campaignId && summary.data?.stage.stage === 'optimize' ? <IterationProgress campaignId={campaignId} /> : null}
      <div className="body">
        <Rail route={route} summary={summary.data} monitor={monitor.data} />
        <div className={'main' + (hideChat && route.page !== 'new' ? ' split' : (wide && route.page !== 'new') || (route.page !== 'new' && !threadId) ? ' wide' : '')} data-detached={hideChat ? '1' : undefined}>
          {route.page === 'new' ? <SetupChat setupId={route.id} /> : hideChat ? <div className="chat-strip" data-testid="chat-strip">
            <button className="btn quiet small" onClick={detach} title="Bring the chat back into this window" data-testid="reattach-strip">Reattach chat</button>
            <span className="faint small strip-label">chat open in its own window</span>
          </div> : campaignId && threadId ? <ThreadChat campaignId={campaignId} threadId={threadId} route={route} onDetach={detach} /> : <div className="chat" />}
          <StagePanel route={route} campaignId={campaignId} threadId={threadId} />
        </div>
      </div>
      {drawer && campaignId ? <MonitorDrawer campaignId={campaignId} route={route} onClose={() => setDrawer(false)} /> : null}
      {palette && campaignId ? <SearchPalette campaignId={campaignId} route={route} onClose={() => setPalette(false)} /> : null}
    </div>
  );
}
