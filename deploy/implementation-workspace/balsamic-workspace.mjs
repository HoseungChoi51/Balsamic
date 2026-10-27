#!/usr/bin/env node
/** balsamic-workspace: the coding box's bridge to Balsamic, as a CLI and a stdio MCP server, for any harness.
 * It writes the same event files as the Pi extension (agent-harness/extensions/implementation.ts) into the same
 * file bridge, so the host side does not change; agent-harness/test/workspace-cli.test.mjs pins the parity. */
import {spawn} from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';

const VERSION = '1.0.0';
const bridge = () => process.env.GRATING_DEVELOPMENT_BRIDGE || '/bridge';
const repository = () => process.env.BALSAMIC_WORKSPACE_REPO || (fs.existsSync('/work/repo') ? '/work/repo' : process.cwd());
let sequence = 0;

export function emit(type, payload, identity = crypto.randomUUID()) {
  const outgoing = path.join(bridge(), 'out', 'events');
  const name = `${Date.now().toString().padStart(13, '0')}_${process.pid}_${(sequence++).toString().padStart(8, '0')}_${identity}`;
  const temporary = path.join(outgoing, `.${name}.tmp`);
  fs.mkdirSync(outgoing, {recursive: true});
  fs.writeFileSync(temporary, JSON.stringify({type, payload, occurred_at: new Date().toISOString()}), {mode: 0o600});
  fs.renameSync(temporary, path.join(outgoing, `${name}.json`));
  return name;
}

// The extension's parameter schemas, as JSON Schema (the extension's TypeBox objects serialize to exactly these).
const tests = () => ({type: 'object', required: ['passed', 'failed'], properties: {passed: {type: 'integer', minimum: 0},
  failed: {type: 'integer', minimum: 0}, skipped: {type: 'integer', minimum: 0}}});
const items = description => ({type: 'array', items: {type: 'string', maxLength: 300}, maxItems: 20, description});
const CHECKPOINT = {type: 'object', required: ['summary'], properties: {
  summary: {type: 'string', minLength: 1, maxLength: 10000},
  next_steps: {type: 'string', maxLength: 10000},
  blocker: {type: 'string', maxLength: 10000},
  question: {type: 'string', maxLength: 10000},
  phase: {type: 'string', enum: ['orienting', 'implementing', 'testing', 'fixing', 'packaging', 'blocked', 'waiting'], description: 'What you are doing now'},
  done: items('What is finished, briefly, one item each'),
  remaining: items('What remains before you submit, one item each'),
  eta_minutes: {type: 'number', minimum: 0, maximum: 1440, description: 'Your estimate of the minutes left until you submit'},
  tests: tests(),
}};
const REPORT = {type: 'object', required: ['verdict', 'summary', 'methods', 'tests', 'limitations', 'next_actions'], properties: {
  verdict: {type: 'string', enum: ['ready', 'ready_with_limits', 'not_ready'], description: 'ready: every method implemented, conformance passed, '
    + 'no failed test and no limitation; ready_with_limits: usable, with the limitations listed; not_ready: say what must happen next'},
  summary: {type: 'string', minLength: 1, maxLength: 2000, description: 'Two or three sentences for the researcher'},
  methods: {type: 'array', items: {type: 'object', required: ['method_id', 'state', 'conformance'], properties: {
    method_id: {type: 'string', pattern: '^[a-z][a-z0-9_]{1,63}$', description: 'The method id the library registers'},
    hypothesis_id: {type: 'string', description: 'The proposal this method implements'},
    state: {type: 'string', enum: ['implemented', 'partial', 'not_implemented']},
    tests: tests(),
    conformance: {type: 'string', enum: ['passed', 'failed', 'not_run'], description: "Balsamic's contract check (tests/test_contract.py)"},
    note: {type: 'string', maxLength: 1000},
  }}, minItems: 1, maxItems: 30},
  tests: {type: 'object', required: ['passed', 'failed'], properties: {...tests().properties,
    command: {type: 'string', maxLength: 1000, description: 'The command that ran them'}}},
  limitations: {type: 'array', items: {type: 'string', maxLength: 1000}, maxItems: 30},
  next_actions: {type: 'array', items: {type: 'object', required: ['owner', 'action'], properties: {
    owner: {type: 'string', enum: ['researcher', 'lead', 'validator']}, action: {type: 'string', minLength: 1, maxLength: 1000}}},
    maxItems: 20, description: 'What must happen for the methods to run, and who does it (Balsamic installs a delivered library itself)'},
}};
const SUBMIT = {type: 'object', required: ['commit', 'report'], properties: {
  commit: {type: 'string', pattern: '^[a-f0-9]{40}$'},
  manifest_path: {type: 'string', default: 'implementation-manifest.json'},
  notes: {type: 'string', maxLength: 10000},
  report: REPORT,
}};

