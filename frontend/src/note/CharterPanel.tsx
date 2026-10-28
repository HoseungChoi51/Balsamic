/** The charter as a form: every blocking finding is settled in place (a value, a bound, an acceptance, an answer), nothing
 *  commits until Confirm, and the formulator is asked in words only when a number is not enough. Values are typed as numbers.
 *  While the formulator revises the charter nothing here takes input: what the page shows is about to change, and the service
 *  refuses a researcher's input until the formulator has saved its revision. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useRead } from '../api/queries';
import { send } from '../commands/bus';
import { Markdown } from '../chat/render/Markdown';
import { Empty, Failed, Loading, Pill, Section } from '../primitives/ui';
import { Differences, plainWhy, type Reading } from './Differences';

export interface Quantity { description?: string; kind?: string; role: 'input' | 'derived' | string; value: number | null; expression: string | null; units?: string; range?: [number | null, number | null] | null; origin?: string; accepted?: boolean; note?: string }
export interface Variable { name: string; description?: string; representation: string; lower: number | null; upper: number | null; values: unknown[]; units?: string; shape?: unknown[]; meaning?: string; layout?: string }
interface Term { variable: string; weight?: number | string; weights?: number[] | null }
export interface Rule { id: string; statement: string; kind?: string; form: string; test?: string | null; terms?: Term[]; relation?: string | null; bound?: number | string | null }
interface Suggestion { label: string; action: 'waive' | 'request' | 'edit' | string; reason?: string; text?: string; changes?: Record<string, unknown>[]; rationale?: string }
export interface Finding { key: string; code: string; severity: 'blocking' | 'warning' | string; message: string; about: string[]; waivable: boolean; suggestions?: Suggestion[]; detail?: string }
export interface Question { id: string; question: string; options?: string[]; unrunnable_options?: number[]; about?: string[]; answer: string | null; sent?: boolean }
interface Change { part: string; name: string; change: string; before?: unknown; after?: unknown }
interface ProposalOption { label?: string; summary?: string; reason?: string; changes?: unknown[]; blocking_reason?: string | null; diff?: Change[]; findings?: { message: string }[] }
interface Proposal { id: string; status: string; request?: string; asked?: string | null; created_at?: string; accepted_option?: number | null; options?: ProposalOption[] }
export interface CharterView { id: string; title?: string; status: string; revision: number; blocking: number; formulator?: { status: string | null; listening: boolean }; writer?: string | null; confirmed_revision?: number | null; question_rounds?: number; question_rounds_max?: number; findings: Finding[]; values: Record<string, number | null>; errors?: Record<string, string>;
  rendered?: Record<string, string>; access?: Access | null; units_elsewhere?: { about: string[]; message: string }[]; proposals: Proposal[]; charter: { title?: string; text?: string; summary?: string; quantities: Record<string, Quantity>; variables: Variable[]; constraints?: Rule[]; questions: Question[]; assumptions: { statement: string; accepted?: boolean }[]; waivers: { key: string; reason: string }[];
    objective?: { name: string; direction: 'minimize' | 'maximize' | string; units: string; definition: string } | null; metrics?: { name: string; units: string; direction?: string | null; definition?: string }[];
    evaluator?: { kind: 'installed' | 'declared' | string; problem_id: string; notes?: string; deterministic?: boolean; fidelity?: Record<string, string> } | null } }

/** How methods reach the objective and what they are compared on (N11): the charter's choice, else the problem's own. */
interface Access { access: string; cost_axis: string | null; problem: { access: string; cost_axis: string | null }; charter: { access: string | null; cost_axis: string | null } }
const ACCESS_WORDS: Record<string, string> = { white_box: 'white box: a method may compute the objective itself, as often as it likes', oracle: 'oracle: a method reaches the objective only by evaluating a candidate' };
const AXIS_WORDS: Record<string, string> = { worker_seconds: 'worker-seconds', core_seconds: 'core-seconds (threads × time)', evaluations: 'evaluations', solver_calls: 'solver calls' };

const number = (text: string) => { const v = Number(text.replace(/[,_\s]/g, '')); return Number.isFinite(v) ? v : null; };
export const show = (v: unknown) => v == null ? '' : typeof v === 'number' ? (Math.abs(v) >= 1e4 ? v.toLocaleString('en-US') : String(v)) : typeof v === 'object' ? JSON.stringify(v) : String(v);
/** Digits grouped by thousands as they are typed; anything else (an exponent, a name) is left as written. */
const group = (text: string) => { const m = /^(\s*-?)(\d[\d,]*)(\.\d*)?(\s*)$/.exec(text); return m ? m[1] + m[2].replace(/,/g, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (m[3] || '') + m[4] : text; };
const grouped = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 12 });
/** A large number in words, so a count typed in tokens reads as millions or billions: "1 billion", "≈ 1.23 million". */
export function magnitude(v: number): string | null {
  const scale = ([[1e12, 'trillion'], [1e9, 'billion'], [1e6, 'million']] as const).find(([f]) => Math.abs(v) >= f);
  if (!scale) return null;
  const x = v / scale[0]; const shown = Number(x.toPrecision(3));
  return `${shown === x ? '' : '≈ '}${shown.toLocaleString('en-US')} ${scale[1]}`;
}
const CHECKS: Record<string, string> = { 'assumption.unaccepted': 'assumption to accept', 'quantity.no_value': 'value missing',
  'quantity.range': 'value outside its range', 'quantity.kind': 'value of the wrong kind', 'relation.error': 'relation does not compute',
  'variable.bounds': 'bounds missing', 'variable.values': 'values missing', 'variable.shape': 'size unknown', 'variable.missing': 'nothing to optimize',
  'constraint.qualitative': 'rule in words only', 'constraint.violated': 'rule broken', 'constraint.infeasible': 'rules conflict',
  'objective.missing': 'no objective', 'text.reference': 'text', 'text.literal_mismatch': 'number in the text',
  'evaluator.provided': 'provided by a library', 'evaluator.provided_mismatch': 'library computes another problem' };
/** How each constraint form is checked (N9 adds design: a condition on the design the lab checks on every candidate; N10
 * adds outcome: a condition on what the evaluator reports, checked on every result). */
export const FORM_WORDS: Record<string, string> = { quantities: 'a test on the values, checked here', linear: 'linear in the design, checked on every candidate',
  design: 'a condition on the design, checked on every candidate',
  outcome: 'a condition on the measured result, checked on every result; one that breaks it never counts as the best',
  evaluator: 'enforced by the evaluator', qualitative: 'words only, not checked' };
const RELATION: Record<string, string> = { le: '≤', ge: '≥', eq: '=' };
const condition = (k: Rule) => k.form === 'linear' ? `${(k.terms || []).map(t => t.weights ? `weighted ${t.variable}` : t.weight === 'mean' ? `mean(${t.variable})` : t.weight === 'sum' || t.weight == null ? `sum(${t.variable})` : `${t.weight} × sum(${t.variable})`).join(' + ')} ${RELATION[k.relation || ''] || k.relation} ${k.bound}`
  : k.test || '';
