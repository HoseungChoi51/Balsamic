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
        : body.operation === 'library.apply' ? { hypothesis_id: 'hypothesis_new', entry_id: body.payload.entry_id, match: { score: 6, reasons: [] } }
        : body.operation === 'intervention.batch' ? { intervention_id: 'intervention_1', items: body.payload.items.map((i: any) => ({ operation: i.operation, command_id: 'c', outcome: {} })) } : { ok: true };
      return json(route, { id: body.id, campaign_id: body.campaign_id, status: 'completed', actor: 'researcher', origin: body.origin || null, outcome, request: { operation: body.operation, payload: body.payload }, created_at: new Date().toISOString() });
    }
    if (method === 'POST' && path.endsWith('/ask')) { const body = route.request().postDataJSON(); recorded.commands.push({ ask: body }); return json(route, { id: 'annotation_q', anchor: body.anchor, kind: body.kind, question: body.question, tier: body.kind === 'define' ? 'lookup' : 'quick', status: 'answered', answer: { text: body.kind === 'define' ? 'efficiency: power in the target order over incident power' : 'About 0.6 is typical here.', answered_by: body.kind === 'define' ? 'glossary' : 'model' }, proposed_edit: null, created_at: '2026-10-19T09:00:00Z' }); }
    if (path.startsWith('/api/v1/setup')) {
      const stateOf = () => (recorded as any).setup || ((recorded as any).setup = JSON.parse(JSON.stringify(f.setupStart)));
      const s = stateOf();
      if (method === 'POST' && path === '/api/v1/setup') { const n = ((recorded as any).setups = ((recorded as any).setups || 0) + 1); (recorded as any).setup = { ...JSON.parse(JSON.stringify(f.setupStart)), id: 'setup_' + n }; return json(route, (recorded as any).setup, 201); }
      if (path.endsWith('/answer')) {
        const body = route.request().postDataJSON(); recorded.commands.push({ setup_answer: body });
        const choice = s.step.choices.find((c: any) => c.id === body.choice);
        s.transcript.push({ role: 'user', text: choice ? choice.label : body.text, field: s.step.field });
        if (s.step.field === 'name') { s.draft.name = body.text; s.draft.identity = 'deflector-v2'; s.step = f.setupSteps.objective; }
        else if (s.step.field === 'objective') { s.draft.objective = choice ? '' : body.text; s.step = f.setupSteps.problem; }
        else if (s.step.field === 'problem') { s.draft.problem_id = choice && choice.id !== 'formulate' ? choice.id : null; s.draft.decided = ['problem_id']; s.step = f.setupSteps.ready; Object.assign(s.draft, { compute_budget_seconds: 3600, llm_budget_usd: 5, delegated_trial_seconds: 300, autonomy: 'delegated', autopilot: { enabled: false } }); }
        else if (s.step.field === 'ready' && body.choice === 'create') { s.status = 'ready'; }
        s.transcript.push({ role: 'assistant', text: s.step.question, field: s.step.field, choices: s.step.choices });
        return json(route, s);
      }
      if (path.endsWith('/abandon')) { recorded.commands.push({ setup_abandon: true }); s.status = 'abandoned'; return json(route, s); }
      if (path.endsWith('/create')) { recorded.commands.push({ setup_create: true }); s.status = 'created'; s.campaign_id = 'deflector-v2'; return json(route, { campaign_id: 'deflector-v2', thread_id: 'thread_main_deflector-v2', setup: s }); }
      if (path.endsWith('/edit')) { const body = route.request().postDataJSON(); s.step = (f.setupSteps as any)[body.field]; s.transcript.push({ role: 'assistant', text: 'Sure. ' + s.step.question, field: body.field, choices: s.step.choices }); return json(route, s); }
      return json(route, s);
    }
    if (path.endsWith('/removal') && method === 'GET') return json(route, { campaign: { name: 'Demo campaign' }, blockers: [], options: [{ keep: 'nothing', kept_bytes: 0 }, { keep: 'summary', kept_bytes: null }, { keep: 'records', kept_bytes: 2500000 }] });
    if (path.endsWith('/removal') && method === 'POST') { recorded.commands.push({ removal: route.request().postDataJSON() }); return json(route, { removed: 'demo' }); }
    if (method === 'POST' && path === '/api/v1/providers/login') { recorded.commands.push({ login: true }); return json(route, { status: 'pending', url: 'https://auth.openai.com/device', user_code: 'ABCD-1234', expires_at: Date.now() + 600000 }); }
    if (method === 'PUT' && path === '/api/v1/model-tiers') { const body = route.request().postDataJSON(); recorded.commands.push({ tiers: body }); return json(route, { mode: 'dev', revision: 1, saved: true, assignable: ['lead', 'proposal_reviewer', 'formulator'], providers: {}, models: [], ...body, applied: { updated: ['lead_demo'], blocked: [] } }); }
    if (method === 'PUT' && path === '/api/v1/resources/slots') { const body = route.request().postDataJSON(); recorded.commands.push({ slots: body }); return json(route, { workers: body.workers, gpu_workers: body.gpu_workers, sizes: { cuda: body.gpu_workers, cpu: body.workers - body.gpu_workers }, launcher: { workers: 2, gpu_workers: 0 } }); }
    if (method === 'POST' && path.endsWith('/inbox/acknowledge')) { recorded.commands.push({ acknowledge: route.request().postDataJSON() }); return json(route, { unacknowledged: [] }); }
    if (method === 'POST' && path.endsWith('/seen')) { recorded.commands.push({ seen: path }); return json(route, { id: 'digest_1', seen_at: 'now' }); }
    if (method === 'POST' && path === '/api/v1/ui-events') { recorded.uiEvents.push(...route.request().postDataJSON().events); return json(route, { recorded: 1 }, 202); }
    const table: Record<string, unknown> = {
      '/api/v1/workspace': f.workspace, '/api/v1/campaigns': { campaigns: [f.campaignRow] }, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/summary`]: f.summary,
      '/api/v1/threads/thread_main_deflector-v2': { ...f.thread, id: 'thread_main_deflector-v2', campaign_id: 'deflector-v2' },
      [`/api/v1/threads/${f.THREAD_ID}`]: f.thread, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [f.thread, f.branch, f.parked] }, [`/api/v1/threads/${f.THREAD_ID}/messages`]: f.messages,
      ...Object.fromEntries(['discussion_moderator', 'experiment_operator', 'implementation_lead', 'resource_planner'].map(role => [`/api/v1/campaigns/${f.CAMPAIGN_ID}/desks/${role}`, { campaign_id: f.CAMPAIGN_ID, role, page: '#hypotheses', event_cursor: 10, agent: null, messages: role === 'discussion_moderator' ? f.deskMessages : [], truncated: false }])),
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/panels`]: { campaign_id: f.CAMPAIGN_ID, panels: [] }, '/api/v1/panels/panel_1': f.panel,
      [`/api/v1/threads/${f.AGENTS_THREAD_ID}`]: f.agentsThread, [`/api/v1/threads/${f.AGENTS_THREAD_ID}/messages`]: f.agentsMessages, [`/api/v1/threads/${f.AGENTS_THREAD_ID}/context`]: { ...f.context, thread_id: f.AGENTS_THREAD_ID },
      [`/api/v1/threads/${f.BRANCH_ID}`]: f.branch, [`/api/v1/threads/${f.BRANCH_ID}/messages`]: f.branchMessages, [`/api/v1/threads/${f.THREAD_ID}/context`]: f.context, [`/api/v1/threads/${f.BRANCH_ID}/context`]: { ...f.context, thread_id: f.BRANCH_ID },
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/problem-note`]: f.noteView, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/evolution`]: f.evolution, '/api/v1/hypotheses/hypothesis_b': f.hypothesisCard,
      '/api/v1/records/hypothesis_b/provenance': { record_id: 'hypothesis_b', trail: f.hypothesisCard.provenance }, '/api/v1/records/trial_1/provenance': { record_id: 'trial_1', trail: f.hypothesisCard.provenance.slice(1) }, [`/api/v1/problem-notes/note_${f.CAMPAIGN_ID}`]: f.noteView,
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/monitor`]: f.monitor, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/inbox`]: f.inbox, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/experiments`]: f.experiments,
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/hypotheses`]: f.hypotheses, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/files`]: f.files, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/agents`]: f.agents,
      '/api/v1/resources': { host: { cpu: { utilization_percent: 12, capacity_cores: 16 }, memory: { used_bytes: 8e9, total_bytes: 32e9, capacity_bytes: 32e9 }, gpu: { devices: { '0': { utilization_percent: 3, memory_used_bytes: 2 ** 30, memory_total_bytes: 24 * 2 ** 30 } } } }, workers: { running_count: 1, configured_limit: 2, queued_count: 1 }, admission: { level: 'balanced', set_by: 'researcher', updated_at: '2026-10-19T08:00:00Z', levels: [{ id: 'cautious', label: 'Cautious', summary: 'Uses at most 60% of memory.' }, { id: 'balanced', label: 'Balanced', summary: 'Uses at most 80% of memory.' }, { id: 'aggressive', label: 'Aggressive', summary: 'Uses at most 92% of memory.' }] } }, '/api/v1/llm-usage': { budget: { cap_usd: 5, agent_charged_usd: .42, implementation_committed_usd: 0 }, agents: {}, family: 'gpt', by_agent: [{ agent_id: 'lead_demo', role: 'lead', calls: 12, total_tokens: 48000, cost_usd: .4 }], by_model: [{ provider: 'centinels', model: 'gpt-6.1-sol', calls: 12, total_tokens: 48000, cost_usd: .4 }], series: [{ bucket: '2026-10-19T08:00:00Z', calls: 12, total_tokens: 48000, cost_usd: .4 }] },
      '/api/v1/model-tiers': { mode: 'dev', revision: 0, saved: false, assignable: ['lead', 'proposal_reviewer', 'formulator'], providers: { deepseek: { auth: 'api_key', billing: 'api' } },
        models: [{ provider: 'deepseek', id: 'deepseek-v4-pro', reasoning: true, thinking_levels: ['off', 'low', 'medium', 'high'], thinking_default: 'medium' }, { provider: 'deepseek', id: 'deepseek-v4-flash', reasoning: false }],
        tiers: [{ id: 'strong', label: 'Strong', model: { provider: 'deepseek', model: 'deepseek-v4-pro', effort: 'high' } }, { id: 'fast', label: 'Fast', model: { provider: 'deepseek', model: 'deepseek-v4-flash', effort: null } }], roles: { lead: 'strong', proposal_reviewer: 'strong', problem_importer: 'strong' } }, [`/api/v1/campaigns/${f.CAMPAIGN_ID}/agents/models`]: { mode: 'dev', models: [], providers: {} }, [`/api/campaigns/${f.CAMPAIGN_ID}/agent-log`]: { lines: ['tool call 1'], events: [] },
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/guidance`]: { state: { guidance: '## Research direction\n\nFind a better deflector', revision: 0, guidance_revision: 2 }, notes: [] }, '/api/v1/problems': { problems: [{ id: 'bounded_continuous', title: 'Bounded continuous' }] },
      [`/api/v1/campaigns/${f.CAMPAIGN_ID}/away-digest`]: f.digest,
      '/api/v1/experiments/trial_1': { trial: f.experiments.short[0], chain_trial_ids: ['trial_1'], validations: [], race: null }, '/api/v1/experiments/trial_1/metrics': [{ evaluations: 10, best_objective: .2 }, { evaluations: 80, best_objective: .41 }],
      '/api/v1/experiments/trial_1/logs': { text: 'worker started' }, '/api/v1/studies/study_1/race': { race: null }, [`/api/v1/implementations`]: { versions: [] },
      ...overrides,
    };
    if (path === '/api/v1/library') return json(route, url.searchParams.get('q') ? { ...f.library, entries: f.library.entries.filter(e => e.entry.strategy.title.toLowerCase().includes(url.searchParams.get('q')!.toLowerCase())) } : f.library);
    if (path === `/api/v1/campaigns/${f.CAMPAIGN_ID}/threads` && url.searchParams.get('q')) return json(route, f.threadSearch);
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
