/** The right side: the page the route names. Every page is a sub page of the rail; the chat stays beside it. */
import { Suspense, lazy } from 'react';
import type { Route } from '../router/routes';
import { pageTitle } from '../router/routes';
import { Loading } from '../primitives/ui';

const pages = {
  note: lazy(() => import('../note/ProblemNotePage')), hypotheses: lazy(() => import('../hypotheses/HypothesesPage')), experiments: lazy(() => import('../experiments/ExperimentsPage')),
  evolution: lazy(() => import('../evolution/EvolutionPage')), files: lazy(() => import('../files/FilesPage')), inbox: lazy(() => import('../inbox/InboxPage')),
  monitor: lazy(() => import('../monitor/MonitorPage')), library: lazy(() => import('../library/LibraryPage')), branches: lazy(() => import('../branches/BranchesPage')),
  new: lazy(() => import('../setup/NewCampaign')),
};

export interface PageProps { route: Route; campaignId: string; threadId: string | null }

export function StagePanel({ route, campaignId, threadId }: { route: Route; campaignId: string | null; threadId: string | null }) {
  const Page = pages[route.page as keyof typeof pages] || pages.monitor;
  if (route.page !== 'new' && !campaignId) return <main className="stage"><div className="empty">Choose a campaign above, or start one.</div></main>;
  return (
    <main className="stage" data-testid={`page-${route.page}`} data-page={route.page} data-sub={route.sub || ''}>
      <h1 className="sr-only">{pageTitle(route.page, route.sub)}</h1>
      <Suspense fallback={<Loading what="Opening the page" />}>
        <Page route={route} campaignId={campaignId || ''} threadId={threadId} />
      </Suspense>
    </main>
  );
}
