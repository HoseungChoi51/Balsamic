import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

// Two campaigns; the newer one is shown first. Removal is answered by the mock as the service answers it.
async function workspace(page: Page, blockers: string[] = []) {
  await page.addInitScript(() => { (window as any).EventSource = class extends EventTarget { close() {} }; });
  const campaigns = [{ id: 'c-kept', name: 'Kept campaign', version: 1, objective: 'Stays.', compute_budget_seconds: 100, llm_budget_usd: 0 },
    { id: 'c-old', name: 'Old screen', version: 1, objective: 'Goes.', compute_budget_seconds: 100, llm_budget_usd: 0 }];
  const posted: any[] = [];
  let removed = false;
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method();
    if (url.pathname === '/api/state') {
      const wanted = url.searchParams.get('campaign_id');
      const listed = campaigns.filter(campaign => !(removed && campaign.id === 'c-old'));
      const campaign = wanted ? listed.find(item => item.id === wanted) : listed.at(-1);
      if (!campaign) return route.fulfill({ status: 404, json: { detail: 'Workspace record not found' } });
      return route.fulfill({ json: { workspace_id: 'removal-workspace', campaigns: listed, campaign, tasks: [], hypotheses: [], trials: [], decisions: [], messages: [],
        events: [], research_runs: [], algorithms: [], settings: { llm_configured: false }, event_cursor: 1 } });
    }
    if (url.pathname === '/api/v1/campaigns/c-old/removal' && method === 'GET') return route.fulfill({ json: { campaign: { id: 'c-old', name: 'Old screen' },
      holds: { experiments: 60, hypotheses: 8, findings: 1, messages: 78, agents: 1, records: 369000, events: 527690 },
      bytes: { files: 72_300_000_000, experiment_files: 72_000_000_000, database: 941_000_000 }, blockers,
      options: [{ keep: 'nothing', kept_bytes: 0 }, { keep: 'summary', kept_bytes: null }, { keep: 'records', kept_bytes: 596_000_000, left_out: { cost_event: 365855 } }],
      folder: '/data/workspace/removed/c-old' } });
    if (url.pathname === '/api/v1/campaigns/c-old/removal' && method === 'POST') {
      posted.push(request.postDataJSON());
      removed = true;
      return route.fulfill({ json: { id: 'removal_c-old', removed_campaign_id: 'c-old', name: 'Old screen', keep: posted.at(-1).keep, status: 'completed',
        folder: '/data/workspace/removed/c-old', kept_bytes: 1_200_000, files_bytes: 72_300_000_000, rows: { records: 369000, events: 527690 } } });
    }
    return route.fulfill({ json: {} });
  });
  return { posted };
}

test('removing a campaign asks what to keep and needs a deliberate confirmation', async ({ page }) => {
  const { posted } = await workspace(page);
  await page.goto('/');
  await expect(page.getByLabel('Active campaign')).toHaveValue('c-old');
  await page.getByTitle('Remove this campaign from the workspace').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Remove “Old screen”' })).toBeVisible();
  await expect(dialog.getByText('It holds 60 experiments, 8 hypotheses, 1 finding and 78 messages: 72.3 GB of files and 941 MB in the database.')).toBeVisible();
  // Nothing is chosen for the researcher, and neither the choice nor the confirmation alone is enough.
  const remove = dialog.getByRole('button', { name: 'Remove campaign' });
  for (const option of ['Nothing', 'A summary of the runs', 'The summary and most records']) await expect(dialog.getByRole('radio', { name: option })).not.toBeChecked();
  await expect(remove).toBeDisabled();
  await dialog.getByLabel('I understand that this cannot be undone.').check();
  await expect(remove).toBeDisabled();
  await dialog.getByRole('radio', { name: 'The summary and most records' }).check();
  await expect(dialog.getByText('every run\'s score journal (596 MB)')).toBeVisible();
  await expect(dialog.getByText('per-evaluation accounting (365,855 rows)')).toBeVisible();
  await dialog.getByRole('radio', { name: 'A summary of the runs' }).check();
  await expect(dialog.getByText('/data/workspace/removed/c-old')).toBeVisible();
  await remove.click();
  await expect(dialog.getByRole('heading', { name: 'Campaign removed' })).toBeVisible();
  await expect(dialog.getByText('Deleted: 72.3 GB of files and 369,000 records.')).toBeVisible();
  await expect(dialog.getByText('Kept, 1.2 MB:')).toBeVisible();
  expect(posted).toEqual([{ keep: 'summary' }]);
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  // The workspace shows the campaign that is left.
  await expect(page.getByLabel('Active campaign')).toHaveValue('c-kept');
  await expect(page.getByLabel('Active campaign').locator('option')).toHaveText(['Kept campaign']);
});

test('a campaign with work in progress shows what stands in the way and cannot be removed', async ({ page }) => {
  const { posted } = await workspace(page, ['2 experiments are queued or running. Stop or finish every experiment first.',
    'Campaign “Kept campaign” uses 10 findings or results of this campaign. Remove that campaign first.']);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByTitle('Remove this campaign from the workspace').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('It cannot be removed yet.')).toBeVisible();
  await expect(dialog.getByText('uses 10 findings or results of this campaign')).toBeVisible();
  await expect(dialog.getByRole('radio', { name: 'Nothing' })).toBeDisabled();
  await expect(dialog.getByLabel('I understand that this cannot be undone.')).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Remove campaign' })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).not.toBeVisible();
  expect(posted).toEqual([]);
});
