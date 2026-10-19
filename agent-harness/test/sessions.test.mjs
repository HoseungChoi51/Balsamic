import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {SessionManager} from '@earendil-works/pi-coding-agent';
import * as sessions from '../dist/sessions.js';
import {Supervisor} from '../dist/supervisor.js';

const usage = {input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0}};
const user = text => ({role: 'user', content: text, timestamp: Date.now()});
const assistant = text => ({role: 'assistant', content: [{type: 'text', text}], api: 'x', provider: 'p', model: 'm', usage, stopReason: 'stop', timestamp: Date.now()});
function manager(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-sessions-')); t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const cwd = path.join(dir, 'work'); fs.mkdirSync(cwd);
  return SessionManager.create(cwd, path.join(dir, 'sessions'));
}
test('branch re-enters a sibling leaf and the tree names both branches', t => {
  const sm = manager(t);
  sm.appendMessage(user('q1')); const a1 = sm.appendMessage(assistant('a1'));
  sm.appendMessage(user('q2')); const a2 = sm.appendMessage(assistant('a2'));
  // Fork at a1: a sibling branch with its own question.
  sessions.setLeaf(sm, a1);
  const u3 = sm.appendMessage(user('q3 on the fork')); const a3 = sm.appendMessage(assistant('a3'));
  assert.equal(sm.getEntry(u3).parentId, a1);
  // Back to the main leaf, append there, then re-enter the fork's leaf: each branch continues where it was.
  sessions.setLeaf(sm, a2); const u4 = sm.appendMessage(user('q4 on main'));
  const main = sessions.entries(sm).entries.map(e => e.preview);
  assert.deepEqual(main, ['q1', 'a1', 'q2', 'a2', 'q4 on main']);
  sessions.setLeaf(sm, a3);
  assert.deepEqual(sessions.entries(sm).entries.map(e => e.preview), ['q1', 'a1', 'q3 on the fork', 'a3']);
  const view = sessions.tree(sm);
  assert.equal(view.leaf_id, a3);
  const a1node = view.tree[0].children[0];
  assert.equal(a1node.children.length, 2, 'a1 has the main continuation and the fork as children');
  const ctx = sessions.context(sm, u4);
  assert.equal(ctx.messages, 5); assert.equal(sm.getLeafId(), a3, 'reading another leaf\'s context leaves the leaf where it was');
  assert.ok(ctx.bytes > 0 && ctx.items.every(item => !('thinking' in item)));
  assert.equal(sessions.entries(sm, {after: a1}).entries.map(e => e.preview).join(','), 'q3 on the fork,a3');
});
test('switching with a summary writes a branch summary under the destination', t => {
  const sm = manager(t);
  sm.appendMessage(user('q1')); const a1 = sm.appendMessage(assistant('a1'));
  sessions.setLeaf(sm, a1); sm.appendMessage(user('side question')); sm.appendMessage(assistant('side answer'));
  const moved = sessions.setLeaf(sm, a1, 'Side branch: asked a side question; nothing concluded.');
  assert.ok(moved.summary_entry_id);
  const entry = sm.getEntry(moved.summary_entry_id);
  assert.equal(entry.type, 'branch_summary'); assert.equal(entry.parentId, a1);
  const ctx = sessions.context(sm);
  assert.equal(ctx.summaries, 1);
  assert.throws(() => sessions.setLeaf(sm, 'missing'), /Unknown session entry/);
  const exported = sessions.exportBranch(sm, a1);
  assert.ok(fs.existsSync(exported.session_file));
});
test('the supervisor positions the leaf before the prompt and reports the turn\'s entries', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-sup-')); t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const sm = manager(t);
  sm.appendMessage(user('q1')); const a1 = sm.appendMessage(assistant('a1'));
  sm.appendMessage(user('q2')); const a2 = sm.appendMessage(assistant('a2'));
  const runtimes = [];
  const factory = async opts => {
    const runtime = {sessionFile: sm.getSessionFile(), sessionId: sm.getSessionId(), sessionManager: sm, messages: [], steers: [],
      subscribe(fn) { this.listener = fn; },
      prompt(text) { this.input = text; return new Promise(resolve => { this.finish = () => { sm.appendMessage(user(text)); sm.appendMessage(assistant('reply')); this.messages.push({role: 'assistant', stopReason: 'stop'}); resolve(); }; }); },
      async steer(text) { this.steers.push(text); }, async abort() { this.finish?.(); }, getLastAssistantText() { return 'reply'; }};
    runtimes.push(runtime); return runtime;
  };
  const gateway = async operation => operation === 'manifest' ? {instructions: 'x', tools: []} : {ok: true};
  const until = async predicate => { for (let i = 0; i < 400; i++) { if (predicate()) return; await new Promise(r => setTimeout(r, 5)); } throw Error('Timed out'); };
  const s = new Supervisor(directory, factory, gateway, 'auth');
  // A fork from a1 while the main leaf is a2.
  await s.submit('lead', {run_id: 'fork1', text: 'fork question', mode: 'follow_up', spec: {model: 'fake', role: 'lead'}, thread_id: 'thread_b', branch_from_entry_id: a1});
  await until(() => runtimes[0]?.finish);
  assert.equal(sm.getLeafId(), a1, 'the leaf was moved to the fork point before the prompt');
  // Steering from another thread does not reach this turn; it waits as its own run.
  const other = await s.submit('lead', {run_id: 'main2', text: 'main follow-up', mode: 'steer', spec: {model: 'fake', role: 'lead'}, thread_id: 'thread_main', leaf_entry_id: a2});
  assert.equal(other.status, 'queued'); assert.equal(runtimes[0].steers.length, 0);
  runtimes[0].finish();
  await until(() => s.view('lead').runs.fork1.status === 'completed');
  const fork = s.view('lead').runs.fork1;
  assert.equal(fork.result.entry_ids.parent, a1); assert.equal(sm.getEntry(fork.result.entry_ids.last).parentId !== null, true);
  assert.notEqual(fork.result.entry_ids.last, a2);
  // The queued main-thread run then continues from a2, not from the fork's leaf.
  await until(() => runtimes[0].input === '[Assignment main2]\nmain follow-up');
  assert.equal(sm.getBranch(sm.getLeafId()).some(e => e.id === a2), true);
  assert.equal(sm.getBranch(sm.getLeafId()).some(e => e.id === fork.result.entry_ids.last), false);
  runtimes[0].finish();
  await until(() => s.view('lead').runs.main2.status === 'completed');
  assert.deepEqual(Object.keys(s.session('lead', 'tree')), ['session_id', 'session_file', 'leaf_id', 'entries', 'tree']);
  assert.throws(() => s.setLeaf('lead', 'nope'), /Unknown session entry/);
});