const checkLabel = (code: string) => CHECKS[code] || (code.startsWith('evaluator.') ? 'evaluator' : code.startsWith('instance.') ? 'instance' : code);
const inUnits = (units?: string) => units && units.trim() && units.trim() !== '1' ? `, in ${units.trim()}` : '';

/** quickNote: the note's id when it is on the quick path (roadmap P2): the lead wrote this charter, and one command confirms it.
 *  reading: the second reading of the lead's last write (P4), settled here; waits: why the note's view says the confirmation would
 *  be refused now (P5), for what this page cannot see itself (the reading, the lead revising on what you sent it). */
export function CharterPanel({ charterId, campaignId, version, onChanged, formulator, formulatorModel, quickNote, reading, waits }: { charterId: string; campaignId: string; version?: number; onChanged: () => unknown; formulator?: string | null; formulatorModel?: { name: string; tier: string | null; calls: number | null } | null; quickNote?: string; reading?: Reading | null; waits?: string | null }) {
  // Read more often while the formulator works, so inputs open as soon as its revision is saved.
  const [waiting, setWaiting] = useState(false);
  const charter = useRead<CharterView>(['charter', charterId], `/api/v1/problem-charters/${charterId}`, { refetchInterval: waiting ? 2000 : 8000 });
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState<{ text: string; at: number; revision: number }[]>([]);
  // The charter's own view says whether the formulator listens, read together with the revision it applies to.
  const listening = charter.data?.formulator ? charter.data.formulator.listening : formulator !== 'running';
  useEffect(() => {
    setWaiting(!listening);
    // Panels bound to this charter and the note's formulator line follow at once.
    void queryClient.invalidateQueries({ queryKey: ['panels', campaignId] });
    void queryClient.invalidateQueries({ queryKey: ['note', campaignId] });
  }, [listening, campaignId, queryClient]);
  if (charter.isPending) return <Loading what="Reading the charter" />;
  if (charter.error) return <Failed error={charter.error} />;
  const c = charter.data;
  const doc = c.charter;
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ['charter', charterId] }), queryClient.invalidateQueries({ queryKey: ['campaigns'] })]);
  const post = async (path: string, body: Record<string, unknown>) => {
    setError(null); setBusy(true);
    const payload = path === 'requests' ? body : { expected_revision: c.revision, ...body };   // a request to the formulator carries only the words
    try {
      await api(`/api/v1/problem-charters/${charterId}/${path}`, { method: 'POST', body: JSON.stringify(payload) });
      if (path === 'requests') setAsked(list => [...list, { text: String(body.text), at: Date.now(), revision: c.revision }]);
      await refresh();
    }
    catch (e) { setError(String((e as Error).message || e)); throw e; }
    finally { setBusy(false); }
  };
  const edit = (changes: Record<string, unknown>[], rationale: string) => post('edit', { changes, rationale });
  // The revision on screen as a standalone Python project (numpy and pytest only), saved under the name the service gives it.
  const exportProject = async () => {
    setError(null);
    try {
      const response = await fetch(`/api/v1/problem-charters/${charterId}/revisions/${c.revision}/export.zip`, { cache: 'no-store' });
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || `HTTP ${response.status}`); }
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || `charter-r${c.revision}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (e) { setError(`Could not export the charter: ${String((e as Error).message || e)}`); }
  };
  const confirm = async () => {
    setError(null); setBusy(true);
    try {
      // On the quick path one command accepts the assumptions of the revision shown, confirms it and installs its tasks.
      if (quickNote) { if (version !== undefined) await send({ operation: 'problem_note.confirm', campaignId, expectedRevision: version, payload: { note_id: quickNote, charter_id: charterId, revision: c.revision } }); }
      else {
        await api(`/api/v1/problem-charters/${charterId}/confirm`, { method: 'POST', body: JSON.stringify({ expected_revision: c.revision }) });
        if (version !== undefined) await send({ operation: 'campaign.update', campaignId, expectedRevision: version, payload: { charter: { id: charterId, revision: c.revision }, rationale: 'Confirmed the charter adopted from the problem note' } });
      }
      // The next-step callout on every page reads the campaigns list: refresh it too, so "confirm the charter" goes at once.
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ['summary', campaignId] }), queryClient.invalidateQueries({ queryKey: ['campaigns'] })]);
      onChanged();
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  // Open: not answered and not yet sent. Left: sent without an answer, for the formulator to decide and record.
  const openQuestions = doc.questions.filter(q => q.answer == null && !q.sent);
  const leftQuestions = doc.questions.filter(q => q.answer == null && q.sent);
  const unsentAnswers = doc.questions.filter(q => q.answer != null && !q.sent);
  const blocking = c.findings.filter(f => f.severity === 'blocking' && f.code !== 'question.open');
  const working = !listening;
  // Every input waits while the formulator works, not only the one that sends answers.
  const locked = busy || working;
  // Open work first, settled work last: the first open item is marked "next" so the eye lands on it.
  const answeredQuestions = doc.questions.filter(q => q.answer != null);
  const rounds = { done: c.question_rounds ?? 0, max: c.question_rounds_max ?? 2 };
  const lastRound = rounds.done >= rounds.max;
  const roundLabel = rounds.done ? `round ${Math.min(rounds.done, rounds.max)} of ${rounds.max} · ` : '';
  const openProposals = c.proposals.filter(p => p.status === 'open');
  const decidedProposals = c.proposals.filter(p => p.status !== 'open');
  // A request the formulator has answered with a proposal is shown with that proposal, not as "sent".
  const pending = asked.filter(a => a.revision === c.revision && !c.proposals.some(p => p.asked === a.text));
  const nextId = blocking.length ? blocking[0].key : openQuestions.length ? openQuestions[0].id : null;
  const warnings = c.findings.filter(f => f.severity !== 'blocking' && f.severity !== 'info');
  // Facts the checks found that need nothing from anyone, such as an installed library providing the declared problem.
  const notes = c.findings.filter(f => f.severity === 'info');
  const confirmed = c.status === 'confirmed';
  // Who writes the charter and hears your answers: the lead on the quick path until it is first confirmed, else the formulator.
  const writer = c.writer === 'lead' && c.confirmed_revision == null ? 'lead' : 'formulator';
  // On the quick path confirming accepts the assumptions, so only the other checks wait.
  const accepts = quickNote ? blocking.filter(f => f.code === 'assumption.unaccepted') : [];
  const unsettled = blocking.filter(f => !accepts.includes(f));
  const local = confirmed ? null : unsettled.length ? `${unsettled.length} check${unsettled.length === 1 ? '' : 's'} to pass first` : openQuestions.length ? `${openQuestions.length} question${openQuestions.length === 1 ? '' : 's'} from the ${writer} to answer first`
    : quickNote && leftQuestions.length ? `The ${writer} is deciding the ${leftQuestions.length === 1 ? 'question' : leftQuestions.length + ' questions'} you left to it` : null;
  // On the quick path the note's view says what this page cannot see: the second reading, and the lead revising on what you sent it.
  const why = local || (quickNote && !confirmed && waits ? plainWhy(waits) : null);
  const variableIndex = (name: string) => doc.variables.findIndex(v => v.name === name);
  // What the unit checks and the other campaigns' charters say about a name, shown with its meaning where it is settled.
  const unitNotes: Record<string, string[]> = {};
  for (const row of [...c.findings.filter(f => f.code === 'units.scale'), ...(c.units_elsewhere || [])]) for (const name of row.about) (unitNotes[name] ||= []).push(row.message);
  return (
    <div className="col" data-testid="charter-panel" data-revision={c.revision}>
      <Section title={String(doc.title || c.title || 'Charter')} right={<div className="row">
        {busy ? <span data-testid="charter-saving"><Pill live>saving your change…</Pill></span> : null}
        <Pill tone={confirmed ? 'clear' : blocking.length ? 'attention' : ''}>{confirmed ? 'confirmed' : blocking.length ? `${blocking.length} blocking` : 'ready to confirm'} · r{c.revision}</Pill>
        <button className="btn small" onClick={exportProject} data-testid="export-charter" disabled={busy} title={`Downloads revision ${c.revision} as a Python project for your own tools: the data, the tests and a comparison script; you write the objective and the methods`}>Export as Python project</button>
        {!confirmed ? <button className="btn primary small" onClick={confirm} data-testid="confirm-charter" disabled={locked || !!why} title={working ? 'The formulator is revising the charter; confirm the revision it saves' : why || (quickNote ? 'Accepts the assumptions it lists, confirms this revision and installs its tasks' : 'Compiles the tasks and sets the campaign\'s charter revision')}>Confirm and set the tasks</button> : null}</div>}>
        {working ? <div className="finding small" role="status" data-testid="formulator-busy"><span className="finding-code">formulator</span>
          <span className="grow">The formulator is revising the charter. What you see here may change, so answers, values and choices wait until it has saved its revision; this page updates by itself.</span><Pill tone="agent">working</Pill></div> : null}
        {error ? <div className="pill bad" role="alert" data-testid="charter-error">{error}</div> : null}
        {why && !confirmed ? <p className="small muted" data-testid="confirm-why">{local ? `${why}. Settle each item below; nothing commits until you confirm.` : why}</p> : null}
        {accepts.length && !why && !confirmed ? <p className="small muted" data-testid="confirm-accepts">The {writer} wrote this charter from your words. Confirming accepts the {accepts.length === 1 ? 'assumption' : `${accepts.length} assumptions`} listed below and installs its tasks.</p> : null}
        {doc.summary ? <p className="lede" data-testid="charter-summary">{c.rendered?.summary || doc.summary}</p> : null}
        {notes.map(f => <div key={f.key} className="finding small" data-testid="charter-note" data-code={f.code}><span className="finding-code">{checkLabel(f.code)}</span> <span className="grow">{f.message}</span></div>)}
        {formulatorModel ? <div className="row small faint" data-testid="formulator-model" style={{ marginTop: 4 }}><span className="finding-code">formulator</span>
          <span>{working ? 'working on' : formulator === 'failed' ? 'failed on' : 'runs on'} <span className="mono">{formulatorModel.name}</span>{formulatorModel.tier ? <> (the "{formulatorModel.tier}" tier; the formulator row under Monitor → Models)</> : null}{formulatorModel.calls != null ? <>, {formulatorModel.calls} call{formulatorModel.calls === 1 ? '' : 's'} so far</> : null}. The model is fixed for this charter; a tier change applies to the next one.</span>
          {working ? <Pill tone="agent">working</Pill> : null}</div> : null}
      </Section>

      {blocking.length ? <Section title="Checks to pass before confirming" right={<span className="small faint">found by code, not by the {writer} · read again on every revision</span>}>
        <p className="small muted" data-testid="checks-lead"><strong>A check is what is wrong with the charter as it is written now</strong>: a value or a bound missing, an assumption nobody has accepted, a rule the lab cannot test. You settle it yourself, here, by changing the charter (type a number, Accept, Waive); it needs no answer from the {writer}, though you may ask it.
          {openQuestions.length ? ` The questions below are different: decisions the ${writer} asks you to make, which it then writes into the charter. Where a check is about the same thing as a question, it says so; answer that question first, since the revision that follows may settle or replace the check.` : ''}</p>
        <div className="col" data-testid="findings">
          {blocking.map(f => <FindingRow key={f.key} writer={writer} finding={f} doc={doc} values={c.values} notes={unitNotes} related={openQuestions.filter(q => (q.about || []).some(n => f.about.includes(n)))} busy={locked} edit={edit} post={post} variableIndex={variableIndex} next={f.key === nextId} />)}
        </div>
      </Section> : null}

      {quickNote && reading ? <Section title="Your words against the charter" right={<span className="small faint">a second reading by a model that saw only your words and the charter</span>}>
        <Differences campaignId={campaignId} noteId={quickNote} reading={reading} live={!confirmed} />
      </Section> : null}

      {doc.questions.length ? <Section title={`Questions from the ${writer}`} right={<span className="small faint" data-testid="questions-state">
          {roundLabel}{openQuestions.length ? `${openQuestions.length} of ${doc.questions.length} open` : working ? (leftQuestions.length ? `${leftQuestions.length} left to the formulator · it is revising the charter` : 'all answered · the formulator is revising the charter') : leftQuestions.length ? `${leftQuestions.length} left to the ${writer}` : 'all answered'}</span>}>
        {openQuestions.length ? <p className="small muted" data-testid="questions-lead"><strong>A question is a decision the {writer} could not make from {writer === 'lead' ? 'your words' : 'the sources'}</strong> and asks you to make. Unlike a check, an answer changes nothing in the charter by itself: the answers go to the {writer}, which revises the charter, and that revision can settle checks above or raise new ones. Answer what you can; its recommendation comes first. You are not expected to know every answer: send the rest unanswered, and the {writer} decides them from your answers and the sources and records each as an assumption you can change later, once a run has shown what it meant.
          {lastRound ? ' This is the last round: no further questions can follow.' : ` At most ${rounds.max - rounds.done} more round${rounds.max - rounds.done === 1 ? '' : 's'} of questions can follow, only for what no answer or source can decide.`}</p> : null}
        {!openQuestions.length && working ? <div className="finding small" data-testid="formulator-working"><span className="finding-code">formulator</span>Revising the charter from your answers{leftQuestions.length ? `, deciding the ${leftQuestions.length} you left to it` : ''}. {lastRound ? 'No further questions can follow; what stays open becomes assumptions or values for you to settle.' : 'At most one more round of questions can follow, only for what no answer or source can decide.'}<Pill tone="agent">working</Pill></div> : null}
        {openQuestions.length ? <div className="col" data-testid="open-questions">{openQuestions.map(q => <QuestionRow key={q.id} writer={writer} question={q} doc={doc} values={c.values} notes={unitNotes} busy={locked} post={post} working={working} next={q.id === nextId} />)}
          <div className="row" style={{ marginTop: 4 }}><button className="btn small" disabled={locked} data-testid="questions-send" title={`Sends the round now. Unanswered questions go to the ${writer}, which decides each from your answers and the sources and records it as an assumption you can change later.`}
            onClick={() => post('send-answers', {})}>{unsentAnswers.length ? `Send ${unsentAnswers.length} answer${unsentAnswers.length === 1 ? '' : 's'}, leave ${openQuestions.length} to the ${writer}` : `Leave all ${openQuestions.length} to the ${writer}`}</button>
            <span className="small faint">or answer the rest; the round goes by itself once nothing is open</span></div></div> : null}
        {leftQuestions.length ? <div className="col" data-testid="left-questions">{leftQuestions.map(q => <QuestionRow key={q.id} question={q} doc={doc} values={c.values} notes={unitNotes} busy={locked} post={post} working={working} writer={writer} />)}</div> : null}
        {answeredQuestions.length ? <details className="fold" data-testid="answered-questions" style={{ marginTop: openQuestions.length ? 8 : 0, borderBottom: 'none' }}>
          <summary><span className="fold-title small">{answeredQuestions.length} answered{working ? ' · the formulator is working on the answers' : ''}</span></summary>
          <div className="col" style={{ marginTop: 6 }}>{answeredQuestions.map(q => <QuestionRow key={q.id} writer={writer} question={q} doc={doc} values={c.values} notes={unitNotes} busy={locked} post={post} working={working} />)}</div>
        </details> : null}
      </Section> : null}

      <Section title="Quantities" right={<span className="small faint">type a number and press Enter; derived values are computed</span>}>
        {Object.keys(doc.quantities).length ? <table className="quantities" data-testid="quantities"><thead><tr><th>Name</th><th>Value</th><th>Unit</th><th>Role</th><th>Origin</th></tr></thead><tbody>
          {Object.entries(doc.quantities).map(([name, q]) => <QuantityRow key={name} name={name} quantity={q} computed={c.values[name]} error={c.errors?.[name]} busy={locked} edit={edit} post={post} />)}
        </tbody></table> : <Empty>None yet.</Empty>}
      </Section>

      {doc.variables.length ? <Section title="Decision variables" right={<span className="small faint">what the optimizer changes; bounds are typed as numbers</span>}>
        <table data-testid="variables"><thead><tr><th>Name</th><th>Representation</th><th>Lower</th><th>Upper</th><th>Unit</th></tr></thead><tbody>
          {doc.variables.map((v, i) => <VariableRow key={v.name} index={i} variable={v} busy={locked} edit={edit} />)}
        </tbody></table>
      </Section> : null}

      {doc.constraints?.length ? <Section title="Constraints" right={<span className="small faint">what a design or the setup must meet, and how each is checked</span>}>
        <table data-testid="constraints"><thead><tr><th>Rule</th><th>Form</th><th>Condition</th></tr></thead><tbody>
          {doc.constraints.map(k => <tr key={k.id} data-testid="constraint" data-id={k.id} data-form={k.form}>
            <td><strong>{k.id}</strong>{k.kind === 'soft' ? <span className="faint small"> · soft</span> : null}<div className="small faint">{c.rendered?.[`constraint ${k.id}`] || k.statement}</div></td>
            <td className="small" data-testid="constraint-form">{k.form}<div className="faint">{FORM_WORDS[k.form] || ''}</div></td>
            <td>{condition(k) ? <code className="small" data-testid="constraint-condition">{condition(k)}</code> : <span className="faint small">none</span>}</td>
          </tr>)}
        </tbody></table>
      </Section> : null}

      {c.access ? <MethodAccess access={c.access} confirmed={confirmed} busy={locked} edit={edit} /> : null}

      {pending.length ? <Section title="Asked of the formulator" right={<span className="small faint">it answers with a proposal below, or a new revision</span>}>
        <div className="col">{pending.map(a => <div key={a.at} className="finding small row" data-testid="asked"><span className="finding-code">sent</span><span className="grow">{a.text}</span><Pill tone="agent">{working ? 'formulator working' : 'sent'}</Pill></div>)}</div>
      </Section> : null}
      {c.proposals.length ? <Section title="Proposals from the formulator" right={<span className="small faint">choose one option, or decline them all; the numbers in them are computed, not stated</span>}>
        <div className="col">{openProposals.map(p => <ProposalRow key={p.id} proposal={p} busy={locked} refresh={refresh} setError={setError} />)}</div>
        {decidedProposals.length ? <details className="fold" data-testid="decided-proposals" style={{ marginTop: openProposals.length ? 8 : 0, borderBottom: 'none' }}>
          <summary><span className="fold-title small">{decidedProposals.length} earlier proposal{decidedProposals.length === 1 ? '' : 's'}</span></summary>
          <div className="col" style={{ marginTop: 6 }}>{decidedProposals.map(p => <ProposalRow key={p.id} proposal={p} busy={locked} refresh={refresh} setError={setError} />)}</div>
        </details> : null}
      </Section> : null}

      {warnings.length ? <Section title="Warnings" right={<span className="small faint">not blocking; the formulator can tidy them</span>}>
        {warnings.map(f => <div key={f.key} className="finding warning small" data-testid="warning"><span className="finding-code">{f.code}</span> {f.message}</div>)}
      </Section> : null}

      <AskFormulator busy={locked} post={post} writer={writer} />

      {c.rendered?.text || doc.text ? <details className="card"><summary>Charter text</summary><Markdown text={String(c.rendered?.text || doc.text)} thread={null} /></details> : null}
      <details className="card"><summary>Raw charter (JSON)</summary><pre className="wrap" data-testid="raw-charter">{JSON.stringify(doc, null, 2)}</pre></details>
    </div>
  );
}

export function NumberField({ initial, units, placeholder, onSet, busy, testId, width = 150 }: { initial?: number | null; units?: string; placeholder?: string; onSet: (value: number) => Promise<unknown>; busy: boolean; testId?: string; width?: number }) {
  const [text, setText] = useState(initial == null ? '' : group(String(initial)));
  const [bad, setBad] = useState(false);
  const [sent, setSent] = useState<number | null | undefined>(initial);   // the value last committed, so Enter and blur never send it twice
  const [saved, setSaved] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  // The charter is re-read after every edit: the field follows the saved value instead of keeping what was typed.
  useEffect(() => { setText(initial == null ? '' : group(String(initial))); setSent(initial); }, [initial]);
  useLayoutEffect(() => { if (caret.current != null && field.current) { field.current.setSelectionRange(caret.current, caret.current); caret.current = null; } }, [text]);
  // Separators follow the digits as they are typed, and the caret stays after the same digit.
  const change = (e: React.ChangeEvent<HTMLInputElement>) => {
    let raw = e.target.value; let at = e.target.selectionStart ?? raw.length;
    const kind = (e.nativeEvent as InputEvent).inputType;
    if (raw.length < text.length && raw.replace(/,/g, '') === text.replace(/,/g, '')) {   // only a separator went: take the digit beside it
      if (kind === 'deleteContentBackward' && at > 0) { raw = raw.slice(0, at - 1) + raw.slice(at); at -= 1; }
      else if (kind === 'deleteContentForward') raw = raw.slice(0, at) + raw.slice(at + 1);
    }
    const next = group(raw);
    const before = raw.slice(0, at).replace(/,/g, '').length;
    let position = 0;
    for (let seen = 0; position < next.length && seen < before; position++) if (next[position] !== ',') seen++;
    caret.current = position; setText(next);
  };
  const typed = number(text);
  const words = typed == null ? null : magnitude(typed);
  const commit = async () => {
    if (!text.trim()) return;
    const v = number(text); if (v == null) { setBad(true); return; }
    setBad(false); if (v === sent) return;
    setSent(v);
    try { await onSet(v); setSaved(true); setTimeout(() => setSaved(false), 2500); }
    catch (e) { setSent(initial); setFailed(String((e as Error).message || e)); }
  };
  return <span className="row" style={{ gap: 4 }}>
    <input ref={field} className={'num' + (bad ? ' bad' : '')} style={{ width }} inputMode="decimal" value={text} placeholder={placeholder || 'number'} disabled={busy} data-testid={testId}
      onChange={change} onBlur={() => void commit()} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void commit(); } }} />
    {units && units !== '1' ? <span className="faint small">{units}</span> : null}
    {words && text.trim() ? <span className="faint small" style={{ whiteSpace: 'nowrap' }} data-testid={testId ? `${testId}-words` : 'number-words'}>· {words}</span> : null}
    {bad ? <span className="pill bad">not a number</span> : failed ? <span className="pill bad" data-testid="control-error">{failed}</span> : saved ? <span className="pill clear" data-testid="saved">saved</span> : null}
  </span>;
}

function useLocalError() {
  const [error, setError] = useState<string | null>(null);
  const guard = async (action: () => Promise<unknown>) => { setError(null); try { await action(); } catch (e) { setError(String((e as Error).message || e)); } };
  return { error, guard, line: error ? <div className="pill bad" role="alert" data-testid="control-error">{error}</div> : null };
}

const escapeRe = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** What a quantity or variable means, for a name in a finding or question. */
function meaningOf(doc: CharterView['charter'], name: string): string {
  const q = doc.quantities[name]; const v = doc.variables.find(x => x.name === name);
  const text = q?.description || v?.description || '';
  const units = q?.units && q.units !== '1' ? ` (${q.units})` : v?.units && v.units !== '1' ? ` (${v.units})` : '';
  return text ? text + units : '';
}
/** Prose with the charter's names set apart, each carrying its meaning on hover. */
function Names({ text, doc }: { text: string; doc: CharterView['charter'] }) {
  const names = [...Object.keys(doc.quantities), ...doc.variables.map(v => v.name)].filter(n => n.length > 1).sort((a, b) => b.length - a.length);
  if (!names.length) return <>{text}</>;
  const re = new RegExp(`(?<![\\w])(${names.map(escapeRe).join('|')})(?![\\w])`, 'g');
  return <>{text.split(re).map((part, i) => names.includes(part) ? <span key={i} className="qname" title={meaningOf(doc, part) || 'No description in the charter'}>{part}</span> : part)}</>;
}
// An order (a permutation) has no bounds or values: it says how many items it orders.
const order = (v: Variable) => `an order of ${v.shape?.length === 1 ? String(v.shape[0]) : '?'} items`;

/** Each name a finding or question is about, under it: what it means, the unit its numbers are in, and its value or bounds
 *  now, with what the unit checks say about it. The reader need not know the charter, or the other campaigns, by heart. */
function Meanings({ names, doc, values, notes }: { names: string[]; doc: CharterView['charter']; values: Record<string, number | null>; notes: Record<string, string[]> }) {
  const rows = names.filter(name => doc.quantities[name] || doc.variables.some(v => v.name === name));
  return rows.length ? <div className="small muted finding-meaning" data-testid="finding-meaning">{rows.map(name => <Meaning key={name} name={name} doc={doc} values={values} notes={notes[name] || []} />)}</div> : null;
}
function Meaning({ name, doc, values, notes }: { name: string; doc: CharterView['charter']; values: Record<string, number | null>; notes: string[] }) {
  const q = doc.quantities[name]; const v = doc.variables.find(x => x.name === name);
  const units = (q?.units ?? v?.units ?? '').trim();
  const numeric = q ? q.kind === 'number' || q.kind === 'integer' : true;
  const amount = (x: number) => <>{grouped(x)}{units && units !== '1' ? ` ${units}` : ''}{magnitude(x) ? ` (${magnitude(x)})` : ''}</>;
  // A bound may name a quantity: show what it stands for now.
  const bound = (b: unknown) => typeof b === 'number' ? amount(b) : typeof b === 'string' ? <>{b}{typeof values[b] === 'number' ? <> = {amount(values[b] as number)}</> : null}</> : 'none yet';
  const now = q ? (typeof values[name] === 'number' ? <>now {amount(values[name] as number)}</> : numeric ? 'no value yet' : null)
    : v?.representation === 'discrete' ? (v.values.length ? `one of ${v.values.map(String).join(', ')}` : 'no values yet')
    : v?.representation === 'structured' ? `a value the problem's library checks: ${v.layout || 'no layout yet'}`
    : v?.representation === 'permutation' ? <>{order(v)}{typeof v.shape?.[0] === 'string' && typeof values[v.shape[0]] === 'number' ? <> ({v.shape[0]} = {grouped(values[v.shape[0]] as number)})</> : null}</>
    : v ? <>from {bound(v.lower as unknown)} to {bound(v.upper as unknown)}</> : null;
  return <div data-testid="meaning" data-name={name}>
    <span className="qname">{name}</span>{q?.description || v?.description || ''}
    {numeric ? <> · {units === '1' ? 'a pure number' : units ? <>in <strong className="unit" data-testid="meaning-unit">{units}</strong></> : 'no unit given'}</> : null}
    {now ? <> · {now}</> : null}
    {notes.map((note, i) => <div key={i} className="unit-note" data-testid="unit-note">{note}</div>)}
  </div>;
}

