import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import * as sessions from './sessions.js';
import { brief } from './brief.js';
import { gatewayExtension } from './gateway-extension.js';
import { createUIContext } from './ui-bridge.js';
export { brief };

const terminal = new Set(['completed', 'failed', 'paused', 'stopped', 'interrupted']);
// An implementation grant's protected roles: their runtime takes no extensions (harness plan §2.8).
const GRANT_ROLES = new Set(['implementation_builder', 'implementation_test_designer', 'implementation_validator']);
const safeID = (id: string) => { if (!/^[a-zA-Z0-9_-]{1,200}$/.test(id)) throw new Error('Invalid identity'); return id; };
function atomic(file: string, value: any) {
  const temp = file + '.tmp'; fs.writeFileSync(temp, JSON.stringify(value), {mode: 0o600}); fs.renameSync(temp, file);
}
function digest(value: any) { return createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
// What an agent is doing at this moment, for the researcher's screen: the steps of its turn, the text it is
// writing and the end of its reasoning. Held in memory only; reasoning never reaches the event journal.
const LIVE_TEXT = 4000, LIVE_STEPS = 40;
const tail = (text: string) => text.length > LIVE_TEXT ? text.slice(-LIVE_TEXT) : text;
export class Supervisor {
  agents = new Map<string, any>();
  closing = false;
  changed = new Set<string>();
  live = new Map<string, any>();
  calls = new Set<string>();
  flushTimer: ReturnType<typeof setTimeout> | null = null;
  // notify(agentIds) tells the workspace which agents to pull; it is a hint, so
  // a lost notice only delays reconciliation until the workspace's next sweep.
  constructor(public directory: string, public factory: any, public gateway: any, public authPath: string,
              public notify: ((ids: string[]) => Promise<unknown> | void) | null = null,
              public reconfigure: ((runtime: any, spec: any) => Promise<void>) | null = null,
              public completer: ((input: any, observe: (event: any) => void, signal?: AbortSignal) => Promise<any>) | null = null) {
    fs.mkdirSync(directory, {recursive: true, mode: 0o700});
    for (const id of fs.readdirSync(directory)) {
      const file = path.join(directory, id, 'state.json');
      if (!fs.existsSync(file)) continue;
      const agent = JSON.parse(fs.readFileSync(file, 'utf8'));
      const journal = path.join(directory, id, 'events.jsonl');
      if (fs.existsSync(journal)) {
        // The append can survive a crash before the state snapshot does.
        const lines = fs.readFileSync(journal, 'utf8').split('\n').filter(Boolean);
        for (const line of lines) { try { agent.seq = Math.max(agent.seq, JSON.parse(line).seq); } catch { /* torn final append */ } }
      }
      agent.runtime = null; agent.busy = false; agent.specChanged = false;
      // The campaign lead role was once named "pi"; Python migrated its records.
      if (agent.spec?.role === 'pi') agent.spec.role = 'lead';
      if (agent.control === 'interrupted') agent.control = null;
      for (const run of Object.values(agent.runs) as any[]) {
        if (!terminal.has(run.status)) { run.status = 'interrupted'; run.error = 'Harness restarted; inspect durable receipts before continuing.'; }
      }
      this.agents.set(id, agent); this.save(agent);
    }
  }
  save(agent: any) {
    if (agent.removed) return;   // its directory is gone; a turn that was still settling has nothing to save
    const {runtime, busy, turnTexts, ...persisted} = agent;   // a turn's texts live only while it runs
    atomic(path.join(this.directory, agent.id, 'state.json'), persisted);
    this.changed.add(agent.id);
    if (this.notify && !this.flushTimer) this.flushTimer = setTimeout(() => this.flush(), 200);
  }
  flush() {
    this.flushTimer = null;
    const ids = [...this.changed]; this.changed.clear();
    if (!ids.length || !this.notify) return;
    try { void Promise.resolve(this.notify(ids)).catch(() => {}); } catch { /* the sweep recovers */ }
  }
  event(agent: any, type: string, data: any = {}) {
    // Never publish hidden reasoning or authentication material.
    const item = {seq: ++agent.seq, type, occurred_at: new Date().toISOString(), ...data};
    if (agent.removed) return item;
    fs.appendFileSync(path.join(this.directory, agent.id, 'events.jsonl'), JSON.stringify(item) + '\n', {mode: 0o600});
    this.save(agent);
    return item;
  }
  begin(id: string, runId: string) {
    const at = new Date().toISOString();
    const entry = {id, run_id: runId, started_at: at, updated_at: at, finished_at: null as string | null, phase: 'starting', steps: [] as any[], thinking: '', text: ''};
    this.live.set(id, entry);
    return entry;
  }
  /** Fold one event of the model's stream into the live entry. */
  observe(entry: any, event: any) {
    if (!entry || entry.finished_at) return;
    const at = new Date().toISOString();
    if (event.type === 'message_update') {
      const part = event.assistantMessageEvent || {};
      if (part.type === 'thinking_start') { entry.thinking = ''; entry.phase = 'thinking'; }
      else if (part.type === 'thinking_delta') { entry.thinking = tail(entry.thinking + (part.delta || '')); entry.phase = 'thinking'; }
      else if (part.type === 'text_start') { entry.text = ''; entry.phase = 'writing'; }
      else if (part.type === 'text_delta') { entry.text = tail(entry.text + (part.delta || '')); entry.phase = 'writing'; }
      else return;
    } else if (event.type === 'tool_execution_start') {
      entry.steps.push({call_id: event.toolCallId, tool: event.toolName, args: brief(event.args), started_at: at});
      if (entry.steps.length > LIVE_STEPS) entry.steps.shift();
      entry.phase = 'tool';
    } else if (event.type === 'tool_execution_end') {
      const step = [...entry.steps].reverse().find((item: any) => item.call_id === event.toolCallId);
      if (step) { step.finished_at = at; if (event.isError) step.failed = true; }
      entry.phase = 'thinking';   // the model reads the result next
    } else return;
    entry.updated_at = at;
  }
  liveView(ids: string[]) {
    return Object.fromEntries(ids.map(safeID).filter(id => this.live.has(id)).map(id => [id, this.live.get(id)]));
  }
  /** An extension's notice or status line: shown as the agent's activity, kept in its journal. */
  activity(agent: any, text: string, data: any = {}) {
    const entry = this.live.get(agent.id);
    if (entry && !entry.finished_at) { entry.activity = String(text).slice(0, 500); entry.updated_at = new Date().toISOString(); }
    this.event(agent, 'extension.' + (data.kind || 'notify'), {...data, text: String(text).slice(0, 2000)});
  }
  /** One model call outside any agent's session, such as a stage of the report writer. Its reasoning shows in the live view under the caller's id. */
  async complete(id: string, input: any, signal?: AbortSignal) {
    safeID(id);
    if (!this.completer) throw new Error('Single model calls are not available on this harness');
    if (this.calls.has(id)) throw new Error('A model call under this identity is still running');
    const entry = this.begin(id, String(input.label || 'call').slice(0, 200));
    this.calls.add(id);
    try {
      const result = await this.completer(input, (event: any) => this.observe(entry, event), signal);
      entry.phase = 'completed';
      return result;
    } catch (error) { entry.phase = 'failed'; throw error; }
    finally { entry.finished_at = new Date().toISOString(); this.calls.delete(id); }
  }
  /** The session tree of an agent: its live runtime's manager, or the saved file when no turn has run since start. */
  sessionsOf(id: string) {
    const agent = this.agents.get(safeID(id)); if (!agent) return null;
    return agent.runtime?.sessionManager ?? sessions.open(agent.sessionFile);
  }
  session(id: string, view: string, params: any = {}) {
    const sm = this.sessionsOf(id);
    if (!sm) return null;
    if (view === 'tree') return sessions.tree(sm);
    if (view === 'entries') return sessions.entries(sm, {after: params.after, leaf: params.leaf});
    if (view === 'context') return sessions.context(sm, params.leaf);
    if (view === 'export') return sessions.exportBranch(sm, params.leaf);
    throw new Error('Unknown session view');
  }
  /** Move an idle agent's leaf (a researcher switching threads); during a turn the run itself positions it. */
  setLeaf(id: string, entryId: string, summary?: string | null) {
    const agent = this.agents.get(safeID(id)); if (!agent) return null;
    if (agent.busy) throw new Error('The agent is in a turn; its leaf moves with the next run');
    const sm = this.sessionsOf(id); if (!sm) throw new Error('The agent has no session yet');
    const result = sessions.setLeaf(sm, entryId, summary);
    this.event(agent, 'session.leaf_moved', {leaf_id: result.leaf_id, previous_leaf_id: result.previous_leaf_id, summary_entry_id: result.summary_entry_id});
    return result;
  }
  view(id: string, after = 0) {
    const agent = this.agents.get(safeID(id)); if (!agent) return null;
    const file = path.join(this.directory, id, 'events.jsonl');
    const events = fs.existsSync(file) ? fs.readFileSync(file, 'utf8').trim().split('\n').filter(Boolean)
      .flatMap(line => { try { return [JSON.parse(line)]; } catch { return []; } }).filter(e => e.seq > after).slice(0, 200) : [];
    return {id, session_id: agent.sessionId, session_file: agent.sessionFile, runs: agent.runs, events, cursor: events.at(-1)?.seq ?? after};
  }
  async submit(id: string, input: any) {
    safeID(id); safeID(input.run_id);
    let agent = this.agents.get(id);
    if (!agent) {
      fs.mkdirSync(path.join(this.directory, id), {recursive: true, mode: 0o700});
      agent = {id, spec: input.spec, seq: 0, runs: {}, sessionFile: null, runtime: null, busy: false};
      this.agents.set(id, agent);
    }
    // The role is the agent's identity. Model, provider and thinking level may change
    // (the workspace enforces which changes are allowed); they apply at the next turn.
    if (agent.spec.role !== input.spec.role) throw new Error('Agent identity cannot change its role');
    if (digest(agent.spec) !== digest(input.spec)) {
      agent.spec = input.spec; agent.specChanged = Boolean(agent.runtime);
      this.event(agent, 'spec.updated', {provider: input.spec.provider, model: input.spec.model, effort: input.spec.effort});
    }
    const requestHash = digest({text: input.text, mode: input.mode || 'follow_up'});
    const old = agent.runs[input.run_id];
    if (old) { if (old.requestHash !== requestHash) throw new Error('Run identity already belongs to another request'); return old; }
    // A thread is a branch of the session tree: the run names the leaf it continues from, or the entry a new branch starts at.
    const run = {id: input.run_id, text: input.text, mode: input.mode || 'follow_up', requestHash,
      status: 'queued', created_at: new Date().toISOString(), result: null, deadline_at: input.deadline_at,
      thread_id: input.thread_id ?? null, leaf_entry_id: input.leaf_entry_id ?? null, branch_from_entry_id: input.branch_from_entry_id ?? null,
      summary: input.summary ?? null};
    agent.runs[run.id] = run; this.event(agent, 'run.queued', {run_id: run.id});
    const active: any = Object.values(agent.runs).find((r: any) => r.status === 'running');
    // Steering reaches the turn in progress only from its own thread; another thread's message waits its turn.
    const sameThread = !active || (active.thread_id ?? null) === (run.thread_id ?? null);
    if (agent.busy && run.mode === 'steer' && agent.runtime && sameThread) {
      // Queue once, persist the acknowledgment; the active turn still owns tool
      // receipts. Ordinary follow-ups are scheduled after the active run settles.
      await agent.runtime.steer(`[Researcher steering ${run.id}]\n${run.text}`);
      Object.assign(run, {status: 'completed', result: {delivery: 'steering_queued'}}); this.save(agent);
    } else void this.pump(agent);
    return run;
  }
  async pump(agent: any) {
    if (this.closing || agent.busy || agent.control) return;
    const run: any = Object.values(agent.runs).find((r: any) => r.status === 'queued'); if (!run) return;
    agent.busy = true; run.status = 'running'; this.event(agent, 'run.started', {run_id: run.id});
    const live = this.begin(agent.id, run.id);
    let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
    let expired = false;
    try {
      if (run.deadline_at && run.deadline_at * 1000 <= Date.now()) throw new Error('Implementation allocation expired before dispatch; saved work is retained.');
      if (!agent.runtime) {
        const manifest = await this.gateway('manifest', {agent_id: agent.id, run_id: run.id});
        const active = () => Object.values(agent.runs).find((r: any) => r.status === 'running') as any;
        const tools = manifest.tools.map((tool: any) => ({...tool, label: tool.name, parameters: tool.input_schema,
          execute: async (callId: string, args: any, signal: AbortSignal) => {
            const owner = active();
            if (!owner) throw new Error('No active assignment');
            const result = await this.gateway('tool', {agent_id: agent.id, run_id: owner.id, call_id: callId, name: tool.name, arguments: args}, signal);
            // A saved yield_work ends the turn: without this a model may keep writing closing lines and yielding again.
            const ends = tool.name === 'yield_work' && result?.saved === true;
            if (ends) owner.yielded = true;
            return {content: [{type: 'text', text: JSON.stringify(result)}], details: {}, ...(ends ? {terminate: true} : {})};
          }}));
        // The extension set is part of the manifest, so it is fixed for the runtime's life. An older workspace's manifest
        // says nothing of it: then every role but an implementation grant's hosts the Balsamic extension.
        const extensionHost = typeof manifest.extension_host === 'boolean' ? manifest.extension_host : !GRANT_ROLES.has(agent.spec.role);
        const extensions = extensionHost && Array.isArray(manifest.extensions) ? manifest.extensions : [];
        const host = {agentId: agent.id, role: agent.spec.role, gatewayTools: new Set<string>(manifest.tools.map((tool: any) => tool.name)),
          allowedTools: new Map<string, string>(extensions.flatMap((e: any) => (e.tools || []).map((name: string) => [name, e.name] as [string, string]))),
          activeRun: active, yielded: (id: string) => Boolean(agent.runs[id]?.yielded), gateway: this.gateway,
          event: (type: string, data: any) => { this.event(agent, type, data); }};
        agent.runtime = await this.factory({directory: path.join(this.directory, agent.id), sessionFile: agent.sessionFile,
          authPath: this.authPath, ...agent.spec, instructions: manifest.instructions, tools, extensionHost, extensions,
          ...(extensionHost ? {balsamicExtension: gatewayExtension(host),
            uiContext: createUIContext({agentId: agent.id, activeRun: active, gateway: this.gateway, activity: (text, data) => this.activity(agent, text, data)})} : {}),
          onExtensionError: (error: any) => { this.event(agent, 'extension.error', {extension: error.extensionPath, event: error.event, error: String(error.error).slice(0, 1500)}); }});
        agent.sessionFile = agent.runtime.sessionFile; agent.sessionId = agent.runtime.sessionId; this.save(agent);
        agent.runtime.subscribe((event: any) => {
          this.observe(this.live.get(agent.id), event);
          if (event.type === 'message_end' && event.message?.role === 'assistant') {
            const message = event.message;
            const content = message.content.filter((c: any) => c.type === 'text').map((c: any) => c.text).join('\n');
            if (content.trim()) (agent.turnTexts ||= []).push(content);
            const usage: any = Object.fromEntries(['input', 'output', 'cacheRead', 'cacheWrite', 'reasoning', 'totalTokens']
              .map(key => [key, message.usage?.[key] || 0]));
            // Pi prices every call from its catalog; whether that is a charge depends on billing.
            usage.cost_usd = message.usage?.cost?.total || 0;
            this.event(agent, 'assistant.message', {text: content, usage, stop_reason: message.stopReason,
              provider: message.provider, model: message.model, thinking_level: message.thinkingLevel ?? agent.runtime?.thinkingLevel,
              billing: agent.runtime?.billing || 'unknown'});
          } else if (['tool_execution_start', 'tool_execution_end', 'auto_compaction_start', 'auto_compaction_end', 'auto_retry_start', 'auto_retry_end'].includes(event.type)) {
            this.event(agent, event.type, {tool: event.toolName, call_id: event.toolCallId, error: event.isError,
              summary: event.type.replaceAll('_', ' ')});
          }
        });
      }
      if (agent.specChanged && this.reconfigure) {
        await this.reconfigure(agent.runtime, agent.spec);
        agent.specChanged = false; this.save(agent);
        this.event(agent, 'model.changed', {provider: agent.spec.provider, model: agent.spec.model, effort: agent.spec.effort});
      }
      if (this.closing || agent.control) {run.status = agent.control || 'interrupted'; return;}
      if (run.deadline_at) deadlineTimer = setTimeout(() => { expired = true; void agent.runtime.abort(); }, Math.max(1, run.deadline_at * 1000 - Date.now()));
      agent.turnTexts = [];
      const sm = agent.runtime.sessionManager;
      if (sm) {
        // Position the leaf for this thread before the prompt; the entries the turn adds hang from it.
        if (run.branch_from_entry_id) sessions.setLeaf(sm, run.branch_from_entry_id, run.summary);
        else if (run.leaf_entry_id && run.leaf_entry_id !== sm.getLeafId()) sessions.setLeaf(sm, run.leaf_entry_id, run.summary);
        run.entry_ids = {parent: sm.getLeafId(), last: null};
        this.save(agent);
      }
      // The state block is built from the workspace's records now, not when the run was queued, and goes before the
      // message: the instructions stay fixed for the session (and the provider's cache). run.text alone is the run's identity.
      const state = await this.turnState(agent, run);
      await agent.runtime.prompt(`[Assignment ${run.id}]\n${state ? state + '\n\n' : ''}${run.text}`);
      if (expired) throw new Error('Implementation time allocation exhausted; session and artifacts are saved.');
      const last = agent.runtime.messages?.filter((m: any) => m.role === 'assistant').at(-1);
      if (last?.stopReason === 'error') throw new Error(last.errorMessage || 'Provider request failed');
      // abort() can return before prompt() settles. Preserve shutdown's durable
      // interruption marker even if close() has already cleared agent.control.
      run.status = agent.control || (run.status === 'interrupted' || last?.stopReason === 'aborted' ? 'interrupted' : 'completed');
      // Everything the agent wrote in the turn, in order. An answer written before the turn's last tool
      // call (the checkpoint, usually) is otherwise lost behind the closing line that follows it.
      run.result = {text: agent.turnTexts?.length ? agent.turnTexts.join('\n\n') : agent.runtime.getLastAssistantText() || '',
        // The separate texts let the chat show the closing message and fold lines written beside earlier tool calls.
        ...(agent.turnTexts?.length > 1 ? {parts: [...agent.turnTexts]} : {}),
        // Where the turn's entries hang in the session tree, for the thread's leaf.
        ...(sm ? {entry_ids: {parent: run.entry_ids?.parent ?? null, last: sm.getLeafId()}} : {})};
      if (sm && run.entry_ids) run.entry_ids.last = sm.getLeafId();
    } catch (e: any) {
      run.status = agent.control || (run.status === 'interrupted' ? 'interrupted' : 'failed'); run.error = String(e.message || e).slice(0, 1500);
    } finally {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      run.finished_at = new Date().toISOString(); agent.busy = false;
      live.finished_at = run.finished_at; live.phase = run.status;
      this.event(agent, 'run.' + run.status, {run_id: run.id, error: run.error});
      if (!this.closing && !agent.control) void this.pump(agent);
    }
  }
  /** This turn's state block from the workspace; empty when its gateway has none (an older workspace answers 404). */
  async turnState(agent: any, run: any) {
    try {
      const state = await this.gateway('turn_state', {agent_id: agent.id, run_id: run.id});
      return typeof state?.text === 'string' ? state.text : '';
    } catch (error: any) {
      if (error?.status === 404) return '';
      throw error;
    }
  }
  async control(id: string, action: string) {
    const agent = this.agents.get(safeID(id)); if (!agent) return {status: action};
    if (!['pause', 'resume', 'stop'].includes(action)) throw new Error('Invalid control');
    agent.control = action === 'resume' ? null : action === 'pause' ? 'paused' : 'stopped'; this.save(agent);
    if (action !== 'resume') {
      for (const run of Object.values(agent.runs) as any[]) if (run.status === 'queued') run.status = agent.control;
      await agent.runtime?.abort(); this.save(agent);
    } else void this.pump(agent);
    return {status: agent.control || 'idle'};
  }
  // Forget an agent whose campaign was removed: end its turn, drop it, and delete its saved session.
  async forget(id: string) {
    const agent = this.agents.get(safeID(id));
    const directory = path.join(this.directory, id);
    if (agent) {
      agent.control = 'stopped';
      for (const run of Object.values(agent.runs) as any[]) if (run.status === 'queued') run.status = 'stopped';
      await agent.runtime?.abort();
      for (let waited = 0; agent.busy && waited < 10000; waited += 50) await new Promise(resolve => setTimeout(resolve, 50));
      agent.removed = true; this.agents.delete(id); this.changed.delete(id);
      this.live.delete(id);
      await this.release(agent);
    }
    const existed = fs.existsSync(directory);
    fs.rmSync(directory, {recursive: true, force: true});
    return {removed: Boolean(agent) || existed};
  }
  async close() {
    this.closing = true;
    for (const agent of this.agents.values()) {
      if (agent.control) continue; // Preserve an explicit researcher pause/stop.
      agent.control = 'interrupted'; this.save(agent);
      await agent.runtime?.abort();
      for (const run of Object.values(agent.runs) as any[]) if (!terminal.has(run.status)) run.status = 'interrupted';
      agent.control = null; this.save(agent); await this.release(agent);
    }
  }
  /** End a runtime: its extensions' session_shutdown handlers run, then the session is disposed. */
  async release(agent: any) {
    const runtime = agent.runtime; agent.runtime = null;
    if (!runtime) return;
    try { if (runtime.shutdown) await runtime.shutdown(); else runtime.dispose?.(); }
    catch (error: any) { this.event(agent, 'extension.error', {event: 'session_shutdown', error: String(error?.message || error).slice(0, 1500)}); }
  }
}
