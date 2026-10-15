import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// A campaign whose team is started. The lead's replies, the live view and the discussions are answered as the service answers them.
function fixture() {
  const campaign = { id: 'c1', version: 1, name: '2D deflector', autonomy: 'delegated', objective: 'Find a good design', compute_budget_seconds: 100, llm_budget_usd: 5 };
  return { workspace_id: 'w1', campaign, campaigns: [campaign], tasks: [], trials: [] as any[], hypotheses: [], decisions: [], messages: [] as any[], events: [], algorithms: [],
    manager_issues: [], manager_commands: [], research_runs: [], budget: {}, event_cursor: 1,
    settings: { llm_configured: true, provider: { configured: true, enabled: true, provider: 'pi', model: 'deepseek-v4-pro', billing_mode: 'api' } },
    agent_runtime: { configuration: { enabled: true, status: 'running', control_revision: 1, request_open: false, provider: { configured: true } },
      agents: [{ id: 'lead', role: 'lead', status: 'waiting', model: 'deepseek-v4-pro', reasoning_effort: 'max', objective: 'Carry out requests', control_revision: 0 }] as any[],
      questions: [], aliases: [] } };
}
type Extra = { live?: () => any; discussions?: any; records?: Record<string, any>; reports?: any };
async function mock(page: Page, state: any, extra: Extra = {}) {
  const writes: any[] = [];
  await page.addInitScript(() => {
    const streams: EventTarget[] = [];
    (window as any).__updateWorkspace = () => streams.forEach(stream => stream.dispatchEvent(new MessageEvent('update')));
    (window as any).EventSource = class extends EventTarget { onopen: any; constructor() { super(); streams.push(this); setTimeout(() => this.onopen?.({}), 1); } close() {} };
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() === 'POST') { writes.push(request.postDataJSON()); return route.fulfill({ json: { status: 'completed', outcome: {} } }); }
    if (path.endsWith('/agents/live')) return route.fulfill({ json: extra.live ? extra.live() : { agents: [] } });
    if (path === '/api/reports') return route.fulfill({ json: extra.reports || { reports: [], jobs: [] } });
    if (path.endsWith('/discussions')) return route.fulfill({ json: extra.discussions || { rounds: [], earlier_rounds: 0, proposals: [], unreviewed_proposals: 0 } });
    if (path.includes('/agents/records/')) return route.fulfill({ json: { data: extra.records?.[path.split('/').pop()!] || {} } });
    if (path.includes('/api/v1/commands/')) return route.fulfill({ status: 404, json: { detail: 'Not received' } });
    return route.fulfill({ json: state });
  });
  return writes;
}
const chat = (page: Page) => page.getByRole('complementary', { name: 'Lead agent conversation' });
const lead = (id: string, content: string, more: any = {}) => ({ id, agent_id: 'lead', origin: 'pi', role: 'assistant', content, turn: 'request', disposition: 'complete', ...more });
const you = (id: string, content: string) => ({ id, agent_id: 'lead', role: 'user', content });

test('Enter sends, Shift+Enter starts a new line, and confirming composed text does not send', async ({ page }) => {
  const writes = await mock(page, fixture());
  await page.goto('/');
  const box = chat(page).getByRole('textbox', { name: 'Message to the lead agent' });
  await expect(chat(page)).toContainText('Enter to send · Shift+Enter for a new line');
  await box.click();
  await page.keyboard.type('Run H6');
  await page.keyboard.press('Shift+Enter');
  await page.keyboard.type('with three seeds');
  await expect(box).toHaveValue('Run H6\nwith three seeds');
  // Enter that confirms an input-method composition (Korean, Japanese, Chinese) belongs to the text, not to sending.
  await box.evaluate(element => element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, isComposing: true })));
  expect(writes).toHaveLength(0);
  await page.keyboard.press('Enter');
  await expect(box).toHaveValue('');
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ operation: 'agent.message', payload: { message: 'Run H6\nwith three seeds', mode: 'steer' } });
  // An empty box sends nothing.
  await page.keyboard.press('Enter');
  expect(writes).toHaveLength(1);
});

