/** The command bus from the browser: every write is a Command with a client-made id, journaled locally, sent once, retried idempotently. */
import { api, ApiError, getWorkspaceId } from '../api/client';
import type { CommandReceipt } from '../api/types';

export interface CommandInput { operation: string; campaignId: string; expectedRevision: number; payload: Record<string, unknown>;
  expectedGuidanceRevision?: number | null; expectedAuthorityHash?: string | null; expectedThreadRevision?: number | null;
  origin?: { thread_id?: string | null; message_id?: string | null; actor?: 'researcher'; rationale?: string | null } }
export interface JournalEntry { id: string; operation: string; campaign_id: string; status: 'sending' | 'completed' | 'rejected' | 'unknown'; sent_at: string; finished_at?: string; detail?: string }

const JOURNAL = 'balsamic.commands';
const LIMIT = 200;
const listeners = new Set<() => void>();

export function newId() { return 'ui_' + crypto.randomUUID().replace(/-/g, ''); }
export function journal(): JournalEntry[] { try { return JSON.parse(localStorage.getItem(JOURNAL) || '[]'); } catch { return []; } }
function write(entries: JournalEntry[]) { try { localStorage.setItem(JOURNAL, JSON.stringify(entries.slice(-LIMIT))); } catch { /* private mode */ } listeners.forEach(fn => fn()); }
function upsert(entry: JournalEntry) { const rows = journal().filter(row => row.id !== entry.id); rows.push(entry); write(rows); }
export function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
export function pending() { return journal().filter(row => row.status === 'sending' || row.status === 'unknown'); }

export async function send(input: CommandInput, id = newId()): Promise<CommandReceipt> {
  const body = { id, campaign_id: input.campaignId, operation: input.operation, expected_revision: input.expectedRevision, payload: input.payload,
    ...(input.expectedGuidanceRevision != null ? { expected_guidance_revision: input.expectedGuidanceRevision } : {}),
    ...(input.expectedAuthorityHash ? { expected_authority_hash: input.expectedAuthorityHash } : {}),
    ...(input.expectedThreadRevision != null ? { expected_thread_revision: input.expectedThreadRevision } : {}),
    ...(input.origin ? { origin: { actor: 'researcher', ...input.origin } } : {}) };
  upsert({ id, operation: input.operation, campaign_id: input.campaignId, status: 'sending', sent_at: new Date().toISOString() });
  try {
    const receipt = await api<CommandReceipt>('/api/v1/commands', { method: 'POST', body: JSON.stringify(body) });
    upsert({ id, operation: input.operation, campaign_id: input.campaignId, status: 'completed', sent_at: body ? new Date().toISOString() : '', finished_at: new Date().toISOString() });
    return receipt;
  } catch (error) {
    if (error instanceof ApiError) {
      upsert({ id, operation: input.operation, campaign_id: input.campaignId, status: 'rejected', sent_at: new Date().toISOString(), finished_at: new Date().toISOString(), detail: error.detail });
      throw error;
    }
    // The network failed: the receipt may or may not exist. The same id is safe to ask about or resend.
    upsert({ id, operation: input.operation, campaign_id: input.campaignId, status: 'unknown', sent_at: new Date().toISOString(), detail: String((error as Error).message || error) });
    throw error;
  }
}

/** Ask the server about a command whose reply was lost; resend it if it never arrived. */
export async function reconcile(entry: JournalEntry, resend?: CommandInput) {
  try {
    const receipt = await api<CommandReceipt>(`/api/v1/commands/${entry.id}`);
    upsert({ ...entry, status: 'completed', finished_at: new Date().toISOString() });
    return receipt;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404 && resend) return send(resend, entry.id);
    throw error;
  }
}

export function workspaceHeader() { return getWorkspaceId(); }