function FindingRow({ finding, doc, values, notes, related = [], busy, edit, post, variableIndex, next, writer = 'formulator' }: { writer?: string; finding: Finding; doc: CharterView['charter']; values: Record<string, number | null>; notes: Record<string, string[]>; related?: Question[]; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown>; post: (path: string, body: Record<string, unknown>) => Promise<unknown>; variableIndex: (name: string) => number; next?: boolean }) {
  const [mode, setMode] = useState<'value' | 'expression' | 'ask' | 'waive' | null>(null);
  const [text, setText] = useState('');
  const local = useLocalError();
  const name = finding.about[0];
  const quantity = name ? doc.quantities[name] : undefined;
  const variable = name ? doc.variables.find(v => v.name === name) : undefined;
  const code = finding.code;
  const setValue = (v: number) => edit([{ op: 'set', path: `quantities.${name}.value`, value: v }], `Set ${name} on the Charter page`);
  const setExpression = () => edit([{ op: 'set', path: `quantities.${name}.expression`, value: text.trim() }, { op: 'set', path: `quantities.${name}.role`, value: 'derived' }], `Derived ${name} on the Charter page`);
  // Waive suggestions are offered only when the service lets this finding be waived.
  const suggestions = (finding.suggestions || []).filter(s => s.action !== 'waive' || finding.waivable);
  const suggestedRequest = suggestions.find(s => s.action === 'request')?.text || '';
  // An assumption is accepted by its subject: a quantity's name, or statement<index> for one stated in words.
  const subject = finding.key.slice(code.length + 1);
  const [accepting, setAccepting] = useState(false);
  const accept = () => local.guard(async () => { setAccepting(true); try { await post('accept-assumptions', { names: [subject] }); } finally { setAccepting(false); } });
  const acceptLabel = (what: string) => accepting ? 'Accepting…' : what;
  return (
    <article className={'finding blocking' + (next ? ' next' : '')} data-testid="finding" data-code={code} data-about={name || ''} data-next={next ? '1' : undefined}>
      <div className="row">{next ? <Pill tone="you">next</Pill> : null}<span className="finding-code" title={code}>{checkLabel(code)}</span><span className="grow"><Names text={finding.message} doc={doc} /></span></div>
      <Meanings names={finding.about} doc={doc} values={values} notes={notes} />
      {related.length ? <div className="small related-question" data-testid="related-question">The {writer} also asks about this, under Questions below: {related.slice(0, 2).map((q, i) => <span key={q.id} title={q.question}>{i ? '; ' : ''}“{brief(q.question, 90)}”</span>)}{related.length > 2 ? ` and ${related.length - 2} more` : ''}. Answering {related.length === 1 ? 'it' : 'them'} may settle or replace this check{code === 'assumption.unaccepted' ? '; accept it now only if you want it as written' : ''}.</div> : null}
      {finding.detail ? <details className="fold" style={{ borderBottom: 'none' }} data-testid="finding-detail"><summary><span className="fold-title small">Technical detail (for the formulator or a developer)</span></summary><pre className="wrap small">{finding.detail}</pre></details> : null}
      <div className="row wrap finding-actions">
        {code === 'assumption.unaccepted' && quantity ? <>
          <button className="btn small primary" disabled={busy} onClick={accept} data-testid="accept-assumption">{acceptLabel(`Accept ${show(quantity.value)}${quantity.units && quantity.units !== '1' ? ` ${quantity.units}` : ''}`)}</button>
          <span className="small faint">or change it:</span>
          <NumberField initial={quantity.value} units={quantity.units} onSet={setValue} busy={busy} testId="finding-value" />
        </> : null}
        {code === 'assumption.unaccepted' && !quantity ? <button className="btn small primary" disabled={busy} onClick={accept} data-testid="accept-assumption" title="Records that you accept this assumption as written">{acceptLabel('Accept as written')}</button> : null}
        {code === 'quantity.no_value' || code === 'quantity.range' || code === 'constraint.test' && quantity ? <>
          <label className="field"><span className="field-label">value of {name}{inUnits(quantity?.units)}</span><NumberField initial={quantity?.value} units={quantity?.units} onSet={setValue} busy={busy} testId="finding-value" width={140} /></label>
          <button className="btn small" disabled={busy} onClick={() => setMode(mode === 'expression' ? null : 'expression')}>or derive it from others</button>
        </> : null}
        {code === 'variable.bounds' && variable ? <>
          <label className="field"><span className="field-label">lowest {name} allowed{inUnits(variable.units)}</span><NumberField initial={variable.lower} units={variable.units} onSet={v => edit([{ op: 'set', path: `variables.${variableIndex(name)}.lower`, value: v }], `Set the lower bound of ${name}`)} busy={busy} testId="finding-lower" width={130} /></label>
          <label className="field"><span className="field-label">highest {name} allowed{inUnits(variable.units)}</span><NumberField initial={variable.upper} units={variable.units} onSet={v => edit([{ op: 'set', path: `variables.${variableIndex(name)}.upper`, value: v }], `Set the upper bound of ${name}`)} busy={busy} testId="finding-upper" width={130} /></label>
        </> : null}
        {code === 'variable.values' && variable ? <>
          <label className="field"><span className="field-label">permitted values of {name}, comma-separated</span><input style={{ width: 260 }} placeholder="e.g. 1, 2, 5, 10" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-values" /></label>
          <button className="btn small primary" disabled={busy || !text.trim()} onClick={() => edit([{ op: 'set', path: `variables.${variableIndex(name)}.values`, value: text.split(',').map(s => number(s) ?? s.trim()) }], `Set the values of ${name}`)}>Set</button>
        </> : null}
        {!quantity && !variable && code !== 'assumption.unaccepted' ? <span className="small faint">{finding.about.length ? `Settled by ${finding.about.join(', ')} above.` : 'No single field settles this: take a suggestion below, or ask the formulator.'}</span> : null}
        <button className="btn small" disabled={busy} onClick={() => { if (mode !== 'ask' && !text.trim() && suggestedRequest) setText(suggestedRequest); setMode(mode === 'ask' ? null : 'ask'); }} data-testid="finding-ask">Ask the {writer}</button>
        {finding.waivable ? <button className="btn small" disabled={busy} onClick={() => setMode(mode === 'waive' ? null : 'waive')}>Waive</button> : null}
      </div>
      {suggestions.length ? <div className="row wrap finding-actions" data-testid="finding-suggestions"><span className="small faint">Suggested:</span>
        {suggestions.map((s, i) => <button key={i} className={'btn small' + (s.action === 'edit' ? ' primary' : '')} disabled={busy} data-testid="finding-suggestion" data-action={s.action}
          title={s.action === 'waive' ? `Waives it with the reason: ${s.reason}` : s.action === 'edit' ? `Changes the charter now: ${s.text}` : `Sends to the ${writer}: ${s.text}`}
          onClick={() => local.guard(() => s.action === 'waive' ? post('waive', { key: finding.key, reason: s.reason || s.label })
            : s.action === 'edit' ? edit(s.changes || [], s.rationale || s.label) : post('requests', { text: s.text || s.label }))}>{s.label}</button>)}
        {suggestions.some(s => s.action === 'edit') ? <span className="small faint">{suggestions.find(s => s.action === 'edit')!.text}</span> : null}</div> : null}
      {mode === 'expression' ? <div className="row" style={{ alignItems: 'flex-end', marginTop: 6 }}><label className="field grow"><span className="field-label">{name} as an expression in other quantities · known: {Object.keys(values).slice(0, 8).join(', ')}</span>
        <input placeholder="e.g. n_seats * weekly_limit_per_seat" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-expression" /></label>
        <button className="btn small primary" disabled={busy || !text.trim()} onClick={setExpression}>Derive</button></div> : null}
      {mode === 'ask' ? <div className="row" style={{ alignItems: 'flex-end', marginTop: 6 }}><label className="field grow"><span className="field-label">What should change, in your words; {writer === 'lead' ? 'the lead writes the charter again' : 'the formulator answers with options to choose from'}</span>
        <input placeholder="e.g. take the bounds from the paper's table 2" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-request" /></label>
        <button className="btn small primary" disabled={busy || !text.trim()} data-testid="finding-request-send" onClick={() => local.guard(async () => { await post('requests', { text: text.trim() === suggestedRequest ? suggestedRequest : `About "${finding.message}": ${text.trim()}` }); setText(''); setMode(null); })}>Send</button></div> : null}
      {local.line}
      {mode === 'waive' ? <div className="row" style={{ alignItems: 'flex-end', marginTop: 6 }}><label className="field grow"><span className="field-label">Why this may stand as it is; recorded with the waiver</span>
        <input placeholder="e.g. the lab never reaches that regime" value={text} onChange={e => setText(e.target.value)} disabled={busy} /></label>
        <button className="btn small" disabled={busy || !text.trim()} onClick={() => local.guard(async () => { await post('waive', { key: finding.key, reason: text.trim() }); setText(''); setMode(null); })}>Waive</button></div> : null}
    </article>
  );
}

