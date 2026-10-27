import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {Readable} from 'node:stream';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import {HARNESSES, adapter, checkedMode, records, refusal, runHeadless} from '../../deploy/implementation-workspace/harness.mjs';

// The coding box's harness adapter (roadmap H2): Pi in its terminal UI, where the extension reports its events, or headless,
// where the adapter maps Pi's JSON stream to the same events and delivers the host's commands itself.
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
// A real `pi --mode json` stream (Pi 1.0.4, a scripted model endpoint), described in tests/test_harness_adapter.py.
const stream = fs.readFileSync(path.join(repo, 'tests', 'fixtures', 'harness', 'pi-json-stream.jsonl'), 'utf8')
  .split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
const temp = (t, prefix) => { const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); t.after(() => fs.rmSync(dir, {recursive: true, force: true})); return dir; };
const events = bridge => { const dir = path.join(bridge, 'out', 'events'); return fs.existsSync(dir) ? fs.readdirSync(dir).sort()
  .map(name => JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'))) : []; };
const comparable = list => list.map(({type, payload}) => ({type, payload}));
const quiet = {log: () => {}};

function box(t) {
  const bridge = temp(t, 'bridge-'), sessions = temp(t, 'sessions-');
  fs.mkdirSync(path.join(bridge, 'in', 'commands'), {recursive: true});
  process.env.GRATING_DEVELOPMENT_BRIDGE = bridge;
  process.env.BALSAMIC_HARNESS_SESSIONS = sessions;
  process.env.BALSAMIC_WORKSPACE_REPO = sessions;
  return {bridge, sessions, command: (name, body) => fs.writeFileSync(path.join(bridge, 'in', 'commands', `${name}.json`), JSON.stringify(body))};
}

// A harness for the runner: Pi's adapter, run on a script that streams Pi-shaped records about the instruction it read.
// An instruction saying "hang" runs until it is stopped; one saying "fail" exits 2 with an error on stderr.
function scripted(t) {
  const script = path.join(temp(t, 'harness-'), 'harness.cjs');
  fs.writeFileSync(script, `const input = require('fs').readFileSync(0, 'utf8');
const out = record => process.stdout.write(JSON.stringify(record) + '\\n');
out({type: 'session', version: 3, id: 'session'});
out({type: 'agent_start'});
out({type: 'message_end', message: {role: 'assistant', content: [{type: 'text', text: 'ran: ' + input.split('\\n').at(-1)}], usage: {input: 10, output: 2}}});
if (input.includes('hang')) setInterval(() => {}, 1000);
else if (input.includes('fail')) { process.stderr.write('No credential for provider scripted\\n'); process.exit(2); }
else out({type: 'agent_settled'});
`);
  return {...HARNESSES.pi, invocation: () => ({command: process.execPath, args: [script], env: {}})};
}

test('the extension and the adapter map Pi\'s recorded session events to the same bridge events', async t => {
  const theirs = temp(t, 'bridge-ext-'), ours = temp(t, 'bridge-adapter-');
  process.env.GRATING_DEVELOPMENT_BRIDGE = theirs;
  const source = fs.readFileSync(path.join(repo, 'agent-harness', 'extensions', 'implementation.ts'), 'utf8');
  const file = path.join(here, `.implementation-${process.pid}-${Math.random().toString(36).slice(2)}.mjs`);
  fs.writeFileSync(file, ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText);
  t.after(() => fs.rmSync(file, {force: true}));
  const handlers = {};
  (await import(file)).default({registerTool() {}, registerCommand() {}, on: (name, handler) => { handlers[name] = handler; }});
  for (const record of stream) await handlers[record.type]?.(record);   // as the terminal UI's Pi calls them
  process.env.GRATING_DEVELOPMENT_BRIDGE = ours;
  const {emit} = await import('../../deploy/implementation-workspace/balsamic-workspace.mjs');
  for (const record of stream) for (const event of HARNESSES.pi.map(record)) emit(event.type, event.payload);
  const mapped = comparable(events(ours));
  assert.deepEqual(mapped, comparable(events(theirs)));
  assert.deepEqual(mapped.map(event => event.type), ['agent_start', 'message', 'tool', 'message', 'tool', 'message', 'tool', 'message', 'agent_settled']);
  assert.deepEqual(mapped[1].payload.usage, stream.find(r => r.type === 'message_end' && r.message.role === 'assistant').message.usage);
});

test('headless, the extension gives only its tools: the adapter reports the events and delivers the commands', async t => {
  const bridge = temp(t, 'bridge-headless-');
  process.env.GRATING_DEVELOPMENT_BRIDGE = bridge;
  process.env.BALSAMIC_HARNESS_MODE = 'headless';
  t.after(() => { delete process.env.BALSAMIC_HARNESS_MODE; });
  const source = fs.readFileSync(path.join(repo, 'agent-harness', 'extensions', 'implementation.ts'), 'utf8');
  const file = path.join(here, `.implementation-${process.pid}-${Math.random().toString(36).slice(2)}.mjs`);
  fs.writeFileSync(file, ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText);
  t.after(() => fs.rmSync(file, {force: true}));
  const tools = [], hooks = [], commands = [];
  (await import(file)).default({registerTool: tool => tools.push(tool.name), registerCommand: name => commands.push(name), on: name => hooks.push(name)});
  assert.deepEqual(tools, ['campaign_checkpoint', 'campaign_submit']);
  assert.deepEqual([hooks, commands], [[], []]);
});

test('the runner runs steering first, a pause interrupts the running instruction, and the queue goes on', async t => {
  const {bridge, sessions, command} = box(t);
  command('1_c1', {id: 'c1', operation: 'message', actor: 'lead', mode: 'follow_up', message: 'hang until paused'});
  command('2_c2', {id: 'c2', operation: 'message', actor: 'researcher', mode: 'follow_up', message: 'then this'});
  command('3_c3', {id: 'c3', operation: 'message', actor: 'system', mode: 'steer', message: 'first this'});
  const harness = scripted(t);
  const done = runHeadless(harness, [], {once: true, ...quiet});
  for (let i = 0; i < 200 && !events(bridge).some(e => e.payload.text === 'ran: hang until paused'); i++) await new Promise(r => setTimeout(r, 25));
  command('4_p1', {id: 'p1', operation: 'pause', actor: 'researcher'});
  await done;
  const seen = events(bridge).map(({type, payload}) => type === 'receipt' ? `${payload.command_id} ${payload.status}`
    : type === 'message' ? payload.text : type === 'agent_settled' ? `settled${payload.interrupted ? ' (interrupted)' : ''}` : type);
  assert.deepEqual(seen, ['ready', 'c1 accepted', 'c2 accepted', 'c3 accepted',
    'agent_start', 'ran: first this', 'c3 completed', 'settled',
    'agent_start', 'ran: hang until paused', 'p1 accepted', 'c1 interrupted', 'settled (interrupted)',
    'agent_start', 'ran: then this', 'c2 completed', 'settled']);
  assert.equal(events(bridge)[0].payload.session_id, path.join(sessions, 'pi.jsonl'));
  // Restarted, the box runs none of them again.
  const before = events(bridge).length;
  await runHeadless(harness, [], {once: true, ...quiet});
  assert.deepEqual(events(bridge).slice(before).map(e => e.type), ['ready']);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(sessions, 'pi-delivered.json'), 'utf8')).sort(), ['c1', 'c2', 'c3', 'p1']);
});

