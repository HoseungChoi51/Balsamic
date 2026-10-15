import { useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { activeStatuses, best, errorText, objectiveValue, seconds } from './api';
import type { Json, State, Trial } from './api';
import type { WorkspaceActions } from './views';
import { useCommand } from './commands';
import { useSubpage } from './routes';
import { Badge, Empty, ErrorNotice, Field, Modal, PageTabs, Panel, Status } from './ui';
import { DurationField } from './duration';
import { DesignView, RunCurve, fallbackPresentation } from './runViews';
import type { Presentation } from './runViews';
import { DraftsPanel } from './experimentForm';
import { TextContent } from './textContent';
import './experimentsPage.css';

type Props = { state: State; actions: WorkspaceActions };
const AT_WORK = ['queued', 'running', 'pausing', 'paused', 'resuming', 'stopping'];
const SECTIONS: [string, string][] = [['design', 'Design'], ['curve', 'Learning curve'], ['objectives', 'Objectives'], ['numbers', 'Counts and time'],
  ['settings', 'Settings'], ['files', 'Files'], ['question', 'Question']];
const COLUMNS: [string, string][] = [['thumbnail', 'Design'], ['name', 'Name'], ['method', 'Method'], ['seed', 'Seed'], ['status', 'Status'], ['best', 'Best'],
  ['objectives', 'Other objectives'], ['evaluations', 'Requests / solves'], ['time', 'Worker time'], ['completion', 'Scientific completion']];

/** A run's name: the first line of its question, which the experiment rules say how to write. */
export function runName(trial: Trial): string {
  return (trial.question || '').trim().split('\n')[0] || `${trial.algorithm} · seed ${trial.seed}`;
}
function presentationOf(state: State): Presentation { return state.experiment_rules?.presentation || fallbackPresentation; }
function objectives(trial: Trial, presentation: Presentation): [string, number][] {
  const values: Json = { ...trial.result, ...trial.progress }.best_objectives || {};
  const primary = trial.problem?.primary_objective?.name;
  return Object.entries(values).filter(([name, value]) => typeof value === 'number' && name !== primary
    && (!presentation.objectives.length || presentation.objectives.includes(name))) as [string, number][];
}
const words = (name: string) => name.replaceAll('_', ' ');

export function ExperimentsPage({ state, actions }: Props) {
  const runs = state.trials as (Trial & { run_kind?: string; hidden?: Json })[];
  const counts = { short: 0, long: 0, check: 0 } as Record<string, number>;
  runs.forEach(run => { if (!run.hidden) counts[run.run_kind || 'short'] += 1; });
  const tabs: [string, string][] = [['short', `Short runs · ${counts.short}`], ['long', `Long runs · ${counts.long}`],
    ...(runs.some(run => run.run_kind === 'check') ? [['checks', `Checks · ${counts.check}`] as [string, string]] : []), ['rules', 'Rules']];
  const [tab, select] = useSubpage('experiments', ['short', 'long', 'checks', 'rules']);
  const linked = () => { const id = location.hash.startsWith('#experiments/') ? location.hash.slice('#experiments/'.length) : ''; return runs.some(run => run.id === id) ? id : null; };
  const [selected, setSelected] = useState<string | null>(linked);
  useEffect(() => { const change = () => setSelected(linked()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, [runs.length]);
  const open = runs.find(run => run.id === selected);
  // A linked run opens on the tab that lists it.
  const shown = open && tab !== 'rules' ? (open.run_kind === 'check' ? 'checks' : open.run_kind || 'short') : tab;
  const rules = state.experiment_rules;
  return <>
    <div className="page-heading"><div><span className="eyebrow">Experiments</span><h1>Follow the evidence.</h1>
      <p>Short runs screen strategies; long runs are for the ones that survived. {rules ? <>Short means allotted less than {seconds(rules.short_run_seconds)}.</> : null}</p></div>
      <button className="button primary" onClick={() => actions.launch()}>Design an experiment</button></div>
    <PageTabs label="Experiments" tabs={tabs} current={shown} onSelect={tab => { setSelected(null); select(tab); }} />
    {shown === 'rules' ? <ExperimentRules state={state} actions={actions} />
      : <RunList key={shown} state={state} actions={actions} kind={shown === 'checks' ? 'check' : shown} onOpen={setSelected} />}
    {shown !== 'rules' && <DraftsPanel state={state} actions={actions} />}
    {open && <RunEntry trial={open} state={state} actions={actions} onClose={() => { setSelected(null); history.replaceState(null, '', shown === 'short' ? '#experiments' : `#experiments/${shown}`); }} />}
  </>;
}

function RunList({ state, actions, kind, onOpen }: Props & { kind: string; onOpen: (id: string) => void }) {
  const command = useCommand(state.campaign);
  const presentation = presentationOf(state);
  const [study, setStudy] = useState(state.campaign?.active_study_id || 'all');
  const [hiddenShown, setHiddenShown] = useState(false), [picked, setPicked] = useState<string[]>([]);
  const [reason, setReason] = useState('Obsolete'), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const all = (state.trials as (Trial & { run_kind?: string; hidden?: Json })[]).filter(run => (run.run_kind || 'short') === kind && (study === 'all' || run.study_id === study));
  const hidden = all.filter(run => run.hidden);
  const rows = hiddenShown ? all : all.filter(run => !run.hidden);
  const columns = presentation.list_columns;
  const pickable = (run: Trial) => !AT_WORK.includes(run.status);
  async function hide(ids: string[], value: boolean) {
    setBusy(true); setError('');
    try { await command('trial.hide', { trial_ids: ids, hidden: value, reason }); setPicked([]); await actions.refresh(); }
    catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  const cell = (run: Trial & { hidden?: Json }, column: string) => {
    const measured = { ...run.result, ...run.progress };
    switch (column) {
      case 'name': return <td key={column}><button className="table-link" onClick={() => onOpen(run.id)}>{runName(run)}</button>
        <small>{run.id}{run.diagnostic_grant_id ? ' · diagnostic job' : ''}</small>{run.hidden && <small className="hidden-note">Hidden: {run.hidden.reason}</small>}</td>;
      case 'method': return <td key={column}>{state.algorithms.find(a => a.id === run.algorithm)?.name || run.algorithm}</td>;
      case 'seed': return <td key={column}>{run.seed}</td>;
      case 'status': return <td key={column}><Status status={run.status} /></td>;
      case 'best': return <td key={column} className="number">{objectiveValue(best(run), run.problem?.primary_objective)}</td>;
      case 'objectives': return <td key={column} className="objective-list">{objectives(run, presentation).map(([name, value]) =>
        <span key={name}>{words(name)} {objectiveValue(value, run.problem?.primary_objective)}</span>)}</td>;
      case 'evaluations': return <td key={column} className="number">{measured.evaluations || 0} / {measured.solver_calls || 0}{measured.unknown_solver_cost && ' + unknown'}</td>;
      case 'time': return <td key={column} className="number">{seconds(measured.elapsed_seconds)} <small>of {seconds(run.wall_seconds)}</small></td>;
      case 'completion': return <td key={column}>{measured.scientific_complete === true ? 'Complete' : 'Incomplete'}</td>;
      case 'thumbnail': return <td key={column} className="thumbnail"><button type="button" className="thumbnail-button" aria-label={`Open ${runName(run)}`} onClick={() => onOpen(run.id)}>
        <DesignView trial={run} presentation={presentation} width={96} /></button></td>;
      default: return <td key={column} />;
    }
  };
  return <>
    <div className="run-filters">
      {!!state.studies?.length && <Field label="Study"><select value={study} onChange={event => setStudy(event.target.value)}>
        <option value="all">All studies</option>{state.studies.map((item: Json) => <option key={item.id} value={item.id}>{item.id === state.campaign?.active_study_id ? 'Current · ' : ''}{item.scope} · {item.id}</option>)}
      </select></Field>}
      {hidden.length > 0 && <label className="check-label"><input type="checkbox" checked={hiddenShown} onChange={event => setHiddenShown(event.target.checked)} />Show {hidden.length} hidden</label>}
    </div>
    {picked.length > 0 && <div className="hide-bar" role="region" aria-label="Hide selected runs"><strong>{picked.length} selected</strong>
      <input aria-label="Why these runs are obsolete" value={reason} onChange={event => setReason(event.target.value)} maxLength={2000} />
      <button className="button small secondary" disabled={busy || !reason.trim()} onClick={() => void hide(picked, true)}>Hide from this page</button>
      <button className="text-button" onClick={() => setPicked([])}>Clear</button>
      <p className="help-text">Hidden runs keep their records; findings and reports may still cite them.</p></div>}
    <ErrorNotice text={error} />
    {!rows.length ? <section className="panel"><Empty title={kind === 'check' ? 'No checks' : `No ${kind} runs`}>
      {kind === 'long' ? 'Long runs are for the strategies that survived screening.' : kind === 'check' ? 'Validations, recipe checks and speed probes appear here.' : 'Screening runs appear here as they are started.'}</Empty></section>
      : <Panel title={kind === 'check' ? 'Checks' : kind === 'long' ? 'Long runs' : 'Short runs'}><div className="table-scroll"><table className="data-table run-table">
        <thead><tr><th className="pick"><span className="sr-only">Select</span></th>{columns.map(column => <th key={column}>{COLUMNS.find(([id]) => id === column)?.[1]}</th>)}</tr></thead>
        <tbody>{rows.map(run => <tr key={run.id} className={(run as Json).hidden ? 'hidden-run' : ''}>
          <td className="pick">{pickable(run) && !(run as Json).hidden ? <input type="checkbox" aria-label={`Select ${runName(run)}`} checked={picked.includes(run.id)}
            onChange={event => setPicked(event.target.checked ? [...picked, run.id] : picked.filter(id => id !== run.id))} />
            : (run as Json).hidden ? <button className="text-button" disabled={busy} onClick={() => void hide([run.id], false)}>Show</button> : null}</td>
          {columns.map(column => cell(run, column))}</tr>)}</tbody></table></div></Panel>}
  </>;
}

function RunEntry({ trial, state, actions, onClose }: Props & { trial: Trial & { hidden?: Json }; onClose: () => void }) {
  const command = useCommand(state.campaign);
  const [error, setError] = useState('');
  const presentation = presentationOf(state);
  const measured = { ...trial.result, ...trial.progress };
  const definition = trial.problem?.primary_objective;
  const atWork = AT_WORK.includes(trial.status);
  async function control(action: string) {
    try { await command('trial.control', { trial_id: trial.id, action, expected_control_revision: trial.control_revision ?? 0 }); await actions.refresh(); }
    catch (failure) { setError(errorText(failure)); }
  }
  async function hide(value: boolean) {
    try { await command('trial.hide', { trial_ids: [trial.id], hidden: value, reason: 'Obsolete' }); await actions.refresh(); }
    catch (failure) { setError(errorText(failure)); }
  }
  const sections: Record<string, ReactNode> = {
    design: presentation.design.render === 'none' ? null : <section key="design" className="run-section"><h3>Best design</h3><DesignView trial={trial} presentation={presentation} width={640} legend /></section>,
    curve: <section key="curve" className="run-section"><h3>Learning curve</h3><RunCurve trial={trial} x={presentation.curve_x} live={trial.status === 'running'} /></section>,
    objectives: <section key="objectives" className="run-section"><h3>Objectives</h3><dl className="run-facts">
      <div><dt>{words(definition?.name || 'objective')} (primary)</dt><dd>{objectiveValue(best(trial), definition)}</dd></div>
      {objectives(trial, presentation).map(([name, value]) => <div key={name}><dt>{words(name)}</dt><dd>{objectiveValue(value, definition)}</dd></div>)}</dl></section>,
    numbers: <section key="numbers" className="run-section"><h3>Counts and time</h3><dl className="run-facts">
      <div><dt>Evaluation requests</dt><dd>{measured.evaluations || 0} of {trial.max_steps}</dd></div>
      <div><dt>Confirmed solver executions</dt><dd>{measured.solver_calls || 0}</dd></div>
      <div><dt>Worker time</dt><dd>{seconds(measured.elapsed_seconds)} of {seconds(trial.wall_seconds)}</dd></div>
      <div><dt>Scientific procedure</dt><dd>{measured.scientific_complete ? 'complete' : 'incomplete'}</dd></div></dl>
      {measured.reason && <p className="help-text">{measured.reason}</p>}</section>,
    settings: <section key="settings" className="run-section"><h3>Settings</h3><dl className="run-facts">
      <div><dt>Method</dt><dd>{state.algorithms.find(a => a.id === trial.algorithm)?.name || trial.algorithm}</dd></div><div><dt>Seed</dt><dd>{trial.seed}</dd></div>
      {trial.hypothesis_id && <div><dt>Proposal</dt><dd><a href="#hypotheses">{state.hypotheses.find(h => h.id === trial.hypothesis_id)?.title || trial.hypothesis_id}</a></dd></div>}
      {trial.schedule_steps && <div><dt>Schedule horizon</dt><dd>{trial.schedule_steps}</dd></div>}</dl>
      {trial.algorithm_config && Object.keys(trial.algorithm_config).length > 0 && <pre className="run-config">{JSON.stringify(trial.algorithm_config, null, 2)}</pre>}</section>,
    files: <section key="files" className="run-section"><h3>Files</h3><p className="run-files">
      {['spec.json', 'result.json', 'metrics.jsonl'].map(name => <a key={name} href={`/api/trials/${trial.id}/artifacts/${name}`} target="_blank" rel="noreferrer">{name}</a>)}
      {!!(trial as Json).output_asset_ids?.length && <a href="#assets">{(trial as Json).output_asset_ids.length} saved assets</a>}</p></section>,
    question: <section key="question" className="run-section"><h3>Question</h3><TextContent text={trial.question || 'Not stated.'} /></section>,
  };
  return <Modal wide title={runName(trial)} description={`${trial.id} · ${trial.run_kind === 'long' ? 'long run' : trial.run_kind === 'check' ? 'check' : 'short run'}`} onClose={onClose}>
    <div className="row-between"><Status status={trial.status} />{trial.hidden && <Badge>Hidden: {trial.hidden.reason}</Badge>}</div>
    <div className="inline-actions run-actions">
      {['queued', 'running'].includes(trial.status) && <button className="button secondary" onClick={() => void control('pause')}>Pause</button>}
      {['paused', 'interrupted'].includes(trial.status) && <button className="button secondary" onClick={() => void control('resume')}>Resume</button>}
      {activeStatuses.includes(trial.status) && <button className="button secondary" onClick={() => void control('stop')}>Stop</button>}
      {trial.status === 'queued' && <button className="button primary" onClick={() => { onClose(); actions.editRun(trial, true); }}>Edit</button>}
      <button className="button secondary" onClick={() => { onClose(); actions.editRun(trial, false); }}>Run again with changes</button>
      {atWork && <button className="button secondary" onClick={() => { onClose(); actions.trialAction(trial, 'extend'); }}>Extend allocation</button>}
      {trial.problem?.definition_id === 'meent_grating' && <button className="button secondary" onClick={() => { onClose(); actions.trialAction(trial, 'validate'); }}>Check physical convergence</button>}
      {!atWork && <button className="text-button" onClick={() => void hide(!trial.hidden)}>{trial.hidden ? 'Show on the page again' : 'Hide from the page'}</button>}
    </div><ErrorNotice text={error} />
    {presentation.entry_sections.map(section => sections[section])}
    {(state.diagnostic_grants || []).some((grant: Json) => grant.parent_trial_id === trial.id) && <section className="run-section"><h3>Declared diagnostic milestones</h3>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>Milestone</th><th>Capture / dispatch</th><th>Evidence</th></tr></thead>
        <tbody>{state.diagnostic_grants.filter((grant: Json) => grant.parent_trial_id === trial.id).map((grant: Json) => <tr key={grant.id}>
          <td>{grant.count} {grant.unit.replaceAll('_', ' ')}</td><td>{grant.status.replaceAll('_', ' ')}</td><td>{grant.asset_ids?.length || 0} assets</td></tr>)}</tbody></table></div></section>}
  </Modal>;
}

/** The experiment operator's rules for this campaign, which the researcher can change. */
function ExperimentRules({ state, actions }: Props) {
  const command = useCommand(state.campaign);
  const rules: Json | undefined = state.experiment_rules;
  const [draft, setDraft] = useState<Json | null>(null), [why, setWhy] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const presentation: Presentation = (draft?.presentation || rules?.presentation || fallbackPresentation);
  const objectiveNames = useMemo(() => [...new Set(state.trials.flatMap(trial => Object.keys({ ...trial.result, ...trial.progress }.best_objectives || {})))], [state.trials.length]);
  if (!rules) return <section className="panel"><Empty title="No campaign">Create a campaign to set its experiment rules.</Empty></section>;
  const value = (key: string) => draft && key in draft ? draft[key] : rules[key];
  const set = (key: string, next: unknown) => setDraft({ ...(draft || {}), [key]: next });
  const setView = (next: Partial<Presentation>) => set('presentation', { ...presentation, ...next });
  const toggle = (list: string[], id: string, order: [string, string][]) => list.includes(id) ? list.filter(item => item !== id) : order.map(([key]) => key).filter(key => key === id || list.includes(key));
  async function save(event: FormEvent) {
    event.preventDefault(); if (!draft) return;
    setBusy(true); setError('');
    try {
      const reason = why.trim() || 'Changed by the researcher';
      await command('experiments.rules', { ...draft, ...(draft.max_concurrent === '' ? { max_concurrent: 0 } : {}),
        ...(draft.presentation ? { presentation: { ...draft.presentation, rationale: reason } } : {}), expected_revision: rules!.revision, rationale: reason });
      setDraft(null); setWhy(''); await actions.refresh();
    } catch (failure) { setError(errorText(failure)); } finally { setBusy(false); }
  }
  const changedBy = rules.updated_by === 'researcher' ? 'you' : rules.updated_by === 'manager' ? 'an agent' : rules.updated_by;
  return <form className="experiment-rules" onSubmit={save}>
    <p className="help-text">The experiment operator follows these rules when it designs, starts and orders runs, and the scheduler holds back runs above the limit.
      {rules.revision ? ` Revision ${rules.revision}, last changed by ${changedBy}${rules.rationale ? `: ${rules.rationale}` : '.'}` : ' These are the defaults; nothing has been changed yet.'}</p>
    <Panel title="Runs"><div className="form-grid">
      <Field label="How runs are named" wide hint="The first line of a run's question. Fields: {stage} (Screen, Tune or Long), {proposal}, {method}, {seed}.">
        <input value={value('naming')} onChange={event => set('naming', event.target.value)} maxLength={300} required /></Field>
      <DurationField label="Short runs are allotted less than" seconds={String(value('short_run_seconds'))} onChange={next => set('short_run_seconds', Number(next))} max={86400} />
      <Field label="Runs of this campaign at once" hint={`Empty: no limit of the campaign's own. The workspace runs at most ${state.settings?.max_workers ?? '—'} in all; changing that is yours, in the Decision inbox.`}>
        <input type="number" min="1" max="64" value={value('max_concurrent') ?? ''} onChange={event => set('max_concurrent', event.target.value === '' ? '' : Number(event.target.value))} /></Field>
      <Field label="How runs are chosen and ordered" wide><textarea rows={8} value={value('strategy')} onChange={event => set('strategy', event.target.value)} maxLength={8000} required /></Field>
    </div></Panel>
    <Panel title="What the page shows" action={<Badge tone={rules.presentation_chosen ? 'green' : ''}>{rules.presentation_chosen ? 'Chosen' : 'Default from the problem'}</Badge>}>
      {rules.presentation?.rationale && <p className="help-text">{rules.presentation_chosen ? 'Why: ' : ''}{rules.presentation.rationale}</p>}
      <div className="presentation-grid">
        <fieldset><legend>Columns of the list</legend>{COLUMNS.map(([id, name]) => <label key={id} className="check-label">
          <input type="checkbox" checked={presentation.list_columns.includes(id)} onChange={() => setView({ list_columns: toggle(presentation.list_columns, id, COLUMNS) })} />{name}</label>)}</fieldset>
        <fieldset><legend>Sections of a run's entry</legend>{SECTIONS.map(([id, name]) => <label key={id} className="check-label">
          <input type="checkbox" checked={presentation.entry_sections.includes(id)} onChange={() => setView({ entry_sections: toggle(presentation.entry_sections, id, SECTIONS) })} />{name}</label>)}</fieldset>
        <fieldset><legend>The design</legend>
          <Field label="Drawn as"><select value={presentation.design.render} onChange={event => setView({ design: { ...presentation.design, render: event.target.value as Presentation['design']['render'] } })}>
            <option value="mask">An image of rows × columns</option><option value="strip">A strip</option><option value="table">A table of values (few values only)</option><option value="none">Not shown</option></select></Field>
          {presentation.design.render === 'mask' && <div className="mask-size">
            <Field label="Rows"><input type="number" min="1" value={presentation.design.rows ?? ''} onChange={event => setView({ design: { ...presentation.design, rows: Number(event.target.value) } })} /></Field>
            <Field label="Columns"><input type="number" min="1" value={presentation.design.cols ?? ''} onChange={event => setView({ design: { ...presentation.design, cols: Number(event.target.value) } })} /></Field></div>}
          <Field label="Learning curve against"><select value={presentation.curve_x} onChange={event => setView({ curve_x: event.target.value as Presentation['curve_x'] })}>
            <option value="evaluations">Evaluations</option><option value="elapsed_seconds">Worker time</option></select></Field>
          {objectiveNames.length > 0 && <Field label="Other objectives shown" hint="None ticked: all."><div className="objective-picks">{objectiveNames.map(name => <label key={name} className="check-label">
            <input type="checkbox" checked={presentation.objectives.includes(name)} onChange={() => setView({ objectives: presentation.objectives.includes(name) ? presentation.objectives.filter(item => item !== name) : [...presentation.objectives, name] })} />{words(name)}</label>)}</div></Field>}
        </fieldset>
      </div>
    </Panel>
    {draft && <div className="rules-save"><Field label="Why the change" wide><input value={why} onChange={event => setWhy(event.target.value)} maxLength={2000} placeholder="Recorded with the revision" /></Field>
      <div className="inline-actions"><button className="button primary" disabled={busy}>{busy ? 'Saving…' : 'Save the rules'}</button><button type="button" className="text-button" onClick={() => setDraft(null)}>Discard</button></div></div>}
    <ErrorNotice text={error} />
  </form>;
}