/** A value that is not one number (a clock reading, a table of orders) as it is: the material gave it, so it is shown, never an empty number field. */
function DataValue({ value }: { value: unknown }) {
  const cell = (v: unknown) => v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : show(v);
  if (Array.isArray(value) && value.length && value.every(row => row && typeof row === 'object' && !Array.isArray(row))) {
    const rows = value as Record<string, unknown>[];
    const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
    return <table className="small" data-testid="data-value"><thead><tr>{columns.map(col => <th key={col}>{col}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={i}>{columns.map(col => <td key={col}>{cell(row[col])}</td>)}</tr>)}</tbody></table>;
  }
  const text = Array.isArray(value) ? value.map(cell).join(', ') : value && typeof value === 'object' ? Object.entries(value).map(([k, v]) => `${k} ${cell(v)}`).join(', ') : cell(value);
  return <span className="mono small" data-testid="data-value">{text}</span>;
}

function QuantityRow({ name, quantity: q, computed, error, busy, edit, post }: { name: string; quantity: Quantity; computed: number | null | undefined; error?: string; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown>; post: (path: string, body: Record<string, unknown>) => Promise<unknown> }) {
  const derived = q.role === 'derived';
  const value = q.value as unknown;
  const data = q.kind === 'data' || (value != null && typeof value !== 'number');
  return <tr data-testid="quantity" data-name={name}>
    <td><strong>{name}</strong>{q.description ? <div className="small faint">{q.description}</div> : null}</td>
    <td>{derived ? <span className="mono" title={q.expression || ''}>{computed == null ? <span className="faint">{error || 'not computable yet'}</span> : show(computed)} <span className="faint small">= {q.expression}</span></span>
      : data ? <DataValue value={value} />
      : <NumberField initial={q.value} onSet={v => edit([{ op: 'set', path: `quantities.${name}.value`, value: v }], `Set ${name} on the Charter page`)} busy={busy} testId={`value-${name}`} width={130} />}
      {!derived && q.range && (q.range[0] != null || q.range[1] != null) ? <div className="small faint">range {show(q.range[0]) || '…'} to {show(q.range[1]) || '…'}</div> : null}</td>
    <td className="small">{q.units && q.units !== '1' ? q.units : ''}</td>
    <td><Pill>{q.role}</Pill></td>
    <td>{q.origin === 'assumed' ? <span className="row" style={{ gap: 4 }}><Pill tone={q.accepted ? 'clear' : 'attention'}>{q.accepted ? 'assumed · accepted' : 'assumed'}</Pill>{!q.accepted ? <button className="btn quiet small" disabled={busy} onClick={() => post('accept-assumptions', { names: [name] })}>Accept</button> : null}</span>
      : <Pill tone={q.origin === 'researcher' ? 'you' : ''}>{q.origin || ''}</Pill>}</td>
  </tr>;
}

