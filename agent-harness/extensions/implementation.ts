/** One native Pi TUI owns this implementation session. The host only exchanges
 * immutable command and event files across the workspace boundary. */
import {StringEnum, Type} from '@earendil-works/pi-ai';
import {defineTool, type ExtensionAPI} from '@earendil-works/pi-coding-agent';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const root = process.env.GRATING_DEVELOPMENT_BRIDGE || '/bridge';
const incoming = path.join(root, 'in', 'commands');
const results = path.join(root, 'in', 'results');
const outgoing = path.join(root, 'out', 'events');
let sequence = 0;
let timer: ReturnType<typeof setInterval> | undefined;
let lastSession = '';
const delivered = new Set<string>();
const outstanding = new Set<string>();

function emit(type: string, payload: Record<string, unknown>, identity = crypto.randomUUID()): string {
  const name = `${Date.now().toString().padStart(13, '0')}_${process.pid}_${(sequence++).toString().padStart(8, '0')}_${identity}`;
  const temporary = path.join(outgoing, `.${name}.tmp`);
  fs.mkdirSync(outgoing, {recursive: true});
  fs.writeFileSync(temporary, JSON.stringify({type, payload, occurred_at: new Date().toISOString()}), {mode: 0o600});
  fs.renameSync(temporary, path.join(outgoing, `${name}.json`));
  return name;
}

function textOnly(content: unknown, limit = 8000): string {
  return Array.isArray(content) ? content.filter((item: any) => item?.type === 'text')
    .map((item: any) => String(item.text || '')).join('\n').slice(-limit) : '';
}

function scan(pi: ExtensionAPI): void {
  let files: string[];
  try { files = fs.readdirSync(incoming).filter(name => name.endsWith('.json')).sort(); }
  catch { return; }
  for (const file of files) {
    let command: any;
    try { command = JSON.parse(fs.readFileSync(path.join(incoming, file), 'utf8')); }
    catch { continue; }
    if (!command?.id || delivered.has(command.id)) continue;
    // The entry is durable before delivery. If Pi crashes in this narrow window,
    // the host shows an accepted but unsettled command for explicit reconciliation.
    delivered.add(command.id);
    pi.appendEntry('campaign_command', {id: command.id, actor: command.actor,
      operation: command.operation, received_at: new Date().toISOString()});
    if (command.operation === 'message') {
      const prefix = command.actor === 'researcher' ? 'Developer instruction (takes precedence over conflicting lead-agent guidance):\n'
        : command.actor === 'lead' || command.actor === 'pi' ? 'Campaign lead agent instruction:\n' : 'Campaign system notice:\n';
      pi.sendUserMessage(prefix + command.message, {deliverAs: command.mode === 'steer' ? 'steer' : 'followUp'});
      outstanding.add(command.id);
    } else if (command.operation === 'pause' || command.operation === 'stop') {
      pi.abort();
    }
    emit('receipt', {command_id: command.id, status: 'accepted'}, command.id);
  }
}

// Test counts as the researcher reads them: what passed, failed and was skipped in the latest run of the suite.
const Tests = () => Type.Object({passed: Type.Integer({minimum: 0}), failed: Type.Integer({minimum: 0}),
  skipped: Type.Optional(Type.Integer({minimum: 0}))});
const Items = (description: string) => Type.Optional(Type.Array(Type.String({maxLength: 300}), {maxItems: 20, description}));

const checkpoint = defineTool({
  name: 'campaign_checkpoint', label: 'Campaign checkpoint',
  description: 'Persist implementation progress, remaining work, a blocker or a question for the campaign lead agent and developer. '
    + 'The researcher follows your work by these: give your phase, what is done and what remains, the latest test counts, and '
    + 'your own estimate of the minutes left until you submit (shown to them as your estimate).',
  parameters: Type.Object({
    summary: Type.String({minLength: 1, maxLength: 10000}),
    next_steps: Type.Optional(Type.String({maxLength: 10000})),
    blocker: Type.Optional(Type.String({maxLength: 10000})),
    question: Type.Optional(Type.String({maxLength: 10000})),
    phase: Type.Optional(StringEnum(['orienting', 'implementing', 'testing', 'fixing', 'packaging', 'blocked', 'waiting'],
      {description: 'What you are doing now'})),
    done: Items('What is finished, briefly, one item each'),
    remaining: Items('What remains before you submit, one item each'),
    eta_minutes: Type.Optional(Type.Number({minimum: 0, maximum: 1440, description: 'Your estimate of the minutes left until you submit'})),
    tests: Type.Optional(Tests()),
  }),
  async execute(_id, params) {
    const id = emit('checkpoint', params as Record<string, unknown>);
    return {content: [{type: 'text' as const, text: `Checkpoint ${id} saved for the campaign.`}], details: {id}};
  },
});

