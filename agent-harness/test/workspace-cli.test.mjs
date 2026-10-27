import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';

// balsamic-workspace, the coding box's CLI and MCP server, against the Pi extension it stands beside: for the same inputs
// both write the same events into the file bridge (roadmap H1).
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const cli = path.join(repo, 'deploy', 'implementation-workspace', 'balsamic-workspace.mjs');
const temp = (t, prefix) => { const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); t.after(() => fs.rmSync(dir, {recursive: true, force: true})); return dir; };
const events = bridge => { const dir = path.join(bridge, 'out', 'events'); return fs.existsSync(dir) ? fs.readdirSync(dir).sort()
  .map(name => ({key: name.slice(0, -5), ...JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'))})) : []; };
// What the host reads of an event: its type and payload (the time and the file's name differ by construction).
const comparable = list => list.map(({type, payload}) => ({type, payload}));

async function extension(t) {
  const bridge = temp(t, 'bridge-ext-');
  process.env.GRATING_DEVELOPMENT_BRIDGE = bridge;
  const source = fs.readFileSync(path.join(repo, 'agent-harness', 'extensions', 'implementation.ts'), 'utf8');
  const file = path.join(here, `.implementation-${process.pid}-${Math.random().toString(36).slice(2)}.mjs`);
  fs.writeFileSync(file, ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText);
  t.after(() => fs.rmSync(file, {force: true}));
  const tools = {};
  (await import(file)).default({registerTool: tool => { tools[tool.name] = tool; }, registerCommand() {}, on() {}});
  return {tools, bridge};
}

function run(bridge, args, {cwd, env = {}, input} = {}) {
  const result = spawnSync(process.execPath, [cli, ...args], {cwd, input, encoding: 'utf8',
    env: {...process.env, GRATING_DEVELOPMENT_BRIDGE: bridge, ...env}});
  return {...result, json: result.status === 0 ? JSON.parse(result.stdout) : undefined};
}

// Answers the first submission event the way the host does, by writing its result file.
function answer(bridge, result) {
  const timer = setInterval(() => {
    const submission = events(bridge).find(event => event.type === 'submission');
    if (!submission) return;
    fs.mkdirSync(path.join(bridge, 'in', 'results'), {recursive: true});
    fs.writeFileSync(path.join(bridge, 'in', 'results', `${submission.key}.json`), JSON.stringify(result));
    clearInterval(timer);
  }, 20);
  return () => clearInterval(timer);
}

const REPORT = {verdict: 'ready_with_limits', summary: 'Both methods work.',
  methods: [{method_id: 'bakery_adjacent', hypothesis_id: 'hypothesis_dev', state: 'implemented', tests: {passed: 12, failed: 0}, conformance: 'passed'}],
  tests: {passed: 32, failed: 0, skipped: 0, command: 'pytest libraries/bakery'},
  limitations: ['The evaluator is not commissioned'], next_actions: [{owner: 'researcher', action: 'Install the library'}]};

test('the CLI and the extension write identical checkpoint and question events for the same inputs', async t => {
  const {tools, bridge: theirs} = await extension(t);
  const ours = temp(t, 'bridge-cli-');
  const checkpoint = {summary: 'Testing', phase: 'testing', done: ['core', 'seed replay'], remaining: ['packaging'],
    eta_minutes: 8, tests: {passed: 30, failed: 2, skipped: 1}, next_steps: 'Fix the two failures', blocker: 'None yet'};
  await tools.campaign_checkpoint.execute('call', checkpoint);
  await tools.campaign_checkpoint.execute('call', {summary: 'Should the seed be configurable?', question: 'Should the seed be configurable?'});
  const flags = run(ours, ['checkpoint', '--summary', 'Testing', '--phase', 'testing', '--done', 'core', '--done', 'seed replay',
    '--remaining', 'packaging', '--eta', '8', '--tests', '30/2/1', '--next-steps', 'Fix the two failures', '--blocker', 'None yet']);
  assert.equal(flags.status, 0, flags.stderr);
  assert.match(flags.json.message, /^Checkpoint .* saved for the campaign\.$/);
  const asked = run(ours, ['ask', 'Should the seed be configurable?']);
  assert.equal(asked.status, 0, asked.stderr);
  assert.deepEqual(comparable(events(ours)), comparable(events(theirs)));
  // The same checkpoint as JSON, on stdin.
  const json = temp(t, 'bridge-json-');
  assert.equal(run(json, ['checkpoint', '--json', '-'], {input: JSON.stringify(checkpoint)}).status, 0);
  assert.deepEqual(comparable(events(json)), comparable(events(theirs)).slice(0, 1));
});

test('the CLI and the extension submit the same event, and both report the host\'s answer', async t => {
  const {tools, bridge: theirs} = await extension(t);
  const ours = temp(t, 'bridge-cli-');
  const reply = {submission_id: 'development_submission_x', status: 'submitted', ignored_fields: ['extra']};
  const stop = answer(theirs, reply);
  const result = await tools.campaign_submit.execute('call', {commit: 'a'.repeat(40), report: REPORT, notes: 'First delivery'}, AbortSignal.timeout(5000));
  stop();
  const report = path.join(temp(t, 'report-'), 'report.json');
  fs.writeFileSync(report, JSON.stringify(REPORT));
  const stopOurs = answer(ours, reply);
  const child = spawn(process.execPath, [cli, 'submit', 'a'.repeat(40), '--report', report, '--notes', 'First delivery'],
    {env: {...process.env, GRATING_DEVELOPMENT_BRIDGE: ours}});
  let stdout = '';
  child.stdout.on('data', data => { stdout += data; });
  const code = await new Promise(resolve => child.on('close', resolve));
  stopOurs();
  assert.equal(code, 0);
  assert.deepEqual(comparable(events(ours)), comparable(events(theirs)));
  assert.equal(events(ours)[0].payload.manifest_path, 'implementation-manifest.json');
  assert.equal(JSON.parse(stdout).message, result.content[0].text);
  assert.match(result.content[0].text, /Submitted development_submission_x\. The manifest's unknown fields were ignored: extra\./);
});

test('the CLI refuses what the extension\'s schema refuses, naming the field, and writes nothing', async t => {
  const bridge = temp(t, 'bridge-cli-');
  for (const [args, says] of [[['checkpoint', '--phase', 'testing'], /arguments\.summary: required/],
                              [['checkpoint', '--summary', 'x', '--phase', 'coding'], /arguments\.phase: one of orienting/],
                              [['checkpoint', '--summary', 'x', '--tests', 'many'], /--tests is PASSED\/FAILED/],
                              [['submit', 'abc', '--json', JSON.stringify({commit: 'abc', report: REPORT})], /arguments\.commit: must match/],
                              [['submit', '--json', JSON.stringify({commit: 'a'.repeat(40), report: {...REPORT, methods: []}})], /report\.methods: at least 1 items/],
                              [['ask'], /arguments\.question: must not be empty/],
                              [['deploy'], /Unknown tool deploy/]]) {
    const result = run(bridge, args);
    assert.equal(result.status, 1, args.join(' '));
    assert.match(result.stderr, says);
  }
  assert.deepEqual(events(bridge), []);
});

test('the MCP server lists the five tools, with the extension\'s own schemas, and calls them', async t => {
  const {tools} = await extension(t);
  const bridge = temp(t, 'bridge-mcp-');
  const child = spawn(process.execPath, [cli, 'mcp'], {env: {...process.env, GRATING_DEVELOPMENT_BRIDGE: bridge}});
  t.after(() => child.kill());
  const replies = new Map();
  let buffer = '';
  child.stdout.on('data', data => {
    buffer += data;
    for (let index; (index = buffer.indexOf('\n')) >= 0;) {
      const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
      const message = JSON.parse(line); replies.set(message.id, message);
    }
  });
  let next = 1;
  const request = async (method, params) => {
    const id = next++;
    child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    for (let i = 0; i < 400 && !replies.has(id); i++) await new Promise(resolve => setTimeout(resolve, 10));
    return replies.get(id);
  };
  const init = await request('initialize', {protocolVersion: '2025-06-18', capabilities: {}, clientInfo: {name: 'test', version: '0'}});
  assert.equal(init.result.serverInfo.name, 'balsamic-workspace');
  assert.deepEqual(init.result.capabilities, {tools: {}});
  child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/initialized'}) + '\n');
  const {result: {tools: listed}} = await request('tools/list', {});
  assert.deepEqual(listed.map(tool => tool.name), ['checkpoint', 'ask', 'submit', 'check', 'evidence']);
  const plain = value => JSON.parse(JSON.stringify(value));
  for (const [ours, theirs] of [['checkpoint', 'campaign_checkpoint'], ['submit', 'campaign_submit']]) {
    const tool = listed.find(item => item.name === ours);
    assert.deepEqual(tool.inputSchema, plain(tools[theirs].parameters), ours);
    assert.equal(tool.description, tools[theirs].description, ours);
  }
  const called = await request('tools/call', {name: 'checkpoint', arguments: {summary: 'Orienting', phase: 'orienting'}});
  assert.match(called.result.content[0].text, /^Checkpoint .* saved for the campaign\.$/);
  assert.deepEqual(comparable(events(bridge)), [{type: 'checkpoint', payload: {summary: 'Orienting', phase: 'orienting'}}]);
  const refused = await request('tools/call', {name: 'checkpoint', arguments: {}});
  assert.equal(refused.result.isError, true);
  assert.match(refused.result.content[0].text, /summary: required/);
  assert.equal((await request('resources/list', {})).error.code, -32601);
  assert.deepEqual((await request('ping')).result, {});
});

test('evidence reads only what .campaign/evidence.json names', t => {
  const work = temp(t, 'repo-');
  fs.mkdirSync(path.join(work, '.campaign'));
  fs.writeFileSync(path.join(work, '.campaign', 'evidence.json'), JSON.stringify([
    {kind: 'source', data: {id: 'source_1', title: 'The paper', campaign_id: 'c'}},
    {kind: 'hypothesis', data: {id: 'hypothesis_1', title: 'Adjacent swaps'}}]));
  const env = {BALSAMIC_WORKSPACE_REPO: work};
  const listed = run(temp(t, 'bridge-'), ['evidence'], {env});
  assert.deepEqual(listed.json.evidence, [{id: 'source_1', kind: 'source', title: 'The paper'}, {id: 'hypothesis_1', kind: 'hypothesis', title: 'Adjacent swaps'}]);
  assert.equal(run(temp(t, 'bridge-'), ['evidence', 'hypothesis_1'], {env}).json.data.title, 'Adjacent swaps');
  const refused = run(temp(t, 'bridge-'), ['evidence', 'source_2'], {env});
  assert.equal(refused.status, 1);
  assert.match(refused.stderr, /source_2 is not evidence this workspace was given/);
});

// check runs pytest: it needs a Python with pytest, which the workspace image has and the repository's environment has.
const python = [process.env.BALSAMIC_WORKSPACE_PYTHON, path.join(repo, '.venv', 'bin', 'python'), 'python3']
  .find(candidate => candidate && spawnSync(candidate, ['-c', 'import pytest'], {stdio: 'ignore'}).status === 0);

test('check runs the library\'s tests and its contract tests, and returns the counts for the report', {skip: !python && 'no Python with pytest'}, t => {
  const work = temp(t, 'repo-');
  const tests = path.join(work, 'libraries', 'bakery', 'tests');
  fs.mkdirSync(tests, {recursive: true});
  fs.writeFileSync(path.join(tests, 'test_contract.py'), 'def test_valid():\n    pass\n\ndef test_replay():\n    pass\n');
  fs.writeFileSync(path.join(tests, 'test_bakery.py'), 'import pytest\n\ndef test_ok():\n    pass\n\n'
    + 'def test_wrong():\n    assert 1 == 2\n\n@pytest.mark.skip\ndef test_later():\n    pass\n');
  fs.writeFileSync(path.join(work, 'implementation-manifest.json'), JSON.stringify({files: ['libraries/bakery/src/bakery/plugin.py']}));
  const env = {BALSAMIC_WORKSPACE_REPO: work, BALSAMIC_WORKSPACE_PYTHON: python};
  const result = run(temp(t, 'bridge-'), ['check'], {env});
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.json.library, 'libraries/bakery');
  assert.deepEqual({...result.json.tests, command: undefined}, {passed: 3, failed: 1, skipped: 1, command: undefined});
  assert.match(result.json.tests.command, /-m pytest .*libraries\/bakery$/);
  assert.deepEqual(result.json.contract, {passed: 2, failed: 0, skipped: 0});
  assert.equal(result.json.conformance, 'passed');
  assert.match(result.json.message, /3 passed, 1 failed, 1 skipped; conformance passed/);
  // A failing contract test fails conformance; without one, it was not run.
  fs.writeFileSync(path.join(tests, 'test_contract.py'), 'def test_valid():\n    assert False\n');
  assert.equal(run(temp(t, 'bridge-'), ['check', 'libraries/bakery'], {env}).json.conformance, 'failed');
  fs.rmSync(path.join(tests, 'test_contract.py'));
  assert.equal(run(temp(t, 'bridge-'), ['check', 'libraries/bakery'], {env}).json.conformance, 'not_run');
  const unnamed = run(temp(t, 'bridge-'), ['check'], {env: {...env, BALSAMIC_WORKSPACE_REPO: temp(t, 'empty-')}});
  assert.match(unnamed.stderr, /Name the library to check/);
});
