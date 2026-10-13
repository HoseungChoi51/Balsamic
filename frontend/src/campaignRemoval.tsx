import { useEffect, useState } from 'react';
import { api, errorText } from './api';
import type { Json } from './api';
import { ErrorNotice, Icon, Modal } from './ui';
import './campaignRemoval.css';

type Keep = 'nothing' | 'summary' | 'records';
type Plan = {
  campaign: { id: string; name: string };
  holds: { experiments: number; hypotheses: number; findings: number; messages: number; agents: number; records: number; events: number };
  bytes: { files: number; experiment_files: number; database: number };
  blockers: string[];
  options: { keep: Keep; kept_bytes: number | null; left_out?: Record<string, number> }[];
  folder: string;
};

function size(bytes?: number | null): string {
  if (typeof bytes !== 'number') return '';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(bytes >= 1e8 ? 0 : 1)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} kB`;
  return `${bytes} bytes`;
}
function counted(count: number, one: string, many = `${one}s`): string { return `${count.toLocaleString()} ${count === 1 ? one : many}`; }

/** Asks what should stay on disk, then removes the campaign from the workspace. */
export function CampaignRemoval({ campaign, onClose, onRemoved }: { campaign: { id: string; name: string }; onClose: () => void; onRemoved: () => void }) {
  // onRemoved: the campaign is gone and the workspace should show another; onClose: the dialog is done.
  const [plan, setPlan] = useState<Plan | null>(null), [keep, setKeep] = useState<Keep | ''>(''), [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [removed, setRemoved] = useState<Json | null>(null);
  const path = `/api/v1/campaigns/${encodeURIComponent(campaign.id)}/removal`;
  useEffect(() => { let current = true; api<Plan>(path).then(value => { if (current) setPlan(value); }).catch(e => { if (current) setError(errorText(e)); }); return () => { current = false; }; }, [path]);
  async function remove() {
    if (!keep) return;
    setBusy(true); setError('');
    try { setRemoved(await api<Json>(path, { keep })); onRemoved(); }
    catch (e) { setError(errorText(e)); api<Plan>(path).then(setPlan).catch(() => undefined); }
    finally { setBusy(false); }
  }
  if (removed) {
    const left: string[] = removed.left || [];
    return <Modal title="Campaign removed" description={`“${removed.name}” is no longer in this workspace.`} onClose={onClose}>
      <div className="removal-result">
        <p>{removed.folder ? <>Kept, {size(removed.kept_bytes)}:</> : 'Nothing was kept.'}</p>
        {removed.folder && <code className="removal-path">{removed.folder}</code>}
        <p>Deleted: {size(removed.files_bytes)} of files and {counted(removed.rows?.records ?? 0, 'record')}.</p>
        {left.length > 0 && <div className="removal-blockers"><strong>Some files could not be deleted. They are tried again when the services next start.</strong><ul>{left.map(item => <li key={item}>{item}</li>)}</ul></div>}
      </div>
      <div className="modal-actions"><button type="button" className="button primary" onClick={onClose}>Close</button></div>
    </Modal>;
  }
  const blocked = (plan?.blockers.length ?? 0) > 0;
  const records = plan?.options.find(option => option.keep === 'records');
  const leftOut = records?.left_out || {};
  const choices: { keep: Keep; title: string; text: string }[] = [
    { keep: 'nothing', title: 'Nothing', text: 'Delete the whole log: every record, journal, design and saved agent session of this campaign.' },
    { keep: 'summary', title: 'A summary of the runs', text: 'Written now, before the logs are deleted: for every run its method, parameters, budget, best score and the evaluations at which the score improved, with the ideas, findings and costs of the campaign. Two small files.' },
    { keep: 'records', title: 'The summary and most records', text: `Also kept: the campaign's records without their long arrays, the best design of every run, every run's score journal${records?.kept_bytes ? ` (${size(records.kept_bytes)})` : ''}, the conversation and the campaign memory. Still deleted: the evaluated designs, checkpoints, per-evaluation accounting${leftOut.cost_event ? ` (${leftOut.cost_event.toLocaleString()} rows)` : ''} and what the agents' tools sent and received.` },
  ];
  return <Modal title={`Remove “${campaign.name}”`} description="The campaign leaves this workspace for good. You choose what stays on this computer." onClose={busy ? () => undefined : onClose}>
    {!plan && !error && <p className="removal-facts">Measuring what the campaign holds…</p>}
    {plan && <>
      <p className="removal-facts">It holds {counted(plan.holds.experiments, 'experiment')}, {counted(plan.holds.hypotheses, 'hypothesis', 'hypotheses')}, {counted(plan.holds.findings, 'finding')} and {counted(plan.holds.messages, 'message')}: {size(plan.bytes.files)} of files and {size(plan.bytes.database)} in the database.</p>
      {blocked && <div className="removal-blockers" role="alert"><strong>It cannot be removed yet.</strong><ul>{plan.blockers.map(text => <li key={text}>{text}</li>)}</ul></div>}
      <fieldset className="removal-choices" disabled={blocked || busy}>
        <legend>What should stay on this computer?</legend>
        {choices.map(choice => <label key={choice.keep} className={keep === choice.keep ? 'chosen' : ''}>
          <input type="radio" name="keep" value={choice.keep} checked={keep === choice.keep} onChange={() => setKeep(choice.keep)} />
          <span><strong>{choice.title}</strong><span>{choice.text}</span></span>
        </label>)}
      </fieldset>
      {keep && keep !== 'nothing' && <p className="removal-where">Kept files go to <code className="removal-path">{plan.folder}</code></p>}
      {keep === 'nothing' && <p className="removal-where">Only one line stays, in the workspace's own records: the campaign's name, when it was removed and that nothing was kept.</p>}
      <label className="checkbox-label removal-confirm"><input type="checkbox" checked={understood} disabled={blocked || busy} onChange={e => setUnderstood(e.target.checked)} />I understand that this cannot be undone.</label>
    </>}
    <ErrorNotice text={error} />
    {busy && <p className="removal-where">{keep === 'nothing' ? 'Deleting' : 'Writing what stays, then deleting'}. A large campaign can take a few minutes; keep this window open.</p>}
    <div className="modal-actions">
      <button type="button" className="button secondary" onClick={onClose} disabled={busy}>Cancel</button>
      <button type="button" className="button danger-button" disabled={!plan || blocked || !keep || !understood || busy} onClick={() => void remove()}><Icon name="close" size={15} />{busy ? 'Removing…' : 'Remove campaign'}</button>
    </div>
  </Modal>;
}