function MethodAccess({ access, confirmed, busy, edit }: { access: Access; confirmed: boolean; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown> }) {
  const own = (value: string | null, words: Record<string, string>, fallback: string) => `the problem's own: ${value ? words[value] || value : fallback}`;
  const choose = (field: 'access' | 'cost_axis', value: string) => value === ''
    ? (access.charter[field] != null ? edit([{ op: 'remove', path: `evaluator.${field}` }], `Use the problem's own ${field === 'access' ? 'access' : 'cost axis'}`) : Promise.resolve())
    : edit([{ op: 'set', path: `evaluator.${field}`, value }], `Set ${field === 'access' ? 'the access' : 'the cost axis'} to ${value}`);
  return <Section title="How methods reach the objective" right={<span className="small faint">{confirmed ? 'fixed by the confirmed revision' : 'choose before confirming'}</span>}>
    <div className="col small" data-testid="charter-access">
      <label className="row">Access <select data-testid="access-select" disabled={busy || confirmed} value={access.charter.access ?? ''} onChange={e => void choose('access', e.target.value)}>
        <option value="">{own(access.problem.access, ACCESS_WORDS, 'white box')}</option>
        {Object.entries(ACCESS_WORDS).map(([key, words]) => <option key={key} value={key}>{words}</option>)}</select></label>
      <label className="row">Compared on <select data-testid="cost-axis-select" disabled={busy || confirmed} value={access.charter.cost_axis ?? ''} onChange={e => void choose('cost_axis', e.target.value)}>
        <option value="">{own(access.problem.cost_axis, AXIS_WORDS, 'worker-seconds, core-seconds when a method uses several threads')}</option>
        {Object.entries(AXIS_WORDS).map(([key, words]) => <option key={key} value={key}>{words}</option>)}</select></label>
      <p className="muted" data-testid="access-why">{access.access === 'oracle'
        ? 'Methods are counted by what they ask the evaluator; choose this for an expensive evaluator (a simulator, a measurement) or when you want a black-box comparison.'
        : 'Methods may use the objective\'s code freely and are judged by the time they take. Choose oracle for an expensive evaluator (a simulator, a measurement) or a black-box comparison.'}</p>
    </div></Section>;
}

