import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// Two rounds run by the moderator: a specialist proposes, a reviewer judges, a second round re-reviews the revision.
const at = (minute: number) => `2026-10-14T06:${String(minute).padStart(2, '0')}:00+00:00`;
const turn = (id: string, summary: string, reply: string, response?: any) => ({ run_id: id, created_at: at(5), status: 'completed', kind: 'assignment', asked: null,
  delivered_while_working: false, summary, reply, error: null, response: response || null });
const specialist = { agent_id: 'spec', role: 'methodology_specialist', model: 'deepseek-v4-pro', status: 'completed', created_at: at(1), assignment: 'Propose two strategies for the deflector.',
  turns: [turn('t-spec', 'Proposed H1 and H2.', 'H1: Gaussian ES. H2: Autograd Adam on the relaxed score.',
    { run_id: 'r-spec', created_at: at(6), status: 'completed', summary: 'Recorded H1 and H2; asked for a review.', text: 'I recorded both proposals.' })], verdicts: [], documents: [] };
const reviewer = { agent_id: 'rev', role: 'proposal_reviewer', model: 'deepseek-v4-pro', status: 'completed', created_at: at(7), assignment: 'Review H1 and H2.',
  turns: [turn('t-rev', 'H1 test, H2 revise.', '## Verdicts\n\nH1 can run as it is. **H2 leaves its schedule open.**')],
  verdicts: [{ artifact_id: 'v1', created_at: at(9), hypothesis_id: 'h1', title: 'H1 — Gaussian ES', verdict: 'test', rationale: 'Complete.', required_changes: [], suggested_tests: ['Two seeds'] },
    { artifact_id: 'v2', created_at: at(9), hypothesis_id: 'h2', title: 'H2 — Autograd Adam', verdict: 'revise', rationale: 'Schedule open.', required_changes: ['Pin the schedule'], suggested_tests: ['Matched budget'] }],
  documents: [] };
const second = { agent_id: 'rev2', role: 'proposal_reviewer', model: 'deepseek-v4-pro', status: 'running', created_at: at(12), assignment: 'Re-review H2b.', turns: [], verdicts: [], documents: [] };
const discussions = { earlier_rounds: 0, unreviewed_proposals: 1,
  rounds: [{ number: 2, started_at: at(12), owner: 'discussion_moderator', trigger: { kind: 'continued', round: 1 }, active: true, assistants: [second], owner_documents: [] },
    { number: 1, started_at: at(1), owner: 'discussion_moderator', trigger: { kind: 'request', text: 'Propose two strategies and have them reviewed.' }, active: false,
      assistants: [specialist, reviewer], owner_documents: [] }],
  proposals: [
    { id: 'h1', title: 'H1 — Gaussian ES', status: 'finalist', reviewed: true, revisions: [{ id: 'h1', title: 'H1 — Gaussian ES', status: 'finalist', parent_ids: [], created_in_round: 1, created_by: 'discussion_moderator', verdicts: [{ verdict: 'test', round: 1 }] }] },
    { id: 'h2b', title: 'H2b — Autograd Adam, schedule pinned', status: 'proposed', reviewed: true, revisions: [
      { id: 'h2', title: 'H2 — Autograd Adam', status: 'archived', parent_ids: [], created_in_round: 1, created_by: 'discussion_moderator', verdicts: [{ verdict: 'revise', round: 1 }] },
      { id: 'h2b', title: 'H2b — Autograd Adam, schedule pinned', status: 'proposed', parent_ids: ['h2'], created_in_round: 1, created_by: 'discussion_moderator', verdicts: [] }] },
    { id: 'h3', title: 'H3 — written by hand', status: 'proposed', reviewed: false, revisions: [{ id: 'h3', title: 'H3 — written by hand', status: 'proposed', parent_ids: [], created_in_round: null, created_by: null, verdicts: [] }] }] };

