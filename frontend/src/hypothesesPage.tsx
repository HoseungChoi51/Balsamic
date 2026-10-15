import type { State } from './api';
import { Hypotheses } from './views';
import type { WorkspaceActions } from './views';
import { DiscussionsView } from './discussions';
import { useSubpage } from './routes';
import { PageTabs } from './ui';
import { AgentDesk } from './agentDesk';

const tabs = [['proposals', 'Proposals'], ['rounds', 'Review rounds']] as const;

/** The proposals, and the review rounds in which agents criticised and revised them. */
export function HypothesesPage({ state, actions }: { state: State; actions: WorkspaceActions }) {
  const [tab, select] = useSubpage('hypotheses', tabs.map(([id]) => id));
  return <>
    <AgentDesk state={state} refresh={actions.refresh} role="discussion_moderator" />
    <PageTabs label="Hypotheses" tabs={tabs} current={tab} onSelect={select} />
    {tab === 'rounds' ? <DiscussionsView key={state.campaign?.id || 'no-campaign'} state={state} /> : <Hypotheses state={state} actions={actions} />}
  </>;
}
