import type { CampaignRow, Monitor, WorkspaceInfo } from '../api/types';
import { Disabled, Pill } from '../primitives/ui';
import { formatHash, navigate, type Route } from '../router/routes';
import { track } from '../telemetry/events';

export function TopBar({ route, campaigns, campaignId, monitor, workspace, onMonitor, wide, onWide }:
  { route: Route; campaigns: CampaignRow[]; campaignId: string | null; monitor?: Monitor; workspace?: WorkspaceInfo; onMonitor: () => void; wide: boolean; onWide: () => void }) {
  const current = campaigns.find(c => c.id === campaignId);
  const pill = monitor?.pill;
  return (
    <header className="topbar">
      <span className="brand">Balsamic</span>
      <select aria-label="Campaign" value={campaignId || ''} data-testid="campaign-switch" onChange={e => {
        const value = e.target.value;
        if (value === '__new') navigate('#new');
        else { const row = campaigns.find(c => c.id === value); if (row) navigate(formatHash({ page: route.page === 'new' ? 'monitor' : route.page, sub: route.sub }, row.active_thread_id)); }
      }}>
        {!current ? <option value="">Choose a campaign</option> : null}
        {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        <option value="__new">+ New campaign…</option>
      </select>
      {current ? <Pill tone={current.stage_pinned ? 'you' : ''} title={current.stage_basis}><span className="stagebadge" data-testid="stage">{current.stage}</span>{current.stage_pinned ? ' (pinned)' : ''}</Pill> : null}
      <span className="grow" />
      <Disabled why="Search arrives with the library milestone"><button className="btn small">Search ⌘K</button></Disabled>
      {current ? <Disabled why="Autopilot arrives with the monitor milestone; the lead acts on requests"><button className="btn small">Autopilot off</button></Disabled> : null}
      {workspace?.dev_mode ? <Pill title="The Pi harness runs a dev profile">dev</Pill> : null}
      {current ? <button className={'pill ' + (pill?.state || '')} data-testid="monitor-pill" onClick={() => { track('monitor.open', { state: pill?.state || 'unknown' }); onMonitor(); }} title="Open the monitor">
        {pill ? pill.text : 'Monitor'}</button> : null}
      <button className="btn quiet small" onClick={onWide} title={wide ? 'Show the conversation' : 'Expand the page'} data-testid="toggle-wide">{wide ? 'Chat' : 'Expand'}</button>
    </header>
  );
}
