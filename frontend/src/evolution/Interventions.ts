/** Frontier interventions as one batched command: stop with a reason, promote, allocate, generate from the selection. */
import { send } from '../commands/bus';
import type { LedgerRow } from '../api/evolution';
import { track } from '../telemetry/events';

export type Intervention = { kind: 'stop'; reason: string } | { kind: 'promote' } | { kind: 'allocate'; seconds: number; rationale: string } | { kind: 'generate'; operation: 'hybrid' | 'revise' | 'diversify'; count: number; note: string };

export async function intervene(rows: LedgerRow[], action: Intervention, campaignId: string, version: number, threadId: string | null, override = false) {
  const items: { operation: string; payload: Record<string, unknown> }[] = [];
  const revision = (row: LedgerRow) => Number((row as unknown as { status_revision?: number }).status_revision ?? 0);
  if (action.kind === 'stop') for (const row of rows) items.push({ operation: 'hypothesis.status', payload: { hypothesis_id: row.id, status: 'archived', expected_status_revision: revision(row), stop_reason: action.reason } });
  if (action.kind === 'promote') for (const row of rows) items.push({ operation: 'hypothesis.nominate', payload: { hypothesis_id: row.id } });
  if (action.kind === 'allocate') for (const row of rows) items.push({ operation: 'hypothesis.allocate', payload: { hypothesis_id: row.id, worker_seconds: action.seconds, rationale: action.rationale } });
  if (action.kind === 'generate') items.push({ operation: 'research.generate', payload: { operation: action.operation, parent_ids: rows.map(r => r.id), count: action.count, note: action.note } });
  const rationale = action.kind === 'stop' ? action.reason : action.kind === 'allocate' ? action.rationale : action.kind === 'generate' ? action.note : 'promoted from the frontier';
  const receipt = await send({ operation: 'intervention.batch', campaignId, expectedRevision: version, payload: { items, rationale, all_or_nothing: true }, origin: { thread_id: threadId } });
  track('intervention.send', { kind: action.kind, count: rows.length, override });
  return receipt;
}
