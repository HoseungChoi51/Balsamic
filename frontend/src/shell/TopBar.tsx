import type { CampaignRow, Monitor, WorkspaceInfo } from '../api/types';
import { Pill } from '../primitives/ui';
import { formatHash, navigate, type Route } from '../router/routes';
import { track } from '../telemetry/events';
import { AutopilotToggle } from '../monitor/AutopilotToggle';

export function TopBar({ route, campaigns, campaignId, monitor, workspace, onMonitor, onSearch, wide, onWide, version }:
  { route: Route; campaigns: CampaignRow[]; campaignId: string | null; monitor?: Monitor; workspace?: WorkspaceInfo; onMonitor: () => void; onSearch: () => void; wide: boolean; onWide: () => void; version?: number }) {
  const current = campaigns.find(c => c.id === campaignId);
  const pill = monitor?.pill;
  return (
    <header className="topbar">
      <a className="brand" href="#home" title="Home" data-testid="brand">Balsamic</a>
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
      {current ? <button className="btn small" onClick={onSearch} data-testid="search-button" title="Pages, threads and messages (Ctrl+K)">Search ⌘K</button> : null}
      {current ? <AutopilotToggle campaign={current} version={version} threadId={route.thread} /> : null}
      {workspace?.dev_mode ? <Pill title="The Pi harness runs a dev profile">dev</Pill> : null}
      {current ? <button className={'btn control ' + (pill?.state || '')} data-testid="monitor-pill" onClick={() => { track('monitor.open', { state: pill?.state || 'unknown' }); onMonitor(); }} title="Open the monitor drawer">
        <span className="dot" />{pill ? pill.text : 'Monitor'}</button> : null}
      <button className="btn quiet small" onClick={onWide} title={wide ? 'Show the conversation' : 'Expand the page'} data-testid="toggle-wide">{wide ? 'Chat' : 'Expand'}</button>
    </header>
  );
}