function VariableRow({ index, variable: v, busy, edit }: { index: number; variable: Variable; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown> }) {
  const continuous = v.representation === 'continuous' || v.representation === 'integer';
  return <tr data-testid="variable" data-name={v.name}>
    <td><strong>{v.name}</strong>{v.description ? <div className="small faint">{v.description}</div> : null}</td>
    <td className="small">{v.representation}{v.shape?.length && v.representation !== 'permutation' ? <span className="faint"> × {v.shape.map(String).join(' × ')}</span> : null}</td>
    <td>{v.representation === 'permutation' ? <span className="small" data-testid={`order-${v.name}`}>{order(v)}</span>
      : v.representation === 'structured' ? <span className="small" data-testid={`structure-${v.name}`} title={v.meaning || ''}>{v.layout || 'no layout yet'}; its library checks it</span>
      : continuous ? <NumberField initial={v.lower} onSet={x => edit([{ op: 'set', path: `variables.${index}.lower`, value: x }], `Set the lower bound of ${v.name}`)} busy={busy} width={110} testId={`lower-${v.name}`} /> : <span className="faint small">{v.values.length ? v.values.map(String).join(', ') : 'no values'}</span>}</td>
    <td>{continuous ? <NumberField initial={v.upper} onSet={x => edit([{ op: 'set', path: `variables.${index}.upper`, value: x }], `Set the upper bound of ${v.name}`)} busy={busy} width={110} testId={`upper-${v.name}`} /> : null}</td>
    <td className="small">{v.units || ''}</td>
  </tr>;
}

