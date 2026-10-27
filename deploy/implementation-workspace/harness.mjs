#!/usr/bin/env node
/** The coding box's harness adapter (roadmap H2): how a workspace runs its coding harness.
 *
 * An adapter points the harness at the balsamic-workspace MCP server (H1), starts it, maps its event stream to the
 * bridge's event kinds (agent_start, agent_settled, message with its usage, tool) and stops it. The host names the
 * harness and its mode for each workspace (BALSAMIC_HARNESS, BALSAMIC_HARNESS_MODE), and start.sh reads them:
 *
 *   tui       the harness's own terminal UI in tmux, for the researcher to attach to. Pi's extension
 *             (agent-harness/extensions/implementation.ts) delivers the host's commands and reports its events.
 *   headless  runHeadless() in tmux, for agent-driven work (H7): each instruction the host sends is one run of the harness
 *             without a terminal (pi --mode json), whose stream this file maps to the same events.
 *
 * Only pi has an adapter (decision 8). Another harness would be one more entry of HARNESSES: opted into per workspace, on
 * the researcher's own credentials mounted read-only, with only its model endpoint added to the box's egress (H5). */
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {emit} from './balsamic-workspace.mjs';

const self = fileURLToPath(import.meta.url);
const bridge = () => process.env.GRATING_DEVELOPMENT_BRIDGE || '/bridge';
const sessions = () => process.env.BALSAMIC_HARNESS_SESSIONS || '/work/sessions';
const repository = () => process.env.BALSAMIC_WORKSPACE_REPO || (fs.existsSync('/work/repo') ? '/work/repo' : process.cwd());
export const MODES = ['tui', 'headless'];

/** The one refusal of a harness without an adapter; the host (agents/development_runtime.py) and start.sh say the same. */
export function refusal(name) {
  return `The coding harness "${name}" is not available: a coding workspace runs only pi. Another harness needs its own `
    + "adapter, opted into per workspace on the researcher's own credentials mounted read-only.";
}

// The assistant's text, as the extension cuts it.
function textOnly(content, limit = 8000) {
  return Array.isArray(content) ? content.filter(item => item?.type === 'text').map(item => String(item.text || '')).join('\n').slice(-limit) : '';
}

const pi = {
  name: 'pi',
  session: () => path.join(sessions(), 'pi.jsonl'),
  extension: () => process.env.BALSAMIC_PI_EXTENSION || '/opt/workspace/extension.ts',

  /** H1's MCP server in Pi's own configuration (~/.pi/agent/mcp.json), its other servers kept. Pi's extension already gives
   * it checkpoint and submit (campaign_checkpoint, campaign_submit), so those two twins are hidden: one tool per act. */
  configure(home = process.env.HOME) {
    const file = path.join(home, '.pi', 'agent', 'mcp.json');
    let config = {};
    if (fs.existsSync(file)) {
      try { config = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { config = null; }
      if (!config || typeof config !== 'object' || Array.isArray(config)) {
        // Someone's own edit: kept as it is, and Pi starts without the MCP server rather than without their file.
        console.error(`harness: ${file} is not a JSON object; left as it is, without the balsamic MCP server`);
        return file;
      }
    }
    config.mcpServers = {...(config.mcpServers || {}), balsamic: {command: process.execPath,
      args: [path.join(path.dirname(self), 'balsamic-workspace.mjs'), 'mcp'], exposure: 'direct',
      toolExposure: {checkpoint: 'hidden', submit: 'hidden'},
      description: "The workspace's bridge to Balsamic: ask a question, run the library's tests, read the evidence given"}};
    fs.mkdirSync(path.dirname(file), {recursive: true});
    const temporary = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(config, null, 2) + '\n', {mode: 0o600});
    fs.renameSync(temporary, file);
    return file;
  },

  /** What tmux runs: Pi's terminal UI with its extension, or the headless runner (which runs pi once per instruction). */
  command(mode, flags) {
    return mode === 'tui' ? ['pi', ...flags, '--session', pi.session(), '--extension', pi.extension()]
      : [process.execPath, self, 'run', '--harness', 'pi', '--', ...flags];
  },

  /** One headless run: the instruction on stdin, the JSON event stream on stdout. The extension gives only its tools. */
  invocation(flags) {
    return {command: 'pi', args: ['--mode', 'json', ...flags, '--session', pi.session(), '--extension', pi.extension()],
      env: {BALSAMIC_HARNESS_MODE: 'headless'}};
  },

  /** The bridge events one record of Pi's JSON stream gives (docs/json.md of the Pi package): the extension's own mapping
   * of the same session events, so both modes report alike (agent-harness/test/harness.test.mjs pins it). */
  map(record) {
    if (record?.type === 'agent_start' || record?.type === 'agent_settled') return [{type: record.type, payload: {}}];
    if (record?.type === 'message_end' && record.message?.role === 'assistant') {
      const msg = record.message;
      return [{type: 'message', payload: {role: 'assistant', text: textOnly(msg.content), usage: msg.usage || undefined,
        stop_reason: msg.stopReason || undefined}}];
    }
    if (record?.type === 'tool_execution_end') {
      return [{type: 'tool', payload: {tool: record.toolName, call_id: record.toolCallId, error: record.isError,
        output: textOnly(record.result?.content, 3000)}}];
    }
    return [];
  },

  /** Interrupts a headless run (a pause, a stop, the container stopping): SIGTERM, then SIGKILL after 5 s. */
  stop(child) {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
    child.once('exit', () => clearTimeout(timer));
  },
};

