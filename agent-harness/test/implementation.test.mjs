import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';

// The coding workspace's extension runs inside its container, loaded by Pi from TypeScript; here it is compiled next to the
// harness's node_modules so its imports resolve, loaded with a bridge directory of the test's own.
const here = path.dirname(fileURLToPath(import.meta.url));
async function load(t) {
  const bridge = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-'));
  t.after(() => fs.rmSync(bridge, {recursive: true, force: true}));
  process.env.GRATING_DEVELOPMENT_BRIDGE = bridge;
  const source = fs.readFileSync(path.join(here, '..', 'extensions', 'implementation.ts'), 'utf8');
  const file = path.join(here, `.implementation-${process.pid}-${Math.random().toString(36).slice(2)}.mjs`);
  fs.writeFileSync(file, ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText);
  t.after(() => fs.rmSync(file, {force: true}));
  const tools = {};
  (await import(file)).default({registerTool: tool => { tools[tool.name] = tool; }, registerCommand() {}, on() {}});
  return {tools, events: () => fs.readdirSync(path.join(bridge, 'out', 'events')).map(name => JSON.parse(fs.readFileSync(path.join(bridge, 'out', 'events', name), 'utf8')))};
}

test('a checkpoint carries the coding agent\'s phase, tests and own estimate to the campaign', async t => {
  const {tools, events} = await load(t);
  const schema = tools.campaign_checkpoint.parameters;
  assert.deepEqual(schema.required, ['summary']);
  assert.ok(['phase', 'done', 'remaining', 'eta_minutes', 'tests'].every(key => key in schema.properties));
  assert.match(tools.campaign_checkpoint.description, /your own estimate of the minutes left/);
  await tools.campaign_checkpoint.execute('call', {summary: 'Testing', phase: 'testing', eta_minutes: 8, tests: {passed: 30, failed: 2}});
  const [event] = events();
  assert.equal(event.type, 'checkpoint');
  assert.deepEqual(event.payload, {summary: 'Testing', phase: 'testing', eta_minutes: 8, tests: {passed: 30, failed: 2}});
});

test('a submission requires the delivery report and hands it to the campaign', async t => {
  const {tools, events} = await load(t);
  const schema = tools.campaign_submit.parameters;
  assert.deepEqual(schema.required, ['commit', 'report']);
  const report = schema.properties.report;
  assert.deepEqual(report.required.sort(), ['limitations', 'methods', 'next_actions', 'summary', 'tests', 'verdict']);
  assert.deepEqual(report.properties.verdict.enum, ['ready', 'ready_with_limits', 'not_ready']);
  assert.ok(!JSON.stringify(schema).includes('allOf'), 'plain objects only: some providers refuse allOf');
  const done = tools.campaign_submit.execute('call', {commit: 'a'.repeat(40), report: {verdict: 'not_ready'}}, AbortSignal.timeout(50)).catch(error => error);
  await new Promise(resolve => setTimeout(resolve, 20));
  const [event] = events();
  assert.equal(event.type, 'submission');
  assert.deepEqual(event.payload.report, {verdict: 'not_ready'});
  await done;
});
