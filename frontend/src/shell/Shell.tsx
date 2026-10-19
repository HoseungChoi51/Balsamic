import { useEffect, useState } from 'react';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { StagePanel } from './StagePanel';
import { ThreadChat } from '../chat/ThreadChat';
import { MonitorDrawer } from '../monitor/MonitorDrawer';
import { IterationProgress } from '../evolution/IterationProgress';
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
  useEffect(() => { try { localStorage.setItem(WIDE, wide ? '1' : '0'); } catch { /* private mode */ } }, [wide]);
  useEffect(() => { setDrawer(false); }, [campaignId]);
  return (
    <div className="shell" data-testid="shell">
      <TopBar route={route} campaigns={campaigns.data || []} campaignId={campaignId} monitor={monitor.data} workspace={workspace.data}
        onMonitor={() => setDrawer(open => !open)} wide={wide || route.page === 'new'} onWide={() => setWide(w => !w)} version={summary.data?.campaign.version} />
      {campaignId && summary.data?.stage.stage === 'optimize' ? <IterationProgress campaignId={campaignId} /> : null}
      <div className="body">
        <Rail route={route} summary={summary.data} monitor={monitor.data} />
        <div className={'main' + (wide || route.page === 'new' || !threadId ? ' wide' : '')}>
          {campaignId && threadId ? <ThreadChat campaignId={campaignId} threadId={threadId} route={route} /> : <div className="chat" />}
          <StagePanel route={route} campaignId={campaignId} threadId={threadId} />
        </div>
      </div>
      {drawer && campaignId ? <MonitorDrawer campaignId={campaignId} route={route} onClose={() => setDrawer(false)} /> : null}
    </div>
  );
}
