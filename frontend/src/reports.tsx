import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { State } from './api';
import { ErrorNotice } from './ui';
import { LiveThought, useLive } from './agentLive';
import type { LiveReport } from './agentLive';
import './reports.css';

type Report = { id: string; title: string; url: string; parent_id: string | null; created_at: string; latest_submission_id: string | null };
type StageRow = { key: string; purpose: string; status: string; started_at?: string; finished_at?: string };
type Job = { id: string; status: string; stage?: string; focus?: string; question?: string; error?: string; result_id?: string;
  cancel_requested?: boolean; workflow?: string; artifacts_url: string; usage: { calls?: number; api_cost_usd?: number; pending_reservation?: { cost_usd_reserved?: number | null } }; limits?: { model_calls: number };
  stage_log?: StageRow[]; model?: string | null; reasoning_effort?: string | null; billing_mode?: string | null; requested_by?: string | null; notes?: string };
type Writer = { model: string; reasoning_effort?: string | null; billing_mode: string; allowance_usd?: number | null };
const stageOrder = ['brief', 'investigate', 'select', 'draft', 'science', 'reader', 'edit', 'verify'];
export const stageNames: Record<string, string> = { brief: 'Interpreting your notes', investigate: 'Investigating the evidence', select: 'Choosing the argument',
  draft: 'Writing the article', science: 'Checking scientific support', reader: 'Reviewing usefulness and depth', edit: 'Resolving the reviews', verify: 'Checking the revised draft' };
const statusNames: Record<string, string> = { completed: 'Draft ready', needs_attention: 'Draft needs attention', awaiting_focus: 'A question about your focus',
  interrupted: 'Writing interrupted', failed: 'Writing stopped', cancelled: 'Writing cancelled' };
const card = { padding: 24, background: 'white', border: '1px solid #d6e0e1', borderRadius: 10 };

function dollars(value: number): string { return `$${value.toFixed(value < 1 ? 3 : 2)}`; }
function modelName(source: { model?: string | null; reasoning_effort?: string | null }): string { return [source.model, source.reasoning_effort].filter(Boolean).join(' · '); }

/** The stages of a report job: what is done, what runs now and, while it runs, what is still to come. */
function Stages({ job, live }: { job: Job; live?: LiveReport }) {
  const log = job.stage_log || [];
  if (!log.length) return null;
  const position = Math.max(...log.map(row => stageOrder.indexOf(row.purpose)));
  const coming = job.status === 'running' ? stageOrder.slice(position + 1) : [];
  const repeat = (row: StageRow) => { const turn = Number(row.key.split('_')[1]); return turn > 1 ? ` (round ${turn})` : row.key.endsWith('_checked') ? ' (after more reading)' : ''; };
  return <ol className="report-stages" aria-label="Writing stages">
    {log.map(row => <li key={row.key} className={row.status === 'completed' ? 'done' : row.status === 'running' ? 'current' : 'failed'}>
      {stageNames[row.purpose] || row.purpose}{repeat(row)}{!['completed', 'running'].includes(row.status) && ` (${row.status})`}
      {row.status === 'running' && live && <LiveThought phase={live.phase} thinking={live.thinking} text={live.text} length={420} />}</li>)}
    {coming.map(purpose => <li key={purpose} className="coming">{stageNames[purpose]}</li>)}
  </ol>;
}

