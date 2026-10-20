/** The charter as a form: every blocking finding is settled in place (a value, a bound, an acceptance, an answer), nothing
 *  commits until Confirm, and the formulator is asked in words only when a number is not enough. Values are typed as numbers. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useRead } from '../api/queries';
import { send } from '../commands/bus';
import { Markdown } from '../chat/render/Markdown';
import { Empty, Failed, Loading, Pill, Section } from '../primitives/ui';

interface Quantity { description?: string; kind?: string; role: 'input' | 'derived' | string; value: number | null; expression: string | null; units?: string; range?: [number | null, number | null] | null; origin?: string; accepted?: boolean; note?: string }
interface Variable { name: string; description?: string; representation: string; lower: number | null; upper: number | null; values: unknown[]; units?: string; shape?: unknown[] }
interface Finding { key: string; code: string; severity: 'blocking' | 'warning' | string; message: string; about: string[]; waivable: boolean }
interface Question { id: string; question: string; options?: string[]; answer: string | null }
interface Proposal { id: string; status: string; request?: string; options?: { summary?: string; changes?: unknown[] }[] }
interface CharterView { id: string; title?: string; status: string; revision: number; blocking: number; findings: Finding[]; values: Record<string, number | null>; errors?: Record<string, string>;
  rendered?: Record<string, string>; proposals: Proposal[]; charter: { title?: string; text?: string; summary?: string; quantities: Record<string, Quantity>; variables: Variable[]; questions: Question[]; assumptions: { statement: string; accepted?: boolean }[]; waivers: { key: string; reason: string }[] } }

const number = (text: string) => { const v = Number(text.replace(/[,_\s]/g, '')); return Number.isFinite(v) ? v : null; };
const show = (v: unknown) => v == null ? '' : typeof v === 'number' ? (Math.abs(v) >= 1e4 ? v.toLocaleString('en-US') : String(v)) : String(v);

export function CharterPanel({ charterId, campaignId, version, onChanged }: { charterId: string; campaignId: string; version?: number; onChanged: () => unknown }) {
  const charter = useRead<CharterView>(['charter', charterId], `/api/v1/problem-charters/${charterId}`, { refetchInterval: 8000 });
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (charter.isPending) return <Loading what="Reading the charter" />;
  if (charter.error) return <Failed error={charter.error} />;
  const c = charter.data;
  const doc = c.charter;
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ['charter', charterId] }), queryClient.invalidateQueries({ queryKey: ['campaigns'] })]);
  const post = async (path: string, body: Record<string, unknown>) => {
    setError(null); setBusy(true);
    try { await api(`/api/v1/problem-charters/${charterId}/${path}`, { method: 'POST', body: JSON.stringify({ expected_revision: c.revision, ...body }) }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); throw e; }
    finally { setBusy(false); }
  };
  const edit = (changes: Record<string, unknown>[], rationale: string) => post('edit', { changes, rationale });
  const confirm = async () => {
    setError(null); setBusy(true);
    try {
      await api(`/api/v1/problem-charters/${charterId}/confirm`, { method: 'POST', body: JSON.stringify({ expected_revision: c.revision }) });
      if (version !== undefined) await send({ operation: 'campaign.update', campaignId, expectedRevision: version, payload: { charter: { id: charterId, revision: c.revision }, rationale: 'Confirmed the charter adopted from the problem note' } });
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ['summary', campaignId] })]);
      onChanged();
    } catch (e) { setError(String((e as Error).message || e)); }
    finally { setBusy(false); }
  };
  const openQuestions = doc.questions.filter(q => q.answer == null);
  const blocking = c.findings.filter(f => f.severity === 'blocking' && f.code !== 'question.open');
  const warnings = c.findings.filter(f => f.severity !== 'blocking');
  const confirmed = c.status === 'confirmed';
  const why = confirmed ? null : blocking.length ? `${blocking.length} blocking finding${blocking.length === 1 ? '' : 's'} to settle first` : openQuestions.length ? `${openQuestions.length} question${openQuestions.length === 1 ? '' : 's'} from the formulator to answer first` : null;
  const variableIndex = (name: string) => doc.variables.findIndex(v => v.name === name);
  return (
    <div className="col" data-testid="charter-panel" data-revision={c.revision}>
      <Section title={String(doc.title || c.title || 'Charter')} right={<div className="row">
        <Pill tone={confirmed ? 'clear' : blocking.length ? 'attention' : ''}>{confirmed ? 'confirmed' : blocking.length ? `${blocking.length} blocking` : 'ready to confirm'} · r{c.revision}</Pill>
        {!confirmed ? <button className="btn primary small" onClick={confirm} data-testid="confirm-charter" disabled={busy || !!why} title={why || 'Compiles the tasks and sets the campaign\'s charter revision'}>Confirm and set the tasks</button> : null}</div>}>
        {error ? <div className="pill bad" role="alert" data-testid="charter-error">{error}</div> : null}
        {why && !confirmed ? <p className="small muted" data-testid="confirm-why">{why}. Settle each item below; nothing commits until you confirm.</p> : null}
        {doc.summary ? <p className="lede">{doc.summary}</p> : null}
      </Section>

      {blocking.length ? <Section title="To settle before confirming">
        <div className="col" data-testid="findings">
          {blocking.map(f => <FindingRow key={f.key} finding={f} doc={doc} values={c.values} busy={busy} edit={edit} post={post} variableIndex={variableIndex} />)}
        </div>
      </Section> : null}

      {doc.questions.length ? <Section title="Questions from the formulator">
        {doc.questions.map(q => <QuestionRow key={q.id} question={q} busy={busy} post={post} />)}
      </Section> : null}

      <Section title="Quantities" right={<span className="small faint">type a number and press Enter; derived values are computed</span>}>
        {Object.keys(doc.quantities).length ? <table className="quantities" data-testid="quantities"><thead><tr><th>Name</th><th>Value</th><th>Unit</th><th>Role</th><th>Origin</th></tr></thead><tbody>
          {Object.entries(doc.quantities).map(([name, q]) => <QuantityRow key={name} name={name} quantity={q} computed={c.values[name]} error={c.errors?.[name]} busy={busy} edit={edit} post={post} />)}
        </tbody></table> : <Empty>None yet.</Empty>}
      </Section>

      {doc.variables.length ? <Section title="Decision variables" right={<span className="small faint">what the optimizer changes; bounds are typed as numbers</span>}>
        <table data-testid="variables"><thead><tr><th>Name</th><th>Representation</th><th>Lower</th><th>Upper</th><th>Unit</th></tr></thead><tbody>
          {doc.variables.map((v, i) => <VariableRow key={v.name} index={i} variable={v} busy={busy} edit={edit} />)}
        </tbody></table>
      </Section> : null}

      {c.proposals.length ? <Section title="Proposals from the formulator">
        {c.proposals.map(p => <ProposalRow key={p.id} proposal={p} busy={busy} charterId={charterId} refresh={refresh} setError={setError} />)}
      </Section> : null}

      {warnings.length ? <Section title="Warnings" right={<span className="small faint">not blocking; the formulator can tidy them</span>}>
        {warnings.map(f => <div key={f.key} className="finding warning small" data-testid="warning"><span className="finding-code">{f.code}</span> {f.message}</div>)}
      </Section> : null}

      <AskFormulator busy={busy} post={post} />

      {c.rendered?.text || doc.text ? <details className="card"><summary>Charter text</summary><Markdown text={String(c.rendered?.text || doc.text)} thread={null} /></details> : null}
      <details className="card"><summary>Raw charter (JSON)</summary><pre className="wrap" data-testid="raw-charter">{JSON.stringify(doc, null, 2)}</pre></details>
    </div>
  );
}

function NumberField({ initial, units, placeholder, onSet, busy, testId, width = 150 }: { initial?: number | null; units?: string; placeholder?: string; onSet: (value: number) => Promise<unknown>; busy: boolean; testId?: string; width?: number }) {
  const [text, setText] = useState(initial == null ? '' : String(initial));
  const [bad, setBad] = useState(false);
  const [sent, setSent] = useState<number | null | undefined>(initial);   // the value last committed, so Enter and blur never send it twice
  const commit = async () => { if (!text.trim()) return; const v = number(text); if (v == null) { setBad(true); return; } setBad(false); if (v === sent) return; setSent(v); await onSet(v); };
  return <span className="row" style={{ gap: 4 }}>
    <input className={'num' + (bad ? ' bad' : '')} style={{ width }} inputMode="decimal" value={text} placeholder={placeholder || 'number'} disabled={busy} data-testid={testId}
      onChange={e => setText(e.target.value)} onBlur={() => void commit()} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void commit(); } }} />
    {units && units !== '1' ? <span className="faint small">{units}</span> : null}
    {bad ? <span className="pill bad">not a number</span> : null}
  </span>;
}

function FindingRow({ finding, doc, values, busy, edit, post, variableIndex }: { finding: Finding; doc: CharterView['charter']; values: Record<string, number | null>; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown>; post: (path: string, body: Record<string, unknown>) => Promise<unknown>; variableIndex: (name: string) => number }) {
  const [mode, setMode] = useState<'value' | 'expression' | 'ask' | 'waive' | null>(null);
  const [text, setText] = useState('');
  const name = finding.about[0];
  const quantity = name ? doc.quantities[name] : undefined;
  const variable = name ? doc.variables.find(v => v.name === name) : undefined;
  const code = finding.code;
  const setValue = (v: number) => edit([{ op: 'set', path: `quantities.${name}.value`, value: v }], `Set ${name} on the Charter page`);
  const setExpression = () => edit([{ op: 'set', path: `quantities.${name}.expression`, value: text.trim() }, { op: 'set', path: `quantities.${name}.role`, value: 'derived' }], `Derived ${name} on the Charter page`);
  return (
    <article className="finding blocking" data-testid="finding" data-code={code} data-about={name || ''}>
      <div className="row"><span className="finding-code">{code}</span><span className="grow">{finding.message}</span></div>
      <div className="row wrap finding-actions">
        {code === 'assumption.unaccepted' && quantity ? <>
          <button className="btn small primary" disabled={busy} onClick={() => post('accept-assumptions', { names: [name] })} data-testid="accept-assumption">Accept {show(quantity.value)}{quantity.units && quantity.units !== '1' ? ` ${quantity.units}` : ''}</button>
          <span className="small faint">or change it:</span>
          <NumberField initial={quantity.value} units={quantity.units} onSet={setValue} busy={busy} testId="finding-value" />
        </> : null}
        {code === 'assumption.unaccepted' && !quantity ? <button className="btn small primary" disabled={busy} onClick={() => post('accept-assumptions', { names: [name] })} data-testid="accept-assumption">Accept</button> : null}
        {code === 'quantity.no_value' || code === 'quantity.range' || code === 'constraint.test' && quantity ? <>
          <NumberField initial={quantity?.value} units={quantity?.units} placeholder={`value of ${name}`} onSet={setValue} busy={busy} testId="finding-value" />
          <button className="btn quiet small" onClick={() => setMode(mode === 'expression' ? null : 'expression')}>or derive it from others</button>
        </> : null}
        {code === 'variable.bounds' && variable ? <>
          <span className="small faint">lower</span><NumberField initial={variable.lower} units={variable.units} onSet={v => edit([{ op: 'set', path: `variables.${variableIndex(name)}.lower`, value: v }], `Set the lower bound of ${name}`)} busy={busy} testId="finding-lower" width={120} />
          <span className="small faint">upper</span><NumberField initial={variable.upper} units={variable.units} onSet={v => edit([{ op: 'set', path: `variables.${variableIndex(name)}.upper`, value: v }], `Set the upper bound of ${name}`)} busy={busy} testId="finding-upper" width={120} />
        </> : null}
        {code === 'variable.values' && variable ? <>
          <input style={{ width: 240 }} placeholder="permitted values, comma-separated" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-values" />
          <button className="btn small primary" disabled={busy || !text.trim()} onClick={() => edit([{ op: 'set', path: `variables.${variableIndex(name)}.values`, value: text.split(',').map(s => number(s) ?? s.trim()) }], `Set the values of ${name}`)}>Set</button>
        </> : null}
        {!quantity && !variable && code !== 'assumption.unaccepted' ? <span className="small faint">{finding.about.length ? `Settled by ${finding.about.join(', ')} above.` : 'Needs a change to the charter itself.'}</span> : null}
        <button className="btn quiet small" onClick={() => setMode(mode === 'ask' ? null : 'ask')} data-testid="finding-ask">Ask the formulator</button>
        {finding.waivable ? <button className="btn quiet small" onClick={() => setMode(mode === 'waive' ? null : 'waive')}>Waive</button> : null}
      </div>
      {mode === 'expression' ? <div className="row"><input style={{ flex: 1 }} placeholder={`expression in other quantities, e.g. n_seats * weekly_limit_per_seat`} value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-expression" />
        <button className="btn small primary" disabled={busy || !text.trim()} onClick={setExpression}>Derive</button><span className="small faint">known: {Object.keys(values).slice(0, 8).join(', ')}</span></div> : null}
      {mode === 'ask' ? <div className="row"><input style={{ flex: 1 }} placeholder="what should change, in words; the formulator answers with options" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="finding-request" />
        <button className="btn small primary" disabled={busy || !text.trim()} onClick={async () => { await post('requests', { text: `About "${finding.message}": ${text.trim()}` }); setText(''); setMode(null); }}>Send</button></div> : null}
      {mode === 'waive' ? <div className="row"><input style={{ flex: 1 }} placeholder="why this finding may stand" value={text} onChange={e => setText(e.target.value)} disabled={busy} />
        <button className="btn small" disabled={busy || !text.trim()} onClick={async () => { await post('waive', { key: finding.key, reason: text.trim() }); setText(''); setMode(null); }}>Waive</button></div> : null}
    </article>
  );
}

function QuantityRow({ name, quantity: q, computed, error, busy, edit, post }: { name: string; quantity: Quantity; computed: number | null | undefined; error?: string; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown>; post: (path: string, body: Record<string, unknown>) => Promise<unknown> }) {
  const derived = q.role === 'derived';
  return <tr data-testid="quantity" data-name={name}>
    <td><strong>{name}</strong>{q.description ? <div className="small faint">{q.description}</div> : null}</td>
    <td>{derived ? <span className="mono" title={q.expression || ''}>{computed == null ? <span className="faint">{error || 'not computable yet'}</span> : show(computed)} <span className="faint small">= {q.expression}</span></span>
      : <NumberField initial={q.value} onSet={v => edit([{ op: 'set', path: `quantities.${name}.value`, value: v }], `Set ${name} on the Charter page`)} busy={busy} testId={`value-${name}`} width={130} />}
      {!derived && q.range && (q.range[0] != null || q.range[1] != null) ? <div className="small faint">range {show(q.range[0]) || '…'} to {show(q.range[1]) || '…'}</div> : null}</td>
    <td className="small">{q.units && q.units !== '1' ? q.units : ''}</td>
    <td><Pill>{q.role}</Pill></td>
    <td>{q.origin === 'assumed' ? <span className="row" style={{ gap: 4 }}><Pill tone={q.accepted ? 'clear' : 'attention'}>{q.accepted ? 'assumed · accepted' : 'assumed'}</Pill>{!q.accepted ? <button className="btn quiet small" disabled={busy} onClick={() => post('accept-assumptions', { names: [name] })}>Accept</button> : null}</span>
      : <Pill tone={q.origin === 'researcher' ? 'you' : ''}>{q.origin || ''}</Pill>}</td>
  </tr>;
}

function VariableRow({ index, variable: v, busy, edit }: { index: number; variable: Variable; busy: boolean; edit: (changes: Record<string, unknown>[], rationale: string) => Promise<unknown> }) {
  const continuous = v.representation === 'continuous' || v.representation === 'integer';
  return <tr data-testid="variable" data-name={v.name}>
    <td><strong>{v.name}</strong>{v.description ? <div className="small faint">{v.description}</div> : null}</td>
    <td className="small">{v.representation}{v.shape?.length ? <span className="faint"> × {v.shape.map(String).join(' × ')}</span> : null}</td>
    <td>{continuous ? <NumberField initial={v.lower} onSet={x => edit([{ op: 'set', path: `variables.${index}.lower`, value: x }], `Set the lower bound of ${v.name}`)} busy={busy} width={110} testId={`lower-${v.name}`} /> : <span className="faint small">{v.values.length ? v.values.map(String).join(', ') : 'no values'}</span>}</td>
    <td>{continuous ? <NumberField initial={v.upper} onSet={x => edit([{ op: 'set', path: `variables.${index}.upper`, value: x }], `Set the upper bound of ${v.name}`)} busy={busy} width={110} testId={`upper-${v.name}`} /> : null}</td>
    <td className="small">{v.units || ''}</td>
  </tr>;
}

function QuestionRow({ question: q, busy, post }: { question: Question; busy: boolean; post: (path: string, body: Record<string, unknown>) => Promise<unknown> }) {
  const [text, setText] = useState('');
  const answer = (value: string) => post('answers', { question_id: q.id, answer: value });
  return <article className={'finding ' + (q.answer != null ? 'answered' : 'blocking')} data-testid="question" data-question-id={q.id}>
    <div className="row"><span className="finding-code">question</span><span className="grow">{q.question}</span>{q.answer != null ? <Pill tone="clear">answered</Pill> : null}</div>
    {q.answer != null ? <div className="small" style={{ marginTop: 4 }}><strong>Your answer:</strong> {q.answer}</div> : <>
      {q.options?.length ? <div className="row wrap" style={{ marginTop: 6 }}>{q.options.map((o, i) => <button key={i} className="btn small" disabled={busy} onClick={() => answer(o)} data-testid="question-option">{o}</button>)}</div> : null}
      <div className="row" style={{ marginTop: 6 }}><input style={{ flex: 1 }} placeholder="or answer in your own words" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="question-text" />
        <button className="btn small primary" disabled={busy || !text.trim()} onClick={async () => { await answer(text.trim()); setText(''); }}>Answer</button></div>
    </>}
  </article>;
}

function ProposalRow({ proposal: p, busy, charterId, refresh, setError }: { proposal: Proposal; busy: boolean; charterId: string; refresh: () => Promise<unknown>; setError: (e: string | null) => void }) {
  const decide = async (option: number | null) => {
    setError(null);
    try { await api(`/api/v1/problem-charter-proposals/${p.id}/decision`, { method: 'POST', body: JSON.stringify({ option }) }); await refresh(); }
    catch (e) { setError(String((e as Error).message || e)); }
  };
  void charterId;
  return <article className="finding" data-testid="proposal" data-status={p.status}>
    <div className="row"><span className="finding-code">proposal</span><span className="grow">{p.request || 'A change the formulator proposes'}</span><Pill tone={p.status === 'open' ? 'attention' : ''}>{p.status}</Pill></div>
    {(p.options || []).map((o, i) => <div key={i} className="row small" style={{ marginTop: 4 }}><span className="grow">{o.summary || JSON.stringify(o.changes)}</span>{p.status === 'open' ? <button className="btn small primary" disabled={busy} onClick={() => decide(i)}>Choose</button> : null}</div>)}
    {p.status === 'open' ? <button className="btn quiet small" disabled={busy} onClick={() => decide(null)}>Decline all</button> : null}
  </article>;
}

function AskFormulator({ busy, post }: { busy: boolean; post: (path: string, body: Record<string, unknown>) => Promise<unknown> }) {
  const [text, setText] = useState('');
  return <Section title="Ask the formulator for a change" right={<span className="small faint">in words; it answers with options you choose from, never with numbers it made up</span>}>
    <div className="row"><input style={{ flex: 1 }} placeholder="e.g. make the weekly limit follow from the monthly budget" value={text} onChange={e => setText(e.target.value)} disabled={busy} data-testid="charter-request" />
      <button className="btn small primary" disabled={busy || !text.trim()} onClick={async () => { await post('requests', { text: text.trim() }); setText(''); }} data-testid="charter-request-send">Send</button></div>
  </Section>;
}
