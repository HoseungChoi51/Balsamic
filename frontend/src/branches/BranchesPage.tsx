/** The branch map (M1): every thread with its summary card. Until then, the list of threads. */
import type { PageProps } from '../shell/StagePanel';
import { useThreads } from '../api/queries';
import { Empty, Failed, Loading, Pill, Section, when } from '../primitives/ui';
import { formatHash } from '../router/routes';

export default function BranchesPage({ campaignId, route }: PageProps) {
  const threads = useThreads(campaignId);
  if (threads.isPending) return <Loading />;
  if (threads.error) return <Failed error={threads.error} />;
  return (
    <div className="col">
      <div className="stage-head"><h1>Branches</h1><span className="muted small">fork, park and merge arrive with milestone M1</span></div>
      <Section title={`Threads (${threads.data.threads.length})`}>
        {threads.data.threads.length ? threads.data.threads.map(t => <a key={t.id} className={'card row' + (route.thread === t.id ? ' selected' : '')} href={formatHash({ page: route.page === 'branches' ? 'monitor' : route.page }, t.id)} data-testid="thread-card">
          <strong className="grow">{t.title}</strong><Pill>{t.name}</Pill><span className="small faint">{t.message_count} messages · {when(t.last_activity_at)}</span>{t.busy ? <Pill tone="agent">lead working</Pill> : null}</a>) : <Empty>No thread yet.</Empty>}
      </Section>
    </div>
  );
}
