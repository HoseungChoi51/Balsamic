import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { api, errorText } from './api';
import type { Json, State } from './api';
import { Badge, ErrorNotice, Field, Icon, Panel, Status } from './ui';
import { DurationField } from './duration';
import { ReadableText } from './readableText';
import { NewImport } from './problemImport';
import { useCommand } from './commands';
import './problemSetup.css';

const charters = '/api/v1/problem-charters';
const imports = '/api/v1/problem-imports';

/** The part of the address after #new: [] to start, ['import', id] while formulating, [charterId] for a charter. */
function useSetupRoute(): [string[], (path: string) => void] {
  const read = () => location.hash.replace(/^#/, '').split('/').slice(1).filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const change = () => setRoute(read());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  return [route, path => { location.hash = path ? `new/${path}` : 'new'; }];
}

const STEPS = ['Start', 'Formulate', 'Review', 'Confirm'];
function Steps({ at }: { at: number }) {
  return <ol className="setup-steps" aria-label="Steps">{STEPS.map((step, index) =>
    <li key={step} className={index < at ? 'done' : index === at ? 'current' : ''} aria-current={index === at ? 'step' : undefined}>
      <span>{index < at ? <Icon name="check" size={13} /> : index + 1}</span>{step}</li>)}</ol>;
}

export function ProblemSetup({ state, onCreated, onRevised }: { state: State; onCreated: (campaign: Json) => void; onRevised: () => void }) {
  const [route, go] = useSetupRoute();
  if (route[0] === 'import' && route[1]) return <Formulating key={route[1]} importId={route[1]} go={go} />;
  if (route[0]) return <CharterWork key={route[0]} charterId={route[0]} state={state} go={go} onCreated={onCreated} onRevised={onRevised} />;
  return <Start go={go} />;
}

// Start ------------------------------------------------------------------------------------------------
function Start({ go }: { go: (path: string) => void }) {
  const [examples, setExamples] = useState<Json[]>([]), [list, setList] = useState<Json[]>([]), [evaluators, setEvaluators] = useState<Json[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(''), [removing, setRemoving] = useState('');
  const loadList = () => api(charters).then(result => setList(result.charters || [])).catch(e => setError(errorText(e)));
  useEffect(() => {
    api('/api/v1/problem-examples').then(result => setExamples(result.examples || [])).catch(e => setError(errorText(e)));
    api('/api/v1/problems').then(result => setEvaluators(result.problems || [])).catch(() => setEvaluators([]));
    void loadList();
  }, []);
  async function remove(charterId: string) {
    setBusy(charterId); setError('');
    try { await api(`${charters}/${charterId}`, undefined, 'DELETE'); setRemoving(''); await loadList(); } catch (e) { setError(errorText(e)); } finally { setBusy(''); }
  }
  async function open(path: string, body: Json, label: string) {
    setBusy(label); setError('');
    try { go((await api(path, body)).id); } catch (e) { setError(errorText(e)); } finally { setBusy(''); }
  }
  const drafts = list.filter(row => row.status === 'draft'), confirmed = list.filter(row => row.confirmed_revision);
  return <>
    <div className="page-heading"><div><span className="eyebrow">New campaign</span><h1>Set up the problem.</h1>
      <p>Describe the problem, start from an example, or fork a problem you confirmed before. A formulator writes the problem charter; you review it, adjust it and confirm it. No problem fields exist until then.</p></div></div>
    <Steps at={0} />
    <ErrorNotice text={error} />
    <div className="setup-start-grid">
      <NewImport title="Describe the problem" submit="Start the formulator" onStarted={record => go(`import/${record.id}`)} />
      <div className="setup-start-side">
        <Panel title="Start from an example">{examples.length ? <ul className="setup-choices">{examples.map(example => <li key={example.id}>
          <div><strong>{example.name}</strong><span>{example.summary}</span></div>
          <button type="button" className="button small secondary" disabled={!!busy} onClick={() => void open(`${charters}/from-example`, { example_id: example.id }, example.id)}>
            {busy === example.id ? 'Opening…' : 'Use'}</button></li>)}</ul> : <p className="help-text">No examples are installed.</p>}</Panel>
        {evaluators.length > 0 && <Panel title="Start from an installed evaluator"><p className="help-text">Its declared defaults, as inputs you set; no model is involved.</p>
          <ul className="setup-choices">{evaluators.map(evaluator => <li key={evaluator.id}>
            <div><strong>{evaluator.name}</strong><span>{evaluator.id}</span></div>
            <button type="button" className="button small secondary" disabled={!!busy} onClick={() => void open(`${charters}/from-evaluator`, { problem_id: evaluator.id }, evaluator.id)}>
              {busy === evaluator.id ? 'Opening…' : 'Use'}</button></li>)}</ul></Panel>}
        {drafts.length > 0 && <Panel title="Continue a draft"><ul className="setup-choices">{drafts.slice(0, 8).map(row => <li key={row.id}>
          <div><strong>{row.title}</strong><span>Revision {row.revision} · {new Date(row.updated_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span></div>
          <div className="inline-actions">{removing === row.id
            ? <><button type="button" className="button small secondary" disabled={!!busy} onClick={() => void remove(row.id)}>Remove for good</button>
                <button type="button" className="text-button" onClick={() => setRemoving('')}>Keep</button></>
            : <><button type="button" className="text-button" onClick={() => setRemoving(row.id)}>Remove…</button>
                <button type="button" className="button small secondary" onClick={() => go(row.id)}>Open</button></>}</div></li>)}</ul></Panel>}
        {confirmed.length > 0 && <Panel title="Fork a confirmed problem"><p className="help-text">A copy you change along a new axis. It records where it came from.</p>
          <ul className="setup-choices">{confirmed.slice(0, 8).map(row => <li key={row.id}>
            <div><strong>{row.title}</strong><span>Confirmed revision {row.confirmed_revision}{row.campaign_ids?.length ? ` · ${row.campaign_ids.length} campaign${row.campaign_ids.length > 1 ? 's' : ''}` : ''}</span></div>
            <button type="button" className="button small secondary" disabled={!!busy} onClick={() => void open(`${charters}/${row.id}/fork`, {}, row.id)}>{busy === row.id ? 'Forking…' : 'Fork'}</button></li>)}</ul></Panel>}
      </div>
    </div>
  </>;
}

// The formulator at work ---------------------------------------------------------------------------------------
function useImport(importId: string | null | undefined) {
  const [record, setRecord] = useState<Json | null>(null), [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!importId) return;
    try { setRecord(await api(`${imports}/${importId}`)); setError(''); } catch (e) { setError(errorText(e)); }
  }, [importId]);
  useEffect(() => { void load(); }, [load]);
  const running = record?.status === 'running';
  useEffect(() => { if (!running) return; const timer = window.setInterval(() => void load(), 2500); return () => window.clearInterval(timer); }, [running, load]);
  return { record, error, load, running };
}

function FormulatorStatus({ record, onStop }: { record: Json; onStop: () => void }) {
  const last = [...(record.activity || [])].reverse().find((row: Json) => row.kind !== 'message');
  const usage = record.usage || {};
  const cost = record.billing === 'api' ? usage.charged_usd : usage.cost_usd;
  return <div className={`formulator-status ${record.status}`} role="status">
    <div><strong>Formulator</strong> <Status status={record.status} /> <small>{record.model?.model}{record.model?.effort ? ` · ${record.model.effort}` : ''} · ${(cost || 0).toFixed(cost >= 1 ? 2 : 4)}</small></div>
    {record.status === 'running' ? <p>{last?.text || 'Reading the material…'}</p> : record.reply ? <ReadableText text={record.reply} preview={3} more="Show the whole reply" /> : null}
    {record.status !== 'running' && record.error && <ErrorNotice text={record.error} />}
    {record.status === 'running' && <button type="button" className="text-button" onClick={onStop}>Stop</button>}
  </div>;
}

function Formulating({ importId, go }: { importId: string; go: (path: string) => void }) {
  const { record, error, load } = useImport(importId);
  useEffect(() => { if (record?.charter_id) go(record.charter_id); }, [record?.charter_id]);
  return <>
    <div className="page-heading"><div><span className="eyebrow">New campaign</span><h1>{record?.title || 'Formulating the problem'}</h1>
      <p>The formulator reads your material and writes the problem charter. It asks when the material leaves something open.</p></div></div>
    <Steps at={1} />
    <ErrorNotice text={error} />
    {record && <FormulatorStatus record={record} onStop={() => void api(`${imports}/${importId}/stop`, {}).then(load)} />}
    {record && record.status !== 'running' && !record.charter_id && <Panel title="No charter yet">
      <p className="help-text">The formulator stopped before writing a charter. <a href={`#problem-import/${importId}`}>Open the import</a> to ask it to continue.</p></Panel>}
    {record?.activity?.length > 0 && <Panel title="What it has done"><ol className="import-activity">{[...record!.activity].reverse().slice(0, 40).map((row: Json, i: number) =>
      <li key={i} className={row.kind}><time>{new Date(row.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span>{row.text}</span></li>)}</ol></Panel>}
  </>;
}

// The charter ---------------------------------------------------------------------------------------------------
type View = Json;
const show = (value: unknown, units = '') => {
  if (value === null || value === undefined) return '—';
  const text = typeof value === 'boolean' ? (value ? 'yes' : 'no') : typeof value === 'number' ? (Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(6)))) : String(value);
  const unit = units.trim();
  if (['deg', 'degree', 'degrees', '°'].includes(unit.toLowerCase())) return `${text}°`;
  return !unit || unit === '1' || unit === 'dimensionless' ? text : `${text} ${unit}`;
};

function Origin({ name, quantity, citations, onAccept }: { name: string; quantity: Json; citations: Json[]; onAccept?: (name: string) => void }) {
  if (quantity.role === 'derived') return <Badge>computed</Badge>;
  if (quantity.origin === 'researcher') return <Badge tone="green">you</Badge>;
  if (quantity.origin === 'assumed') return quantity.accepted ? <Badge>assumed · accepted</Badge>
    : <span className="origin-assumed"><Badge tone="amber">assumed</Badge>{onAccept && <button type="button" className="text-button" onClick={() => onAccept(name)}>Accept</button>}</span>;
  const citation = citations.find(c => c.id === quantity.citation);
  return <span title={citation ? `${citation.source}${citation.location ? ` · ${citation.location}` : ''}${citation.quote ? ` — “${citation.quote}”` : ''}` : undefined}>
    <Badge>source{citation ? ` ${citation.id}` : ''}</Badge></span>;
}

function CharterWork({ charterId, state, go, onCreated, onRevised }: { charterId: string; state: State; go: (path: string) => void; onCreated: (campaign: Json) => void; onRevised: () => void }) {
  const [view, setView] = useState<View | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [edits, setEdits] = useState<Record<string, string | boolean>>({}), [preview, setPreview] = useState<Json | null>(null);
  const [request, setRequest] = useState(''), [busy, setBusy] = useState(''), [settings, setSettings] = useState(false);
  const requestBox = useRef<HTMLTextAreaElement>(null);
  const load = useCallback(async () => { try { setView(await api(`${charters}/${charterId}`)); setError(''); } catch (e) { setError(errorText(e)); } }, [charterId]);
  useEffect(() => { void load(); }, [load]);
  const formulator = useImport(view?.import_id);
  const wasRunning = useRef(false);
  useEffect(() => {   // When the formulator finishes a turn, its draft, questions or proposal are on the charter.
    if (wasRunning.current && !formulator.running) void load();
    wasRunning.current = formulator.running;
  }, [formulator.running, load]);
  useEffect(() => { if (!formulator.running) return; const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [formulator.running, load]);

  const charter = view?.charter;
  const changes = useMemo(() => Object.entries(edits).flatMap(([name, raw]) => {
    const quantity = charter?.quantities?.[name];
    if (!quantity) return [];
    let value: unknown = raw;
    if (quantity.kind === 'number' || quantity.kind === 'integer') { if (raw === '' || !Number.isFinite(Number(raw))) return []; value = Number(raw); }
    if (quantity.kind === 'data') { try { value = JSON.parse(String(raw)); } catch { return []; } }
    return [{ op: 'set', path: `quantities.${name}.value`, value }];
  }), [edits, charter]);
  useEffect(() => {
    if (!changes.length) { setPreview(null); return; }
    const timer = window.setTimeout(() => { api(`${charters}/${charterId}/preview`, { changes }).then(setPreview).catch(e => setError(errorText(e))); }, 250);
    return () => window.clearTimeout(timer);
  }, [changes, charterId]);

  async function act(label: string, path: string, body: Json, done?: string) {
    setBusy(label); setError(''); setNotice('');
    try { const result = await api(path, body); if (result?.charter && result?.id === charterId) setView(result); else await load(); if (done) setNotice(done); return true; }
    catch (e) { setError(errorText(e)); return false; } finally { setBusy(''); }
  }
  if (!view || !charter) return error ? <ErrorNotice text={error} /> : <p className="help-text">Opening the charter…</p>;
  const shown = preview || view, values = shown.values || {}, rendered = shown.rendered || {};
  const quantities: [string, Json][] = Object.entries(charter.quantities || {});
  const inputs = quantities.filter(([, q]) => q.role === 'input'), derived = quantities.filter(([, q]) => q.role === 'derived');
  const findings: Json[] = shown.findings || [], open = findings.filter(f => f.severity === 'blocking' && !f.waived);
  const questions: Json[] = (charter.questions || []).filter((q: Json) => q.answer === null || q.answer === undefined);
  const proposals: Json[] = view.proposals || [];
  const unaccepted = inputs.filter(([, q]) => q.origin === 'assumed' && !q.accepted).map(([name]) => name);
  const revision = view.revision, citations: Json[] = charter.citations || [];
  const accept = (names: string[]) => void act('accept', `${charters}/${charterId}/accept-assumptions`, { expected_revision: revision, names });
  function change(name: string, quantity: Json) {
    setRequest(`Set ${quantity.description.toLowerCase()} (${name}) to `);
    window.setTimeout(() => { requestBox.current?.focus(); requestBox.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 0);
  }
  const source = view.source || {};
  return <>
    <div className="page-heading"><div><span className="eyebrow">Problem charter · revision {revision} · {view.status === 'confirmed' ? 'confirmed' : 'draft'}</span>
      <h1>{charter.title}</h1>
      <p className="help-text">{source.kind === 'example' ? `Started from the example “${source.name}”.` : source.kind === 'evaluator' ? `Started from the installed evaluator “${source.name}”.` : source.kind === 'import' ? 'Formulated from your material.'
        : source.kind === 'campaign' ? `Made from the campaign “${source.name}”.` : source.kind === 'fork' ? '' : ''}
        {view.lineage && <> Forked from <a href={`#new/${view.lineage.charter_id}`}>{view.lineage.title}</a> (revision {view.lineage.revision}){view.lineage.changes.length ? ': ' : ', unchanged so far.'}
          {view.lineage.changes.map((row: Json) => `${row.name} ${row.before} → ${row.after}`).join('; ')}</>}</p></div>
      <div className="inline-actions">{view.confirmed_revision && <button type="button" className="button secondary" disabled={!!busy}
        onClick={() => void api(`${charters}/${charterId}/fork`, {}).then(result => go(result.id)).catch(e => setError(errorText(e)))}>Fork along a new axis</button>}</div></div>
    <Steps at={settings ? 3 : 2} />
    {formulator.record && <FormulatorStatus record={formulator.record} onStop={() => void api(`${imports}/${view.import_id}/stop`, {}).then(formulator.load)} />}
    <ErrorNotice text={error || formulator.error} />{notice && <p className="help-text" role="status">{notice}</p>}

    {(rendered.summary || rendered.text) && <section className="charter-text" aria-label="The problem">
      {rendered.summary && <p className="charter-summary">{rendered.summary}</p>}<ReadableText text={rendered.text} /></section>}

    {questions.length > 0 && <Panel title={`The formulator asks (${questions.length})`} className="charter-questions">
      {questions.map(question => <QuestionCard key={question.id} question={question} disabled={!!busy}
        onAnswer={answer => act(`answer-${question.id}`, `${charters}/${charterId}/answers`, { expected_revision: revision, question_id: question.id, answer })} />)}</Panel>}

    <Findings findings={findings} busy={!!busy} onAccept={names => accept(names)}
      onWaive={(key, reason) => act(`waive-${key}`, `${charters}/${charterId}/waive`, { expected_revision: revision, key, reason }, 'Waived, with your reason recorded.')} />

    <div className="charter-columns">
      <Panel title="What you set" className="charter-inputs" action={unaccepted.length > 1 ? <button type="button" className="button small secondary" onClick={() => accept(unaccepted)}>Accept all {unaccepted.length} assumptions</button> : undefined}>
        {inputs.length ? <div className="quantity-list">{inputs.map(([name, q]) => <div key={name} className={`quantity-row ${name in edits ? 'edited' : ''}`}>
          <label htmlFor={`q-${name}`}><span>{q.description}</span><code>{name}</code></label>
          <div className="quantity-value">{q.kind === 'boolean'
            ? <input id={`q-${name}`} type="checkbox" checked={Boolean(name in edits ? edits[name] : q.value)} onChange={e => setEdits({ ...edits, [name]: e.target.checked })} />
            : <input id={`q-${name}`} type={q.kind === 'text' || q.kind === 'data' ? 'text' : 'number'} step={q.kind === 'integer' ? 1 : 'any'}
              className={q.kind === 'data' ? 'code-input' : undefined}
              value={String(name in edits ? edits[name] : q.kind === 'data' ? JSON.stringify(q.value ?? null) : q.value ?? '')}
              onChange={e => setEdits({ ...edits, [name]: e.target.value })} />}
            <span className="quantity-units">{q.units && q.units !== '1' ? q.units : ''}</span></div>
          <Origin name={name} quantity={q} citations={citations} onAccept={n => accept([n])} />
          {q.note && <p className="quantity-note">{q.note}</p>}</div>)}</div> : <p className="help-text">No inputs yet.</p>}
        {changes.length > 0 && <div className="charter-unsaved" role="region" aria-label="Unsaved changes">
          <span>{changes.length} unsaved {changes.length === 1 ? 'change' : 'changes'}; everything below shows the result.</span>
          <button type="button" className="button small primary" disabled={!!busy} onClick={() => void act('save', `${charters}/${charterId}/edit`, { expected_revision: revision, changes }).then(ok => { if (ok) { setEdits({}); setPreview(null); } })}>Save</button>
          <button type="button" className="button small secondary" onClick={() => { setEdits({}); setPreview(null); }}>Discard</button></div>}
      </Panel>
      <Panel title="What follows" className="charter-derived">
        {derived.length ? <ul className="derived-list">{derived.map(([name, q]) => <li key={name}>
          <details><summary><span>{q.description}</span><strong>{shown.errors?.[name] ? <span className="derived-error">{shown.errors[name]}</span> : show(values[name], q.units)}</strong></summary>
            <p><code>{name} = {q.expression}</code></p>{q.note && <p>{q.note}</p>}
            {q.citation && <p className="help-text">Source {q.citation}: {citations.find(c => c.id === q.citation)?.source}</p>}</details>
          <button type="button" className="text-button" onClick={() => change(name, q)}>Change…</button></li>)}</ul>
          : <p className="help-text">Nothing here follows from other values.</p>}
        <p className="help-text">These are computed from what you set. To set one directly, ask for the change below.</p>
      </Panel>
    </div>

    <Panel title="Ask for a change" className="charter-ask">
      <form onSubmit={e => { e.preventDefault(); void act('request', `${charters}/${charterId}/requests`, { text: request }, 'Sent to the formulator.').then(ok => { if (ok) { setRequest(''); void formulator.load(); } }); }}>
        <Field label="Your request" hint="In words, as partial as you like: “set the period to 1100 nm”, “add a minimum feature of 80 nm”, “score the worse polarization”. The formulator answers with options; every number in them is computed here.">
          <textarea ref={requestBox} value={request} onChange={e => setRequest(e.target.value)} rows={3} /></Field>
        <button className="button small primary" disabled={!!busy || !request.trim() || formulator.running}>{formulator.running ? 'The formulator is working…' : 'Ask the formulator'}</button>
      </form>
      {proposals.filter(p => p.status === 'open' || p.status === 'stale').slice(0, 2).map(proposal => <ProposalCard key={proposal.id} proposal={proposal} busy={!!busy}
        onDecide={option => act(`decide-${proposal.id}`, `/api/v1/problem-charter-proposals/${proposal.id}/decision`, { option }, option === null ? 'Rejected; nothing changed.' : 'Applied.')} />)}
      {proposals.some(p => !['open', 'stale'].includes(p.status)) && <details className="charter-past"><summary>Earlier proposals</summary><ul>
        {proposals.filter(p => !['open', 'stale'].includes(p.status)).map(p => <li key={p.id}>{p.request} — {p.status}{p.status === 'accepted' ? `: ${p.options[p.accepted_option]?.label}` : ''}</li>)}</ul></details>}
    </Panel>

    <CharterDetails view={view} shown={shown} onSaveJson={async text => {
      let parsed: Json;
      try { parsed = JSON.parse(text); } catch (e) { setError(`The JSON cannot be read: ${errorText(e)}`); return false; }
      return act('json', `${charters}/${charterId}/edit`, { expected_revision: revision, charter: parsed, rationale: 'Edited as JSON' }, 'Saved.');
    }} />

    <div className="charter-confirm" role="region" aria-label="Confirm">
      {open.length ? <p>{open.length} blocking {open.length === 1 ? 'finding' : 'findings'} to resolve or waive before confirming.</p>
        : changes.length ? <p>Save or discard your changes first.</p>
        : formulator.running ? <p>Wait for the formulator to finish.</p>
        : <p>Nothing blocks confirming revision {revision}.</p>}
      <button type="button" className="button primary" disabled={open.length > 0 || changes.length > 0 || formulator.running || settings} onClick={() => setSettings(true)}>
        Continue to campaign settings<Icon name="arrow" size={16} /></button></div>
    {settings && <CampaignSettings view={view} state={state} onCancel={() => setSettings(false)} onCreated={onCreated} onRevised={onRevised} />}
  </>;
}

function QuestionCard({ question, disabled, onAnswer }: { question: Json; disabled: boolean; onAnswer: (answer: string) => Promise<boolean> }) {
  const [own, setOwn] = useState('');
  return <div className="question-card" role="group" aria-label={question.question}>
    <p className="question-text">{question.question}{!question.blocking && <Badge>minor</Badge>}</p>
    {question.about?.length > 0 && <p className="help-text">About {question.about.join(', ')}</p>}
    <div className="question-options">{(question.options || []).map((option: string, index: number) =>
      <button key={index} type="button" className={`button small ${index === 0 ? 'primary' : 'secondary'}`} disabled={disabled} onClick={() => void onAnswer(option)}>{option}</button>)}</div>
    <form className="question-own" onSubmit={e => { e.preventDefault(); void onAnswer(own).then(ok => { if (ok) setOwn(''); }); }}>
      <input aria-label="Answer in your own words" placeholder="Or answer in your own words" value={own} onChange={e => setOwn(e.target.value)} />
      <button className="button small secondary" disabled={disabled || !own.trim()}>Answer</button></form>
  </div>;
}

function Findings({ findings, busy, onAccept, onWaive }: { findings: Json[]; busy: boolean; onAccept: (names: string[]) => void; onWaive: (key: string, reason: string) => Promise<boolean> }) {
  const [waiving, setWaiving] = useState(''), [reason, setReason] = useState('');
  const blocking = findings.filter(f => f.severity === 'blocking' && !f.waived && f.code !== 'question.open');
  const warnings = findings.filter(f => f.severity === 'warning'), waived = findings.filter(f => f.waived);
  if (!blocking.length && !warnings.length && !waived.length) return <p className="charter-clean"><Icon name="check" size={15} /> The checks find nothing to resolve.</p>;
  return <section className="charter-findings" aria-label="Findings">
    {blocking.length > 0 && <ul className="findings blocking">{blocking.map(f => <li key={f.key}>
      <span>{f.message}</span>
      {f.code === 'assumption.unaccepted' && f.about?.length > 0 && <button type="button" className="button small secondary" disabled={busy} onClick={() => onAccept(f.about.slice(0, 1))}>Accept</button>}
      {f.code === 'assumption.unaccepted' && !f.about?.length && <button type="button" className="button small secondary" disabled={busy} onClick={() => onAccept([f.key.split(':')[1]])}>Accept</button>}
      {f.waivable && (waiving === f.key
        ? <form className="waive-form" onSubmit={e => { e.preventDefault(); void onWaive(f.key, reason).then(ok => { if (ok) { setWaiving(''); setReason(''); } }); }}>
            <input aria-label="Why it can stand" placeholder="Why it can stand" value={reason} onChange={e => setReason(e.target.value)} required />
            <button className="button small secondary" disabled={busy || !reason.trim()}>Waive</button></form>
        : <button type="button" className="text-button" onClick={() => setWaiving(f.key)}>Waive…</button>)}</li>)}</ul>}
    {(warnings.length > 0 || waived.length > 0) && <details className="findings-more"><summary>{warnings.length} {warnings.length === 1 ? 'warning' : 'warnings'}{waived.length ? ` · ${waived.length} waived` : ''}</summary>
      <ul className="findings">{warnings.map(f => <li key={f.key}><span>{f.message}</span></li>)}
        {waived.map(f => <li key={f.key}><span>{f.message} <em>Waived: {f.waived}</em></span></li>)}</ul></details>}
  </section>;
}

function ProposalCard({ proposal, busy, onDecide }: { proposal: Json; busy: boolean; onDecide: (option: number | null) => Promise<boolean> }) {
  const stale = proposal.status === 'stale';
  return <div className={`proposal-card ${stale ? 'stale' : ''}`} role="region" aria-label={`Proposal: ${proposal.request}`}>
    <p className="proposal-request"><strong>You asked:</strong> {proposal.request}</p>
    {stale && <p className="help-text">The charter changed after this was proposed; ask again.</p>}
    <div className="proposal-options">{proposal.options.map((option: Json, index: number) => <div key={index} className="proposal-option">
      <h4>{option.label}</h4><p>{option.reason}</p>
      <ul className="proposal-diff" aria-label="Changes">{option.diff.filter((row: Json) => row.part !== 'text' && row.part !== 'summary').map((row: Json, i: number) =>
        <li key={i}><span className="diff-name"><code>{row.name}</code>{row.part === 'relation' ? <Badge>relation</Badge> : row.role === 'derived' && row.part === 'value' ? <Badge>computed</Badge> : null}</span>
          {row.before !== undefined || row.after !== undefined
            ? <span className="diff-values"><span className="diff-before">{row.before ?? '—'}</span> <span aria-hidden="true">→</span><span className="sr-only">becomes</span> <strong>{row.after ?? '—'}</strong></span>
            : <span className="diff-values">{row.change}</span>}</li>)}
        {option.diff.some((row: Json) => row.part === 'text') && <li><span className="diff-name"><code>text</code></span><span className="diff-values">reworded</span></li>}</ul>
      {option.findings?.length > 0 && <ul className="findings blocking">{option.findings.map((f: Json) => <li key={f.key}><span>{f.message}</span></li>)}</ul>}
      {option.blocking_reason && <p className="help-text">Why it is offered anyway: {option.blocking_reason}</p>}
      {!stale && <button type="button" className="button small primary" disabled={busy} onClick={() => void onDecide(index)}>Accept this option</button>}</div>)}</div>
    {!stale && <button type="button" className="text-button" disabled={busy} onClick={() => void onDecide(null)}>Reject {proposal.options.length > 1 ? 'all' : 'it'}</button>}
  </div>;
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return <details className="charter-section"><summary>{title}{count !== undefined && <span className="count">{count}</span>}</summary><div>{children}</div></details>;
}

function CharterDetails({ view, shown, onSaveJson }: { view: View; shown: Json; onSaveJson: (text: string) => Promise<boolean> }) {
  const charter = view.charter, values = shown.values || {};
  const [json, setJson] = useState<string | null>(null);
  const citations: Json[] = charter.citations || [];
  const bound = (value: unknown) => typeof value === 'string' ? `${value} (${values[value] ?? '?'})` : value ?? '—';
  return <div className="charter-details">
    <Section title="Decision variables" count={charter.variables.length}><ul className="detail-list">{charter.variables.map((v: Json) => <li key={v.name}>
      <strong>{v.name}</strong> <Badge>{v.representation}</Badge> {v.description}
      <p className="help-text">Shape {v.shape.length ? v.shape.map((part: string | number) => typeof part === 'string' ? `${part} (${values[part] ?? '?'})` : part).join(' × ') : 'one value'}
        {v.representation === 'continuous' && ` · from ${bound(v.lower)} to ${bound(v.upper)}`}{v.representation === 'discrete' && ` · values ${v.values.join(', ')}`}
        {v.meaning && ` · ${v.meaning}`}{v.layout && ` · ${v.layout}`}</p></li>)}</ul></Section>
    <Section title="Constraints" count={charter.constraints.length}>{charter.constraints.length ? <ul className="detail-list">{charter.constraints.map((c: Json) => <li key={c.id}>
      <strong>{c.id}</strong> <Badge>{c.kind}</Badge> <Badge>{c.form}</Badge> {shown.rendered?.[`constraint ${c.id}`] || c.statement}
      {c.test && <p><code>{c.test}</code></p>}{c.form === 'linear' && <p><code>{c.terms.map((t: Json) => `${t.weights ? 'weighted' : t.weight} of ${t.variable}`).join(' + ')} {({ le: '≤', ge: '≥', eq: '=' } as Json)[c.relation]} {String(c.bound)}</code></p>}</li>)}</ul>
      : <p className="help-text">None.</p>}</Section>
    <Section title="Objective and recorded metrics">{charter.objective ? <><p><strong>{charter.objective.direction} {charter.objective.name}</strong> · {charter.objective.units}</p>
      <ReadableText text={shown.rendered?.objective || charter.objective.definition} /></> : <p className="help-text">No objective yet.</p>}
      {charter.metrics.length > 0 && <ul className="detail-list">{charter.metrics.map((m: Json) => <li key={m.name}><strong>{m.name}</strong> · {m.units}{m.definition && ` · ${m.definition}`}</li>)}</ul>}</Section>
    <Section title="Evaluator and fidelity">{charter.evaluator ? <>
      <p><strong>{charter.evaluator.problem_id}</strong> <Badge>{charter.evaluator.kind === 'installed' ? 'installed' : 'declared · to be built'}</Badge>{!charter.evaluator.deterministic && <Badge>noisy</Badge>}</p>
      {charter.evaluator.notes && <ReadableText text={charter.evaluator.notes} preview={4} />}
      <table className="data-table"><thead><tr><th>Evaluator field</th><th>Takes</th><th>Value</th></tr></thead><tbody>
        {[...Object.entries(charter.evaluator.configuration), ...Object.entries(charter.evaluator.fidelity).map(([f, q]) => [`${f} (fidelity)`, q])].map(([field, name]) =>
          <tr key={field as string}><td><code>{field as string}</code></td><td><code>{name as string}</code></td><td>{show(values[name as string], charter.quantities[name as string]?.units || '')}</td></tr>)}</tbody></table></>
      : <p className="help-text">No evaluator yet.</p>}</Section>
    <Section title="Instances" count={charter.instances.length}><ul className="detail-list">{charter.instances.map((i: Json) => <li key={i.name}><strong>{i.name}</strong> <Badge>{i.split}</Badge>
      {Object.keys(i.values).length > 0 && <span> · {Object.entries(i.values).map(([k, v]) => `${k} = ${v}`).join(', ')}</span>}{i.note && <p className="help-text">{i.note}</p>}</li>)}</ul></Section>
    <Section title="Reference results" count={charter.references.length}>{charter.references.length ? <ul className="detail-list">{charter.references.map((r: Json, index: number) => <li key={index}>
      {r.statement}{r.value !== null && r.value !== undefined && <strong> {show(r.value, r.units)}</strong>}
      {shown.references?.[index]?.applies === false && <Badge tone="amber">does not apply to these values</Badge>}
      {Object.keys(r.holds_at || {}).length > 0 && <p className="help-text">Reported at {Object.entries(r.holds_at).map(([k, v]) => `${k} = ${v}`).join(', ')}</p>}</li>)}</ul>
      : <p className="help-text">None.</p>}</Section>
    <Section title="Sources" count={citations.length}>{citations.length ? <ol className="detail-list">{citations.map(c => <li key={c.id}>[{c.id}] {c.source}{c.location && ` · ${c.location}`}{c.quote && <q> {c.quote}</q>}</li>)}</ol>
      : <p className="help-text">None cited.</p>}{charter.assumptions.length > 0 && <><h4>Other assumptions</h4><ul>{charter.assumptions.map((a: Json, i: number) => <li key={i}>{a.statement}{a.accepted ? ' (accepted)' : ''}</li>)}</ul></>}</Section>
    <Section title="History" count={view.history.length}><ol className="detail-list history">{[...view.history].reverse().map((h: Json) => <li key={h.revision}>
      <strong>Revision {h.revision}</strong> · {h.by} · {new Date(h.at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} · {h.rationale}</li>)}</ol></Section>
    <Section title="JSON">{json === null ? <><pre className="charter-json">{JSON.stringify(charter, null, 2)}</pre>
      <button type="button" className="button small secondary" onClick={() => setJson(JSON.stringify(charter, null, 2))}>Edit as JSON</button></>
      : <><textarea className="code-input" aria-label="Charter JSON" rows={18} value={json} spellCheck={false} onChange={e => setJson(e.target.value)} />
        <div className="inline-actions"><button type="button" className="button small primary" onClick={() => void onSaveJson(json).then(ok => { if (ok) setJson(null); })}>Save the JSON</button>
          <button type="button" className="button small secondary" onClick={() => setJson(null)}>Cancel</button></div></>}</Section>
  </div>;
}

// Confirm: campaign settings ----------------------------------------------------------------------------
function CampaignSettings({ view, state, onCancel, onCreated, onRevised }: { view: View; state: State; onCancel: () => void; onCreated: (campaign: Json) => void; onRevised: () => void }) {
  const defaults: Json = view.source?.campaign || {};
  const current = state.campaign && (view.campaign_ids || []).includes(state.campaign.id) ? state.campaign : null;
  const create = useCommand(null), revise = useCommand(current);
  const [name, setName] = useState(defaults.name || view.charter.title);
  const [question, setQuestion] = useState(current?.research_question ?? defaults.research_question ?? '');
  const [compute, setCompute] = useState(String(defaults.compute_budget_seconds ?? 3600));
  const [implementation, setImplementation] = useState(String(defaults.implementation_compute_budget_seconds ?? 0));
  const [llm, setLlm] = useState(String(defaults.llm_budget_usd ?? 5));
  const [reserve, setReserve] = useState(String(defaults.validation_reserve_seconds ?? 120));
  const [delegated, setDelegated] = useState(String(defaults.delegated_trial_seconds ?? 60));
  const [autonomy, setAutonomy] = useState(defaults.autonomy || 'guided');
  const [rationale, setRationale] = useState(''), [mode, setMode] = useState<'create' | 'revise'>(current ? 'revise' : 'create');
  const [checks, setChecks] = useState<Json[]>([]), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => { api(`${charters}/${view.id}/text-check`, { text: question }).then(r => setChecks(r.findings || [])).catch(() => setChecks([])); }, 400);
    return () => window.clearTimeout(timer);
  }, [question, view.id]);
  const panel = useRef<HTMLFormElement>(null);
  useEffect(() => { panel.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const confirmed = await api(`${charters}/${view.id}/confirm`, { expected_revision: view.revision });
      if (mode === 'revise' && current) {
        await revise('campaign.update', { charter: confirmed.charter, research_question: question, rationale: rationale || `Problem charter revision ${view.revision}` });
        onRevised();
      } else {
        const outcome = await create('campaign.create', { name, research_question: question, charter: confirmed.charter, compute_budget_seconds: Number(compute),
          implementation_compute_budget_seconds: Number(implementation), llm_budget_usd: Number(llm), validation_reserve_seconds: Math.min(Number(reserve), Number(compute)),
          delegated_trial_seconds: Number(delegated), autonomy });
        onCreated(outcome.campaign);
      }
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <form ref={panel} className="panel campaign-settings" onSubmit={submit} aria-label="Campaign settings">
    <div className="panel-heading"><div><span className="eyebrow">Confirm</span><h2>{mode === 'revise' ? `Revise “${current?.name}”` : 'The campaign'}</h2></div></div>
    {current && <div className="settings-mode" role="radiogroup" aria-label="What confirming does">
      <label><input type="radio" checked={mode === 'revise'} onChange={() => setMode('revise')} /> Revise “{current.name}” with this problem</label>
      <label><input type="radio" checked={mode === 'create'} onChange={() => setMode('create')} /> Create a new campaign</label></div>}
    <div className="form-grid">
      {mode === 'create' && <Field label="Campaign name" wide><input value={name} onChange={e => setName(e.target.value)} required maxLength={180} /></Field>}
      <Field label="Research question" hint="What this campaign asks about the problem: methods to compare, what to establish. The problem itself, with its values, is the charter and is added after it." wide>
        <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={4} /></Field>
      {checks.length > 0 && <ul className="findings wide">{checks.map(f => <li key={f.key}><span>{f.message}</span></li>)}</ul>}
      {mode === 'revise' ? <Field label="Why the problem changes" wide><input value={rationale} onChange={e => setRationale(e.target.value)} maxLength={1000} /></Field> : <>
        <DurationField label="Compute cap" unit="h" hint="Total numerical execution budget across the campaign." seconds={compute} onChange={setCompute} />
        <DurationField label="Implementation compute cap" unit="h" hint="Separate allocation for building and validating reusable implementations." seconds={implementation} onChange={setImplementation} min={0} />
        <Field label="API spending cap (USD)" hint="Applies only to paid API calls."><input type="number" value={llm} onChange={e => setLlm(e.target.value)} min="0" step="0.01" required /></Field>
        <DurationField label="Validation reserve" hint="Held back from ordinary optimization trials." seconds={reserve} onChange={setReserve} min={0} max={Number(compute) || undefined} />
        <DurationField label="Agent per-experiment limit" hint="The most time one experiment the agents start may use." seconds={delegated} onChange={setDelegated} max={86400} />
        <Field label="Research autonomy"><select value={autonomy} onChange={e => setAutonomy(e.target.value)}><option value="manual">Manual · researcher chooses each experiment</option>
          <option value="guided">Guided · propose actions and request decisions</option><option value="delegated">Delegated · allow bounded, eligible probes</option></select></Field></>}
    </div>
    <ErrorNotice text={error} />
    <div className="modal-actions"><button type="button" className="button secondary" onClick={onCancel}>Back to the charter</button>
      <button className="button primary" disabled={busy}>{busy ? 'Confirming…' : mode === 'revise' ? `Confirm revision ${view.revision} and revise the campaign` : `Confirm revision ${view.revision} and create the campaign`}<Icon name="arrow" size={16} /></button></div>
  </form>;
}

/** The confirmed charter of a campaign, as the Problem page shows it. */
export function CharterSummary({ charterId, onRevise }: { charterId: string; onRevise: () => void }) {
  const [view, setView] = useState<Json | null>(null), [error, setError] = useState('');
  useEffect(() => { api(`${charters}/${charterId}`).then(setView).catch(e => setError(errorText(e))); }, [charterId]);
  if (!view) return error ? <ErrorNotice text={error} /> : <p className="help-text">Reading the problem charter…</p>;
  const charter = view.charter, values = view.values || {};
  const entries: [string, Json][] = Object.entries(charter.quantities);
  return <Panel title="Problem charter" eyebrow={`Revision ${view.revision}${view.status === 'confirmed' ? ' · confirmed' : ' · draft in progress'}`}
    action={<button type="button" className="button small secondary" onClick={onRevise}>Open the charter</button>}>
    <section className="charter-text compact">{view.rendered?.summary && <p className="charter-summary">{view.rendered.summary}</p>}<ReadableText text={view.rendered?.text} preview={6} /></section>
    <table className="data-table charter-values"><thead><tr><th>Quantity</th><th>Value</th><th>From</th></tr></thead><tbody>
      {entries.map(([name, q]) => <tr key={name}><td>{q.description} <code>{name}</code></td><td>{show(values[name], q.units)}</td>
        <td><Origin name={name} quantity={q} citations={charter.citations || []} /></td></tr>)}</tbody></table>
  </Panel>;
}
