import { RAIL, PAGES, formatHash, type Route } from '../router/routes';
import type { Monitor, Summary } from '../api/types';

const SHORT: Record<string, string> = { overview: 'Ov', note: 'Nt', hypotheses: 'Hy', experiments: 'Ex', evolution: 'Ev', files: 'Fi', inbox: 'In', monitor: 'Mo', library: 'Li', branches: 'Br' };

export function Rail({ route, summary, monitor, collapsed = false, onToggle }: { route: Route; summary?: Summary; monitor?: Monitor; collapsed?: boolean; onToggle?: () => void }) {
  const counts: Record<string, number | undefined> = {
    hypotheses: summary?.counts.hypothesis, experiments: summary?.counts.trial, inbox: monitor ? monitor.rows.needs_you.decisions + monitor.rows.needs_you.issues + monitor.rows.needs_you.questions : undefined,
    branches: summary?.counts.thread,
  };
  return (
    <nav className={'rail' + (collapsed ? ' collapsed' : '')} aria-label="Pages" data-collapsed={collapsed ? '1' : undefined}>
      {RAIL.map(page => (
        <a key={page} href={formatHash({ page }, route.thread)} className={route.page === page ? 'active' : ''} data-testid={`rail-${page}`} title={collapsed ? `${PAGES[page].title}: ${PAGES[page].description}` : PAGES[page].description}>
          <span>{collapsed ? SHORT[page] || PAGES[page].title.slice(0, 2) : PAGES[page].title}</span>{counts[page] ? <span className={'count' + (page === 'inbox' ? ' waiting' : '')} title={page === 'inbox' ? `${counts[page]} waiting for you` : undefined}>{counts[page]}</span> : null}
        </a>
      ))}
      <span className="grow" />
      {onToggle ? <button type="button" className="btn quiet small rail-toggle" onClick={onToggle} title={collapsed ? 'Show the page names' : 'Fold the rail to its initials'} aria-expanded={!collapsed} data-testid="rail-toggle">{collapsed ? '›' : '‹ fold'}</button> : null}
    </nav>
  );
}