// What you deliver, in your own judgement: the researcher reads this as the outcome of the work.
const Report = Type.Object({
  verdict: StringEnum(['ready', 'ready_with_limits', 'not_ready'], {description: 'ready: every method implemented, conformance passed, '
    + 'no failed test and no limitation; ready_with_limits: usable, with the limitations listed; not_ready: say what must happen next'}),
  summary: Type.String({minLength: 1, maxLength: 2000, description: 'Two or three sentences for the researcher'}),
  methods: Type.Array(Type.Object({
    method_id: Type.String({pattern: '^[a-z][a-z0-9_]{1,63}$', description: 'The method id the library registers'}),
    hypothesis_id: Type.Optional(Type.String({description: 'The proposal this method implements'})),
    state: StringEnum(['implemented', 'partial', 'not_implemented']),
    tests: Type.Optional(Tests()),
    conformance: StringEnum(['passed', 'failed', 'not_run'], {description: "Balsamic's contract check (tests/test_contract.py)"}),
    note: Type.Optional(Type.String({maxLength: 1000})),
  }), {minItems: 1, maxItems: 30}),
  tests: Type.Object({...Tests().properties, command: Type.Optional(Type.String({maxLength: 1000, description: 'The command that ran them'}))}),
  limitations: Type.Array(Type.String({maxLength: 1000}), {maxItems: 30}),
  next_actions: Type.Array(Type.Object({owner: StringEnum(['researcher', 'lead', 'validator']), action: Type.String({minLength: 1, maxLength: 1000})}),
    {maxItems: 20, description: 'What must happen for the methods to run, and who does it (Balsamic installs a delivered library itself)'}),
});

const submit = defineTool({
  name: 'campaign_submit', label: 'Submit implementation',
  description: 'Submit a committed source revision and implementation-manifest.json for independent campaign validation, with your '
    + 'delivery report. The host reads only files from this exact commit, and refuses a report that contradicts itself, naming the field.',
  parameters: Type.Object({
    commit: Type.String({pattern: '^[a-f0-9]{40}$'}),
    manifest_path: Type.Optional(Type.String({default: 'implementation-manifest.json'})),
    notes: Type.Optional(Type.String({maxLength: 10000})),
    report: Report,
  }),
  async execute(_id, params, signal) {
    const id = emit('submission', {commit: params.commit,
      manifest_path: params.manifest_path || 'implementation-manifest.json', notes: params.notes || '', report: params.report});
    const reply = path.join(results, `${id}.json`);
    for (let attempt = 0; attempt < 120; attempt++) {
      if (signal.aborted) throw new Error('Submission wait interrupted; the campaign receipt may already exist. Inspect status before retrying.');
      if (fs.existsSync(reply)) {
        const result = JSON.parse(fs.readFileSync(reply, 'utf8'));
        if (result.error) throw new Error(result.error);
        const ignored = result.ignored_fields?.length ? ` The manifest's unknown fields were ignored: ${result.ignored_fields.join(', ')}.` : '';
        return {content: [{type: 'text' as const, text: `Submitted ${result.submission_id}.${ignored} Independent validation has not been run yet.`}], details: result};
      }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    return {content: [{type: 'text' as const, text: `Submission queued as ${id}; campaign receipt is delayed. Check workspace status before retrying.`}], details: {id, status: 'pending'}};
  },
});

export default function(pi: ExtensionAPI) {
  pi.registerTool(checkpoint);
  pi.registerTool(submit);
  pi.registerCommand('campaign-status', {
    description: 'Show campaign bridge state and latest command receipt',
    handler: async (_args, ctx) => {
      scan(pi);
      ctx.ui.notify(`${delivered.size} campaign commands accepted in this session. Session: ${lastSession || 'starting'}`, 'info');
    },
  });
  pi.on('session_start', async (_event, ctx) => {
    lastSession = ctx.sessionManager.getSessionFile() || '';
    const entries = ctx.sessionManager.getEntries();
    for (const entry of entries) {
      if (entry.type === 'custom' && entry.customType === 'campaign_command') {
        const id = (entry.data as any)?.id;
        if (typeof id === 'string') delivered.add(id);
      }
    }
    emit('ready', {session_id: lastSession, tools: pi.getActiveTools()});
    scan(pi);
    if (timer) clearInterval(timer);
    timer = setInterval(() => scan(pi), 600);
  });
  pi.on('session_shutdown', async () => {
    if (timer) clearInterval(timer);
    timer = undefined;
  });
  pi.on('agent_start', async () => {emit('agent_start', {});});
  pi.on('agent_settled', async () => {
    for (const id of outstanding) emit('receipt', {command_id: id, status: 'completed'}, id + '-completed');
    outstanding.clear();
    emit('agent_settled', {});
  });
  pi.on('message_end', async event => {
    const msg: any = event.message;
    if (msg.role !== 'assistant') return;
    emit('message', {role: 'assistant', text: textOnly(msg.content), usage: msg.usage || undefined,
      stop_reason: msg.stopReason || undefined});
  });
  pi.on('tool_execution_end', async event => {
    emit('tool', {tool: event.toolName, call_id: event.toolCallId, error: event.isError,
      output: textOnly(event.result?.content, 3000)});
  });
}
