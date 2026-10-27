import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Supervisor} from '../dist/supervisor.js';
import {gatewayExtension, REMINDER, TOOL_RESULT_BYTES} from '../dist/gateway-extension.js';
import {createUIContext} from '../dist/ui-bridge.js';

const fixtures = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'extensions');
const until = async predicate => { for (let i=0; i<400; i++) { if (predicate()) return; await new Promise(r=>setTimeout(r,5)); } throw Error('Timed out'); };
const temp = (t, prefix) => { const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); t.after(() => fs.rmSync(dir, {recursive: true, force: true})); return dir; };

// The locked-mode runtime (no profile), loaded fresh with this test's environment.
async function lockedRuntime() {
  delete process.env.GRATING_PI_PROFILE;
  return import(`../dist/runtime.js?locked=${Math.random()}`);
}
function signIn(authPath) {
  fs.writeFileSync(authPath, JSON.stringify({'openai-codex': {type: 'oauth', access: 'test-access', refresh: 'test-refresh', expires: Date.now() + 3600000}}));
}
async function session(t, extra = {}) {
  const {createRuntime} = await lockedRuntime();
  const root = temp(t, 'pi-ext-'), markers = temp(t, 'pi-markers-'), home = temp(t, 'pi-home-');
  process.env.BALSAMIC_TEST_MARKERS = markers;
  // Extensions where Pi would discover them, in the user's ~/.pi and in the working directory: none may load.
  const directory = path.join(root, 'agent');
  for (const dir of [path.join(home, '.pi', 'agent', 'extensions'), path.join(directory, '.pi', 'extensions')]) {
    fs.mkdirSync(dir, {recursive: true}); fs.copyFileSync(path.join(fixtures, 'evil.js'), path.join(dir, 'evil.js'));
  }
  const saved = process.env.HOME; process.env.HOME = home; t.after(() => { process.env.HOME = saved; });
  const authPath = path.join(root, 'auth.json'); signIn(authPath);
  globalThis.__balsamicOrder = [];
  const errors = [];
  const runtime = await createRuntime({directory, authPath, provider: 'openai-codex', model: 'gpt-6-astra', instructions: 'Test agent.', tools: [],
    extensionHost: true, extensions: [{name: 'marker', path: path.join(fixtures, 'marker', 'index.js'), tools: ['marker_lookup']}],
    balsamicExtension: pi => { globalThis.__balsamicOrder.push('balsamic:load'); pi.on('session_start', () => globalThis.__balsamicOrder.push('balsamic:start')); },
    onExtensionError: error => errors.push(error), ...extra});
  return {runtime, markers, errors};
}

test('the harness binds extensions: session_start runs, the Balsamic extension first, and nothing is discovered', async t => {
  const {runtime, markers, errors} = await session(t);
  assert.ok(fs.existsSync(path.join(markers, 'marker-started')), 'the allowlisted extension started');
  assert.ok(!fs.existsSync(path.join(markers, 'evil-loaded')), 'nothing from ~/.pi or the working directory loaded');
  assert.deepEqual(globalThis.__balsamicOrder.filter(item => item.endsWith(':start')), ['balsamic:start', 'marker:start']);
  assert.ok(runtime.getActiveToolNames().includes('marker_lookup'), 'an allowlisted extension tool is active');
  assert.deepEqual(errors, []);
  await runtime.shutdown();
  assert.ok(fs.existsSync(path.join(markers, 'marker-shutdown')), 'session_shutdown ran on release');
  await runtime.shutdown();   // idempotent
});

test('a runtime that hosts no extension takes none; an extension error is reported', async t => {
  const bare = await session(t, {extensionHost: false});
  assert.ok(!fs.existsSync(path.join(bare.markers, 'marker-started')) && !globalThis.__balsamicOrder.length);
  await bare.runtime.shutdown();
  const broken = await session(t, {extensions: [{name: 'broken', path: path.join(fixtures, 'broken', 'index.js'), tools: []}]});
  assert.equal(broken.errors.length, 1);
  assert.match(broken.errors[0].error, /broken on purpose/); assert.equal(broken.errors[0].event, 'session_start');
  await broken.runtime.shutdown();
});

function fakePi() {
  const handlers = {};
  return {handlers, on(name, fn) { (handlers[name] ||= []).push(fn); }, getAllTools: () => [{name: 'web_read', annotations: {readOnlyHint: true}}],
    emit: async (name, event, ctx = {signal: undefined, getContextUsage: () => ({tokens: 1200, contextWindow: 200000, percent: 0.6})}) => {
      let result; for (const fn of handlers[name] || []) result = await fn(event, ctx) ?? result; return result; }};
}
function gatewayHost(overrides = {}) {
  const calls = [], events = [];
  const run = {id: 'run_1'};
  const host = {agentId: 'lead_x', role: 'lead', gatewayTools: new Set(['campaign_inspect', 'yield_work']), allowedTools: new Map([['web_read', 'web']]),
    activeRun: () => run, yielded: () => false, event: (type, data) => events.push({type, ...data}),
    gateway: async (operation, data) => { calls.push({operation, data}); return {receipt_id: 'pi_tool_abc'}; }, ...overrides};
  const pi = fakePi(); gatewayExtension(host)(pi);
  return {pi, calls, events, run};
}

