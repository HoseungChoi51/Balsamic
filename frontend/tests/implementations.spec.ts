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
