/** Local UI telemetry: which controls are used, never what was written. Batched to POST /api/v1/ui-events. */
import { api, getWorkspaceId } from '../api/client';

export interface UiEvent { kind: string; at: string; campaign_id?: string | null; thread_id?: string | null; page?: string | null; session?: string; data?: Record<string, string | number | boolean | null> }
const queue: UiEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let context: { campaign_id: string | null; thread_id: string | null; page: string | null } = { campaign_id: null, thread_id: null, page: null };
const SESSION = (() => { try { const saved = sessionStorage.getItem('balsamic.session'); if (saved) return saved; const fresh = Math.random().toString(36).slice(2, 10); sessionStorage.setItem('balsamic.session', fresh); return fresh; } catch { return 'anon'; } })();

export function setTelemetryContext(next: Partial<typeof context>) { context = { ...context, ...next }; }
export function track(kind: string, data: UiEvent['data'] = {}) {
  queue.push({ kind, at: new Date().toISOString(), ...context, session: SESSION, data });
  if (queue.length >= 20) void flush(); else if (!timer) timer = setTimeout(() => void flush(), 5000);
}
export async function flush() {
  if (timer) { clearTimeout(timer); timer = null; }
  const workspace = getWorkspaceId();
  if (!workspace || !queue.length) return;
  const events = queue.splice(0, 64);
  try { await api('/api/v1/ui-events', { method: 'POST', body: JSON.stringify({ workspace_id: workspace, events }) }); }
  catch { /* telemetry never blocks work; a lost batch is lost */ }
}
if (typeof window !== 'undefined') window.addEventListener('pagehide', () => { void flush(); });