function JobCard({ job, live, action }: { job: Job; live?: LiveReport; action: (job: Job, operation: string, body?: unknown) => Promise<void> }) {
  const [answer, setAnswer] = useState(''), [busy, setBusy] = useState(false);
  async function send(operation: string, body?: unknown) { setBusy(true); try { await action(job, operation, body); } finally { setBusy(false); } }
  const stage = stageNames[(job.stage || '').split('_')[0]] || 'Preparing the draft';
  // While a call runs, its upper bound is held against the budget; the page shows what was spent and what is held apart.
  const held = job.usage.pending_reservation?.cost_usd_reserved || 0;
  const cost = job.billing_mode === 'api' && typeof job.usage.api_cost_usd === 'number' ? Math.max(0, job.usage.api_cost_usd - held) : null;
  return <article style={card} aria-label="Writing progress">
    <h3>{job.status === 'running' ? stage : statusNames[job.status] || job.status}</h3>
    <p role="status">{job.status === 'running' ? (job.cancel_requested ? 'Stopping after the current call finishes.' : 'You can leave this page and return later.') : job.error}
      {job.usage.calls !== undefined && <span> · {job.usage.calls} of at most {job.limits?.model_calls || 1} model calls</span>}
      {cost !== null && <span> · {dollars(cost)} so far{held > 0 && job.status === 'running' && `, up to ${dollars(held)} held for the current call`}</span>}</p>
    {(job.requested_by === 'lead' || job.model) && <p className="report-origin">{job.requested_by === 'lead' ? 'Started by the lead agent at your request' : 'Started from this page'}
      {job.model && <> · written by {modelName(job)}{job.billing_mode === 'api' ? ', billed to this campaign' : ''}</>}</p>}
    {job.notes && <p className="report-notes"><strong>About:</strong> {job.notes}</p>}
    <Stages job={job} live={live} />
    {job.focus && <p><strong>Inferred focus:</strong> {job.focus}</p>}
    {job.status === 'awaiting_focus' && <form onSubmit={event => { event.preventDefault(); void send('answer', { answer }); }}>
      <label htmlFor={`focus-${job.id}`}>{job.question}</label>
      <textarea id={`focus-${job.id}`} value={answer} onChange={event => setAnswer(event.target.value)} rows={2} maxLength={4000} required style={{ width: '100%', margin: '8px 0' }} />
      <button className="button" disabled={busy || !answer.trim()}>Continue writing</button>
    </form>}
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
      {job.result_id && <a className="button" href={`/reports/${job.result_id}`}>Open draft →</a>}
      <a href={job.artifacts_url}>Download writing record</a>
      {['running', 'awaiting_focus'].includes(job.status) && job.workflow !== 'legacy' && <button className="button secondary small" disabled={busy || job.cancel_requested} onClick={() => void send('cancel', {})}>Stop writing</button>}
    </div>
  </article>;
}