test('the Balsamic extension blocks tools no allowlist names and receipts the allowlisted ones', async () => {
  const {pi, calls, events} = gatewayHost();
  assert.equal(await pi.emit('tool_call', {toolName: 'campaign_inspect', toolCallId: 'c1', input: {}}), undefined);
  assert.equal(await pi.emit('tool_call', {toolName: 'web_read', toolCallId: 'c2', input: {url: 'https://x'}}), undefined);
  const blocked = await pi.emit('tool_call', {toolName: 'bash', toolCallId: 'c3', input: {command: 'rm -rf /'}});
  assert.equal(blocked.block, true); assert.match(blocked.reason, /not allowed for the lead/);
  assert.equal(events[0].type, 'extension.tool_blocked');
  // A gateway tool's result is the gateway's own receipt; a blocked call ran nothing.
  assert.equal(await pi.emit('tool_result', {toolName: 'campaign_inspect', toolCallId: 'c1', input: {}, content: [], isError: false}), undefined);
  assert.equal(await pi.emit('tool_result', {toolName: 'bash', toolCallId: 'c3', input: {}, content: [], isError: true}), undefined);
  assert.equal(calls.length, 0);
  // An allowlisted extension tool: receipted with the active run, its result unchanged when small.
  assert.equal(await pi.emit('tool_result', {toolName: 'web_read', toolCallId: 'c2', input: {url: 'https://x', body: 'y'.repeat(500)},
    content: [{type: 'text', text: 'page text'}], isError: false}), undefined);
  const receipt = calls[0];
  assert.equal(receipt.operation, 'external_receipt');
  assert.deepEqual([receipt.data.agent_id, receipt.data.run_id, receipt.data.call_id, receipt.data.tool, receipt.data.extension], ['lead_x', 'run_1', 'c2', 'web_read', 'web']);
  assert.equal(receipt.data.result_excerpt, 'page text'); assert.deepEqual(receipt.data.annotations, {readOnlyHint: true});
  assert.ok(receipt.data.arguments.body.length <= 201, 'arguments are bounded');
  // A large result is cut for the model and points at the receipt.
  const large = await pi.emit('tool_result', {toolName: 'web_read', toolCallId: 'c4', input: {}, content: [{type: 'text', text: 'z'.repeat(TOOL_RESULT_BYTES + 5000)}], isError: false});
  assert.ok(Buffer.byteLength(JSON.stringify(large.content)) <= TOOL_RESULT_BYTES); assert.match(large.content[0].text, /pi_tool_abc/);
  assert.equal(calls[1].data.result_excerpt.length, 24 * 1024);
});

test('a result the workspace cannot receipt is withheld from the model', async () => {
  const {pi, events} = gatewayHost({gateway: async () => { throw new Error('Run is not active'); }});
  const result = await pi.emit('tool_result', {toolName: 'web_read', toolCallId: 'c1', input: {}, content: [{type: 'text', text: 'secret'}], isError: false});
  assert.equal(result.isError, true); assert.ok(!JSON.stringify(result.content).includes('secret'));
  assert.equal(events.at(-1).type, 'extension.receipt_failed');
});

test('a run ending without yield_work gets one continuation in the turn; none when it yielded', async () => {
  const yielded = new Set();
  const {pi, events} = gatewayHost({yielded: id => yielded.has(id)});
  // As Pi sends it when a turn ended in prose: the preview ends on the assistant's message and cannot continue yet.
  const settle = (outcome = 'completed') => pi.emit('agent_before_settle', {type: 'agent_before_settle', entries: [], continue: false, outcome, context: {canContinue: false}});
  assert.equal(await settle('aborted'), undefined, 'an aborted run is not continued');
  const first = await settle();
  assert.equal(first.continue, true); assert.equal(first.entries[0].type, 'custom_message'); assert.equal(first.entries[0].content, REMINDER);
  assert.equal(await settle(), undefined, 'at most one continuation per run');
  assert.equal(events.filter(e => e.type === 'turn.continued').length, 1);
  const other = gatewayHost({yielded: () => true});
  assert.equal(await other.pi.emit('agent_before_settle', {entries: [], continue: false, outcome: 'completed', context: {canContinue: false}}), undefined);
  // Context usage reaches the journal at each turn's end.
  await pi.emit('turn_end', {type: 'turn_end'});
  assert.deepEqual(events.at(-1), {type: 'context.usage', tokens: 1200, context_window: 200000, percent: 0.6});
});

