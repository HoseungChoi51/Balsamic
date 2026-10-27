/** Fetch helpers: JSON in and out, the workspace identity on every write, and typed errors with the server's detail. */
export class ApiError extends Error {
  constructor(public status: number, public detail: string, public body: unknown = null) { super(detail); }
}

let workspaceId: string | null = null;
export function setWorkspaceId(id: string | null) { workspaceId = id; }
export function getWorkspaceId() { return workspaceId; }

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...(init.headers as Record<string, string> | undefined) };
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (workspaceId && init.method && init.method !== 'GET') headers['X-Workspace-Id'] = workspaceId;
  const response = await fetch(path, { ...init, headers, cache: 'no-store' });
  const text = await response.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    const detail = (body && typeof body === 'object' && 'detail' in body) ? String((body as { detail: unknown }).detail) : response.statusText || `HTTP ${response.status}`;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail), body);
  }
  return body as T;
}

/** A read that answers unchanged when nothing newer than the cursor exists; the previous value is kept. */
export async function scoped<T extends { event_cursor?: number }>(path: string, previous: T | undefined, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value));
  if (previous?.event_cursor) query.set('after', String(previous.event_cursor));
  const url = path + (query.toString() ? (path.includes('?') ? '&' : '?') + query.toString() : '');
  const body = await api<T & { unchanged?: boolean }>(url);
  if (body.unchanged && previous) return { ...previous, event_cursor: body.event_cursor };
  return body;
}
