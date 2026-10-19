import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the shell opens the newest campaign on its main thread with the rail, the stage badge and the monitor pill', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto('/');
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/monitor$`));
  await expect(page.getByTestId('stage')).toHaveText('generate');
  await expect(page.getByTestId('monitor-pill')).toHaveText('1 waiting for you');
  await expect(page.getByTestId('rail-inbox')).toContainText('1');
  await expect(page.getByTestId('thread-chat')).toContainText('What do we know about the deflector');
  // The lead's reply links records and pages as chips that open in this thread.
  const chip = page.getByTestId('thread-chat').locator('a.chip', { hasText: 'trial_1' }).first();
  await expect(chip).toHaveAttribute('href', `#t/${THREAD_ID}/experiments/trial_1?sel=trial_1`);
  await chip.click();
  await expect(page.getByTestId('page-experiments')).toContainText('trial_1');
  await expect(page.getByTestId('page-experiments')).toContainText('random_search');
  // The monitor pill opens the drawer with honest rows.
  await page.getByTestId('monitor-pill').click();
  await expect(page.getByTestId('monitor-drawer')).toContainText('Needs you');
  await expect(page.getByTestId('monitor-rows')).toContainText('1 of 2 workers');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('monitor-drawer')).toHaveCount(0);
  // Expand hides the chat; the choice survives a reload.
  await page.getByTestId('toggle-wide').click();
  await expect(page.getByTestId('thread-chat')).toBeHidden();
  await page.reload();
  await expect(page.getByTestId('thread-chat')).toBeHidden();
});

test('a stopped run reads as stopped, never failed, and disabled controls say why', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/experiments`);
  const row = page.getByTestId('page-experiments').locator('tr[data-record-id="trial_2"]');
  await expect(row).toContainText('stopped');
  await expect(row.locator('.pill')).toHaveAttribute('title', /not failed/);
  await expect(page.getByTestId('autopilot-toggle')).toHaveText('Autopilot off');
  // A disabled control says why: the new-campaign form without a name.
  await page.evaluate(() => { location.hash = '#new'; });
  await expect(page.getByTestId('new-campaign').getByRole('button', { name: 'Create campaign' })).toBeDisabled();
});
