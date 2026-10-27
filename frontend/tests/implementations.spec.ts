import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;
const WID = 'development_bakery';
export const workspace = {
  id: WID, campaign_id: CAMPAIGN_ID, title: 'Adjacent swap search', hypothesis_id: 'hypothesis_a', hypothesis_ids: ['hypothesis_a', 'hypothesis_b'],
  status: 'running', desired_status: 'running', created_at: '2026-10-27T03:10:32Z', started_at: '2026-10-27T03:10:40Z',
  last_activity_at: new Date(Date.now() - 60_000).toISOString(), cpu_budget_seconds: 300, usage: { container_cpu_seconds: 120 },
  opened_by: { actor: 'lead', role: 'implementation_lead' }, ide_url: '/implementation-workspaces/development_bakery/ide/?folder=/work/repo',
  checkpoints: [{ at: '2026-10-27T03:19:38Z', summary: 'Implemented the library; **32 tests** pass.', next_steps: 'Commit and submit', blocker: 'The evaluator is not commissioned' }],
  last_error_at: '2026-10-27T03:21:40Z', questions: [], submissions: [],
};
const entries = [
  { at: '2026-10-27T03:22:04Z', kind: 'delivery', title: 'Delivered commit 2a3eb08', detail: '32 passed', tone: 'ok', ref: 'development_submission_1', items: [] },
  { at: '2026-10-27T03:21:40Z', kind: 'refused', title: 'Refused: 8 validation errors for SubmissionManifest', detail: 'library_path: extra', tone: 'warn', ref: null, items: [] },
  { at: '2026-10-27T03:20:00Z', kind: 'work', title: 'Worked 12 min · 74 tool calls · 1 failed', detail: 'Both methods pass.', tone: '', ref: null, items: ['bash: FAILED test_replay (exit 1)'] },
];
const opened = { at: '2026-10-27T03:10:32Z', kind: 'opened', title: 'Opened by the implementation lead under your go-ahead', detail: 'Approved plan: build four methods', tone: 'info', ref: 'approval_1', items: [] };