function QuestionRow({ question: q, doc, values, notes, busy, post, working, next, writer = 'formulator' }: { question: Question; doc: CharterView['charter']; values: Record<string, number | null>; notes: Record<string, string[]>; busy: boolean; post: (path: string, body: Record<string, unknown>) => Promise<unknown>; working?: boolean; next?: boolean; writer?: string }) {
  const [text, setText] = useState('');
  const local = useLocalError();
  const answer = (value: string) => local.guard(() => post('answers', { question_id: q.id, answer: value }));
  const answered = q.answer != null;
  const left = !answered && !!q.sent;   // sent without an answer: the formulator decides it and records an assumption
  return <article className={'finding ' + (answered || left ? 'answered' : 'blocking') + (next ? ' next' : '')} data-testid="question" data-question-id={q.id} data-answered={answered ? '1' : undefined} data-left={left ? '1' : undefined} data-next={next ? '1' : undefined}>
    <div className="row">{next ? <Pill tone="you">next</Pill> : null}<span className="finding-code">question</span><span className={'grow' + (answered || left ? ' faint' : '')}><Names text={q.question} doc={doc} /></span>
      {answered ? <Pill tone={working ? 'agent' : 'clear'}>{working ? 'formulator working' : 'answered'}</Pill> : left ? <Pill tone="agent">{working ? 'formulator deciding' : `left to the ${writer}`}</Pill> : null}</div>
    {!answered && !left ? <Meanings names={q.about || []} doc={doc} values={values} notes={notes} /> : null}
    {answered ? <div className="small faint" style={{ marginTop: 4 }}>Your answer: {q.answer}</div> : left ? <div className="small faint" style={{ marginTop: 4 }}>Left to the {writer}: it decides from your answers and the sources and records an assumption you can change later.</div> : <>
      {q.options?.length ? <div className="row wrap" style={{ marginTop: 6 }}>{q.options.map((o, i) => {
        // The first option is the formulator's recommendation, unless nothing could run under it.
        const unrunnable = (q.unrunnable_options || []).includes(i);
        return <button key={i} className="btn small" disabled={busy} onClick={() => answer(o)} data-testid="question-option" data-unrunnable={unrunnable ? '1' : undefined}
          title={unrunnable ? 'Nothing can run under this choice until something outside the charter changes' : i === 0 ? `The ${writer} recommends this one` : undefined}>
          {o}{unrunnable ? <span className="faint"> · nothing can run</span> : i === 0 ? <span className="faint"> · recommended</span> : null}</button>; })}</div> : null}
      <div className="row" style={{ marginTop: 6 }}><input style={{ flex: 1, minWidth: 160 }} placeholder="or answer in your own words" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="question-text" />
        <button className="btn small primary" disabled={busy || !text.trim()} onClick={async () => { await answer(text.trim()); setText(''); }}>Answer</button></div>
      {local.line}
    </>}
  </article>;
}

