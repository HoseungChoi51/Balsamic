import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// A campaign whose team is started, with the experiment operator asked once on its page.
function fixture() {
  const campaign = { id: 'c1', version: 1, name: '2D deflector', autonomy: 'delegated', objective: 'Find a good design', compute_budget_seconds: 100, llm_budget_usd: 5 };
  return { workspace_id: 'w1', campaign, campaigns: [campaign], tasks: [], trials: [] as any[], hypotheses: [], decisions: [] as any[], messages: [] as any[], events: [], algorithms: [],
    manager_issues: [], manager_commands: [], research_runs: [], budget: {}, event_cursor: 1, report_writer_jobs: [] as any[],
    settings: { llm_configured: true, provider: { configured: true, enabled: true, provider: 'pi', model: 'deepseek-v4-pro', billing_mode: 'api' } },
    agent_runtime: { configuration: { enabled: true, status: 'running', control_revision: 1, request_open: false, provider: { configured: true } },
      agents: [{ id: 'lead', role: 'lead', status: 'waiting', model: 'deepseek-v4-pro', reasoning_effort: 'max', objective: 'Carry out requests', control_revision: 0 },
        { id: 'op', role: 'experiment_operator', parent_agent_id: 'lead', status: 'waiting', model: 'deepseek-v4-flash', objective: 'Run experiments', control_revision: 0, request_open: false }] as any[],
      questions: [] as any[], aliases: [] } };
}
async function mock(page: Page, state: any, live?: () => any) {
  const writes: any[] = [];
  await page.addInitScript(() => {
    const streams: EventTarget[] = [];
    (window as any).__updateWorkspace = () => streams.forEach(stream => stream.dispatchEvent(new MessageEvent('update')));
    (window as any).EventSource = class extends EventTarget { onopen: any; constructor() { super(); streams.push(this); setTimeout(() => this.onopen?.({}), 1); } close() {} };
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() === 'POST') { writes.push(request.postDataJSON()); return route.fulfill({ json: { status: 'completed', outcome: {} } }); }
    if (path.endsWith('/agents/live')) return route.fulfill({ json: live ? live() : { agents: [] } });
    if (path.endsWith('/discussions')) return route.fulfill({ json: { rounds: [], earlier_rounds: 0, proposals: [], unreviewed_proposals: 0 } });
    if (path === '/api/state') return route.fulfill({ json: state });
    return route.fulfill({ status: 404, json: { detail: 'Not in this mock' } });
  });
  return writes;
}
const menu = (page: Page) => page.getByRole('navigation', { name: 'Workspace navigation' });