export const HARNESSES = {pi};

export function adapter(name) {
  if (!Object.hasOwn(HARNESSES, name)) throw new Error(refusal(name));
  return HARNESSES[name];
}

export function checkedMode(mode) {
  if (!MODES.includes(mode)) throw new Error(`The harness mode "${mode}" is not one of ${MODES.join(', ')}.`);
  return mode;
}

/** A JSONL stream's records, split on LF only (Pi's JSON strings may hold U+2028, which readline would split on). */
export async function* records(stream) {
  let pending = [];
  for await (const chunk of stream) {
    let start = 0, index;
    while ((index = chunk.indexOf(0x0a, start)) >= 0) {
      pending.push(chunk.subarray(start, index));
      const line = Buffer.concat(pending).toString('utf8').replace(/\r$/, '');
      pending = [];
      start = index + 1;
      if (!line.trim()) continue;
      try { yield JSON.parse(line); } catch { /* not a record: Pi keeps stdout for records, so nothing to map */ }
    }
    if (start < chunk.length) pending.push(chunk.subarray(start));
  }
  const rest = Buffer.concat(pending).toString('utf8').trim();
  if (rest) { try { yield JSON.parse(rest); } catch { /* a cut record */ } }
}

// The host's instruction as the extension puts it before the coding agent.
function prompt(command) {
  const prefix = command.actor === 'researcher' ? 'Developer instruction (takes precedence over conflicting lead-agent guidance):\n'
    : command.actor === 'lead' || command.actor === 'pi' ? 'Campaign lead agent instruction:\n' : 'Campaign system notice:\n';
  return prefix + command.message;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const stamp = () => new Date().toISOString().slice(11, 19);

/** The headless runner: delivers the host's commands as the extension does (an accepted receipt for each; pause and stop
 * interrupt the running instruction) and runs the harness once per message, steering first, its stream mapped to bridge
 * events and its receipts completed when it settles. Commands already run are kept in <sessions>/<harness>-delivered.json,
 * so a restarted box does not run them again. once: return when nothing is left to run (tests). */
export async function runHeadless(harness, flags, {once = false, log = line => console.log(`${stamp()} ${line}`)} = {}) {
  const incoming = path.join(bridge(), 'in', 'commands');
  const ledger = path.join(sessions(), `${harness.name}-delivered.json`);
  let delivered;
  try { delivered = new Set(JSON.parse(fs.readFileSync(ledger, 'utf8'))); } catch { delivered = new Set(); }
  const save = () => {
    fs.mkdirSync(path.dirname(ledger), {recursive: true});
    fs.writeFileSync(`${ledger}.tmp`, JSON.stringify([...delivered]));
    fs.renameSync(`${ledger}.tmp`, ledger);
  };
  const steering = [], followUps = [], queued = new Set();
  let current = null, stopping = false;

  const interrupt = () => {
    if (!current) return;
    current.interrupted = true;
    harness.stop(current.child);
  };
  const scan = () => {
    let files;
    try { files = fs.readdirSync(incoming).filter(name => name.endsWith('.json')).sort(); } catch { return; }
    for (const file of files) {
      let command;
      try { command = JSON.parse(fs.readFileSync(path.join(incoming, file), 'utf8')); } catch { continue; }
      if (!command?.id || delivered.has(command.id) || queued.has(command.id)) continue;
      if (command.operation === 'message') {
        queued.add(command.id);
        (command.mode === 'steer' ? steering : followUps).push({id: command.id, text: prompt(command)});
        log(`instruction ${command.id} from ${command.actor || 'the host'} queued`);
      } else {
        delivered.add(command.id);
        save();
        if (command.operation === 'pause' || command.operation === 'stop') {
          log(`${command.operation}: interrupting the running instruction`);
          interrupt();
        }
      }
      emit('receipt', {command_id: command.id, status: 'accepted'}, command.id);
    }
  };
  const finish = status => {
    for (const id of current.outstanding) emit('receipt', {command_id: id, status}, `${id}-${status}`);
    current.outstanding = [];
  };

  const run = async item => {
    delivered.add(item.id);
    save();
    queued.delete(item.id);
    const {command, args, env} = harness.invocation(flags);
    log(`running ${harness.name} on ${item.id}`);
    const child = spawn(command, args, {cwd: repository(), env: {...process.env, ...env}, stdio: ['pipe', 'pipe', 'pipe']});
    current = {child, outstanding: [item.id], settled: false, interrupted: false};
    let stderr = '';
    child.stderr.on('data', data => { stderr = (stderr + data).slice(-4000); process.stderr.write(data); });
    const exited = new Promise(resolve => {
      child.once('error', error => resolve({code: null, signal: null, error: String(error.message || error)}));
      child.once('close', (code, signal) => resolve({code, signal}));
    });
    child.stdin.on('error', () => { /* the harness exited before reading its instruction */ });
    child.stdin.end(item.text);
    for await (const record of records(child.stdout)) {
      for (const event of harness.map(record)) {
        if (event.type === 'agent_settled') { finish('completed'); current.settled = true; }
        if (event.type === 'message' && event.payload.text) log(`assistant: ${event.payload.text.replace(/\s+/g, ' ').slice(0, 200)}`);
        if (event.type === 'tool') log(`tool ${event.payload.tool}${event.payload.error ? ' failed' : ''}`);
        emit(event.type, event.payload);
      }
    }
    const result = await exited;
    if (!current.interrupted && (result.error || result.code || result.signal)) {
      const error = result.error || stderr.trim().slice(-2000) || `${harness.name} exited with ${result.signal || `code ${result.code}`}`;
      log(`${harness.name} failed: ${error.split('\n').at(-1)}`);
      emit('harness_error', {harness: harness.name, exit_code: result.code, signal: result.signal, error});
    }
    if (!current.settled) {
      // A run that ended without settling (interrupted, or failed): closed here, so the record does not stay running.
      finish(current.interrupted ? 'interrupted' : 'failed');
      emit('agent_settled', {interrupted: current.interrupted});
    }
    log(`${harness.name} settled${current.interrupted ? ' (interrupted)' : ''}`);
    current = null;
  };

  const shutdown = () => { stopping = true; interrupt(); };
  // Someone attached to the tmux pane to watch: Ctrl+C would end the runner, not the instruction.
  const ignore = () => log('Ctrl+C does not stop a headless workspace: pause or stop it from Balsamic');
  process.on('SIGTERM', shutdown);
  process.on('SIGHUP', shutdown);
  process.on('SIGINT', ignore);
  emit('ready', {session_id: harness.session(), harness: harness.name, mode: 'headless'});
  log(`headless ${harness.name}: waiting for instructions`);
  scan();
  const timer = setInterval(scan, 600);
  try {
    while (!stopping) {
      const item = steering.shift() || followUps.shift();
      if (item) await run(item);
      else if (once) break;
      else await sleep(600);
    }
  } finally {
    clearInterval(timer);
    process.off('SIGTERM', shutdown);
    process.off('SIGHUP', shutdown);
    process.off('SIGINT', ignore);
  }
}

// ---- CLI: what start.sh calls ----

const USAGE = `harness.mjs: the coding workspace's harness adapter

  harness.mjs configure --harness NAME                  point the harness at the balsamic-workspace MCP server
  harness.mjs command --harness NAME --mode MODE -- FLAGS...   print the command tmux runs (MODE: ${MODES.join(', ')})
  harness.mjs run --harness NAME -- FLAGS...            the headless runner

FLAGS are the harness's own (for pi: --provider P --model M [--thinking T]).`;

function options(argv) {
  const split = argv.indexOf('--');
  const own = split < 0 ? argv : argv.slice(0, split), flags = split < 0 ? [] : argv.slice(split + 1);
  const found = {};
  for (let index = 0; index < own.length; index += 2) {
    if (!own[index].startsWith('--') || own[index + 1] === undefined) throw new Error(`${own[index]}: expected --name VALUE`);
    found[own[index].slice(2)] = own[index + 1];
  }
  return {...found, flags};
}

const quote = value => /^[A-Za-z0-9_@%+=:,./-]+$/.test(value) ? value : `'${value.replace(/'/g, `'\\''`)}'`;

export async function main(argv = process.argv.slice(2)) {
  const [command, ...rest] = argv;
  if (!command || command === '--help' || command === 'help') { console.log(USAGE); return 0; }
  try {
    const given = options(rest);
    const harness = adapter(given.harness ?? 'pi');
    if (command === 'configure') { console.log(harness.configure()); return 0; }
    if (command === 'command') { console.log(harness.command(checkedMode(given.mode ?? 'tui'), given.flags).map(quote).join(' ')); return 0; }
    if (command === 'run') { await runHeadless(harness, given.flags, {once: process.env.BALSAMIC_HARNESS_ONCE === '1'}); return 0; }
    throw new Error(`Unknown command ${command}; the commands are configure, command, run`);
  } catch (error) {
    console.error(`harness ${command}: ${error.message || error}`);
    return 1;
  }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === self) {
  main().then(code => { process.exitCode = code; });
}
