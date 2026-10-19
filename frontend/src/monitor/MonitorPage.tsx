/** The monitor's pages: resources, model usage, race progress, the agent team, the log, models, guidance, the away digest. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useMonitor, useRead, useSummary } from '../api/queries';
import { Rows } from './Rows';
import { Empty, Failed, Kv, Loading, Pill, Section, num, statusTone, when } from '../primitives/ui';
import { formatHash } from '../router/routes';
import { send } from '../commands/bus';
import { AgentDesk } from '../desks/AgentDesk';
import { AwayDigest } from './AwayDigest';
import { CampaignRemoval } from '../setup/CampaignRemoval';

export default function MonitorPage({ campaignId, route }: PageProps) {
  const sub = route.sub || 'resources';
  const monitor = useMonitor(campaignId);
  const tabs = [['resources', 'Resources'], ['usage', 'Model usage'], ['races', 'Race progress'], ['agents', 'Agents'], ['log', 'Agent log'], ['models', 'Models'], ['guidance', 'Guidance'], ['digest', 'Away digest']] as const;
  return (
    <div className="col">
      <div className="stage-head"><h1>Monitor</h1>{monitor.data ? <Pill tone={monitor.data.pill.state}>{monitor.data.pill.text}</Pill> : null}</div>
      <nav className="tabs">{tabs.map(([key, label]) => <a key={key} href={formatHash({ page: 'monitor', sub: key }, route.thread)} className={sub === key ? 'active' : ''}>{label}</a>)}</nav>
      {sub === 'resources' ? <Resources campaignId={campaignId} /> : null}
      {sub === 'usage' ? <Usage campaignId={campaignId} /> : null}
      {sub === 'races' ? <Races campaignId={campaignId} /> : null}
      {sub === 'agents' ? <Agents campaignId={campaignId} /> : null}
      {sub === 'log' ? <Log campaignId={campaignId} /> : null}
      {sub === 'models' ? <Models campaignId={campaignId} /> : null}
      {sub === 'guidance' ? <Guidance campaignId={campaignId} /> : null}
      {sub === 'digest' ? <AwayDigest campaignId={campaignId} /> : null}
      {monitor.data && sub === 'resources' ? <Rows monitor={monitor.data} /> : null}
    </div>
  );
}

function Resources({ campaignId }: { campaignId: string }) {
  const snapshot = useRead<Record<string, unknown>>(['resources', campaignId], `/api/v1/resources?campaign_id=${campaignId}`, { refetchInterval: 5000, staleTime: 2000 });
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  if (snapshot.isPending) return <Loading what="Reading the machine" />;
  if (snapshot.error) return <Failed error={snapshot.error} />;
  const data = snapshot.data;
  const host = (data.host || data.machine || {}) as Record<string, unknown>;
  const level = String(data.level || summary.data?.row?.autopilot ? data.level : data.level || '');
  const setLevel = async (value: string) => {
    setError(null);
    try { await fetch('/api/v1/resources/level', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: value, reason: 'set from the monitor' }) }).then(r => { if (!r.ok) throw new Error('Could not set the level'); }); await queryClient.invalidateQueries({ queryKey: ['resources'] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <>
      <Section title="Machine" right={<span className="small faint">measured every 5 s while this page is open</span>}>
        <Kv rows={[['CPU busy', num(host.cpu_percent ?? host.cpu_busy_percent, 0, ' %')], ['Memory', host.memory_used_bytes != null ? `${num(Number(host.memory_used_bytes) / 1e9, 1, ' GB')} of ${num(Number(host.memory_total_bytes) / 1e9, 1, ' GB')}` : <span className="faint">unknown</span>],
          ['GPU', host.gpu ? JSON.stringify(host.gpu).slice(0, 120) : <span className="faint">not reported</span>], ['Workers', `${String(data.running ?? data.busy ?? '?')} running of ${String(data.max_workers ?? data.limit ?? '?')}`]]} />
      </Section>
      <Section title="Resource level" right={<span className="small faint">yours alone; agents plan within it</span>}>
        <div className="row wrap">{['cautious', 'balanced', 'aggressive'].map(value => <button key={value} className={'btn small' + (level === value ? ' primary' : '')} onClick={() => setLevel(value)}>{value}</button>)}{error ? <span className="pill bad">{error}</span> : null}</div>
      </Section>
      <AgentDesk campaignId={campaignId} role="resource_planner" />
      <CampaignRemoval campaignId={campaignId} />
      <details className="card"><summary>Raw snapshot</summary><pre>{JSON.stringify(data, null, 1).slice(0, 6000)}</pre></details>
    </>
  );
}

function Usage({ campaignId }: { campaignId: string }) {
  const usage = useRead<Record<string, unknown>>(['usage', campaignId], `/api/v1/llm-usage?campaign_id=${campaignId}`);
  if (usage.isPending) return <Loading />;
  if (usage.error) return <Failed error={usage.error} />;
  const budget = (usage.data.budget || {}) as Record<string, unknown>;
  const agents = (usage.data.agents || {}) as Record<string, Record<string, unknown>>;
  return (
    <>
      <Section title="Model spend"><Kv rows={[['Charged to agents', num(budget.agent_charged_usd, 3, ' $')], ['Committed to implementations', num(budget.implementation_committed_usd, 3, ' $')], ['Cap', budget.cap_usd != null ? num(budget.cap_usd, 2, ' $') : <span className="faint">none set</span>], ['Family', String(usage.data.family || 'unknown')]]} /></Section>
      <Section title="Agents"><table><thead><tr><th>Agent</th><th>Role</th><th>Status</th><th>Model</th></tr></thead><tbody>{Object.entries(agents).map(([id, a]) => <tr key={id}><td className="mono small">{id}</td><td>{String(a.role)}</td><td><Pill tone={statusTone(String(a.status))}>{String(a.status)}</Pill></td><td>{String(a.provider || '')}/{String(a.model)} {a.effort ? `(${a.effort})` : ''}</td></tr>)}</tbody></table></Section>
      <details className="card"><summary>Raw usage</summary><pre>{JSON.stringify(usage.data, null, 1).slice(0, 6000)}</pre></details>
    </>
  );
}

function Races({ campaignId }: { campaignId: string }) {
  const summary = useSummary(campaignId);
  const studies = summary.data?.studies || [];
  return (
    <Section title="Race progress">
      {studies.length ? studies.map(s => <RaceRow key={String(s.id)} studyId={String(s.id)} goal={String(s.goal || s.id)} />) : <Empty>No study yet.</Empty>}
    </Section>
  );
}
function RaceRow({ studyId, goal }: { studyId: string; goal: string }) {
  const race = useRead<{ race: Record<string, unknown> | null }>(['race', studyId], `/api/v1/studies/${studyId}/race`);
  const r = race.data?.race;
  return <div className="card"><div className="row"><strong className="grow">{goal}</strong>{r ? <Pill tone={statusTone(String(r.status))}>{String(r.status)}</Pill> : <span className="faint small">no race</span>}</div>{r ? <Kv rows={[['Rung', String(r.rung ?? r.current_rung ?? 'unknown')], ['Deadline', when(r.deadline_at)]]} /> : null}</div>;
}

function Agents({ campaignId }: { campaignId: string }) {
  const team = useRead<{ configuration: Record<string, unknown> | null; agents: Record<string, unknown>[]; questions: unknown[] }>(['agents', campaignId], `/api/v1/campaigns/${campaignId}/agents`, { refetchInterval: 5000 });
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  if (team.isPending) return <Loading />;
  if (team.error) return <Failed error={team.error} />;
  const config = team.data.configuration;
  const control = async (action: 'pause' | 'resume' | 'stop') => {
    const campaign = summary.data?.campaign; if (!campaign || !config) return;
    setError(null);
    try { await send({ operation: 'agent.control', campaignId, expectedRevision: campaign.version, payload: { action, expected_control_revision: config.control_revision } }); await queryClient.invalidateQueries({ queryKey: ['agents', campaignId] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <>
      <Section title="Team" right={config ? <div className="row"><button className="btn small" onClick={() => control('pause')}>Pause</button><button className="btn small" onClick={() => control('resume')}>Resume</button><button className="btn small" onClick={() => control('stop')}>Stop</button></div> : null}>
        {config ? <Kv rows={[['Status', String(config.status)], ['Delegation', summary.data?.campaign.autonomy || ''], ['Provider', (config.provider as Record<string, unknown>)?.configured ? 'connected' : String((config.provider as Record<string, unknown>)?.reason || 'not connected')]]} /> : <Empty>No agent team yet. Your first message to the lead starts it.</Empty>}
        {error ? <div className="pill bad">{error}</div> : null}
      </Section>
      <Section title="Agents"><table><thead><tr><th>Role</th><th>Status</th><th>Activity</th><th>Model</th><th>Last</th></tr></thead><tbody>
        {team.data.agents.map(a => <tr key={String(a.id)}><td>{String(a.role)}</td><td><Pill tone={statusTone(String(a.status))}>{String(a.status)}</Pill></td><td className="small">{String(a.activity || '')}</td><td className="small">{String(a.model)}</td><td className="small faint">{when(a.last_activity_at)}</td></tr>)}
      </tbody></table></Section>
    </>
  );
}

function Log({ campaignId }: { campaignId: string }) {
  const page = useRead<{ lines: string[]; events: Record<string, unknown>[] }>(['agent-log', campaignId], `/api/campaigns/${campaignId}/agent-log?limit=200`, { refetchInterval: 5000 });
  if (page.isPending) return <Loading />;
  if (page.error) return <Failed error={page.error} />;
  return <Section title="Agent log" right={<a href={`/api/campaigns/${campaignId}/agent-log/download`}>download</a>}>{page.data.lines?.length ? <pre style={{ maxHeight: 520 }}>{page.data.lines.join('\n')}</pre> : <Empty>No tool call recorded yet.</Empty>}</Section>;
}

function Models({ campaignId }: { campaignId: string }) {
  const models = useRead<Record<string, unknown>>(['agent-models', campaignId], `/api/v1/campaigns/${campaignId}/agents/models`);
  const tiers = useRead<Record<string, unknown>>(['model-tiers'], '/api/v1/model-tiers');
  if (models.isPending || tiers.isPending) return <Loading />;
  if (models.error) return <Failed error={models.error} />;
  const list = (models.data.models || []) as Record<string, unknown>[];
  return (
    <>
      <Section title="Models" right={<Pill>{String(models.data.mode)} mode</Pill>}>
        <p className="small muted">{models.data.mode === 'dev' ? 'The Pi harness runs a dev profile: models can be chosen per agent within a family.' : 'Models are locked by the harness profile; the lead reports which it uses.'}</p>
        <table><thead><tr><th>Provider</th><th>Model</th><th>Reasoning</th><th>Context</th></tr></thead><tbody>{list.map(m => <tr key={`${m.provider}/${m.id}`}><td>{String(m.provider)}</td><td>{String(m.id)}</td><td>{m.reasoning ? (m.thinking_levels as string[]).join(', ') : 'no'}</td><td>{String(m.context_window ?? '')}</td></tr>)}</tbody></table>
      </Section>
      <details className="card"><summary>Tiers</summary><pre>{JSON.stringify(tiers.data, null, 1).slice(0, 4000)}</pre></details>
    </>
  );
}

function Guidance({ campaignId }: { campaignId: string }) {
  const guidance = useRead<{ state: { guidance: string; revision: number; guidance_revision: number }; notes: Record<string, unknown>[] }>(['guidance', campaignId], `/api/v1/campaigns/${campaignId}/guidance`);
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (guidance.isPending) return <Loading />;
  if (guidance.error) return <Failed error={guidance.error} />;
  const state = guidance.data.state;
  const save = async () => {
    const campaign = summary.data?.campaign; if (!campaign || draft === null) return;
    setError(null);
    try { await send({ operation: 'context.edit', campaignId, expectedRevision: campaign.version, payload: { content: draft, expected_revision: state.revision, reason: 'Edited on the Guidance page' } }); setDraft(null); await queryClient.invalidateQueries({ queryKey: ['guidance', campaignId] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <>
      <Section title="Researcher guidance" right={<span className="small faint">revision {state.guidance_revision}; every edit stales the agents' prepared commands</span>}>
        <textarea style={{ width: '100%', minHeight: 220 }} value={draft ?? state.guidance} onChange={e => setDraft(e.target.value)} />
        <div className="row"><button className="btn primary small" disabled={draft === null || draft === state.guidance} onClick={save}>Save</button>{draft !== null ? <button className="btn small" onClick={() => setDraft(null)}>Discard</button> : null}{error ? <span className="pill bad">{error}</span> : null}</div>
      </Section>
      <Section title="Notes">{guidance.data.notes.length ? guidance.data.notes.slice().reverse().map(n => <div key={String(n.id)} className="small" style={{ marginBottom: 6 }}><Pill>{String(n.kind)}</Pill> {String(n.content).slice(0, 300)} <span className="faint">{when(n.created_at)}</span></div>) : <Empty>No note yet.</Empty>}</Section>
    </>
  );
}
