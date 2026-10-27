/** The monitor behind the pill: the rows, then tabs into the monitor's pages. Resources poll only while it is open. */
import { useEffect } from 'react';
import { useMonitor } from '../api/queries';
import { Rows } from './Rows';
import { Failed, Loading } from '../primitives/ui';
import { formatHash, type Route } from '../router/routes';
import { track } from '../telemetry/events';

export function MonitorDrawer({ campaignId, route, onClose }: { campaignId: string; route: Route; onClose: () => void }) {
  const monitor = useMonitor(campaignId);
  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  const tabs = [['resources', 'Resources'], ['usage', 'Usage'], ['races', 'Race progress'], ['agents', 'Agents'], ['digest', 'Away digest']] as const;
  return (
    <aside className="drawer" data-testid="monitor-drawer" aria-label="Monitor">
      <div className="row" style={{ marginBottom: 10 }}><h2 className="grow">Monitor</h2><button className="btn quiet small" onClick={onClose}>Close</button></div>
      {monitor.isPending ? <Loading /> : monitor.error ? <Failed error={monitor.error} /> : <Rows monitor={monitor.data} />}
      <nav className="tabs" style={{ marginTop: 12 }}>{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'monitor', sub: key }, route.thread)} onClick={() => { track('monitor.alert_acted', { tab: key }); onClose(); }}>{label}</a>)}</nav>
    </aside>
  );
}