test('a run that fails is reported with the harness\'s error and closed', async t => {
  const {bridge, command} = box(t);
  command('1_c1', {id: 'c1', operation: 'message', actor: 'lead', mode: 'steer', message: 'fail now'});
  await runHeadless(scripted(t), [], {once: true, ...quiet});
  const found = comparable(events(bridge)).slice(2);
  assert.deepEqual(found.map(e => e.type), ['agent_start', 'message', 'harness_error', 'receipt', 'agent_settled']);
  assert.deepEqual(found[2].payload, {harness: 'pi', exit_code: 2, signal: null, error: 'No credential for provider scripted'});
  assert.deepEqual([found[3].payload, found[4].payload], [{command_id: 'c1', status: 'failed'}, {interrupted: false}]);
  // A harness that cannot start at all says so the same way.
  command('2_c2', {id: 'c2', operation: 'message', actor: 'lead', mode: 'steer', message: 'anything'});
  await runHeadless({...HARNESSES.pi, invocation: () => ({command: path.join(bridge, 'no-such-pi'), args: [], env: {}})}, [], {once: true, ...quiet});
  const missing = comparable(events(bridge)).filter(e => e.type === 'harness_error').at(-1);
  assert.match(missing.payload.error, /ENOENT/);
});

test('Pi\'s stream is split on LF only, as its JSON mode asks', async () => {
  const text = JSON.stringify({type: 'message_end', message: {role: 'assistant', content: [{type: 'text', text: 'one two'}]}});
  const chunks = [Buffer.from(text.slice(0, 20)), Buffer.from(text.slice(20) + '\r\n{"type":"agent_settled"}\nnot json\n{"type":"agent_end"'),
    Buffer.from(',"messages":[]}')];
  const found = [];
  for await (const record of records(Readable.from(chunks))) found.push(record);
  assert.deepEqual(found.map(record => record.type), ['message_end', 'agent_settled', 'agent_end']);
  assert.equal(found[0].message.content[0].text, 'one two');
});

test('only pi has an adapter; another harness or mode is refused with the text', () => {
  assert.throws(() => adapter('claude-code'), {message: refusal('claude-code')});
  assert.match(refusal('claude-code'), /^The coding harness "claude-code" is not available: a coding workspace runs only pi\. /);
  assert.equal(adapter('pi'), HARNESSES.pi);
  assert.throws(() => adapter('constructor'), {message: refusal('constructor')});
  assert.throws(() => checkedMode('gui'), {message: 'The harness mode "gui" is not one of tui, headless.'});
});