export const TOOLS = [
  {name: 'checkpoint', description: 'Persist implementation progress, remaining work, a blocker or a question for the campaign lead agent and developer. '
    + 'The researcher follows your work by these: give your phase, what is done and what remains, the latest test counts, and '
    + 'your own estimate of the minutes left until you submit (shown to them as your estimate).', inputSchema: CHECKPOINT},
  {name: 'ask', description: 'Ask the campaign lead agent and the researcher a question. The answer arrives in this session as a message.',
    inputSchema: {type: 'object', required: ['question'], properties: {question: {type: 'string', minLength: 1, maxLength: 10000},
      summary: {type: 'string', minLength: 1, maxLength: 10000, description: 'Where the work stands, if not the question itself'}}}},
  {name: 'submit', description: 'Submit a committed source revision and implementation-manifest.json for independent campaign validation, with your '
    + 'delivery report. The host reads only files from this exact commit, and refuses a report that contradicts itself, naming the field.', inputSchema: SUBMIT},
  {name: 'check', description: "Run the library's tests, its tests/test_contract.py included, and return the counts for the delivery report.",
    inputSchema: {type: 'object', properties: {library: {type: 'string', description: 'The library directory, e.g. libraries/<name>; '
      + "by default the one implementation-manifest.json's files are in"}}}},
  {name: 'evidence', description: 'List the evidence this workspace was given (.campaign/evidence.json), or read one entry by its id.',
    inputSchema: {type: 'object', properties: {id: {type: 'string', description: 'The id of one entry'}}}},
];

/** The schema keywords the tools use, checked the way Pi checks the extension's parameters. */
export function validate(schema, value, at = 'arguments') {
  const type = Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value;
  if (schema.type === 'integer' ? !Number.isInteger(value) : schema.type && schema.type !== type)
    throw new Error(`${at}: expected ${schema.type}`);
  if (schema.enum && !schema.enum.includes(value)) throw new Error(`${at}: one of ${schema.enum.join(', ')}`);
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) throw new Error(`${at}: must not be empty`);
    if (schema.maxLength !== undefined && value.length > schema.maxLength) throw new Error(`${at}: at most ${schema.maxLength} characters`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) throw new Error(`${at}: must match ${schema.pattern}`);
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) throw new Error(`${at}: at least ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) throw new Error(`${at}: at most ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) throw new Error(`${at}: at least ${schema.minItems} items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) throw new Error(`${at}: at most ${schema.maxItems} items`);
    value.forEach((item, index) => validate(schema.items || {}, item, `${at}[${index}]`));
  }
  if (type === 'object') {
    for (const key of schema.required || []) if (value[key] === undefined) throw new Error(`${at}.${key}: required`);
    for (const [key, sub] of Object.entries(schema.properties || {})) if (value[key] !== undefined) validate(sub, value[key], `${at}.${key}`);
  }
  return value;
}

function evidenceEntries() {
  const file = path.join(repository(), '.campaign', 'evidence.json');
  if (!fs.existsSync(file)) return [];
  const entries = JSON.parse(fs.readFileSync(file, 'utf8'));
  return Array.isArray(entries) ? entries : [];
}

function libraryOf(given) {
  const root = repository();
  if (given) {
    const resolved = path.resolve(root, given);
    if (!fs.existsSync(resolved)) throw new Error(`${given} does not exist in ${root}`);
    return path.relative(root, resolved) || '.';
  }
  const manifest = path.join(root, 'implementation-manifest.json');
  const found = new Set();
  if (fs.existsSync(manifest)) {
    for (const file of JSON.parse(fs.readFileSync(manifest, 'utf8')).files || []) {
      const match = /^libraries\/[^/]+/.exec(String(file));
      if (match) found.add(match[0]);
    }
  }
  if (found.size !== 1) throw new Error('Name the library to check, e.g. libraries/<name>: '
    + (found.size ? `implementation-manifest.json names ${[...found].join(', ')}` : 'implementation-manifest.json names none'));
  return [...found][0];
}

/** Counts a pytest JUnit report: every test case, and the contract's (tests/test_contract.py) apart. */
export function counts(xml) {
  const all = {passed: 0, failed: 0, skipped: 0}, contract = {passed: 0, failed: 0, skipped: 0};
  for (const match of xml.matchAll(/<testcase\b([^>]*?)(?:\/>|>([\s\S]*?)<\/testcase>)/g)) {
    const body = match[2] || '';
    const outcome = /<(failure|error)\b/.test(body) ? 'failed' : /<skipped\b/.test(body) ? 'skipped' : 'passed';
    all[outcome]++;
    if (/classname="[^"]*\btest_contract\b/.test(match[1])) contract[outcome]++;
  }
  return {all, contract};
}

export async function runCheck({library} = {}, {timeoutSeconds = 1800} = {}) {
  const target = libraryOf(library);
  const python = process.env.BALSAMIC_WORKSPACE_PYTHON || 'python';
  const report = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'balsamic-check-')), 'junit.xml');
  const args = ['-m', 'pytest', '-q', '-p', 'no:cacheprovider', `--junitxml=${report}`, target];
  const code = await new Promise((resolve, reject) => {
    const child = spawn(python, args, {cwd: repository(), stdio: ['ignore', 'pipe', 'pipe']});
    let output = '';
    child.stdout.on('data', data => { output = (output + data).slice(-4000); });
    child.stderr.on('data', data => { output = (output + data).slice(-4000); });
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutSeconds * 1000);
    child.on('error', reject);
    child.on('close', status => { clearTimeout(timer); resolve({status, output}); });
  });
  const xml = fs.existsSync(report) ? fs.readFileSync(report, 'utf8') : '';
  fs.rmSync(path.dirname(report), {recursive: true, force: true});
  if (!xml) throw new Error(`pytest wrote no report (exit ${code.status}): ${code.output.slice(-1000)}`);
  const {all, contract} = counts(xml);
  const ran = contract.passed + contract.failed;
  return {library: target, tests: {...all, command: `${path.basename(python)} ${args.filter(a => !a.startsWith('--junitxml')).join(' ')}`},
    contract, conformance: contract.failed ? 'failed' : ran ? 'passed' : 'not_run', exit_code: code.status};
}

async function waitFor(id, signal) {
  const reply = path.join(bridge(), 'in', 'results', `${id}.json`);
  for (let attempt = 0; attempt < 120; attempt++) {
    if (signal?.aborted) throw new Error('Submission wait interrupted; the campaign receipt may already exist. Inspect status before retrying.');
    if (fs.existsSync(reply)) {
      const result = JSON.parse(fs.readFileSync(reply, 'utf8'));
      if (result.error) throw new Error(result.error);
      const ignored = result.ignored_fields?.length ? ` The manifest's unknown fields were ignored: ${result.ignored_fields.join(', ')}.` : '';
      return {text: `Submitted ${result.submission_id}.${ignored} Independent validation has not been run yet.`, details: result};
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  return {text: `Submission queued as ${id}; campaign receipt is delayed. Check workspace status before retrying.`, details: {id, status: 'pending'}};
}

