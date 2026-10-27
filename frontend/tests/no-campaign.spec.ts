import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('without a chosen campaign a page shows nothing of any campaign; Monitor shows the machine and the models', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto('/#new');
  await expect(page).toHaveURL(/#new\/setup_\d+$/);
  const setup = new URL(page.url()).hash;
  const started = (recorded as unknown as { setups: number }).setups;
  await expect(page.getByTestId('setup-model-link')).toHaveAttribute('href', '#monitor/models');
  // Monitor from the new campaign stays without a campaign: no other campaign is put in front.
  await page.getByTestId('rail-monitor').click();
  await expect(page).toHaveURL(/#monitor$/);
  await expect(page.getByTestId('campaign-switch')).toHaveValue('');
  const monitor = page.getByTestId('page-monitor');
  await expect(monitor.locator('nav.tabs a')).toHaveText(['Resources', 'Models']);
  await expect(page.getByTestId('machine-stats')).toBeVisible();
  await expect(page.getByTestId('thresholds-now')).toHaveCount(0);   // a campaign's setting
  // The lead's model is chosen before the campaign exists.
  await monitor.getByRole('link', { name: 'Models' }).click();
  await expect(page.getByTestId('tier-row')).toHaveCount(2);
  await expect(page.getByLabel('tier of lead')).toBeVisible();
  // A campaign's pages, and Monitor's campaign tabs, show nothing until one is chosen.
  await page.getByTestId('rail-experiments').click();
  await expect(page).toHaveURL(/#experiments$/);
  await expect(page.getByTestId('no-campaign')).toBeVisible();
  await page.goto('/#monitor/usage');
  await expect(page.getByTestId('no-campaign')).toBeVisible();
  // A thread-less address opened from a campaign stays in that campaign.
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await expect(page.getByTestId('campaign-switch')).not.toHaveValue('');
  await page.evaluate(() => { location.hash = '#experiments'; });
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/experiments$`));
  // Back to the new campaign: the setup left open continues.
  await page.getByTestId('campaign-switch').selectOption('__new');
  await expect.poll(() => new URL(page.url()).hash).toBe(setup);
  expect((recorded as unknown as { setups: number }).setups).toBe(started);
});
