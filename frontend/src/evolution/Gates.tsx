/** The evidence gates on a frontier row (roadmap V5): each gate's state with its evidence; a closed one says why, what would
 * open it, and lets the researcher run the check or waive it with a rationale (decision 16). */
import { useState } from 'react';
import type { Gate, LedgerRow } from '../api/evolution';
import { Pill } from '../primitives/ui';
import { formatHash } from '../router/routes';

const GATE_TONE: Record<Gate['state'], string> = { open: 'clear', waived: 'you', closed: 'attention' };
const GATE_NAME: Record<Gate['gate'], string> = { assessment: 'tried', fidelity: 'fidelity' };

/** The row's gates in a line each: "tried 1 of 3 configurations, 1 seed each", "fidelity not checked: …". */
export function GateCell({ row, open, onToggle }: { row: LedgerRow; open: boolean; onToggle: () => void }) {
  const gates = row.gates || [];
  if (!gates.length) return null;
  const closed = gates.some(g => g.state === 'closed');
  return <div className="col" style={{ gap: 2, maxWidth: 200, marginTop: 4, overflowWrap: 'anywhere' }}>
    {gates.map(g => <span key={g.gate} className="small" data-testid={`gate-${g.gate}`} data-state={g.state}>
      <Pill tone={GATE_TONE[g.state]} title={g.state === 'closed' ? g.why : `${g.transition}: ${g.state}`}>{GATE_NAME[g.gate]}</Pill> {g.words}</span>)}
    <button className="btn quiet small" style={{ alignSelf: 'flex-start' }} onClick={onToggle} data-testid="gate-toggle" aria-expanded={open}>{open ? 'hide' : closed ? 'why, and what unlocks it' : 'evidence'}</button>
  </div>;
}

/** Evidence ids as links: a run opens its page, any other record its trail of origin. */
function Evidence({ ids, thread, onTrace }: { ids: string[]; thread: string | null; onTrace: (id: string) => void }) {
  if (!ids.length) return <span className="faint">no record yet</span>;
  return <>{ids.map(id => id.startsWith('trial_')
    ? <a key={id} className="mono small" href={formatHash({ page: 'experiments', id }, thread)}>{id} </a>
    : <a key={id} className="mono small" href="#" onClick={e => { e.preventDefault(); onTrace(id); }}>{id} </a>)}</>;
}

export function GateDetails({ row, thread, pending, onTrace, onWaive, onCheck }: { row: LedgerRow; thread: string | null; pending: string | null; onTrace: (id: string) => void;
  onWaive: (gate: Gate, rationale: string) => void; onCheck: (check: NonNullable<NonNullable<Gate['unlock']>['check']>) => void }) {
  const [rationale, setRationale] = useState<Record<string, string>>({});
  const busy = !!pending;
  return <div className="col" data-testid="gate-details" data-record-id={row.id} style={{ overflowWrap: 'anywhere' }}>
    {row.stop ? <div className="small" data-testid="gate-stop"><strong>Stop:</strong> {row.stop.words}{row.stop_reason ? ` (${row.stop_reason})` : ''}. Evidence: <Evidence ids={row.stop.evidence_ids} thread={thread} onTrace={onTrace} /></div> : null}
    {(row.gates || []).map(g => <div key={g.gate} className="small" data-testid={`gate-detail-${g.gate}`} data-state={g.state}>
      <div><strong>{g.transition[0].toUpperCase() + g.transition.slice(1)}:</strong> <Pill tone={GATE_TONE[g.state]}>{g.state === 'waived' ? 'waived by you' : g.state}</Pill> {g.words}. Evidence: <Evidence ids={g.evidence_ids} thread={thread} onTrace={onTrace} /></div>
      {g.state === 'closed' ? <>
        <p className="why" data-testid="gate-why">{g.why}{g.gate === 'assessment' ? ' Your own stop goes through and records how it was tried.' : ''}</p>
        {g.unlock?.runs ? <div data-testid="gate-unlock-runs">To unlock: {g.unlock.runs}</div> : null}
        {g.unlock?.check ? <div className="row wrap">To unlock: run {g.unlock.check.recipe_id} on {g.unlock.check.trial_id}
          <button className="btn small" disabled={busy} onClick={() => onCheck(g.unlock!.check!)} data-testid="gate-run-check">Run the check</button></div> : null}
        {g.unlock?.waive ? <div className="row wrap" style={{ marginTop: 4 }}>
          <input className="grow" placeholder={g.gate === 'assessment' ? 'Why a stop as inferior may rest on fewer runs (recorded with the waiver)' : 'Why this score may count without the check (recorded with the waiver)'}
            value={rationale[g.gate] || ''} onChange={e => setRationale({ ...rationale, [g.gate]: e.target.value })} data-testid={`waive-reason-${g.gate}`} />
          <button className="btn primary small" disabled={busy || !(rationale[g.gate] || '').trim()} onClick={() => onWaive(g, rationale[g.gate].trim())} data-testid={`waive-${g.gate}`}>Waive</button></div> : null}
      </> : null}
    </div>)}
  </div>;
}
