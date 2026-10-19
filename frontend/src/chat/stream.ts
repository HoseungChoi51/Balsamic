/** AG-UI events from /api/v1/threads/{id}/stream folded into one live turn. */
export interface LiveStep { id: string; label: string; done: boolean; failed: boolean; link?: string | null }
export interface LiveTurn { runId: string | null; text: string; thinking: string; steps: LiveStep[]; status: 'idle' | 'running' | 'finished' | 'error'; error?: string }
export interface StreamState { live: LiveTurn; snapshot: Record<string, unknown> | null; messagesVersion: number }

export const initial: StreamState = { live: { runId: null, text: '', thinking: '', steps: [], status: 'idle' }, snapshot: null, messagesVersion: 0 };

export function reduce(state: StreamState, event: Record<string, unknown>): StreamState {
  const type = String(event.type);
  const live = state.live;
  switch (type) {
    case 'RUN_STARTED': return { ...state, live: { runId: String(event.runId), text: '', thinking: '', steps: [], status: 'running' } };
    case 'RUN_FINISHED': return { ...state, live: { ...live, status: 'finished' } };
    case 'RUN_ERROR': return { ...state, live: { ...live, status: 'error', error: String(event.message || 'The turn failed') } };
    case 'TEXT_MESSAGE_START': return { ...state, live: { ...live, text: '' } };
    case 'TEXT_MESSAGE_CONTENT': return { ...state, live: { ...live, text: live.text + String(event.delta || '') } };
    case 'THINKING_TEXT_MESSAGE_CONTENT': return { ...state, live: { ...live, thinking: (live.thinking + String(event.delta || '')).slice(-2000) } };
    case 'TOOL_CALL_START': return { ...state, live: { ...live, steps: [...live.steps, { id: String(event.toolCallId), label: String(event.toolCallName), done: false, failed: false }] } };
    case 'TOOL_CALL_END': return { ...state, live: { ...live, steps: live.steps.map(step => step.id === event.toolCallId ? { ...step, done: true, failed: Boolean(event.failed), link: (event.link as string) || step.link } : step) } };
    case 'STATE_SNAPSHOT': return { ...state, snapshot: event.snapshot as Record<string, unknown> };
    case 'STATE_DELTA': {
      const next = { ...(state.snapshot || {}) };
      for (const op of (event.delta as { op: string; path: string; value: unknown }[]) || []) if (op.op === 'replace') next[op.path.replace(/^\//, '')] = op.value;
      return { ...state, snapshot: next };
    }
    case 'MESSAGES_SNAPSHOT': return { ...state, messagesVersion: state.messagesVersion + 1 };
    default: return state;
  }
}
