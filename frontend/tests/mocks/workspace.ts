/** A mocked backend for the Playwright specs: every /api/** route answered from fixtures, commands recorded, EventSource stubbed. */
import type { Page, Route } from '@playwright/test';
import * as f from './fixtures';

export interface Recorded { commands: Record<string, unknown>[]; uiEvents: Record<string, unknown>[] }

export async function mockWorkspace(page: Page, overrides: Partial<Record<string, unknown>> = {}): Promise<Recorded> {
  const recorded: Recorded = { commands: [], uiEvents: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.addInitScript(() => {
    // SSE is stubbed: specs push frames with window.__pushEvent / window.__pushChat.
    class FakeSource extends EventTarget {
      url: string; readyState = 1; onmessage: ((e: MessageEvent) => void) | null = null;
      constructor(url: string) { super(); this.url = url; (window as any).__sources = [...((window as any).__sources || []), this]; }
      close() { this.readyState = 2; }
    }
    (window as any).EventSource = FakeSource;
    (window as any).__pushEvent = (frame: unknown) => { for (const s of (window as any).__sources || []) if (s.readyState !== 2 && s.url.startsWith('/api/v1/events')) s.dispatchEvent(new MessageEvent('update', { data: JSON.stringify(frame) })); };
    (window as any).__pushChat = (event: unknown) => { for (const s of (window as any).__sources || []) if (s.readyState !== 2 && s.url.includes('/stream')) { const e = new MessageEvent('message', { data: JSON.stringify(event) }); s.onmessage?.(e); } };
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (!path.startsWith('/api/')) return route.continue();   // Vite serves src/api/*.ts through the same glob
    if (method === 'POST' && path === '/api/v1/commands') {
      const body = route.request().postDataJSON();
      recorded.commands.push(body);
      const outcome = body.operation === 'campaign.create' ? { campaign: { ...f.campaign, id: body.campaign_id, name: body.payload.name } }
        : body.operation === 'thread.fork' ? { thread_id: f.BRANCH_ID, thread: f.branch } : body.operation === 'note.ask' ? { annotation_id: 'annotation_new', tier: 'lead', status: 'open', run_id: 'pi_run_x' }
        : body.operation === 'research.generate' ? { run_id: 'pi_run_g', batch_id: 'ph_1', placeholders: ['ph_1_1', 'ph_1_2'] }
        : body.operation === 'intervention.batch' ? { intervention_id: 'intervention_1', items: body.payload.items.map((i: any) => ({ operation: i.operation, command_id: 'c', outcome: {} })) } : { ok: true };
      return json(route, { id: body.id, campaign_id: body.campaign_id, status: 'completed', actor: 'researcher', origin: body.origin || null, outcome, request: { operation: body.operation, payload: body.payload }, created_at: new Date().toISOString() });
    }
    if (method === 'POST' && path.endsWith('/ask')) { const body = route.request().postDataJSON(); recorded.commands.push({ ask: body }); return json(route, { id: 'annotation_q', anchor: body.anchor, kind: body.kind, question: body.question, tier: body.kind === 'define' ? 'lookup' : 'quick', status: 'answered', answer: { text: body.kind === 'define' ? 'efficiency: power in the target order over incident power' : 'About 0.6 is typical here.', answered_by: body.kind === 'define' ? 'glossary' : 'model' }, proposed_edit: null, created_at: '2026-10-19T09:00:00Z' }); }
    if (method === 'POST' && path === '/api/v1/ui-events') { recorded.uiEvents.push(...route.request().postDataJSON().events); return json(route, { recorded: 1 }, 202); }
    const table: Record<string, unknown> = {
      '/api/v1/workspace': f.workspace, '/api/v1/campaigns': { campaigns: [f.campaignRow] }, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/summary`]: f.summary,
      [`/api/v1/threads/${f.THREAD_ID}`]: f.thread, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [f.thread, f.branch, f.parked] }, [`/api/v1/threads/${f.THREAD_ID}/messages`]: f.messages,
      [`/api/v1/threads/${f.BRANCH_ID}`]: f.branch, [`/api/v1/threads/${f.BRANCH_ID}/messages`]: f.branchMessages, [`/api/v1/threads/${f.THREAD_ID}/context`]: f.context, [`/api/v1/threads/${f.BRANCH_ID}/context`]: { ...f.context, thread_id: f.BRANCH_ID },
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/problem-note`]: f.noteView, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/evolution`]: f.evolution, '/api/v1/hypotheses/hypothesis_b': f.hypothesisCard,
      '/api/v1/records/hypothesis_b/provenance': { record_id: 'hypothesis_b', trail: f.hypothesisCard.provenance }, '/api/v1/records/trial_1/provenance': { record_id: 'trial_1', trail: f.hypothesisCard.provenance.slice(1) }, [`/api/v1/problem-notes/note_${f.CAMPAIGN_ID}`]: f.noteView,
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/monitor`]: f.monitor, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/inbox`]: f.inbox, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/experiments`]: f.experiments,
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/hypotheses`]: f.hypotheses, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/files`]: f.files, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/agents`]: f.agents,
      '/api/v1/resources': { host: { cpu_percent: 12, memory_used_bytes: 8e9, memory_total_bytes: 32e9 }, running: 1, max_workers: 2, level: 'balanced' }, '/api/v1/llm-usage': { budget: { cap_usd: 5, agent_charged_usd: .42, implementation_committed_usd: 0 }, agents: {}, family: 'gpt' },
      '/api/v1/model-tiers': { mode: 'dev', tiers: [] }, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/agents/models`]: { mode: 'dev', models: [], providers: {} }, [`/api/campaigns/${f.CAMPAIGN_ID}/agent-log`]: { lines: ['tool call 1'], events: [] },
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/guidance`]: { state: { guidance: '## Research direction\n\nFind a better deflector', revision: 0, guidance_revision: 2 }, notes: [] }, '/api/v1/problems': { problems: [{ id: 'bounded_continuous', title: 'Bounded continuous' }] },
      '/api/v1/experiments/trial_1': { trial: f.experiments.short[0], chain_trial_ids: ['trial_1'], validations: [], race: null }, '/api/v1/experiments/trial_1/metrics': [{ evaluations: 10, best_objective: .2 }, { evaluations: 80, best_objective: .41 }],
      '/api/v1/experiments/trial_1/logs': { text: 'worker started' }, '/api/v1/studies/study_1/race': { race: null }, [`/api/v1/implementations`]: { versions: [] },
      ...overrides,
    };
    if (path in table) {
      const body = table[path];
      // Scoped reads answer unchanged for a cursor at or past theirs.
      const after = Number(url.searchParams.get('after') || 0);
      if (body && typeof body === 'object' && 'event_cursor' in (body as object) && after >= (body as { event_cursor: number }).event_cursor) return json(route, { unchanged: true, event_cursor: after });
      return json(route, body);
    }
    if (path.startsWith('/api/v1/threads/') && path.endsWith('/stream')) return route.abort();
    if (path.startsWith('/api/v1/events')) return route.abort();
    return json(route, { detail: `unmocked ${method} ${path}` }, 404);
  });
  return recorded;
}
