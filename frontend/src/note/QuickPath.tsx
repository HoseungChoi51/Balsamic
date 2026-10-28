/** The quick path (roadmap track P): the lead wrote the charter itself from the researcher's words, and their one action is to
 *  confirm it. Here: whether the path holds and the switch to the full path (the note page), and the card in the conversation
 *  that puts the lead's charter before them in plain words and confirms it in one click (roadmap P5). What the second reading
 *  found is settled with Differences, on the card and the Charter tab. */
import { useState } from 'react';
import { api } from '../api/client';
import { useRead, useSummary } from '../api/queries';
import type { Message } from '../api/types';
import { send } from '../commands/bus';
import { Pill } from '../primitives/ui';
import { formatHash, navigate } from '../router/routes';
import { track } from '../telemetry/events';
import { FORM_WORDS, show, type CharterView, type Question, type Variable } from './CharterPanel';
import { Differences, plainWhy, useRefresh, type Reading } from './Differences';

export interface Criterion { id: string; label: string; holds: boolean | null; detail: string }
/** The note's own account of the quick path: the criteria on the lead's last write (revision), its reading, and why it ended. */
export interface Quick { holds: boolean; criteria?: Criterion[]; revision?: number; reading?: Reading | null; ended?: string; ended_by?: string; failed?: string[]; charter_id?: string }
/** The view's word on the one click: the revision it confirms, and why it would be refused now (confirm()'s own words). */
export interface Confirmation { revision: number; confirmed: boolean; why: string | null }
export interface QuickNote { id: string; status: string; path?: 'quick' | 'full' | null; charter_id?: string | null; quick?: Quick | null }
interface NoteRead { note: QuickNote; confirmation?: Confirmation | null }

const units = (u?: string) => u && u.trim() && u.trim() !== '1' ? ' ' + u.trim() : '';
const amount = (value: unknown, u?: string) => Array.isArray(value)
  ? (value.length > 40 ? value.slice(0, 40).map(show).join(', ') + `, … (${value.length} in all)` : value.map(show).join(', ')) + units(u)
  : show(value) + units(u);
const clamp = (text: string, limit = 400) => text.length > limit ? text.slice(0, limit - 1).replace(/\s+\S*$/, '') + '…' : text;