test('a coding workspace is a card with what it is for, how it is going and its history, newest first', async ({ page }) => {
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [workspace] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/timeline**`, route => {
    const before = new URL(route.request().url()).searchParams.get('before');
    return route.fulfill({ json: before ? { entries: [opened], next_before: null } : { entries, next_before: entries[2].at } });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.getByTestId('workspace-card');
  await expect(card).toHaveAttribute('data-status', 'running');
  await expect(card).toContainText('working');
  await expect(card.locator('a.chip')).toHaveCount(2);   // the library serves both proposals
  await expect(card).toContainText('by the implementation lead');
  await expect(card).toContainText('120 of 300 s');
  await expect(card.getByTestId('workspace-checkpoint')).toContainText('32 tests');
  await expect(card.getByTestId('workspace-checkpoint')).toContainText('Blocker: The evaluator is not commissioned');
  await card.getByTestId('workspace-history').locator('summary').first().click();
  const history = card.getByTestId('history-entry');
  await expect(history).toHaveCount(3);
  await expect(history.first()).toContainText('Delivered commit 2a3eb08');
  await expect(history.nth(1)).toHaveAttribute('data-kind', 'refused');
  await history.nth(2).locator('details summary').click();
  await expect(history.nth(2)).toContainText('bash: FAILED test_replay (exit 1)');
  await card.getByTestId('history-older').click();
  await expect(history).toHaveCount(4);
  await expect(history.last()).toContainText('Opened by the implementation lead under your go-ahead');
  await expect(card.getByTestId('history-older')).toHaveCount(0);
});

test('a link to a workspace opens its card with its history', async ({ page }) => {
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [workspace] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/timeline**`, route => route.fulfill({ json: { entries, next_before: null } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations/${WID}`);
  await expect(page.getByTestId('history-entry')).toHaveCount(3);
});

const report = {
  verdict: 'ready_with_limits', summary: 'Four methods and the evaluator work; the evaluator still needs commissioning.',
  methods: [{ method_id: 'bakery_adjacent', hypothesis_id: 'hypothesis_a', state: 'implemented', conformance: 'passed', tests: { passed: 8, failed: 0 } },
            { method_id: 'bakery_dp', hypothesis_id: 'hypothesis_b', state: 'implemented', conformance: 'not_run', tests: { passed: 8, failed: 0 } }],
  tests: { passed: 32, failed: 0, skipped: 0, command: 'pytest libraries/baking-order-search' },
  limitations: ['The evaluator is not commissioned'], next_actions: [{ owner: 'researcher', action: 'Install the library' }, { owner: 'lead', action: 'Commission the evaluator' }],
};

test('while it works the card says its phase, its tests and the coding agent\'s own estimate, said as its own', async ({ page }) => {
  const given = new Date(Date.now() - 2 * 60_000).toISOString();
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, phase: 'testing', tests: { passed: 30, failed: 2 }, estimate: { remaining_minutes: 8, given_at: given, source: 'coding agent' } },
    { ...workspace, id: 'development_late', title: 'Late one', created_at: '2026-10-27T02:00:00Z', estimate: { remaining_minutes: 5, given_at: '2026-10-27T02:10:00Z', source: 'coding agent' } }] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  await expect(card).toContainText('testing');
  await expect(card.getByTestId('workspace-estimate')).toContainText(/about [56] min left: the coding agent's estimate at/);
  await expect(card).toContainText('30 passed, 2 failed');
  await expect(page.locator('[data-workspace="development_late"]').getByTestId('workspace-estimate')).toContainText('has passed; it has given no newer one');
});

test('a delivery shows the coding agent\'s verdict, each method, the limitations and who does what next; the researcher can message it', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      estimate: { remaining_minutes: 4, given_at: '2026-10-27T03:19:38Z', source: 'coding agent' },
      submissions: [{ id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report }] },
    { ...workspace, id: 'development_old', title: 'Old one', status: 'idle', outcome: { state: 'delivered', verdict: 'unreported', submission_id: 's0', commit: '1111111', at: '2026-10-26T00:00:00Z' },
      submissions: [{ id: 's0', commit: '1111111', status: 'submitted', created_at: '2026-10-26T00:00:00Z', notes: 'NOT attach-ready' }] }] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/messages`, async route => {
    recorded.commands.push({ workspace_message: route.request().postDataJSON() }); return route.fulfill({ json: { id: 'cmd' } });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  const outcome = card.getByTestId('workspace-outcome');
  await expect(outcome).toHaveAttribute('data-verdict', 'ready_with_limits');
  await expect(outcome).toContainText('ready, with limits');
  await expect(outcome.getByTestId('outcome-methods').locator('tbody tr')).toHaveCount(2);
  await expect(outcome.getByTestId('outcome-methods')).toContainText('not run');
  await expect(outcome.getByTestId('outcome-limitations')).toContainText('The evaluator is not commissioned');
  await expect(outcome.getByTestId('outcome-next')).toContainText('You Install the library');
  await expect(card.getByTestId('workspace-estimate')).toHaveCount(0);   // the estimate is older than the delivery
  await expect(page.locator('[data-workspace="development_old"]').getByTestId('workspace-outcome')).toContainText('No delivery report');
  await card.getByTestId('workspace-message').fill('What is left?');
  await card.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => recorded.commands.find(c => 'workspace_message' in c)).toMatchObject({ workspace_message: { message: 'What is left?', mode: 'steer' } });
});

test('each implementation result is news in the inbox, linked to its workspace', async ({ page }) => {
  const row = { workspace_id: WID, workspace_title: 'Adjacent swap search', state: 'delivered', verdict: 'ready_with_limits', at: '2026-10-27T03:22:04Z',
    title: 'Implementation delivered: Adjacent swap search: ready, with limits, 32 passed, 0 failed' };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, implementations: [row],
    unacknowledged: [{ key: `implementation:${WID}:delivered:s1`, kind: 'implementation', id: WID, title: row.title, at: row.at }] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await expect(page.getByTestId('inbox-notice')).toContainText(`Implementation: ${row.title}`);
  const item = page.getByTestId('implementation-outcome');
  await expect(item).toContainText('new');
  await expect(item.getByRole('link')).toHaveAttribute('href', new RegExp(`hypotheses/implementations/${WID}`));
});
