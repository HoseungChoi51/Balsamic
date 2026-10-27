/** The monitor's pages: resources, model usage, race progress, the agent team, the log, models, guidance, the away digest. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { PageProps } from '../shell/StagePanel';
import { useMonitor, useRead, useSummary } from '../api/queries';
import { Rows } from './Rows';
import { Empty, Failed, Kv, Loading, Pill, Section, duration, num, statusTone, when } from '../primitives/ui';
import { formatHash } from '../router/routes';
import { send } from '../commands/bus';
import { AwayDigest } from './AwayDigest';
import { ModelTiers } from './ModelTiers';
import { Bars, Columns, Meter, Ring, Slots } from '../primitives/charts';

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
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  if (snapshot.isPending) return <Loading what="Reading the machine" />;
  if (snapshot.error) return <Failed error={snapshot.error} />;
  const data = snapshot.data;
  const host = (data.host || data.machine || {}) as Record<string, unknown>;
  const cpu = (host.cpu || {}) as Record<string, unknown>, memory = (host.memory || {}) as Record<string, unknown>;
  const cpuPercent = cpu.utilization_percent ?? host.cpu_percent ?? host.cpu_busy_percent;
  const memUsed = memory.used_bytes ?? host.memory_used_bytes, memTotal = memory.capacity_bytes ?? memory.total_bytes ?? host.memory_total_bytes;
  const gpus = Object.entries((host.gpu && typeof host.gpu === 'object' && !Array.isArray(host.gpu) ? (host.gpu as Record<string, unknown>).devices || host.gpu : {}) as Record<string, Record<string, unknown>>).filter(([, v]) => v && typeof v === 'object' && 'utilization_percent' in v);
  const workers = (data.workers || {}) as Record<string, unknown>;
  const admission = (data.admission || {}) as Record<string, unknown>;
  const busy = workers.running_count ?? workers.running ?? data.running, limit = workers.configured_limit ?? workers.max_workers ?? admission.max_workers ?? data.max_workers;
  const queued = workers.queued_count ?? workers.queued ?? data.queued;
  const level = String(admission.level || data.level || '');
  const levels: { id: string; label: string; summary?: string }[] = ((admission.levels || []) as { id: string; label: string; summary?: string }[]).length ? (admission.levels as { id: string; label: string; summary?: string }[]) : ['cautious', 'balanced', 'aggressive'].map(id => ({ id, label: id[0].toUpperCase() + id.slice(1) }));
  const setLevel = async (value: string) => {
    setError(null);
    try { await fetch('/api/v1/resources/level', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: value, reason: 'set from the monitor' }) }).then(r => { if (!r.ok) throw new Error('Could not set the level'); }); await queryClient.invalidateQueries({ queryKey: ['resources'] }); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <>
      <Section title="Machine" right={<span className="small faint">measured every 5 s while this page is open</span>}>
        <div className="stat-grid" data-testid="machine-stats">
          <div className="stat"><Ring percent={cpuPercent != null ? Number(cpuPercent) : null} label="CPU" /><span className="small">CPU busy<br /><span className="faint">{cpu.capacity_cores != null ? `${String(cpu.capacity_cores)} cores` : ''}</span></span></div>
          <div className="stat"><Ring percent={memUsed != null && memTotal ? Number(memUsed) / Number(memTotal) * 100 : null} label="memory" tone="info" /><span className="small">Memory<br /><span className="faint">{memUsed != null ? `${num(Number(memUsed) / 1e9, 1, ' GB')} of ${num(Number(memTotal) / 1e9, 1, ' GB')}` : 'unknown'}</span></span></div>
          {gpus.map(([name, g]) => <div key={name} className="stat"><Ring percent={Number(g.utilization_percent)} label={`GPU ${name}`} tone="accent" /><span className="small">GPU {name}<br /><span className="faint">{(Number(g.memory_used_bytes) / 2 ** 30).toFixed(1)} of {(Number(g.memory_total_bytes) / 2 ** 30).toFixed(1)} GiB</span></span></div>)}
          <div className="stat"><div className="col" style={{ gap: 6 }}><span className="small">Workers <span className="faint">{String(busy ?? '?')} of {String(limit ?? '?')}{queued ? `, ${String(queued)} queued` : ''}</span></span><Slots busy={Number(busy) || 0} limit={Number(limit) || 0} queued={Number(queued) || 0} /></div></div>
        </div>
        <Kv rows={[['CPU busy', num(cpuPercent, 0, ' %')], ['Memory', memUsed != null ? `${num(Number(memUsed) / 1e9, 1, ' GB')} of ${num(Number(memTotal) / 1e9, 1, ' GB')}` : <span className="faint">unknown</span>],
          ['GPU', gpus.length ? gpus.map(([name, g]) => `${name}: ${String(g.utilization_percent)} %`).join(' · ') : <span className="faint">not reported</span>], ['Workers', `${String(busy ?? '?')} running of ${String(limit ?? '?')}`]]} />
      </Section>
      {data.slots ? <SlotSettings slots={data.slots as SlotsView} gpuReported={gpus.length > 0} /> : null}
      <ComputeThresholds campaignId={campaignId} />
      <Section title="Resource level" right={<span className="small faint">yours alone; agents plan within it{admission.set_by ? ` · set by ${String(admission.set_by)} ${when(admission.updated_at)}` : ''}</span>}>
        <div className="level-grid" data-testid="resource-levels" data-level={level}>
          {levels.map(option => <button key={option.id} type="button" className={'level' + (level === option.id ? ' chosen' : '')} aria-pressed={level === option.id} onClick={() => setLevel(option.id)} data-testid={`level-${option.id}`}>
            <strong>{option.label}</strong>{option.summary ? <span className="small faint">{option.summary}</span> : null}
          </button>)}
        </div>
        {error ? <div className="pill bad" style={{ marginTop: 6 }}>{error}</div> : null}
      </Section>
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
  const byAgent = ((usage.data.by_agent || []) as Record<string, unknown>[]).map(r => ({ name: `${String(r.role || '')} ${String(r.agent_id || '').slice(-8)}`.trim(), value: Number(r.cost_usd ?? r.total_tokens ?? 0), title: `${String(r.calls)} calls, ${String(r.total_tokens)} tokens` }));
  const byModel = ((usage.data.by_model || []) as Record<string, unknown>[]).map(r => ({ name: String(r.model || ''), value: Number(r.cost_usd ?? r.total_tokens ?? 0), title: `${String(r.provider)} · ${String(r.calls)} calls, ${String(r.total_tokens)} tokens` }));
  const costs = ((usage.data.by_agent || []) as Record<string, unknown>[]).some(r => r.cost_usd != null);
  const fmt = (v: number) => costs ? `${v.toFixed(3)} $` : `${Math.round(v / 1000)}k tok`;
  const series = ((usage.data.series || []) as Record<string, unknown>[]).map(r => ({ x: String(r.bucket), y: Number(r.cost_usd ?? r.total_tokens ?? 0) }));
  return (
    <>
      <Section title="Model spend">
        <div className="meter-block"><div className="row"><span>Charged and committed</span><span className="faint">{budget.cap_usd != null ? <>{num(budget.cap_usd, 2, ' $')} cap</> : 'no cap set'}</span></div>
          <Meter total={budget.cap_usd != null ? Number(budget.cap_usd) : null} label="model spend" segments={[{ value: Number(budget.agent_charged_usd) + Number(budget.implementation_committed_usd || 0), tone: 'info-soft', title: 'plus implementations' }, { value: Number(budget.agent_charged_usd), tone: 'info', title: 'charged to agents' }]} /></div>
        <Kv rows={[['Charged to agents', num(budget.agent_charged_usd, 3, ' $')], ['Committed to implementations', num(budget.implementation_committed_usd, 3, ' $')], ['Cap', budget.cap_usd != null ? num(budget.cap_usd, 2, ' $') : <span className="faint">none set</span>], ['Family', String(usage.data.family || 'unknown')]]} />
      </Section>
      {series.length ? <Section title="Over time" right={<span className="small faint">per hour</span>}><Columns points={series} format={fmt} label="model use over time" /></Section> : null}
      <div className="row wrap" style={{ alignItems: 'stretch', gap: 12 }}>
        <div className="grow"><Section title="By agent"><Bars rows={byAgent} format={fmt} label="spend by agent" /></Section></div>
        <div className="grow"><Section title="By model"><Bars rows={byModel} format={fmt} tone="accent" label="spend by model" /></Section></div>
      </div>
      {Object.keys(agents).length ? <Section title="Agents"><table><thead><tr><th>Agent</th><th>Role</th><th>Status</th><th>Model</th><th>Thinking</th></tr></thead><tbody>{Object.entries(agents).map(([id, a]) => <tr key={id} data-testid="usage-agent"><td className="mono small">{id}</td><td>{String(a.role)}</td><td><Pill tone={statusTone(String(a.status))}>{String(a.status)}</Pill></td><td>{String(a.provider || '')}/{String(a.model)}</td>
        <td>{a.effort ? String(a.effort) : 'default'}{a.last_thinking ? <span className="faint"> · last call {String(a.last_thinking)}</span> : null}</td></tr>)}</tbody></table></Section> : null}
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
  const race = useRead<{ race: Record<string, unknown> | null }>(['race', studyId], `/api/v1/studies/${studyId}/race`, { refetchInterval: 5000 });
  const r = race.data?.race;
  const configurations = ((r?.configurations || []) as Record<string, unknown>[]);
  const scored = configurations.filter(c => c.mean_score != null).map(c => ({ name: `${String(c.algorithm)} ${String(c.id).slice(-6)}`, value: Number(c.mean_score), title: `${String(c.status)} · ${String(c.seeds)} seeds at ${String(c.rung_seconds)} s` }));
  return <div className="card"><div className="row"><strong className="grow">{goal}</strong>{r ? <Pill tone={statusTone(String(r.status))}>{String(r.status)}</Pill> : <span className="faint small">no race</span>}</div>
    {r ? <>
      <div className="meter-block"><div className="row"><span>Elapsed</span><span className="faint">{duration(r.elapsed_seconds)} of {duration(r.total_seconds)}</span></div>
        <Meter total={Number(r.total_seconds)} segments={[{ value: Number(r.elapsed_seconds), tone: 'accent', title: 'elapsed' }]} label="race elapsed" /></div>
      <div className="meter-block"><div className="row"><span>Worker seconds</span><span className="faint">{duration(r.worker_seconds_spent)} of {duration(r.worker_seconds_cap)}</span></div>
        <Meter total={Number(r.worker_seconds_cap)} segments={[{ value: Number(r.worker_seconds_spent), tone: 'info', title: 'spent' }]} label="race worker seconds" /></div>
      <div className="row" style={{ gap: 12, alignItems: 'center' }}><span className="small faint">Workers</span><Slots busy={Number(r.running_workers) || 0} limit={Number(r.max_workers) || 0} /></div>
      {scored.length ? <div style={{ marginTop: 8 }}><span className="small faint">Mean score by configuration</span><Bars rows={scored} format={v => v.toPrecision(4)} tone="accent" label="race configurations" /></div> : null}
      <Kv rows={[['Rung', String(r.rung ?? r.current_rung ?? 'unknown')], ['Deadline', when(r.deadline_at)], ['Configurations', `${configurations.filter(c => c.status === 'active' || c.status === 'running').length} active of ${configurations.length}`]]} />
    </> : null}</div>;
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
      <Section title="Agents"><div className="agent-grid" data-testid="agent-cards">
        {team.data.agents.map(a => { const tone = statusTone(String(a.status)); return <div key={String(a.id)} className="agent-card" data-status={String(a.status)}>
          <div className="row"><span className="dot" style={{ background: String(tone) === 'bad' ? 'var(--bad)' : String(tone) === 'clear' || String(tone) === 'agent' ? 'var(--accent)' : String(tone) === 'attention' ? 'var(--warn)' : 'var(--ink-3)' }} /><strong className="grow">{String(a.role).replaceAll('_', ' ')}</strong><Pill tone={tone}>{String(a.status)}</Pill></div>
          <span className="small">{String(a.activity || '')}</span>
          <span className="small faint mono">{String(a.model)}</span>
          <span className="small faint">{when(a.last_activity_at)}</span>
        </div>; })}
      </div></Section>
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
  return (
    <>
      <ModelTiers />
      {models.data ? <details className="card"><summary>This campaign's agents ({String(models.data.mode)} mode, default {JSON.stringify(models.data.default)})</summary><pre>{JSON.stringify(models.data, null, 1).slice(0, 4000)}</pre></details> : null}
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

const NOTICE_SECONDS = 60, GATE_SECONDS = 300;   // the defaults (campaigns/compute_consent.py)

/** The researcher's two compute thresholds for this campaign: an agent's work longer than the first starts with a notice in the
 * inbox, longer than the second (and any coding workspace) waits for their go-ahead. A campaign limit, set with campaign.update. */