test('while the lead works the chat shows its steps and its reasoning, and they go when the reply arrives', async ({ page }) => {
  const state = fixture();
  state.messages = [you('m1', 'Start H6 with three seeds.')];
  state.agent_runtime.agents[0].status = 'running'; state.agent_runtime.configuration.request_open = true;
  let polls = 0;
  await mock(page, state, { live: () => ({ agents: [{ agent_id: 'lead', role: 'lead', status: 'running', phase: 'tool', run_id: 'r1', started_at: new Date(Date.now() - 65000).toISOString(),
    steps: [{ label: "Reading the campaign's state", done: true, failed: false }, { label: 'Reading experiment …eb4321', done: true, failed: true },
      { label: `Starting an experiment: H6 seed ${Math.min(polls++, 1)}`, done: false, failed: false }],
    thinking: 'The profile covers this evaluator, so the three seeds can start at once.', text: '' }] }) });
  await page.goto('/');
  const note = chat(page).getByLabel('Lead agent at work');
  await expect(note.getByRole('status')).toHaveText('Lead agent is working');
  await expect(note.locator('li.done')).toHaveText("Reading the campaign's state");
  await expect(note.locator('li.failed')).toContainText('Reading experiment …eb4321 (failed)');
  // The view follows the turn: the next poll shows the next step.
  await expect(note.locator('li.current')).toHaveText('Starting an experiment: H6 seed 1');
  await expect(note).toContainText('The profile covers this evaluator');
  await expect(note.locator('time')).toHaveText(/^1:\d\d$/);
  // The turn ends: the reply is in the conversation and the temporary text is gone.
  state.agent_runtime.agents[0].status = 'waiting'; state.agent_runtime.configuration.request_open = false;
  state.messages = [...state.messages, lead('m2', 'Three runs of H6 are started.')];
  await page.evaluate(() => (window as any).__updateWorkspace());
  await expect(chat(page)).toContainText('Three runs of H6 are started.');
  await expect(note).toHaveCount(0);
  await expect(chat(page)).not.toContainText('The profile covers this evaluator');
});

