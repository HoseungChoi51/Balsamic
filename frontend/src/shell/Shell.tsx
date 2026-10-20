import { useEffect, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { StagePanel } from './StagePanel';
import { ThreadChat } from '../chat/ThreadChat';
import { SetupChat } from '../setup/SetupChat';
import { MonitorDrawer } from '../monitor/MonitorDrawer';
import { IterationProgress } from '../evolution/IterationProgress';
import { SearchPalette } from './SearchPalette';
import { DeskPanel, deskRole } from '../desks/AgentDesk';
import { CHAT_WINDOW, RAIL, chatChannel, formatHash, isDetachedWindow, navigate, withThread } from '../router/routes';
import { useCampaigns, useMonitor, useSummary, useWorkspace } from '../api/queries';
import type { Route } from '../router/routes';

const WIDE = 'balsamic.panelWide';
const DETACHED = 'balsamic.chatDetached';
const LAYOUT = 'balsamic.layout';
const RAIL_MIN = 120, RAIL_MAX = 320, CHAT_MIN = 280, RAIL_COLLAPSED = 48;

interface Layout { rail: number; chat: number; railCollapsed: boolean }
const DEFAULT_LAYOUT: Layout = { rail: 168, chat: 0.42, railCollapsed: false };
function loadLayout(): Layout { try { return { ...DEFAULT_LAYOUT, ...JSON.parse(localStorage.getItem(LAYOUT) || '{}') }; } catch { return DEFAULT_LAYOUT; } }

/** A drag handle between two columns; the drag reports the pointer's x position. */
function Gutter({ onDrag, label }: { onDrag: (x: number) => void; label: string }) {
  const start = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const move = (ev: PointerEvent) => onDrag(ev.clientX);
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); document.body.classList.remove('resizing'); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop); document.body.classList.add('resizing');
  };
  return <div className="gutter" role="separator" aria-label={label} aria-orientation="vertical" onPointerDown={start} data-testid={`gutter-${label}`} />;
}

export function Shell({ route, campaignId, threadId }: { route: Route; campaignId: string | null; threadId: string | null }) {
  const workspace = useWorkspace();
  const campaigns = useCampaigns();
  const summary = useSummary(campaignId);
  const monitor = useMonitor(campaignId);
  const [wide, setWide] = useState(() => { try { return localStorage.getItem(WIDE) === '1'; } catch { return false; } });
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [detached, setDetached] = useState(() => { try { return localStorage.getItem(DETACHED) === '1'; } catch { return false; } });
  const [layout, setLayout] = useState<Layout>(loadLayout);
  useEffect(() => { try { localStorage.setItem(LAYOUT, JSON.stringify(layout)); } catch { /* private mode */ } }, [layout]);
  const railWidth = layout.railCollapsed ? RAIL_COLLAPSED : layout.rail;
  const dragRail = (x: number) => setLayout(l => ({ ...l, railCollapsed: false, rail: Math.min(RAIL_MAX, Math.max(RAIL_MIN, x)) }));
  const dragChat = (x: number) => setLayout(l => { const width = window.innerWidth - railWidth; const share = (x - railWidth) / width; return { ...l, chat: Math.min(0.75, Math.max(CHAT_MIN / width, share)) }; });
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
  const desk = hideChat && campaignId ? deskRole(route) : null;
  return (
    <div className="shell" data-testid="shell" style={{ '--rail-w': `${railWidth}px`, '--chat-w': `${Math.round(layout.chat * 100)}%` } as React.CSSProperties}>
      <TopBar route={route} campaigns={campaigns.data || []} campaignId={campaignId} monitor={monitor.data} workspace={workspace.data}
        onSearch={() => setPalette(true)} onMonitor={() => setDrawer(open => !open)} wide={wide} onWide={() => setWide(w => !w)} version={summary.data?.campaign.version} />
      {campaignId && summary.data?.stage.stage === 'optimize' ? <IterationProgress campaignId={campaignId} /> : null}
      <div className="body">
        <Rail route={route} summary={summary.data} monitor={monitor.data} collapsed={layout.railCollapsed} onToggle={() => setLayout(l => ({ ...l, railCollapsed: !l.railCollapsed }))} />
        <Gutter onDrag={dragRail} label="rail" />
        <div className={'main' + (hideChat && route.page !== 'new' ? (desk ? ' desk-column' : ' split') : (wide && route.page !== 'new') || (route.page !== 'new' && !threadId) ? ' wide' : '')} data-detached={hideChat ? '1' : undefined}>
          {route.page === 'new' ? <SetupChat setupId={route.id} /> : hideChat ? <div className={desk ? 'chat desk-host' : 'chat-strip'} data-testid={desk ? 'desk-column' : 'chat-strip'}>
            <div className="strip-head"><button className="btn quiet small" onClick={detach} title="Bring the lead's chat back into this window" data-testid="reattach-strip">Reattach chat</button>{!desk ? <span className="faint small strip-label">chat open in its own window</span> : <span className="faint small">lead chat is in its own window</span>}</div>
            {desk && campaignId ? <DeskPanel campaignId={campaignId} role={desk} mode="column" /> : null}
          </div> : campaignId && threadId ? <ThreadChat campaignId={campaignId} threadId={threadId} route={route} onDetach={detach} /> : <div className="chat" />}
          {route.page === 'new' || (!(hideChat && !desk) && !(wide || !threadId)) ? <Gutter onDrag={dragChat} label="chat" /> : null}
          <StagePanel route={route} campaignId={campaignId} threadId={threadId} desk={!desk} />
        </div>
      </div>
      {drawer && campaignId ? <MonitorDrawer campaignId={campaignId} route={route} onClose={() => setDrawer(false)} /> : null}
      {palette && campaignId ? <SearchPalette campaignId={campaignId} route={route} onClose={() => setPalette(false)} /> : null}
    </div>
  );
}