/** One tool call, the same for the CLI and the MCP server: {text, details}. */
export async function call(name, args = {}, {signal} = {}) {
  const tool = TOOLS.find(item => item.name === name);
  if (!tool) throw new Error(`Unknown tool ${name}; the tools are ${TOOLS.map(item => item.name).join(', ')}`);
  validate(tool.inputSchema, args);
  if (name === 'checkpoint') {
    const id = emit('checkpoint', args);
    return {text: `Checkpoint ${id} saved for the campaign.`, details: {id}};
  }
  if (name === 'ask') {
    // A question travels as a checkpoint with a question, which the host turns into a pending question and a notice.
    const id = emit('checkpoint', {summary: args.summary || args.question, question: args.question});
    return {text: `Question ${id} sent to the campaign; the answer arrives in this session.`, details: {id}};
  }
  if (name === 'submit') {
    const id = emit('submission', {commit: args.commit,
      manifest_path: args.manifest_path || 'implementation-manifest.json', notes: args.notes || '', report: args.report});
    return waitFor(id, signal);
  }
  if (name === 'check') {
    const result = await runCheck(args);
    return {text: `${result.library}: ${result.tests.passed} passed, ${result.tests.failed} failed, ${result.tests.skipped} skipped; `
      + `conformance ${result.conformance.replace('_', ' ')}.`, details: result};
  }
  const entries = evidenceEntries();
  if (!args.id) {
    const listed = entries.map(entry => ({id: entry.data?.id, kind: entry.kind, title: entry.data?.title || entry.data?.name || ''}));
    return {text: listed.length ? listed.map(item => `${item.id} (${item.kind}) ${item.title}`.trim()).join('\n') : 'No evidence was given to this workspace.',
      details: {evidence: listed}};
  }
  const entry = entries.find(item => item.data?.id === args.id);
  if (!entry) throw new Error(`${args.id} is not evidence this workspace was given; list it with evidence and no id`);
  return {text: JSON.stringify(entry, null, 2), details: entry};
}

// ---- MCP over stdio: newline-delimited JSON-RPC 2.0 (tools only) ----