const brief = (value: unknown, limit = 90) => { const text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value); return text.length > limit ? text.slice(0, limit - 1) + '…' : text; };
function describeChange(d: Change): string {
  const what = `${d.part === 'text' ? 'the ' : ''}${d.part} ${d.part === 'text' ? '' : d.name}`.trim();
  if (d.change === 'added') return `adds ${what}${d.after != null && typeof d.after !== 'object' ? ` = ${brief(d.after)}` : ''}`;
  if (d.change === 'removed') return `removes ${what}`;
  if (d.before != null || d.after != null) return `changes ${what}: ${brief(d.before)} → ${brief(d.after)}`;
  return `changes ${what}`;
}

function ProposalRow({ proposal: p, busy, refresh, setError }: { proposal: Proposal; busy: boolean; refresh: () => Promise<unknown>; setError: (e: string | null) => void }) {
  const decide = async (option: number | null) => {
    setError(null);
    try { await api(`/api/v1/problem-charter-proposals/${p.id}/decision`, { method: 'POST', body: JSON.stringify({ option }) }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  const open = p.status === 'open';
  const options = p.options || [];
  return <article className={'finding ' + (open ? 'blocking' : 'answered')} data-testid="proposal" data-status={p.status}>
    <div className="row"><span className="finding-code">formulator</span>
      <span className={'grow' + (open ? '' : ' faint')}>{p.asked ? <><strong>Answers your request:</strong> “{p.asked}”</> : <><strong>Proposes a change.</strong>{p.request ? <span className="muted"> {p.request}</span> : null}</>}</span>
      <Pill tone={open ? 'attention' : p.status === 'accepted' ? 'clear' : ''}>{open ? `${options.length} option${options.length === 1 ? '' : 's'}` : p.status === 'accepted' && p.accepted_option != null ? `chose “${options[p.accepted_option]?.label || p.accepted_option + 1}”` : p.status}</Pill></div>
    {open ? <div className="col" style={{ marginTop: 8 }}>
      {options.map((o, i) => {
        const diff = o.diff || []; const left = o.findings || [];
        return <div key={i} className="card" data-testid="proposal-option">
          <div className="row"><strong className="grow">{o.label || o.summary || `Option ${i + 1}`}</strong><button className="btn small primary" disabled={busy} data-testid="proposal-choose" onClick={() => decide(i)}>Choose</button></div>
          {o.reason ? <p className="small" style={{ margin: '4px 0 0', maxWidth: '70ch' }}>{o.reason}</p> : null}
          {diff.length ? <details className="fold" style={{ borderBottom: 'none' }}><summary><span className="fold-title small">What changes ({diff.length})</span></summary>
            <ul className="small" style={{ margin: '2px 0 4px' }}>{diff.map((d, j) => <li key={j}>{describeChange(d)}</li>)}</ul></details> : null}
          {o.blocking_reason || left.length ? <details className="fold" style={{ borderBottom: 'none' }}><summary><span className="fold-title small">Leaves {left.length || 'some'} check{left.length === 1 ? '' : 's'} open</span></summary>
            {o.blocking_reason ? <p className="small muted" style={{ margin: '2px 0', maxWidth: '70ch' }}>{o.blocking_reason}</p> : null}
            <ul className="small" style={{ margin: '2px 0 4px' }}>{left.map((f, j) => <li key={j}>{f.message}</li>)}</ul></details> : null}
        </div>;
      })}
      <div className="row"><button className="btn quiet small" disabled={busy} data-testid="proposal-decline" onClick={() => decide(null)}>Decline all</button></div>
    </div> : null}
  </article>;
}

function AskFormulator({ busy, post, writer = 'formulator' }: { busy: boolean; post: (path: string, body: Record<string, unknown>) => Promise<unknown>; writer?: string }) {
  const [text, setText] = useState('');
  const local = useLocalError();
  return <Section title={`Ask the ${writer} for a change`} right={<span className="small faint">{writer === 'lead' ? 'in words; it writes the charter again, which is read against your words again'
    : 'in words; it answers with options you choose from, never with numbers it made up'}</span>}>
    <div className="row"><input style={{ flex: 1 }} placeholder="e.g. make the weekly limit follow from the monthly budget" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="charter-request"
      onKeyDown={e => { if (e.key === 'Enter' && text.trim()) { e.preventDefault(); void local.guard(async () => { await post('requests', { text: text.trim() }); setText(''); }); } }} />
      <button className="btn small primary" disabled={busy || !text.trim()} onClick={() => local.guard(async () => { await post('requests', { text: text.trim() }); setText(''); })} data-testid="charter-request-send">Send</button></div>
    {local.line}
  </Section>;
}