test('extension dialogs become questions to the researcher: answered, timed out, dismissed', async () => {
  const requests = [], activities = [];
  let answer = {status: 'pending'};
  const gateway = async (operation, data) => {
    requests.push({operation, data});
    if (operation === 'ui_request') return {status: 'pending', question_id: 'question_ui_1'};
    return {question_id: 'question_ui_1', ...answer};
  };
  const ui = createUIContext({agentId: 'lead_x', activeRun: () => ({id: 'run_1'}), gateway, activity: (text, data) => activities.push({text, ...data}), pollMs: 5});
  const confirmed = ui.confirm('Allow web access?', 'The extension wants to read a page.');
  await until(() => requests.length >= 2);
  assert.deepEqual(requests[0], {operation: 'ui_request', data: {agent_id: 'lead_x', run_id: 'run_1', method: 'confirm', title: 'Allow web access?',
    message: 'The extension wants to read a page.', timeout_ms: null}});
  assert.equal(requests[1].operation, 'ui_request/question_ui_1');
  answer = {status: 'answered', value: true};
  assert.equal(await confirmed, true);
  // The extension's own timeout: the default answer when nobody answers.
  answer = {status: 'pending'};
  assert.equal(await ui.select('Which?', ['a', 'b'], {timeout: 30}), undefined);
  assert.equal(await ui.confirm('Again?', 'x', {timeout: 30}), false);
  // A dismissed (cancelled) or expired dialog resolves as in RPC mode; an answer outside the options is no answer.
  answer = {status: 'cancelled'};
  assert.equal(await ui.input('Name?'), undefined);
  answer = {status: 'answered', value: 'c'};
  assert.equal(await ui.select('Which?', ['a', 'b']), undefined);
  answer = {status: 'answered', value: 'b'};
  assert.equal(await ui.select('Which?', ['a', 'b']), 'b');
  // Notices and status lines are the agent's activity; terminal-only calls do nothing.
  ui.notify('Fetched 3 pages', 'info'); ui.setStatus('web', 'idle'); ui.setWidget('w', ['x']); ui.setTitle('t');
  assert.deepEqual(activities, [{text: 'Fetched 3 pages', kind: 'notify', level: 'info'}, {text: 'idle', kind: 'status', key: 'web'}]);
  // With no turn running there is nobody to ask.
  const idle = createUIContext({agentId: 'lead_x', activeRun: () => undefined, gateway, activity: () => {}, pollMs: 5});
  assert.equal(await idle.confirm('x', 'y'), false);
});

test('the supervisor hosts extensions unless the manifest says not to, and journals extension errors and notices', async t => {
  const directory = temp(t, 'pi-sup-');
  const options = [], runtimes = [];
  const factory = async opts => {
    options.push(opts);
    const runtime = {sessionFile: path.join(opts.directory, 's.jsonl'), sessionId: 's', messages: [], subscribe() {}, async abort() { this.finish?.(); },
      prompt() { return new Promise(resolve => { this.finish = () => { this.messages.push({role: 'assistant', stopReason: 'stop'}); resolve(); }; }); },
      getLastAssistantText() { return ''; }, shutdown: async () => { runtime.released = true; }};
    runtimes.push(runtime); return runtime;
  };
  const gateway = async (operation, data) => operation === 'manifest'
    ? {instructions: 'x', tools: [{name: 'yield_work', input_schema: {type: 'object'}}],
       extension_host: !data.agent_id.startsWith('builder'), extensions: [{name: 'web', path: '/x/web/index.ts', tools: ['web_read']}]}
    : operation === 'tool' ? {saved: true} : {text: ''};
  const s = new Supervisor(directory, factory, gateway, 'auth');
  await s.submit('lead', {run_id: 'r1', text: 'go', spec: {model: 'm', role: 'lead'}}); await until(() => runtimes[0]?.finish);
  assert.equal(typeof options[0].balsamicExtension, 'function'); assert.ok(options[0].uiContext);
  assert.equal(options[0].extensionHost, true); assert.deepEqual(options[0].extensions.map(e => e.name), ['web']);
  options[0].onExtensionError({extensionPath: '/x/web/index.ts', event: 'session_start', error: 'no network'});
  const failure = s.view('lead').events.find(e => e.type === 'extension.error');
  assert.deepEqual([failure.extension, failure.event, failure.error], ['/x/web/index.ts', 'session_start', 'no network']);
  options[0].uiContext.notify('Indexed 4 files');
  assert.equal(s.liveView(['lead']).lead.activity, 'Indexed 4 files');
  assert.ok(s.view('lead').events.some(e => e.type === 'extension.notify' && e.text === 'Indexed 4 files'));
  // yield_work saved in the run is what the extension's continuation check reads.
  await options[0].tools[0].execute('y1', {disposition: 'complete'});
  assert.equal(s.agents.get('lead').runs.r1.yielded, true);
  runtimes[0].finish(); await until(() => s.view('lead').runs.r1.status === 'completed');
  await s.submit('builder_1', {run_id: 'r2', text: 'build', spec: {model: 'm', role: 'results_analyst'}}); await until(() => runtimes[1]?.finish);
  assert.equal(options[1].extensionHost, false); assert.equal(options[1].balsamicExtension, undefined); assert.deepEqual(options[1].extensions, []);
  runtimes[1].finish(); await until(() => s.view('builder_1').runs.r2.status === 'completed');
  // Forgetting an agent ends its runtime through session_shutdown.
  await s.forget('lead');
  assert.equal(runtimes[0].released, true);
});
