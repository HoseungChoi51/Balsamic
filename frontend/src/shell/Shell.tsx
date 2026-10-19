import { useEffect, useState } from 'react';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { StagePanel } from './StagePanel';
import { ThreadChat } from '../chat/ThreadChat';
import { MonitorDrawer } from '../monitor/MonitorDrawer';
import { IterationProgress } from '../evolution/IterationProgress';
import { SearchPalette } from './SearchPalette';
import { RAIL, formatHash, navigate } from '../router/routes';
import { useCampaigns, useMonitor, useSummary, useWorkspace } from '../api/queries';
import type { Route } from '../router/routes';

const WIDE = 'balsamic.panelWide';

export function Shell({ route, campaignId, threadId }: { route: Route; campaignId: string | null; threadId: string | null }) {
  const workspace = useWorkspace();
  const campaigns = useCampaigns();
  const summary = useSummary(campaignId);
  const monitor = useMonitor(campaignId);
  const [wide, setWide] = useState(() => { try { return localStorage.getItem(WIDE) === '1'; } catch { return false; } });
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
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
  return (
    <div className="shell" data-testid="shell">
      <TopBar route={route} campaigns={campaigns.data || []} campaignId={campaignId} monitor={monitor.data} workspace={workspace.data}
        onSearch={() => setPalette(true)} onMonitor={() => setDrawer(open => !open)} wide={wide || route.page === 'new'} onWide={() => setWide(w => !w)} version={summary.data?.campaign.version} />
      {campaignId && summary.data?.stage.stage === 'optimize' ? <IterationProgress campaignId={campaignId} /> : null}
      <div className="body">
        <Rail route={route} summary={summary.data} monitor={monitor.data} />
        <div className={'main' + (wide || route.page === 'new' || !threadId ? ' wide' : '')}>
          {campaignId && threadId ? <ThreadChat campaignId={campaignId} threadId={threadId} route={route} /> : <div className="chat" />}
          <StagePanel route={route} campaignId={campaignId} threadId={threadId} />
        </div>
      </div>
      {drawer && campaignId ? <MonitorDrawer campaignId={campaignId} route={route} onClose={() => setDrawer(false)} /> : null}
      {palette && campaignId ? <SearchPalette campaignId={campaignId} route={route} onClose={() => setPalette(false)} /> : null}
    </div>
  );
}