export function serve(input = process.stdin, output = process.stdout) {
  const send = message => output.write(JSON.stringify({jsonrpc: '2.0', ...message}) + '\n');
  const lines = readline.createInterface({input});
  const pending = new Set();
  lines.on('line', line => {
    if (!line.trim()) return;
    let request;
    try { request = JSON.parse(line); } catch { send({id: null, error: {code: -32700, message: 'Parse error'}}); return; }
    const {id, method, params} = request;
    const reply = id === undefined ? () => {} : send;   // notifications get no answer
    if (method === 'initialize') {
      reply({id, result: {protocolVersion: params?.protocolVersion || '2025-06-18', capabilities: {tools: {}},
        serverInfo: {name: 'balsamic-workspace', version: VERSION}}});
    } else if (method === 'ping') {
      reply({id, result: {}});
    } else if (method === 'tools/list') {
      reply({id, result: {tools: TOOLS}});
    } else if (method === 'tools/call') {
      const job = call(params?.name, params?.arguments || {})
        .then(result => reply({id, result: {content: [{type: 'text', text: result.text}], structuredContent: result.details}}))
        .catch(error => reply({id, result: {content: [{type: 'text', text: String(error.message || error)}], isError: true}}))
        .finally(() => pending.delete(job));
      pending.add(job);
    } else if (method?.startsWith('notifications/')) {
      // initialized, cancelled: nothing to do
    } else {
      reply({id, error: {code: -32601, message: `Method not found: ${method}`}});
    }
  });
  return new Promise(resolve => lines.on('close', () => Promise.allSettled([...pending]).then(resolve)));
}

// ---- CLI ----

const USAGE = `balsamic-workspace: the coding workspace's bridge to Balsamic

  balsamic-workspace checkpoint --summary TEXT [--phase PHASE] [--done TEXT]... [--remaining TEXT]...
                                [--eta MINUTES] [--tests PASSED/FAILED[/SKIPPED]] [--next-steps TEXT] [--blocker TEXT] [--question TEXT]
  balsamic-workspace ask QUESTION [--summary TEXT]
  balsamic-workspace submit COMMIT --report FILE [--manifest PATH] [--notes TEXT]
  balsamic-workspace check [LIBRARY]
  balsamic-workspace evidence [ID]
  balsamic-workspace mcp                     serve the five tools over stdio (MCP)

Any command also takes --json OBJECT (or --json - to read it from stdin) with the tool's arguments.
Results are printed as JSON.`;

function parse(argv) {
  const flags = {}, positional = [];
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (!arg.startsWith('--')) { positional.push(arg); continue; }
    const key = arg.slice(2), value = argv[++index];
    if (value === undefined) throw new Error(`${arg} needs a value`);
    (flags[key] ||= []).push(value);
  }
  return {flags, positional};
}

function testsFlag(value) {
  const parts = value.split('/').map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some(part => !Number.isInteger(part))) throw new Error('--tests is PASSED/FAILED[/SKIPPED]');
  return {passed: parts[0], failed: parts[1], ...(parts.length === 3 ? {skipped: parts[2]} : {})};
}

export function argumentsFor(command, argv, stdin = () => fs.readFileSync(0, 'utf8')) {
  const {flags, positional} = parse(argv);
  const one = key => flags[key]?.at(-1);
  if (flags.json) {
    const text = one('json') === '-' ? stdin() : one('json');
    return JSON.parse(text);
  }
  const args = {};
  if (command === 'checkpoint') {
    for (const [flag, key] of [['summary', 'summary'], ['next-steps', 'next_steps'], ['blocker', 'blocker'], ['question', 'question'], ['phase', 'phase']])
      if (one(flag) !== undefined) args[key] = one(flag);
    if (flags.done) args.done = flags.done;
    if (flags.remaining) args.remaining = flags.remaining;
    if (one('eta') !== undefined) args.eta_minutes = Number(one('eta'));
    if (one('tests') !== undefined) args.tests = testsFlag(one('tests'));
  } else if (command === 'ask') {
    args.question = positional.join(' ');
    if (one('summary') !== undefined) args.summary = one('summary');
  } else if (command === 'submit') {
    args.commit = positional[0];
    if (one('manifest') !== undefined) args.manifest_path = one('manifest');
    if (one('notes') !== undefined) args.notes = one('notes');
    if (one('report') !== undefined) args.report = JSON.parse(one('report') === '-' ? stdin() : fs.readFileSync(path.resolve(one('report')), 'utf8'));
  } else if (command === 'check') {
    if (positional[0]) args.library = positional[0];
  } else if (command === 'evidence') {
    if (positional[0]) args.id = positional[0];
  }
  return args;
}

export async function main(argv = process.argv.slice(2)) {
  const [command, ...rest] = argv;
  if (!command || command === '--help' || command === 'help') { console.log(USAGE); return 0; }
  if (command === 'mcp') { await serve(); return 0; }
  try {
    const result = await call(command, argumentsFor(command, rest));
    console.log(JSON.stringify({ok: true, message: result.text, ...result.details}, null, 2));
    return 0;
  } catch (error) {
    console.error(`balsamic-workspace ${command}: ${error.message || error}`);
    return 1;
  }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(code => { process.exitCode = code; });
}