test('a waiting lead says what it waits for and links the pages that show it', async ({ page }) => {
  const state = fixture();
  state.messages = [you('m1', 'Review the proposals and run the survivors.'), lead('m2', 'A reviewer is reading them.', { disposition: 'waiting' })];
  state.agent_runtime.configuration.request_open = true;
  state.agent_runtime.agents[0].disposition = { disposition: 'waiting', summary: 'Ten proposals are with the reviewer; two short runs are going.' };
  state.agent_runtime.agents.push({ id: 'rev', parent_agent_id: 'lead', role: 'proposal_reviewer', status: 'running', model: 'deepseek-v4-pro', objective: 'Review', control_revision: 0 });
  const trial = (id: string, status: string) => ({ id, campaign_id: 'c1', task_id: 'task', algorithm: 'flrl_lsf_es', status, seed: 0, max_steps: 100, wall_seconds: 60, priority: 0,
    created_at: '2026-10-13T16:00:00+00:00', progress: {} });
  state.trials = [trial('t1', 'running'), trial('t2', 'queued'), trial('t3', 'completed')];
  await mock(page, state, { live: () => ({ agents: [{ agent_id: 'rev', role: 'proposal_reviewer', status: 'running', phase: 'tool', steps: [{ label: 'Reading hypothesis …24ec63', done: false, failed: false }], thinking: '', text: '' }] }) });
  await page.goto('/#hypotheses');   // a page without charts: this mock serves no score journals
  const waiting = chat(page).getByLabel('What the lead agent is waiting for');
  await expect(waiting).toContainText('Ten proposals are with the reviewer');
  await expect(waiting).toContainText('1 agent at work');
  await expect(waiting).toContainText('Proposal reviewer: Reading hypothesis …24ec63');
  await expect(waiting).toContainText('2 experiments running');
  await waiting.getByRole('link', { name: 'Proposal reviewer' }).click();
  await expect(page.getByRole('heading', { name: 'What the agents said to each other.' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Hypotheses' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('tab', { name: 'Review rounds' })).toHaveAttribute('aria-selected', 'true');
});

test('progress notes the lead has superseded fold into one line; answers, and what you replied to, stay', async ({ page }) => {
  const state = fixture();
  const note = (id: string, content: string, more: any = {}) => lead(id, content, { turn: 'notice', disposition: 'waiting', ...more });
  state.messages = [you('m1', 'Run the finals.'), lead('m2', 'Nine runs are started.', { disposition: 'waiting' }),
    note('n1', 'Waiting on wave 1.'), note('n2', 'First result in: **H6 at 81.6%**.'), note('n3', 'The waiver was declined. I need your call on the path forward.'),
    you('m3', 'Use four runs at a time. How many runs will I see?'), note('n4', 'Nine: three proposals with three seeds each.'),
    note('n5', 'Waiting on wave 2.'), note('n6', 'All nine runs are complete.', { disposition: 'complete' }), note('n7', 'One run was restarted and is still going.')];
  await mock(page, state);
  await page.goto('/');
  const panel = chat(page);
  const folds = panel.locator('.progress-notes > button');
  await expect(folds).toHaveCount(2);
  await expect(folds.nth(0)).toContainText('2 progress notes');
  await expect(folds.nth(0)).toContainText('latest: First result in: H6 at 81.6%.');
  await expect(folds.nth(1)).toHaveText(/1 progress note\s*latest: Waiting on wave 2\./);
  await expect(panel).not.toContainText('Waiting on wave 1.');
  await expect(panel.locator('article.message').filter({ hasText: 'Waiting on wave 2.' })).toHaveCount(0);
  // What the researcher replied to stays, and so does the answer that came in a notice turn, the final report and the newest note.
  await expect(panel).toContainText('I need your call on the path forward.');
  await expect(panel).toContainText('Nine: three proposals with three seeds each.');
  await expect(panel).toContainText('All nine runs are complete.');
  await expect(panel).toContainText('One run was restarted and is still going.');
  await folds.nth(0).click();
  await expect(panel).toContainText('Waiting on wave 1.');
  await expect(panel.locator('.progress-notes strong').filter({ hasText: 'H6 at 81.6%' })).toBeVisible();
  await folds.nth(0).click();
  await expect(panel).not.toContainText('Waiting on wave 1.');
});

test('lines written beside earlier tool calls fold under the closing message of the turn, unless they are the substance', async ({ page }) => {
  const state = fixture();
  const answer = 'Final table: ' + 'N2 95.7%, H6 93.5%, H5 87.6%; '.repeat(20);
  state.messages = [you('m1', 'Write the report.'),
    lead('m2', 'The writer failed. I will restart it.\n\nThe writer restarted; follow it on [Reports](#reports).',
      { parts: ['The writer failed. I will restart it.', 'The writer restarted; follow it on [Reports](#reports).'], disposition: 'waiting' }),
    lead('m3', answer + '\n\nSaved.', { parts: [answer, 'Saved.'] })];
  await mock(page, state);
  await page.goto('/');
  const panel = chat(page);
  const folded = panel.locator('article.message').filter({ hasText: 'The writer restarted' });
  await expect(folded.getByRole('button')).toHaveText('▸ 1 earlier note from this turn');
  await expect(folded).not.toContainText('I will restart it.');
  await folded.getByRole('button').click();
  await expect(folded).toContainText('I will restart it.');
  // An earlier text much longer than the closing one is the answer: the message stays whole.
  const whole = panel.locator('article.message').filter({ hasText: 'Final table' });
  await expect(whole.getByRole('button')).toHaveCount(0);
  await expect(whole).toContainText('Saved.');
});

test('a link in a reply opens the page it names; where the chat covers the page, the chat closes', async ({ page }) => {
  const state = fixture();
  state.messages = [you('m1', 'Compare the finals.'), lead('m2', 'N2 leads. The curves are in [Compare results](#comparison), and the draft is [here](/reports/report_1).')];
  await mock(page, state);
  await page.goto('/');
  await expect(chat(page).getByRole('link', { name: 'here' })).toHaveAttribute('target', '_blank');
  await expect(chat(page).getByRole('link', { name: 'here' })).toHaveAttribute('href', '/reports/report_1');
  const link = chat(page).getByRole('link', { name: 'Compare results' });
  await expect(link).not.toHaveAttribute('target', '_blank');
  await link.click();
  await expect(page.locator('.breadcrumb strong')).toHaveText('Results');
  await expect(chat(page)).toBeVisible();
  // In a narrow window the chat lies over the page.
  await page.setViewportSize({ width: 1000, height: 800 });
  await page.goto('/#hypotheses');
  await expect(page.locator('.breadcrumb strong')).toHaveText('Hypotheses');
  await chat(page).getByRole('link', { name: 'Compare results' }).click();
  await expect(page.locator('.breadcrumb strong')).toHaveText('Results');
  await expect(chat(page)).toHaveCount(0);
});

test('the review rounds show each round concisely and open the full texts in place; an old link to the discussions page still leads there', async ({ page }) => {
  const state = fixture();
  const reviewer = { agent_id: 'rev1', role: 'proposal_reviewer', model: 'deepseek-v4-pro', status: 'completed', created_at: '2026-10-13T15:55:20+00:00',
    assignment: 'Act as the independent conceptual reviewer for the proposals that are about to run. ' + 'Check every parameter against the installed method. '.repeat(8),
    turns: [{ run_id: 'assignment_rev1', created_at: '2026-10-13T15:55:20+00:00', status: 'completed', kind: 'assignment', asked: null, delivered_while_working: false,
      summary: 'Reviewed both proposals: H5 test, H6 revise.', reply: '## Verdicts\n\nH5 can run as it is. **H6 leaves its schedule open.**', error: null,
      response: { run_id: 'pi_child_result_1', created_at: '2026-10-13T16:00:58+00:00', status: 'completed', summary: 'Created a revision of H6 that pins the schedule; re-review asked.', text: 'I revised H6 and sent it back to the reviewer.' } }],
    verdicts: [{ artifact_id: 'a1', created_at: '2026-10-13T15:59:56+00:00', hypothesis_id: 'h5', title: 'H5 — Gaussian ES', verdict: 'test', rationale: 'Complete and in bounds.', required_changes: [], suggested_tests: ['Two more seeds'] },
      { artifact_id: 'a2', created_at: '2026-10-13T15:59:57+00:00', hypothesis_id: 'h6', title: 'H6 — Autograd Adam', verdict: 'revise', rationale: 'The Adam schedule is left to defaults.', required_changes: ['Pin reference_epochs', 'Pin reference_samples'], suggested_tests: ['Matched budget against ES'] }],
    documents: [{ id: 'doc1', kind: 'review', title: 'Review of two proposals', created_at: '2026-10-13T16:00:41+00:00' }] };
  const second = { ...reviewer, agent_id: 'rev2', status: 'running', created_at: '2026-10-13T16:03:05+00:00', assignment: 'Re-review the revised H6.', turns: [], documents: [],
    verdicts: [] };
  await mock(page, state, { discussions: { earlier_rounds: 0, unreviewed_proposals: 4,
    rounds: [{ number: 2, started_at: second.created_at, trigger: { kind: 'continued', round: 1 }, active: true, assistants: [second], owner_documents: [] },
      { number: 1, started_at: reviewer.created_at, trigger: { kind: 'request', text: 'Good. Proceed to short runs with all proposals.' }, active: false, assistants: [reviewer],
        owner_documents: [{ id: 'doc2', kind: 'analysis', title: 'Consolidated picks', created_at: '2026-10-13T15:47:26+00:00' }] }],
    proposals: [{ id: 'h6b', title: 'H6 — Autograd Adam, schedule pinned', status: 'finalist', revisions: [{ id: 'h6', title: 'H6', status: 'archived', verdicts: [{ verdict: 'revise', round: 1 }] }, { id: 'h6b', title: 'H6b', status: 'finalist', verdicts: [{ verdict: 'test', round: 2 }] }] },
      { id: 'h5', title: 'H5 — Gaussian ES', status: 'proposed', revisions: [{ id: 'h5', title: 'H5', status: 'proposed', verdicts: [{ verdict: 'test', round: 1 }] }] }] },
    live: () => ({ agents: [{ agent_id: 'rev2', role: 'proposal_reviewer', status: 'running', phase: 'tool', steps: [{ label: 'Reading hypothesis …a1b2c3', done: false, failed: false }], thinking: '', text: '' }] }),
    records: { doc1: { content: { scope: 'short runs at (10,5)', per_strategy: ['H5 is ready', 'H6 needs pinning'] } } } });
  await page.goto('/#discussions');
  // How each proposal fared: its verdicts in order, across a revision.
  const fared = page.locator('.discussion-proposals');
  const h6 = fared.getByRole('row', { name: /H6 — Autograd Adam, schedule pinned/ });
  await expect(h6.locator('.verdict-chain')).toHaveText('reviserevisedtest');
  await expect(h6).toContainText('finalist');
  await expect(fared).toContainText('4 proposals have no review.');
  // Newest round first; the running assistant shows its current step.
  const rounds = page.locator('.discussion-round');
  await expect(rounds).toHaveCount(2);
  await expect(rounds.nth(0)).toContainText('Round 2 · Proposal reviewer');
  await expect(rounds.nth(0)).toContainText('at work: Reading hypothesis …a1b2c3');
  await expect(rounds.nth(0)).toContainText('the lead agent, after the answers of round 1');
  // A round in a few lines: the request, the assignment cut short, the assistant's own summary, the verdicts and what the lead did.
  const first = page.getByRole('region', { name: 'Round 1' });
  await expect(first).toContainText('Good. Proceed to short runs with all proposals.');
  await expect(first).toContainText('Reviewed both proposals: H5 test, H6 revise.');
  await expect(first).toContainText('Created a revision of H6 that pins the schedule; re-review asked.');
  await expect(first).toContainText('Asked for: Pin reference_epochs (+1 more)');
  await expect(first.getByText('H5 can run as it is.')).not.toBeVisible();
  // The full texts open in place.
  await first.getByText('Full reply').click();
  await expect(first.locator('strong').filter({ hasText: 'H6 leaves its schedule open.' })).toBeVisible();
  await first.getByRole('button', { name: /revise\s*H6 — Autograd Adam/ }).click();
  await expect(first).toContainText('The Adam schedule is left to defaults.');
  await expect(first).toContainText('Pin reference_samples');
  await expect(first).toContainText('Matched budget against ES');
  await first.getByRole('button', { name: 'Show the full assignment' }).click();
  await expect(first.getByRole('button', { name: 'Show less' })).toBeVisible();
  await first.getByRole('button', { name: /Saved review: Review of two proposals/ }).click();
  await expect(first).toContainText('short runs at (10,5)');
  await expect(first).toContainText('H6 needs pinning');
  await expect(first).toContainText('Consolidated picks');
  // A verdict in the table leads to its round.
  await h6.getByRole('link').first().click();
  await expect(page).toHaveURL(/#hypotheses\/rounds\/round-1$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('a campaign without assistants says so, and the page fits a phone', async ({ page }) => {
  await mock(page, fixture());
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#discussions');
  await expect(page.getByText('No discussion yet')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('a report asked for in the chat is followed on the Reports page: stages, model, cost and the current reasoning', async ({ page }) => {
  const state = fixture();
  const stage = (key: string, status = 'completed') => ({ key, purpose: key.split('_')[0], status, started_at: '2026-10-14T03:00:00+00:00', ...(status === 'running' ? {} : { finished_at: '2026-10-14T03:02:00+00:00' }) });
  const job = { id: 'report_writer_lead_1', status: 'running', stage: 'science', requested_by: 'lead', workflow: 'staged', notes: 'Requests and solves per run; leave out the unfinished run.',
    model: 'deepseek-v4-pro', reasoning_effort: 'max', billing_mode: 'api', usage: { calls: 5, api_cost_usd: 0.39, pending_reservation: { cost_usd_reserved: 0.27 } }, limits: { model_calls: 14 }, artifacts_url: '/api/report-writer/jobs/report_writer_lead_1/artifacts',
    stage_log: [stage('brief'), stage('investigate_1'), stage('investigate_2'), stage('select'), stage('draft'), stage('science', 'running')] };
  state.messages = [you('m1', 'Make a report of the final round.'), lead('m2', 'The report writer has started; follow it on [Reports](#reports).', { disposition: 'waiting' })];
  state.agent_runtime.configuration.request_open = true;
  (state as any).report_writer_jobs = [job];
  await mock(page, state, { reports: { reports: [], jobs: [job], writer: { model: 'deepseek-v4-pro', reasoning_effort: 'max', billing_mode: 'api', allowance_usd: 2.31 } },
    live: () => ({ agents: [], reports: [{ job_id: job.id, stage: 'science', phase: 'thinking', started_at: new Date().toISOString(), thinking: 'Does claim c1 follow from the receipts it cites?', text: '' }] }) });
  await page.goto('/#hypotheses');
  // The chat says what the lead waits for, and the link in its reply leads to the page.
  await expect(chat(page).getByLabel('What the lead agent is waiting for')).toContainText('A report is being written: checking scientific support');
  await chat(page).getByRole('link', { name: 'Reports' }).first().click();
  const card = page.getByRole('article', { name: 'Writing progress' });
  await expect(card.getByRole('heading')).toHaveText('Checking scientific support');
  await expect(card.getByRole('status')).toContainText('5 of at most 14 model calls · $0.120 so far, up to $0.270 held for the current call');
  await expect(card).toContainText('Started by the lead agent at your request · written by deepseek-v4-pro · max, billed to this campaign');
  await expect(card).toContainText('About: Requests and solves per run; leave out the unfinished run.');
  const stages = card.getByRole('list', { name: 'Writing stages' });
  await expect(stages.locator('li.done')).toHaveText(['Interpreting your notes', 'Investigating the evidence', 'Investigating the evidence (round 2)', 'Choosing the argument', 'Writing the article']);
  await expect(stages.locator('li.current')).toContainText('Checking scientific support');
  await expect(stages.locator('li.current')).toContainText('Does claim c1 follow from the receipts it cites?');
  await expect(stages.locator('li.coming')).toHaveText(['Reviewing usefulness and depth', 'Resolving the reviews', 'Checking the revised draft']);
  // The form names the model that writes and what it draws on.
  await expect(page.getByRole('form', { name: 'Write a report' })).toContainText("Written by the lead agent's model (deepseek-v4-pro · max), billed to this campaign's model budget ($2.31 left)");
});