async function mock(page: Page) {
  const campaign = { id: 'c1', version: 1, name: '2D deflector', objective: 'Find a design', compute_budget_seconds: 100 };
  const state = { workspace_id: 'w1', campaign, campaigns: [campaign], tasks: [], trials: [], hypotheses: [], decisions: [], messages: [], events: [], algorithms: [], research_runs: [], budget: {}, event_cursor: 1,
    settings: { llm_configured: true }, agent_runtime: { configuration: { enabled: true, status: 'running', control_revision: 1, provider: { configured: true } },
      agents: [{ id: 'lead', role: 'lead', status: 'waiting', model: 'm', objective: 'x', control_revision: 0 }, { id: 'rev2', role: 'proposal_reviewer', parent_agent_id: 'mod', status: 'running', model: 'm', objective: 'x', control_revision: 0 }],
      questions: [], aliases: [] } };
  await page.addInitScript(() => { (window as any).EventSource = class extends EventTarget { close() {} }; });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/state') return route.fulfill({ json: state });
    if (path.endsWith('/discussions')) return route.fulfill({ json: discussions });
    if (path.endsWith('/agents/live')) return route.fulfill({ json: { agents: [{ agent_id: 'rev2', role: 'proposal_reviewer', status: 'running', phase: 'tool',
      steps: [{ label: 'Reading hypothesis …h2b', done: false, failed: false }], thinking: '', text: '' }], reports: [] } });
    return route.fulfill({ status: 404, json: { detail: 'Not in this mock' } });
  });
}
const card = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"] .graph-card`);

test('the rounds are one graph: who asked whom, the verdicts on proposals, and how proposals were made and revised', async ({ page }) => {
  await mock(page);
  await page.goto('/#hypotheses/rounds/graph');
  await expect(page.getByRole('tab', { name: 'Graph' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.react-flow__node')).toHaveCount(11);
  await expect(page.locator('.react-flow__edge')).toHaveCount(12);
  await expect(page.locator('.react-flow__edge-text').filter({ hasText: /^test$/ })).toHaveCount(1);
  await expect(page.locator('.react-flow__edge-text').filter({ hasText: /^revise$/ })).toHaveCount(1);
  await expect(page.locator('.react-flow__edge-text').filter({ hasText: /^revised$/ })).toHaveCount(1);
  await expect(card(page, 'request-1')).toContainText('Propose two strategies and have them reviewed.');
  await expect(card(page, 'round-1')).toContainText('Round 1 · discussion moderator');
  // The re-reviewer is at work: it pulses and shows its step.
  await expect(card(page, 'assistant-rev2')).toHaveClass(/active/);
  await expect(card(page, 'assistant-rev2')).toContainText('Reading hypothesis …h2b');
  // A card opens its full text beside the graph.
  await card(page, 'assistant-rev').click();
  const detail = page.getByRole('complementary', { name: 'Selected part of the discussion' });
  await expect(detail).toContainText('H1 test, H2 revise.');
  await detail.getByText('Full reply').click();
  await expect(detail.locator('strong').filter({ hasText: 'H2 leaves its schedule open.' })).toBeVisible();
  await expect(detail.getByRole('list', { name: 'Verdicts' })).toContainText('H1 — Gaussian ES');
  // It opens on the newest round; the fit button shows the whole graph.
  await page.getByRole('button', { name: 'Fit View' }).click();
  await card(page, 'proposal-h3').click();
  await expect(detail).toContainText('put in by hand');
  await card(page, 'proposal-h2b').click();
  await expect(detail).toContainText('proposed by the discussion moderator in round 1');
  await detail.getByRole('button', { name: 'Close the details' }).click();
  await expect(detail).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('following one proposal dims the rest; the list and the graph keep their own addresses', async ({ page }) => {
  await mock(page);
  await page.goto('/#hypotheses/rounds/graph');
  await page.getByLabel('Follow one proposal').selectOption('h2b');
  for (const id of ['proposal-h2', 'proposal-h2b', 'assistant-rev', 'round-1', 'request-1']) await expect(card(page, id)).not.toHaveClass(/dimmed/);
  for (const id of ['proposal-h1', 'proposal-h3', 'assistant-spec', 'round-2']) await expect(card(page, id)).toHaveClass(/dimmed/);
  await page.getByRole('tab', { name: 'List' }).click();
  await expect(page).toHaveURL(/#hypotheses\/rounds$/);
  await expect(page.getByRole('region', { name: 'Round 1' })).toBeVisible();
  await expect(page.locator('.discussion-proposals tbody tr')).toHaveCount(2);   // the table keeps to reviewed proposals
  await page.getByRole('tab', { name: 'Graph' }).click();
  await expect(page).toHaveURL(/#hypotheses\/rounds\/graph$/);
  await expect(page.locator('.react-flow__node')).toHaveCount(11);
});

test('on a phone the graph fills the width and a card opens over it', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto('/#hypotheses/rounds/graph');
  await expect(page.locator('.react-flow__node')).toHaveCount(11);
  await page.getByRole('button', { name: 'Fit View' }).click();
  await card(page, 'round-1').click();
  const detail = page.getByRole('complementary', { name: 'Selected part of the discussion' });
  await expect(detail).toContainText('Run by the discussion moderator');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