/** The note page on the quick path: whether it holds, criterion by criterion, and the researcher's switch to the full path. */
export function QuickPathPanel({ campaignId, note, threadId }: { campaignId: string; note: QuickNote; threadId?: string | null }) {
  const summary = useSummary(campaignId);
  const refresh = useRefresh(campaignId, note.charter_id);
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const criteria = note.quick?.criteria || [];
  const failed = criteria.filter(c => c.holds === false).length;
  const pending = criteria.filter(c => c.holds === null).length;
  const full = async () => {
    const version = summary.data?.campaign.version;
    if (version === undefined) return;
    setBusy(true); setError(null);
    try {
      await send({ operation: 'problem_note.full_path', campaignId, expectedRevision: version, payload: { note_id: note.id }, ...(threadId ? { origin: { thread_id: threadId } } : {}) });
      track('note.full_path', {}); setSure(false); await refresh();
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  return <section className="card" data-testid="quick-path">
    <div className="section-head"><h2>The quick path</h2>
      <Pill tone={failed ? 'warn' : pending ? '' : 'clear'}>{failed ? 'ends' : pending ? `${pending} still to check` : 'holds'}</Pill></div>
    <p className="small muted" style={{ marginTop: 4 }}>The lead wrote the charter itself from your words, and this note is read from it. The checks below, made by code on
      each of its writes, decide whether the problem is simple enough for that; when one fails, the note goes to the full path.</p>
    {criteria.length ? <ul className="small" style={{ margin: '4px 0', paddingLeft: 4, listStyle: 'none' }} data-testid="quick-criteria">{criteria.map(c =>
      <li key={c.id} data-testid="quick-criterion" data-id={c.id} data-holds={c.holds === null ? 'pending' : String(c.holds)}>
        <strong>{c.holds === true ? '✓ ' : c.holds === false ? '✗ ' : '… '}{c.label}</strong> <span className="faint">{c.detail}</span></li>)}</ul> : null}
    {note.status !== 'confirmed' ? <div className="row wrap" style={{ gap: 8 }}>
      {!sure ? <button className="btn small" onClick={() => setSure(true)} data-testid="use-full-path" title="Write and adopt the note yourself, with the lead; the formulator then revises the lead's charter for you to confirm">Use the full path</button> : <>
        <span className="small grow">The lead's charter is kept: the note is written from it for you to edit and adopt, and the formulator then revises the charter. The quick path does not come back.</span>
        <button className="btn small primary" disabled={busy} onClick={full} data-testid="use-full-path-confirm">Use the full path</button>
        <button className="btn quiet small" disabled={busy} onClick={() => setSure(false)}>cancel</button></>}
      {error ? <span className="pill bad" role="alert">{error}</span> : null}</div> : null}
  </section>;
}

function variableWords(v: Variable, values: Record<string, number | null>): string {
  const shape = (v.shape || []).map(part => typeof part === 'string' ? `${part} = ${show(values[part])}` : String(part)).join(' × ');
  const each = shape ? `, for each of ${shape}` : '';
  if (v.representation === 'permutation') return `an order of ${shape || 'its items'}, each item once`;
  if (v.representation === 'continuous' || v.representation === 'integer') return `${v.representation === 'integer' ? 'a whole number' : 'a number'} from ${show(v.lower)} to ${show(v.upper)}${units(v.units)}${each}`;
  if (v.representation === 'discrete') return `one of ${v.values.map(show).join(', ')}${each}`;
  if (v.representation === 'binary') return `0 or 1${each}`;
  return 'a structured value' + (v.layout ? ` laid out as ${v.layout}` : '');
}

/** The charter in plain words: what is chosen, what is measured, the values given, the rules, what computes the score. */
function PlainCharter({ c }: { c: CharterView }) {
  const doc = c.charter;
  const quantities = Object.entries(doc.quantities);
  const inputs = quantities.filter(([, q]) => q.role !== 'derived');
  const derived = quantities.filter(([, q]) => q.role === 'derived');
  const binding = doc.evaluator;
  const group = (title: string, testId: string, lines: React.ReactNode[]) => lines.length ? <div data-testid={testId}><div className="small faint">{title}</div>
    <ul className="small" style={{ margin: '2px 0 6px', paddingLeft: 18 }}>{lines.map((line, i) => <li key={i}>{line}</li>)}</ul></div> : null;
  return <div className="col" style={{ gap: 2 }} data-testid="confirm-card-charter">
    {c.rendered?.summary || doc.summary ? <p className="small" style={{ margin: '2px 0 6px' }}>{c.rendered?.summary || doc.summary}</p> : null}
    {group('Objective', 'card-objective', [
      ...(doc.objective ? [<><strong>{doc.objective.direction === 'minimize' ? 'Minimize' : 'Maximize'} {doc.objective.name}</strong>{units(doc.objective.units) ? ` (${doc.objective.units})` : ''}: {c.rendered?.objective || doc.objective.definition}</>] : ['No objective yet.']),
      ...(doc.metrics || []).map(m => `${m.name}${units(m.units) ? ` (${m.units})` : ''}, recorded${m.definition ? ': ' + (c.rendered?.[`metric ${m.name}`] || m.definition) : ''}`)])}
    {group('What is chosen', 'card-variables', doc.variables.length ? doc.variables.map(v => <><code>{v.name}</code>: {v.description}; {variableWords(v, c.values)}.{v.meaning ? ` ${v.meaning}` : ''}</>) : ['No decision variable yet.'])}
    {group('The values', 'card-inputs', [
      ...inputs.map(([name, q]) => <><code>{name}</code> = {amount(q.value, q.units)}: {q.description}{q.origin === 'assumed' ? <span className="faint"> (assumed{q.accepted ? ', accepted' : ''})</span> : null}</>),
      ...derived.map(([name, q]) => <><code>{name}</code> = {c.values[name] == null ? <span className="faint">{c.errors?.[name] || 'not computable yet'}</span> : amount(c.values[name], q.units)}: {q.description} <span className="faint">(computed: {q.expression})</span></>)])}
    {group('Rules', 'card-constraints', (doc.constraints || []).length ? (doc.constraints || []).map(k => `${c.rendered?.[`constraint ${k.id}`] || k.statement} (${k.kind === 'soft' ? 'soft; ' : ''}${FORM_WORDS[k.form] || k.form})`)
      : ['None beyond the bounds of what is chosen.'])}
    {group('What computes the score', 'card-evaluator', binding ? [
      binding.kind === 'installed' ? `The installed problem ${binding.problem_id}.` : `A new problem, ${binding.problem_id}, built for this campaign` + (binding.notes?.trim() ? `: ${clamp(binding.notes.trim())}` : '.'),
      binding.deterministic === false ? 'Not deterministic: evaluations of one design differ.' : 'Deterministic: a design always gets the same score.'] : ['No evaluator yet.'])}
  </div>;
}

/** A question of the lead's, answered on the card with an option or in the researcher's own words. */
function CardQuestion({ question: q, busy, answer }: { question: Question; busy: boolean; answer: (question: Question, text: string) => Promise<void> }) {
  const [text, setText] = useState('');
  return <article className="finding blocking" data-testid="card-question" data-question-id={q.id}>
    <div className="row"><span className="finding-code">question</span><span className="grow">{q.question}</span></div>
    {q.options?.length ? <div className="row wrap finding-actions">{q.options.map((option, i) =>
      <button key={i} className="btn small" disabled={busy} onClick={() => answer(q, option)} data-testid="card-question-option" title={i === 0 ? 'The lead recommends this one' : undefined}>
        {option}{i === 0 ? <span className="faint"> · recommended</span> : null}</button>)}</div> : null}
    <div className="row" style={{ marginTop: 6 }}><input className="grow" placeholder="or answer in your own words" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="card-question-text" />
      <button className="btn small primary" disabled={busy || !text.trim()} onClick={async () => { await answer(q, text.trim()); setText(''); }}>Answer</button></div>
  </article>;
}

/** The confirm card (roadmap P5): the lead's charter put before the researcher in the conversation, once its write was read
 *  against their words. In plain words, with the lead's questions, the assumptions confirming accepts and the differences the
 *  second reading found; one button confirms it, the same command as the Charter tab. While the lead's last write is the card's,
 *  it follows the charter as it is now (an answer or a value the researcher changed included); once the lead writes again it
 *  says it is out of date and points at the newest, and it says when the charter is confirmed or the quick path ended. */
export function ConfirmCard({ message, thread }: { message: Message; thread: string | null }) {
  const campaignId = message.campaign_id;
  const charterId = typeof message.charter_id === 'string' ? message.charter_id : '';
  const revision = Number(message.charter_revision) || 0;
  const view = useRead<NoteRead>(['note', campaignId], `/api/v1/campaigns/${campaignId}/problem-note`, { refetchInterval: 8000 });
  const charter = useRead<CharterView>(['charter', charterId], charterId ? `/api/v1/problem-charters/${charterId}` : null, { refetchInterval: 8000 });
  const summary = useSummary(campaignId);
  const refresh = useRefresh(campaignId, charterId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const note = view.data?.note;
  const quick = note?.quick;
  const latest = quick?.revision ?? revision;   // the lead's last write
  const c = charter.data;
  const confirmation = view.data?.confirmation;
  const state = !note || !c ? 'loading' : note.path !== 'quick' ? 'ended' : latest > revision ? 'stale'
    : confirmation?.confirmed || note.status === 'confirmed' ? 'confirmed' : 'live';
  const post = async (path: string, body: Record<string, unknown>) => {
    if (!c) return;
    setBusy(true); setError(null);
    try { await api(`/api/v1/problem-charters/${charterId}/${path}`, { method: 'POST', body: JSON.stringify({ expected_revision: c.revision, ...body }) }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  const answer = (q: Question, text: string) => post('answers', { question_id: q.id, answer: text });
  const confirm = async () => {
    const version = summary.data?.campaign.version;
    if (!c || !note || version === undefined) return;
    setBusy(true); setError(null);
    try {
      await send({ operation: 'problem_note.confirm', campaignId, expectedRevision: version, payload: { note_id: note.id, charter_id: charterId, revision: c.revision }, ...(thread ? { origin: { thread_id: thread } } : {}) });
      track('note.quick_confirm', { from: 'card' }); await refresh();
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  // The newest card is the one of the lead's last write, when that write was read; otherwise the Charter tab shows it.
  const showNewest = () => {
    const newest = document.querySelector(`[data-testid="confirm-card"][data-revision="${latest}"]`);
    if (newest) newest.scrollIntoView({ behavior: 'smooth', block: 'start' }); else navigate(formatHash({ page: 'note', sub: 'charter' }, thread));
  };
  const charterLink = <a href={formatHash({ page: 'note', sub: 'charter' }, thread)} data-testid="confirm-card-open">open the Charter tab</a>;
  const head = <div className="row"><Pill tone="agent">charter</Pill><span className="grow">The lead wrote the charter from your words (revision {revision}).</span>{charterLink}</div>;
  if (state === 'loading') return <article className="turn lab confirm-card" data-message-id={message.id} data-testid="confirm-card" data-revision={revision} data-state="loading">
    {head}<span className="faint small">{view.error || charter.error ? 'This charter is gone.' : 'Loading the charter…'}</span></article>;
  if (state !== 'live') return <article className="turn lab confirm-card" data-message-id={message.id} data-testid="confirm-card" data-revision={revision} data-state={state}>
    {head}
    {state === 'stale' ? <div className="small" data-testid="confirm-card-stale">This card is out of date: the lead wrote revision {latest} since. <button className="btn quiet small" onClick={showNewest} data-testid="confirm-card-newest">Show the newest</button></div>
      : state === 'confirmed' ? <div className="small" data-testid="confirm-card-confirmed"><Pill tone="clear">confirmed</Pill> You confirmed the charter{c?.confirmed_revision ? ` at revision ${c.confirmed_revision}` : ''}: the gate is open, and its tasks are installed.</div>
      : <div className="small" data-testid="confirm-card-ended">The quick path ended{quick?.ended ? `: ${quick.ended}` : ''}. The note is on the full path, written from this charter: <a href={formatHash({ page: 'note' }, thread)}>open the note</a>.</div>}
  </article>;
  const doc = c!.charter;
  const open = doc.questions.filter(q => q.answer == null && !q.sent);
  const left = doc.questions.filter(q => q.answer == null && q.sent);
  const answered = doc.questions.filter(q => q.answer != null);
  const unsent = answered.filter(q => !q.sent);
  const assumptions = c!.findings.filter(f => f.code === 'assumption.unaccepted' && f.severity === 'blocking').map(f => {
    const subject = f.key.slice(f.code.length + 1);
    const q = doc.quantities[subject];
    const statement = /^statement(\d+)$/.exec(subject);
    return q ? <><code>{subject}</code> = {amount(q.value, q.units)}{q.note ? <span className="faint">: {q.note}</span> : null}</>
      : statement ? doc.assumptions[Number(statement[1])]?.statement || f.message : f.message;
  });
  const reading = quick?.reading && quick.reading.revision === latest ? quick.reading : null;
  const why = confirmation?.why || null;
  return <article className="turn lab confirm-card" data-message-id={message.id} data-testid="confirm-card" data-revision={revision} data-state="live">
    {head}
    <PlainCharter c={c!} />
    {open.length || left.length || answered.length ? <div className="col" style={{ gap: 6 }} data-testid="card-questions">
      <div className="small faint">The lead's questions</div>
      {open.map(q => <CardQuestion key={q.id} question={q} busy={busy} answer={answer} />)}
      {open.length ? <div className="row"><button className="btn small" disabled={busy} onClick={() => post('send-answers', {})} data-testid="card-questions-send"
        title="The lead decides what you leave unanswered and records it as an assumption you can change later">
        {unsent.length ? `Send ${unsent.length} answer${unsent.length === 1 ? '' : 's'}, leave ${open.length} to the lead` : `Leave ${open.length === 1 ? 'it' : `all ${open.length}`} to the lead`}</button></div> : null}
      {[...left, ...answered].map(q => <div key={q.id} className="small" data-testid="card-question-done" data-question-id={q.id}><span className="faint">{q.question}</span> {q.answer != null ? <>Your answer: {q.answer}</> : <>Left to the lead to decide.</>}</div>)}
    </div> : null}
    {assumptions.length ? <div data-testid="card-assumptions"><div className="small faint">Confirming accepts {assumptions.length === 1 ? 'this assumption' : `these ${assumptions.length} assumptions`}</div>
      <ul className="small" style={{ margin: '2px 0 6px', paddingLeft: 18 }}>{assumptions.map((line, i) => <li key={i}>{line}</li>)}</ul></div> : null}
    {reading ? <Differences campaignId={campaignId} noteId={note!.id} reading={reading} threadId={thread} live /> : null}
    <div className="row wrap" style={{ gap: 8 }}>
      <button className="btn primary small" onClick={confirm} disabled={busy || !!why} data-testid="confirm-card-confirm"
        title={why || `Accepts the assumptions it lists, confirms revision ${c!.revision} and installs its tasks`}>Confirm and set the tasks</button>
      {why ? <span className="small muted grow" data-testid="confirm-card-why">{plainWhy(why)}</span> : <span className="small faint grow">Revision {c!.revision}{c!.revision !== revision ? ', with your changes' : ''}. The gate opens once it is confirmed.</span>}
    </div>
    {error ? <div className="pill bad" role="alert" data-testid="confirm-card-error">{error}</div> : null}
  </article>;
}
