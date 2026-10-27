// The in-turn continuation against Pi itself: a real AgentSession, the Balsamic gateway extension, and a scripted model.
// At agent_before_settle the turn ends on the assistant's own message, so Pi's context preview says it cannot continue
// until the extension adds its reminder; a test that hands the hook canContinue: true cannot see that.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager} from '@earendil-works/pi-coding-agent';
import {fauxAssistantMessage, fauxProvider, fauxToolCall} from '@earendil-works/pi-ai';
import {gatewayExtension, REMINDER} from '../dist/gateway-extension.js';

async function scripted(t, responses) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-settle-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const faux = fauxProvider({provider: 'faux', models: [{id: 'scripted'}]});
  faux.setResponses(responses);
  const runtime = await ModelRuntime.create({authPath: path.join(dir, 'auth.json'), refreshOnCreate: false});
  runtime.registerNativeProvider(faux.provider);
  const events = [], yielded = new Set();
  const host = {agentId: 'lead_x', role: 'lead', gatewayTools: new Set(['yield_work']), allowedTools: new Map(), activeRun: () => ({id: 'run_1'}),
    yielded: id => yielded.has(id), gateway: async () => ({}), event: (type, data) => events.push({type, ...data})};
  const settingsManager = SettingsManager.inMemory({});
  const agentDir = path.join(dir, 'pi-agent'); fs.mkdirSync(agentDir);
  const resourceLoader = new DefaultResourceLoader({cwd: dir, agentDir, settingsManager, systemPrompt: 'Test agent.', noContextFiles: true,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, extensionFactories: [{name: 'balsamic', factory: gatewayExtension(host)}]});
  await resourceLoader.reload();
  const yieldWork = {name: 'yield_work', label: 'yield_work', description: 'End the turn.', parameters: {type: 'object', properties: {}},
    execute: async () => { yielded.add('run_1'); return {content: [{type: 'text', text: '{"saved": true}'}], details: undefined}; }};
  const {session} = await createAgentSession({cwd: dir, modelRuntime: runtime, model: runtime.getModel('faux', 'scripted'), resourceLoader,
    customTools: [yieldWork], tools: ['yield_work'], sessionManager: SessionManager.inMemory(dir), settingsManager});
  const errors = [];
  await session.bindExtensions({mode: 'rpc', onError: error => errors.push(error), shutdownHandler: () => {}});
  t.after(() => session.dispose());
  return {session, faux, events, errors};
}

const lastUserText = context => {
  const last = context.messages.at(-1);
  return last.role === 'user' ? (typeof last.content === 'string' ? last.content : last.content.map(c => c.text || '').join('')) : null;
};

test('a turn that ends in prose is continued once in the same turn, with the reminder, and then yields', async t => {
  const asked = [];
  const {session, faux, events, errors} = await scripted(t, [
    fauxAssistantMessage('The plan: two runs at once.'),
    context => { asked.push(lastUserText(context)); return fauxAssistantMessage(fauxToolCall('yield_work', {})); },
    fauxAssistantMessage(''),
  ]);
  await session.prompt('Plan the resources.');
  assert.deepEqual(errors, []);
  assert.deepEqual(asked, [REMINDER], 'the second request ends with the reminder');
  assert.equal(events.filter(e => e.type === 'turn.continued').length, 1);
  assert.equal(faux.getPendingResponseCount(), 0);
});

test('a model that still does not yield is continued only once; a turn that yielded is not continued', async t => {
  const stubborn = await scripted(t, [fauxAssistantMessage('An answer.'), fauxAssistantMessage('The same answer.'), fauxAssistantMessage('Never asked.')]);
  await stubborn.session.prompt('Plan the resources.');
  assert.equal(stubborn.faux.state.callCount, 2);
  assert.equal(stubborn.events.filter(e => e.type === 'turn.continued').length, 1);
  const done = await scripted(t, [fauxAssistantMessage(fauxToolCall('yield_work', {})), fauxAssistantMessage(''), fauxAssistantMessage('Never asked.')]);
  await done.session.prompt('Plan the resources.');
  assert.equal(done.faux.state.callCount, 2);
  assert.equal(done.events.filter(e => e.type === 'turn.continued').length, 0);
});
