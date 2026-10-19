import { RAIL, PAGES, formatHash, type Route } from '../router/routes';
import type { Monitor, Summary } from '../api/types';

export function Rail({ route, summary, monitor }: { route: Route; summary?: Summary; monitor?: Monitor }) {
  const counts: Record<string, number | undefined> = {
    hypotheses: summary?.counts.hypothesis, experiments: summary?.counts.trial, inbox: monitor ? monitor.rows.needs_you.decisions + monitor.rows.needs_you.issues + monitor.rows.needs_you.questions : undefined,
    branches: summary?.counts.thread,
  };
  return (
    <nav className="rail" aria-label="Pages">
      {RAIL.map(page => (
        <a key={page} href={formatHash({ page }, route.thread)} className={route.page === page ? 'active' : ''} data-testid={`rail-${page}`} title={PAGES[page].description}>
          <span>{PAGES[page].title}</span>{counts[page] ? <span className="count">{counts[page]}</span> : null}
        </a>
      ))}
    </nav>
  );
}
