import { useState } from 'react';
import { api, errorText } from './api';
import type { Json, State } from './api';
import { useCommand } from './commands';
import { AgentLog } from './agentLog';
import { CampaignMemoryView } from './implementations';
import { LlmUsageView } from './llmUsage';
import { ModelControlPanel } from './models';
import { agentPage, pageAgentRoles, roleName } from './agentLive';
import { useSubpage } from './routes';
import { Badge, Empty, ErrorNotice, PageTabs } from './ui';
import { TextContent } from './textContent';

const tabs = [['team', 'Team'], ['models', 'Models'], ['guidance', 'Guidance'], ['usage', 'Usage'], ['log', 'Log']] as const;
const pageNames: Record<string, string> = { hypotheses: 'Hypotheses', experiments: 'Experiments', implementations: 'Implementations' };

/** Everything about the campaign's agents that is not their work: who they are, their models, their guidance, their cost and their log. */
export function AgentsPage({ state, refresh, campaignId }: { state: State; refresh: () => Promise<void>; campaignId?: string }) {
  const [tab, select] = useSubpage('agents', tabs.map(([id]) => id));
  return <>
    <PageTabs label="Agents" tabs={tabs} current={tab} onSelect={select} />
    {tab === 'team' ? <TeamView key={state.campaign?.id} state={state} refresh={refresh} />
      : tab === 'models' ? <ModelControlPanel key={state.campaign?.id || 'no-campaign'} state={state} refresh={refresh} />
      : tab === 'guidance' ? <CampaignMemoryView state={state} refresh={refresh} />
      : tab === 'usage' ? <LlmUsageView campaignId={campaignId || state.campaign?.id || undefined} />
      : <><div className="page-heading"><div><span className="eyebrow">Agents</span><h1>Agent log</h1><p>Every recorded tool call and event of this campaign's agents.</p></div></div>
        {state.campaign ? <AgentLog key={state.campaign.id} campaignId={state.campaign.id} /> : <Empty icon="notebook" title="No campaign yet">Create a campaign to see its agents' log.</Empty>}</>}
  </>;
}

function TeamView({ state, refresh }: { state: State; refresh: () => Promise<void> }) {
  const runtime = state.agent_runtime;
  const command = useCommand(state.campaign);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [login, setLogin] = useState<Json | null>(null);
  const heading = <div className="page-heading"><div><span className="eyebrow">Agents</span><h1>The team on this campaign.</h1>
    <p>The lead agent takes your requests in the chat. The agents in charge of Hypotheses, Experiments and Implementations take requests on their pages. Assistants are created for one assignment each.</p></div></div>;
  if (!state.campaign || !runtime?.configuration?.enabled) return <>{heading}<section className="panel"><Empty icon="spark" title="No agent team yet">
    {state.campaign ? <>This campaign is run by the campaign manager. Start the agent team on the <a href="#agents/models">Models</a> tab to hand it to a lead agent.</> : 'Create a campaign first.'}</Empty></section></>;
  const config = runtime.configuration;
  const agents: Json[] = runtime.agents || [];
  async function signIn() {
    setBusy(true); setError('');
    try { setLogin(await api(`/api/campaigns/${state.campaign!.id}/agents/login`, { method: 'POST', body: '{}' })); }
    catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  async function control(action: string, agent?: Json) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await command('agent.control', { action, expected_control_revision: (agent || config).control_revision, ...(agent ? { agent_id: agent.id } : {}) });
      setNotice(`${action === 'resume' ? 'Resume' : action === 'pause' ? 'Pause' : 'Stop'} requested; saved work is retained.`);
      try { await refresh(); } catch { /* Accepted control must not be resent after a refresh failure. */ }
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  const atWork = (agent: Json) => ['queued', 'running', 'paused'].includes(agent.status);
  const standing = agents.filter(agent => agent.role === 'lead' || pageAgentRoles.includes(agent.role));
  const assistants = agents.filter(agent => !standing.includes(agent));
  const working = assistants.filter(atWork), finished = assistants.filter(agent => !atWork(agent));
  const parentName = (agent: Json) => roleName(agents.find(other => other.id === agent.parent_agent_id)?.role || 'lead').toLowerCase();
  const card = (agent: Json) => {
    const page = agentPage(agent.role);
    return <article key={agent.id} className={agent.role === 'lead' || page ? '' : 'pi-child'}>
      <div><strong>{roleName(agent.role)}</strong> <Badge>{agent.status}</Badge>{page && <> · <a href={`#${page}`}>{pageNames[page]}</a></>}</div>
      {agent.role === 'implementation_builder' && agent.status === 'stopped' && runtime.development?.workspaces?.some((workspace: Json) => workspace.submissions?.length > 0) &&
        <p className="help-text">Earlier builder session. Its submitted source and review remain in the implementation workspace.</p>}
      {agent.role !== 'lead' && !page && <p>{agent.objective.length > 300 ? agent.objective.slice(0, 300) + '…' : agent.objective}</p>}
      <small>{[agent.model, agent.reasoning_effort, agent.role !== 'lead' && !page ? `reports to the ${parentName(agent)}` : ''].filter(Boolean).join(' · ')}</small>
      <details><summary>Assignment, activity and references</summary><TextContent text={agent.objective} /><TextContent text={agent.activity || 'Waiting for the next recorded event.'} />
        <a href={`/api/campaigns/${state.campaign!.id}/agents/records/${agent.id}`} target="_blank" rel="noreferrer">Inspect saved agent record</a>
        {agent.artifact_ids?.map((id: string) => <p key={id}><a href={`/api/campaigns/${state.campaign!.id}/agents/records/${id}`} target="_blank" rel="noreferrer">Saved artifact · {id.slice(-12)}</a></p>)}
        {agent.evidence_ids?.length > 0 && <p>Evidence: {agent.evidence_ids.join(', ')}</p>}
      </details>
      {agent.role !== 'lead' && <div className="research-progress-actions">
        <button className="button small secondary" disabled={busy || agent.status === 'completed'} onClick={() => void control(agent.status === 'paused' ? 'resume' : 'pause', agent)}>{agent.status === 'paused' ? 'Resume' : 'Pause'}</button>
        <button className="button small secondary" disabled={busy || ['completed', 'stopped'].includes(agent.status)} onClick={() => void control('stop', agent)}>Stop</button>
      </div>}
    </article>;
  };
  return <>{heading}
    <section className="research-progress pi-panel" aria-label="Agent team">
      <div className="research-progress-heading"><div><h2>All agents</h2><Badge>{!config.provider?.configured ? 'waiting for sign-in' : config.status}</Badge></div>
        <div className="research-progress-actions">
          {config.status === 'running' ? <button className="button small secondary" disabled={busy} onClick={() => void control('pause')}>Pause agents</button>
            : <button className="button small primary" disabled={busy} onClick={() => void control('resume')}>Resume agents</button>}
          <button className="button small secondary" disabled={busy || config.status === 'stopped'} onClick={() => void control('stop')}>Stop agents</button>
        </div>
      </div>
      {!config.provider?.configured && <div role="status"><p>{config.provider?.reason || 'Pi needs a signed-in model provider.'} Your assignments are saved.</p>
        <button className="button secondary" disabled={busy} onClick={() => void signIn()}>Get browser sign-in link</button>
        {(login || config.provider?.login)?.status === 'pending' && <p>Open <a href={(login || config.provider.login).url} target="_blank" rel="noreferrer">OpenAI sign-in</a> and enter <strong>{(login || config.provider.login).user_code}</strong>. Pi detects completion automatically. The code expires after 15 minutes.</p>}
      </div>}
      {config.sync_error && <ErrorNotice text={`Agent status could not be synchronized: ${config.sync_error}. Saved work is retained; synchronization will retry.`} />}
      <p className="help-text">Pausing or stopping keeps every saved record. Experiments that are already running are controlled on the Experiments page.</p>
      <ErrorNotice text={error} />{notice && <p role="status">{notice}</p>}
      <div className="pi-agent-tree">{standing.map(card)}</div>
      {working.length > 0 && <><h3 className="team-group">Assistants at work</h3><div className="pi-agent-tree">{working.map(card)}</div></>}
      {finished.length > 0 && <details className="team-finished"><summary>{finished.length} finished {finished.length === 1 ? 'assistant' : 'assistants'}</summary>
        <div className="pi-agent-tree">{finished.map(card)}</div></details>}
    </section></>;
}
