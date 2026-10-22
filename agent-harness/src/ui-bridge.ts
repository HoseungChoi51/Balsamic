import type { ExtensionUIContext, ExtensionUIDialogOptions } from '@earendil-works/pi-coding-agent';

/**
 * The extension UI of a Balsamic session, built as Pi's RPC mode builds one (dist/modes/rpc/rpc-mode.js).
 *
 * A dialog (select, confirm, input, editor) becomes a question to the researcher: the workspace saves it
 * (POST /api/internal/pi/ui_request), the researcher answers it above the chat or on the agent's page, and the
 * waiting extension gets the answer, not a new turn. Its deadline is the extension's own timeout, else the
 * workspace's default; under autopilot the workspace cancels it at once. A cancelled or expired dialog resolves
 * as in RPC mode: undefined, or false for confirm. notify and setStatus become the agent's activity line and
 * journal events. Widgets, titles, themes and terminal components do nothing, as in RPC mode.
 */
export interface UIHost {
  agentId: string;
  activeRun(): any | undefined;
  gateway(operation: string, data: any, signal?: AbortSignal): Promise<any>;
  activity(text: string, data: Record<string, any>): void;
  pollMs?: number;
}

const wait = (ms: number, signal?: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, {once: true});
});

export function createUIContext(host: UIHost): ExtensionUIContext {
  const pollMs = host.pollMs ?? 1000;
  async function dialog<T>(request: Record<string, any>, opts: ExtensionUIDialogOptions | undefined, fallback: T, parse: (answer: any) => T): Promise<T> {
    const run = host.activeRun();
    const signal = opts?.signal;
    if (!run || signal?.aborted) return fallback;
    const scope = {agent_id: host.agentId, run_id: run.id};
    let state: any;
    try {
      state = await host.gateway('ui_request', {...scope, ...request, timeout_ms: opts?.timeout ?? null}, signal);
    } catch (error: any) {
      host.activity('An extension asked something that could not be shown: ' + String(error?.message || error).slice(0, 200), {kind: 'dialog_failed'});
      return fallback;
    }
    // The extension's own timeout holds here too, in case the workspace cannot be reached when it passes.
    const deadline = opts?.timeout ? Date.now() + opts.timeout : null;
    while (state?.status === 'pending') {
      if (signal?.aborted || (deadline !== null && Date.now() >= deadline)) return fallback;
      await wait(deadline === null ? pollMs : Math.max(1, Math.min(pollMs, deadline - Date.now())), signal);
      if (signal?.aborted) return fallback;
      try {
        state = await host.gateway(`ui_request/${state.question_id}`, scope, signal);
      } catch (error: any) {
        if (error?.definitive) return fallback;   // the question is gone or not this agent's
      }
    }
    return state?.status === 'answered' ? parse(state) : fallback;
  }
  const text = (answer: any) => typeof answer.value === 'string' ? answer.value : undefined;
  return {
    select: (title, options, opts) => dialog({method: 'select', title, options}, opts, undefined,
      answer => typeof answer.value === 'string' && options.includes(answer.value) ? answer.value : undefined),
    confirm: (title, message, opts) => dialog({method: 'confirm', title, message}, opts, false, answer => answer.value === true),
    input: (title, placeholder, opts) => dialog({method: 'input', title, placeholder}, opts, undefined, text),
    editor: (title, prefill) => dialog({method: 'editor', title, prefill}, undefined, undefined, text),
    notify(message, type) { host.activity(String(message), {kind: 'notify', level: type || 'info'}); },
    setStatus(key, value) { if (value) host.activity(String(value), {kind: 'status', key}); },
    onTerminalInput() { return () => {}; },
    setWorkingMessage() {}, setWorkingVisible() {}, setWorkingIndicator() {}, setHiddenThinkingLabel() {},
    setWidget() {}, setFooter() {}, setHeader() {}, setTitle() {},
    async custom() { return undefined as any; },
    pasteToEditor() {}, setEditorText() {}, getEditorText() { return ''; },
    addAutocompleteProvider() {}, setEditorComponent() {}, getEditorComponent() { return undefined; },
    // No terminal, so no theme: an extension guards terminal-only use with ctx.mode === 'tui'.
    get theme() { return undefined as any; },
    getAllThemes() { return []; }, getTheme() { return undefined; },
    setTheme() { return {success: false, error: 'Themes are not available in Balsamic sessions'}; },
    getToolsExpanded() { return false; }, setToolsExpanded() {},
  };
}