export function ReportsView({ state }: { state: State }) {
  const [reports, setReports] = useState<Report[]>([]), [jobs, setJobs] = useState<Job[]>([]), [writer, setWriter] = useState<Writer | null>(null);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState(''), [references, setReferences] = useState(''), [literature, setLiterature] = useState(true);
  const [refresh, setRefresh] = useState(0), requestId = useRef<string | null>(null);
  const campaignId = state.campaign?.id;
  const headers = { 'X-Workspace-Id': String(state.workspace_id || '') };
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const result = await api<{ reports: Report[]; jobs: Job[]; writer?: Writer | null }>(`/api/reports${campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : ''}`);
        if (active) { setReports(result.reports); setJobs(result.jobs || []); setWriter(result.writer || null); }
      } catch (failure) { if (active) setError(errorText(failure)); }
      finally { if (active) setLoading(false); }
    }
    void load(); const timer = setInterval(() => void load(), 3000);
    return () => { active = false; clearInterval(timer); };
  }, [campaignId, refresh]);
  useEffect(() => { requestId.current = null; }, [notes, references, literature, campaignId]);
  async function write(event: React.FormEvent) {
    event.preventDefault(); if (!campaignId || busy) return;
    setBusy(true); setError('');
    requestId.current ||= `draft_${crypto.randomUUID()}`;
    try {
      await api('/api/report-writer/jobs', { request_id: requestId.current, campaign_id: campaignId, notes,
        references: references.split(/[\s,]+/).filter(Boolean), literature }, 'POST', headers);
      requestId.current = null; // A later explicit click is new work; lost responses retain their ID for retry.
      setRefresh(value => value + 1);
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  }
  async function act(job: Job, operation: string, body?: unknown) {
    setError('');
    try { await api(`/api/report-writer/jobs/${job.id}/${operation}`, body, 'POST', headers); setRefresh(value => value + 1); }
    catch (failure) { setError(errorText(failure)); }
  }
  const running = jobs.some(job => job.status === 'running');
  const live = useLive(campaignId, running).reports;
  return <section aria-label="Reports">
    <div className="page-heading"><div><h1>Reports</h1><p>Turn a few observations into a focused scientific draft, then refine it with highlights and short remarks.</p></div></div>
    <form onSubmit={event => void write(event)} style={{ ...card, marginBottom: 24 }} aria-label="Write a report">
      <h2>What caught your attention?</h2>
      <p>A few rough sentences are enough. The writer will investigate saved evidence, choose the argument, and check the draft through scientific and reader reviews.</p>
      {writer && <p className="report-writer-model">Written by the lead agent's model ({modelName(writer)}){writer.billing_mode === 'api'
        ? <>, billed to this campaign's model budget{typeof writer.allowance_usd === 'number' && <> ({dollars(Math.max(0, writer.allowance_usd))} left)</>}</> : ''}: up to 14 model calls, which can take 20 to 40 minutes.
        You can also ask the lead agent for a report in the chat; it starts this same writer.</p>}
      <label htmlFor="report-notes">Your observations and intended focus</label>
      <textarea id="report-notes" rows={4} maxLength={12000} value={notes} onChange={event => setNotes(event.target.value)} required
        placeholder="Annealing looks strong. DQN is still climbing. Wall time probably matters more."
        style={{ display: 'block', width: '100%', margin: '8px 0 16px', padding: 12 }} />
      <details style={{ marginBottom: 16 }}><summary>Evidence starting points</summary>
        <label htmlFor="report-references" style={{ display: 'block', marginTop: 12 }}>Optional record IDs, separated by spaces or commas</label>
        <input id="report-references" value={references} onChange={event => setReferences(event.target.value)} placeholder="Trial, decision, hypothesis, or source IDs" style={{ width: '100%', margin: '8px 0 12px', padding: 8 }} />
        <label><input type="checkbox" checked={literature} onChange={event => setLiterature(event.target.checked)} /> Allow targeted literature checks</label>
        <p>Uses saved campaign records and bounded analysis of existing runs. Proposed new experiments stay in the writing notes.</p>
      </details>
      <button className="button" disabled={busy || running || !campaignId || !notes.trim()}>{busy ? 'Starting…' : running ? 'Writer is working…' : 'Write a draft'}</button>
      {!campaignId && <p>Select a campaign to write from its saved evidence.</p>}
    </form>
    {error && <ErrorNotice text={error} />}
    {jobs.length > 0 && <div style={{ display: 'grid', gap: 16, marginBottom: 24 }}>
      {[...jobs].reverse().filter((job, index) => index < 5 || ['running', 'awaiting_focus'].includes(job.status)).map(job => <JobCard key={job.id} job={job} live={live.find(row => row.job_id === job.id)} action={act} />)}
    </div>}
    <h2>Review drafts</h2>
    <p>Green keeps strong phrases, yellow asks for improvements, and red requests removal. Unmarked text stays flexible. Share any review as a single HTML file.</p>
    {loading ? <p>Loading reports…</p> : reports.length ? <div style={{ display: 'grid', gap: 16, marginTop: 24 }}>
      {reports.map(report => <article key={report.id} style={card}>
        <p style={{ fontSize: 12, color: '#59727a' }}>{report.parent_id ? 'REVISED DRAFT' : 'FIRST DRAFT'} · {new Date(report.created_at).toLocaleDateString()}</p>
        <h2>{report.title}</h2><p>{report.latest_submission_id ? 'Feedback submitted. Open the draft to continue reviewing or request a revision.' : 'Ready for highlights and short remarks.'}</p>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}><a className="button" href={report.url}>Open review →</a>
          <a href={`/api/reports/${report.id}/export?format=review`}>Download review HTML</a>
          {report.parent_id && <a href={`/reports/${report.parent_id}`}>Previous draft</a>}</div>
      </article>)}
    </div> : !error && <p>No reports have been added to this campaign yet.</p>}
  </section>;
}
