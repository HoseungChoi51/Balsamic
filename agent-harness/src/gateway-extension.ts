import type { ExtensionAPI, ExtensionFactory } from '@earendil-works/pi-coding-agent';
import { brief } from './brief.js';

/**
 * The Balsamic extension, loaded first in every session whose manifest hosts extensions (every role's since roadmap H8).
 *
 * Extensions may change how an agent thinks; what acts goes through the gateway or reports to it (harness plan, §2.5):
 * - tool_call: the gateway's tools pass; another tool runs only if the manifest allowlists it for the agent's role.
 * - tool_result: every other tool's result is receipted by the workspace (POST /api/internal/pi/external_receipt),
 *   as a gateway call is, and a result over the gateway's size limit is cut for the model.
 * - agent_before_settle: a run about to end without a saved yield_work gets one continuation in the same turn,
 *   instead of a separate notice turn from the controller (pi_continue_*), which stays the fallback.
 * - turn_end: the session's context usage goes to the agent's journal, for tuning compaction.
 */
export const TOOL_RESULT_BYTES = 256 * 1024;
export const RECEIPT_EXCERPT = 24 * 1024;
export const REMINDER = 'End the turn with yield_work: complete with the answer in report, or waiting if work you started is still running.';

export interface GatewayHost {
  agentId: string;
  role: string;
  gatewayTools: Set<string>;
  /** Extension tools this role may run, with the extension that provides each. */
  allowedTools: Map<string, string>;
  activeRun(): any | undefined;
  /** Whether the run saved a yield_work (the supervisor sees it in the tool wrapper). */
  yielded(runId: string): boolean;
  gateway(operation: string, data: any, signal?: AbortSignal): Promise<any>;
  event(type: string, data: Record<string, any>): void;
}

const name = (role: string) => 'the ' + role.replaceAll('_', ' ');

export function gatewayExtension(host: GatewayHost): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    const continued = new Set<string>();
    const blocked = new Set<string>();
    pi.on('tool_call', async event => {
      if (host.gatewayTools.has(event.toolName) || host.allowedTools.has(event.toolName)) return;
      blocked.add(event.toolCallId);
      host.event('extension.tool_blocked', {tool: event.toolName, call_id: event.toolCallId});
      return {block: true, reason: `${event.toolName} is not allowed for ${name(host.role)}: only the workspace's tools and the extension tools allowlisted for this role run in Balsamic.`};
    });
    pi.on('tool_result', async (event, ctx) => {
      if (host.gatewayTools.has(event.toolName) || blocked.has(event.toolCallId)) return;
      const run = host.activeRun();
      const text = event.content.filter((part: any) => part.type === 'text').map((part: any) => part.text).join('\n');
      const bytes = Buffer.byteLength(JSON.stringify(event.content));
      const annotations = pi.getAllTools().find(tool => tool.name === event.toolName)?.annotations ?? null;
      let receipt: any = null;
      try {
        if (!run) throw new Error('No active assignment');
        receipt = await host.gateway('external_receipt', {agent_id: host.agentId, run_id: run.id, call_id: event.toolCallId, tool: event.toolName,
          extension: host.allowedTools.get(event.toolName) ?? 'unknown', arguments: brief(event.input), result_excerpt: text.slice(0, RECEIPT_EXCERPT),
          result_bytes: bytes, is_error: event.isError, annotations}, ctx.signal);
      } catch (error: any) {
        host.event('extension.receipt_failed', {tool: event.toolName, call_id: event.toolCallId, error: String(error?.message || error).slice(0, 500)});
        // An unrecorded result is not evidence: the model is told so instead of being given it.
        return {content: [{type: 'text', text: `${event.toolName} ran, but the workspace could not record its result (${String(error?.message || error).slice(0, 300)}). Do not use or cite it.`}],
          structuredContent: undefined, isError: true};
      }
      if (bytes <= TOOL_RESULT_BYTES) return;
      return {content: [{type: 'text', text: text.slice(0, TOOL_RESULT_BYTES - 1024) + `\n[Cut: the result was ${bytes} bytes; a tool returns at most ${TOOL_RESULT_BYTES}. `
        + `Receipt ${receipt?.receipt_id} keeps its first ${RECEIPT_EXCERPT} bytes (evidence_read); ask for less.]`}], structuredContent: undefined};
    });
    pi.on('agent_before_settle', event => {
      const run = host.activeRun();
      // Not event.context.canContinue: it previews the context before the reminder, which ends on the assistant's own
      // message, so it is false exactly when a turn ended in prose. Pi checks again with the reminder appended.
      if (!run || event.outcome !== 'completed') return;
      if (host.yielded(run.id) || continued.has(run.id)) return;
      continued.add(run.id);
      host.event('turn.continued', {run_id: run.id, reason: 'The run was ending without yield_work'});
      return {continue: true, entries: [...event.entries, {type: 'custom_message', customType: 'balsamic.yield_work', content: REMINDER, display: false}]};
    });
    pi.on('turn_end', (_event, ctx) => {
      const usage = ctx.getContextUsage();
      if (usage) host.event('context.usage', {tokens: usage.tokens, context_window: usage.contextWindow, percent: usage.percent});
    });
  };
}