function ComputeThresholds({ campaignId }: { campaignId: string }) {
  const summary = useSummary(campaignId);
  const queryClient = useQueryClient();
  const campaign = summary.data?.campaign;
  const savedNotice = Number(campaign?.compute_notice_seconds ?? NOTICE_SECONDS), savedGate = Number(campaign?.compute_gate_seconds ?? GATE_SECONDS);
  const [notice, setNotice] = useState<number | null>(null);
  const [gate, setGate] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!campaign) return null;
  const noticeMinutes = notice ?? savedNotice / 60, gateMinutes = gate ?? savedGate / 60;
  const changed = noticeMinutes * 60 !== savedNotice || gateMinutes * 60 !== savedGate;
  const apply = async () => {
    setError(null);
    try {
      await send({ operation: 'campaign.update', campaignId, expectedRevision: campaign.version, payload: {
        compute_notice_seconds: Math.round(noticeMinutes * 60), compute_gate_seconds: Math.round(gateMinutes * 60), rationale: 'Compute thresholds set on the Resources page' } });
      setNotice(null); setGate(null);
      await queryClient.invalidateQueries({ queryKey: ['summary', campaignId] });
      await queryClient.invalidateQueries({ queryKey: ['inbox', campaignId] });
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <Section title="Compute thresholds" right={<span className="small faint">yours, for this campaign; agents' work only, never your own</span>}>
      <p className="small" data-testid="thresholds-now">Now: up to {duration(savedNotice)} starts freely; up to {duration(savedGate)} starts with a notice in your inbox; longer waits for your go-ahead.</p>
      <div className="row wrap" style={{ gap: 12 }}>
        <label className="small">Notice above <input type="number" min={0} step={0.5} value={noticeMinutes} onChange={e => setNotice(Number(e.target.value))} style={{ width: 70 }} data-testid="threshold-notice" /> min</label>
        <label className="small">Go-ahead above <input type="number" min={0.5} step={0.5} value={gateMinutes} onChange={e => setGate(Number(e.target.value))} style={{ width: 70 }} data-testid="threshold-gate" /> min</label>
        <button className="btn small primary" disabled={!changed || noticeMinutes > gateMinutes} onClick={() => void apply()} data-testid="thresholds-apply">Apply</button>
      </div>
      <p className="why">Worker time of each thing an agent starts: a run, a profile, a validation, an implementation job, an analysis script. A coding workspace always waits for your go-ahead, and work an approved plan covers starts without a notice.
        {noticeMinutes > gateMinutes ? ' The notice threshold cannot be above the go-ahead threshold.' : ''}</p>
      {error ? <div className="pill bad">{error}</div> : null}
    </Section>
  );
}

type SlotsView = { workers: number; gpu_workers: number; sizes: { cuda: number; cpu: number }; launcher: { workers: number; gpu_workers: number };
  chosen_by?: string | null; updated_at?: string | null; reason?: string | null };

/** How many runs go at once on this server and how many of them on the GPU: the researcher's, here, at any time; it holds from
 * the next scheduling pass and across restarts (the launcher's settings are only the defaults). Runs already going keep their device. */
function SlotSettings({ slots, gpuReported }: { slots: SlotsView; gpuReported: boolean }) {
  const queryClient = useQueryClient();
  const [workers, setWorkers] = useState(slots.workers);
  const [gpu, setGpu] = useState(slots.gpu_workers);
  const [error, setError] = useState<string | null>(null);
  const changed = workers !== slots.workers || gpu !== slots.gpu_workers;
  const apply = async () => {
    setError(null);
    try {
      const response = await fetch('/api/v1/resources/slots', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workers, gpu_workers: gpu, reason: 'set on the Resources page' }) });
      if (!response.ok) throw new Error(((await response.json().catch(() => ({}))) as { detail?: string }).detail || 'Could not set the slots');
      await queryClient.invalidateQueries({ queryKey: ['resources'] });
    } catch (e) { setError(String((e as Error).message || e)); }
  };
  return (
    <Section title="Run slots" right={<span className="small faint">yours; applies from the next scheduling pass and is kept across restarts</span>}>
      <p className="small" data-testid="slots-now">Now {slots.workers} runs at once: {slots.sizes.cuda} on the GPU, {slots.sizes.cpu} on CPU.
        <span className="faint"> Launcher default: {slots.launcher.workers}, {slots.launcher.gpu_workers} on the GPU{slots.chosen_by ? `; set by the ${slots.chosen_by} ${when(slots.updated_at)}` : ''}.</span></p>
      <div className="row wrap" style={{ gap: 12 }}>
        <label className="small">Runs at once <input type="number" min={1} max={64} value={workers} onChange={e => setWorkers(Number(e.target.value))} style={{ width: 70 }} data-testid="slots-workers" /></label>
        <label className="small">of them on the GPU <input type="number" min={0} max={Math.max(0, workers - 1)} value={gpu} onChange={e => setGpu(Number(e.target.value))} style={{ width: 70 }} data-testid="slots-gpu" /></label>
        <button className="btn small primary" disabled={!changed} onClick={() => void apply()} data-testid="slots-apply">Apply</button>
      </div>
      <p className="why">At least one slot stays on CPU, where every kind of run can go. A run already going keeps its device: continue a stopped run to move it.
        {gpu > 0 && !gpuReported ? ' This machine reports no GPU, so GPU slots may stay empty.' : ''}</p>
      {error ? <div className="pill bad">{error}</div> : null}
    </Section>
  );
}
