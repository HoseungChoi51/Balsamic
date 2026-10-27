/** The right side: the page the route names. Every page is a sub page of the rail; the chat stays beside it. */
import { Component, Suspense, lazy, type ReactNode } from 'react';
import type { Route } from '../router/routes';
import { pageTitle } from '../router/routes';
import { Loading } from '../primitives/ui';
import { DeskPanel, deskRole } from '../desks/AgentDesk';
import { NextStep } from './NextStep';
import { PanelsOnPage } from '../panels/PanelsOnPage';
import { useCampaigns } from '../api/queries';

const RELOADED = 'balsamic.chunkReload';

/** A page chunk that fails to load (a rebuild changed the file names while this tab was open) reloads the tab once. */
function lazyPage<T extends { default: React.ComponentType<PageProps> }>(load: () => Promise<T>) {
  return lazy(() => load().catch(error => {
    let reloaded = false;
    try { reloaded = sessionStorage.getItem(RELOADED) === location.hash; if (!reloaded) sessionStorage.setItem(RELOADED, location.hash); } catch { /* private mode */ }
    if (!reloaded) { location.reload(); return new Promise<T>(() => undefined); }
    throw error;
  }));
}

const pages = {
  overview: lazyPage(() => import('../overview/OverviewPage')),
  note: lazyPage(() => import('../note/ProblemNotePage')), hypotheses: lazyPage(() => import('../hypotheses/HypothesesPage')), experiments: lazyPage(() => import('../experiments/ExperimentsPage')),
  evolution: lazyPage(() => import('../evolution/EvolutionPage')), files: lazyPage(() => import('../files/FilesPage')), inbox: lazyPage(() => import('../inbox/InboxPage')),
  monitor: lazyPage(() => import('../monitor/MonitorPage')), library: lazyPage(() => import('../library/LibraryPage')), branches: lazyPage(() => import('../branches/BranchesPage')),
  new: lazyPage(() => import('../setup/NewCampaign')),
};

export interface PageProps { route: Route; campaignId: string; threadId: string | null }

/** A page that throws shows what went wrong instead of a blank panel; Reload is one click away. */
class PageBoundary extends Component<{ where: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { where: string }) { if (prev.where !== this.props.where && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card" role="alert" data-testid="page-error">
        <strong>This page could not be drawn.</strong>
        <pre className="small" style={{ whiteSpace: 'pre-wrap' }}>{String(this.state.error.message || this.state.error)}</pre>
        <div className="row"><button className="btn small" onClick={() => this.setState({ error: null })}>Try again</button><button className="btn small" onClick={() => location.reload()}>Reload</button></div>
      </div>
    );
  }
}

export function StagePanel({ route, campaignId, threadId, desk = true }: { route: Route; campaignId: string | null; threadId: string | null; desk?: boolean }) {
  const Page = pages[route.page as keyof typeof pages] || pages.monitor;
  // Without a campaign a page shows nothing, except Monitor's machine and models, which are the workspace's.
  if (route.page !== 'new' && route.page !== 'monitor' && !campaignId) return <main className="stage"><div className="empty" data-testid="no-campaign">Choose a campaign above, or start one.</div></main>;
  const role = campaignId ? deskRole(route) : null;
  const campaigns = useCampaigns();
  const step = campaigns.data?.find(c => c.id === campaignId)?.next_step;
  return (
    <main className={'stage' + (desk && role ? ' with-desk' : '')} data-testid={`page-${route.page}`} data-page={route.page} data-sub={route.sub || ''}>
      <h1 className="sr-only">{pageTitle(route.page, route.sub)}</h1>
      {route.page !== 'new' ? <NextStep step={step} threadId={threadId} page={route.sub ? `${route.page}/${route.sub}` : route.page} /> : null}
      {route.page !== 'new' && campaignId ? <PanelsOnPage campaignId={campaignId} page={route.sub ? `${route.page}/${route.sub}` : route.page} placement="top" threadId={threadId} /> : null}
      <PageBoundary where={route.raw}>
        <Suspense fallback={<Loading what="Opening the page" />}>
          <Page route={route} campaignId={campaignId || ''} threadId={threadId} />
        </Suspense>
      </PageBoundary>
      {route.page !== 'new' && campaignId ? <PanelsOnPage campaignId={campaignId} page={route.sub ? `${route.page}/${route.sub}` : route.page} placement="bottom" threadId={threadId} /> : null}
      {desk && role && campaignId ? <DeskPanel campaignId={campaignId} role={role} mode="docked" /> : null}
    </main>
  );
}