test('the menu groups the pages and marks what runs; the addresses of merged pages lead to their new places', async ({ page }) => {
  const state = fixture();
  const trial = (id: string, status: string) => ({ id, campaign_id: 'c1', task_id: 'task', algorithm: 'flrl', status, seed: 0, max_steps: 10, wall_seconds: 60, priority: 0, created_at: '2026-10-14T06:00:00+00:00', progress: {} });
  state.trials = [trial('t1', 'running'), trial('t2', 'queued'), trial('t3', 'completed')];
  state.decisions = [{ id: 'd1', status: 'pending', title: 'Approve a longer run', options: [] }];
  state.agent_runtime.agents.push({ id: 'rev', role: 'proposal_reviewer', parent_agent_id: 'lead', status: 'running', model: 'm', objective: 'Review', control_revision: 0 });
  state.report_writer_jobs = [{ id: 'job', status: 'running', stage: 'draft' }];
  await mock(page, state);
  await page.goto('/#overview');
  const nav = menu(page);
  for (const group of ['Research', 'Evidence', 'Operations']) await expect(nav.getByText(group, { exact: true })).toBeVisible();
  for (const gone of ['Problem workbench', 'Agent discussions', 'Experiment drafts', 'Compare results', 'LLM usage', 'Models', 'Campaign memory', 'Research notebook', 'Problem importer'])
    await expect(nav.getByRole('button', { name: gone, exact: true })).toHaveCount(0);
  await expect(nav.getByRole('button')).toHaveCount(14);
  await expect(nav.getByRole('button', { name: /^Experiments/ })).toContainText('2');
  await expect(nav.getByRole('button', { name: /^Decision inbox/ })).toContainText('1');
  await expect(nav.getByRole('button', { name: /^Hypotheses/ })).toContainText('Agents are reviewing');
  await expect(nav.getByRole('button', { name: /^Reports/ })).toContainText('A report is being written');
  await expect(nav.getByRole('button', { name: /^Implementations/ })).not.toContainText('built');
  // The lead agent is in the chat, not above every page.
  for (const view of ['experiments', 'decisions', 'notebook', 'assets']) {
    await nav.getByRole('button', { name: new RegExp(`^${{ experiments: 'Experiments', decisions: 'Decision inbox', notebook: 'Notebook', assets: 'Research assets' }[view]}`) }).click();
    await expect(page.getByRole('region', { name: 'Agent team' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Campaign research progress' })).toHaveCount(0);
  }
  for (const [old, now] of [['memory', 'agents/guidance'], ['llm-usage', 'agents/usage'], ['models', 'agents/models'], ['drafts', 'experiments'],
    ['notebook/agent-log', 'agents/log'], ['discussions/round-2', 'hypotheses/rounds/round-2']]) {
    await page.goto(`/#${old}`);
    await expect(page).toHaveURL(new RegExp(`#${now.replaceAll('/', '\\/')}$`));
  }
  await expect(page.getByRole('tab', { name: 'Review rounds' })).toHaveAttribute('aria-selected', 'true');
  await page.goto('/#memory');
  await expect(page.getByRole('tab', { name: 'Guidance' })).toHaveAttribute('aria-selected', 'true');
  await expect(nav.getByRole('button', { name: 'Agents', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('the experiment operator is one line above its page, opens into its conversation, and takes a message there', async ({ page }) => {
  const state = fixture();
  state.messages = [{ id: 'm1', agent_id: 'lead', role: 'user', content: 'Plan the week.' },
    { id: 'm2', agent_id: 'op', role: 'user', content: 'Why did run 41 fail?' },
    { id: 'm3', agent_id: 'op', origin: 'pi', role: 'assistant', content: 'Run 41 ran out of GPU memory; I restarted it at harmonic order 9.', turn: 'request', disposition: 'complete' },
    { id: 'm4', agent_id: 'op', role: 'lead', content: 'Start two seeds of H5.' }];
  let working = false;
  const writes = await mock(page, state, () => ({ agents: working ? [{ agent_id: 'op', role: 'experiment_operator', status: 'running', phase: 'tool',
    steps: [{ label: 'Starting an experiment', done: false, failed: false }], thinking: '', text: '' }] : [] }));
  await page.goto('/#experiments');
  const bar = page.getByRole('region', { name: 'Experiment operator', exact: true });
  const line = bar.getByRole('button', { name: /Experiment operator/ });
  await expect(line).toContainText('ready');
  await expect(line).toContainText('Run 41 ran out of GPU memory');
  await expect(line).toHaveAttribute('aria-expanded', 'false');
  // Its conversation is its own: not in the lead's chat.
  const chat = page.getByRole('complementary', { name: 'Lead agent conversation' });
  await expect(chat).toContainText('Plan the week.');
  await expect(chat).not.toContainText('Why did run 41 fail?');
  await line.click();
  await expect(bar).toContainText('Why did run 41 fail?');
  await expect(bar.locator('.message').filter({ hasText: 'Start two seeds of H5.' })).toContainText('Lead agent');
  const box = bar.getByRole('textbox', { name: 'Message to the experiment operator' });
  await box.fill('Stop run 42.');
  await box.press('Enter');
  await expect(box).toHaveValue('');
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ operation: 'agent.message', payload: { page_agent: 'experiment_operator', message: 'Stop run 42.', mode: 'steer' } });
  // At work, the line shows its current step and the conversation its working note.
  working = true;
  state.agent_runtime.agents[1].status = 'running';
  await page.evaluate(() => (window as any).__updateWorkspace());
  await expect(line).toContainText('Starting an experiment');
  await expect(bar.getByLabel('Experiment operator at work')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('a page agent not yet asked says what it does; the Agents page lists the page agents with their pages', async ({ page }) => {
  const writes = await mock(page, fixture());
  await page.goto('/#hypotheses');
  const bar = page.getByRole('region', { name: 'Discussion moderator', exact: true });
  await expect(bar).toContainText('not asked yet');
  await expect(page.getByRole('tab', { name: 'Proposals' })).toHaveAttribute('aria-selected', 'true');
  await bar.getByRole('button', { name: /Discussion moderator/ }).click();
  await expect(bar).toContainText('It acts only when you or the lead agent ask.');
  await bar.getByRole('textbox', { name: 'Message to the discussion moderator' }).fill('Have H3 reviewed by two reviewers.');
  await bar.getByRole('button', { name: 'Send message to the discussion moderator' }).click();
  expect(writes[0]).toMatchObject({ operation: 'agent.message', payload: { page_agent: 'discussion_moderator', message: 'Have H3 reviewed by two reviewers.' } });
  await page.getByRole('tab', { name: 'Review rounds' }).click();
  await expect(page).toHaveURL(/#hypotheses\/rounds$/);
  await expect(bar).toBeVisible();
  await menu(page).getByRole('button', { name: 'Agents', exact: true }).click();
  const team = page.getByRole('region', { name: 'Agent team' });
  await expect(team).toContainText('Experiment operator');
  await team.getByRole('link', { name: 'Experiments' }).click();
  await expect(page.getByRole('region', { name: 'Experiment operator', exact: true })).toBeVisible();
});

test('a long question from the lead agent is shown short in the chat and can be set aside without an answer', async ({ page }) => {
  const state = fixture();
  state.agent_runtime.questions = [{ id: 'q1', agent_id: 'lead', status: 'pending', question: 'Which gate path do you want? ' + 'Option details. '.repeat(40), reason: 'The gate refuses long runs.' }];
  const writes = await mock(page, state);
  await page.goto('/#overview');
  const chat = page.getByRole('complementary', { name: 'Lead agent conversation' });
  const card = chat.locator('.agent-question');
  await expect(card).toContainText('Which gate path do you want?');
  await expect(card.locator('.agent-question-text')).toHaveClass(/clipped/);
  await card.getByRole('button', { name: 'Show the whole question' }).click();
  await expect(card.locator('.agent-question-text')).not.toHaveClass(/clipped/);
  await card.getByRole('button', { name: 'Dismiss' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ operation: 'agent.question_dismiss', payload: { question_id: 'q1' } });
});

test('a question the operator asked the lead shows in both conversations as an exchange between them', async ({ page }) => {
  const state = fixture();
  state.messages = [{ id: 'q', agent_id: 'lead', from_agent_id: 'op', role: 'agent', content: 'Why does H2 use a log-scaled step?' },
    { id: 'a', agent_id: 'lead', to_agent_id: 'op', origin: 'pi', role: 'assistant', turn: 'notice', disposition: 'complete', content: 'Its step spans three decades.' }];
  await mock(page, state);
  await page.goto('/#experiments');
  const chat = page.getByRole('complementary', { name: 'Lead agent conversation' });
  await expect(chat.locator('.message.between-agents')).toHaveCount(2);
  await expect(chat.locator('.message').first()).toContainText('Experiment operator, to the lead agent');
  await expect(chat.locator('.message').nth(1)).toContainText('Lead agent, to the experiment operator');
  const bar = page.getByRole('region', { name: 'Experiment operator', exact: true });
  await bar.getByRole('button', { name: /Experiment operator/ }).click();
  await expect(bar.locator('.message')).toHaveCount(2);
  await expect(bar.locator('.message').nth(1)).toContainText('Its step spans three decades.');
});
