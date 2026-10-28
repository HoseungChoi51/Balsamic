import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the library ranks entries by fit with the reasons, searches by words, and applies one as a new root', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/library`);
  const entries = page.getByTestId('library-entry');
  await expect(entries).toHaveCount(3);
  await expect(entries.first()).toContainText('Restart hill climbing');
  await expect(entries.first()).toContainText('fit 6');
  await expect(entries.first()).toContainText('same problem; same objective and direction; same representation');
  await expect(entries.first()).toContainText('0.1200 best (measured), 30.0 min of worker time, 4 seeds won, confirmed');
  await expect(entries.first()).toContainText('passed: meent_2d_order_convergence:v1 (validation_1)');
  await expect(entries.nth(1)).toContainText('not recorded (published before fidelity checks)');
  await expect(entries.nth(1)).toContainText('nothing in common with this problem');
  // A negative entry (K4) shows apart, under "Assessed and stopped", with its outcome, assessment and evidence.
  const negative = page.locator('[data-testid="library-entry"][data-kind="negative"]');
  await expect(negative).toHaveCount(1);
  await expect(page.locator('[data-testid="library-entry"][data-kind="positive"]')).toHaveCount(2);
  await expect(page.getByText('Assessed and stopped (1)')).toBeVisible();
  await expect(page.getByText('Strategies that won (2)')).toBeVisible();
  await expect(negative).toContainText('assessed and stopped: configuration unpromising');
  await expect(negative).toContainText('configuration unpromising: no configuration came within 20% of the baseline (manager)');
  await expect(negative).toContainText('3 of 3 configurations, 2 seeds each (adequate) · aaaaaa on seeds 0, 1');
  await expect(negative).toContainText('0.3100 best as measured');
  await expect(negative).toContainText('rests on trial_31, comparison_2');
  await expect(negative).not.toContainText('Fidelity');
  await expect(entries.first()).not.toContainText('assessed and stopped');
  await page.getByTestId('library-search').fill('grating');
  await expect(page.getByTestId('library-entry')).toHaveCount(1);
  await page.getByTestId('library-search').fill('');
  await entries.first().getByTestId('apply').click();
  await page.getByTestId('apply-dialog').locator('textarea').fill('start from the winner');
  await page.getByTestId('apply-dialog').getByRole('button', { name: 'Apply', exact: true }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'library.apply', payload: { entry_id: 'library_1', note: 'start from the winner' }, origin: { thread_id: THREAD_ID } });
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/hypotheses/hypothesis_new`));
});

test('a strategy stopped after a fair assessment is offered for publishing as assessed and stopped', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/library`);
  const candidate = page.getByTestId('negative-candidate');
  await expect(candidate).toHaveCount(1);
  await expect(candidate).toContainText('Annealing');
  await expect(candidate).toContainText('stopped: adequately assessed, deprioritized');
  await expect(candidate).toContainText('3 of 3 configurations, 2 seeds each');
  await candidate.getByTestId('publish-negative').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'library.publish', payload: { hypothesis_id: 'hypothesis_c', kind: 'negative' } });
});

test('Ctrl+K searches pages, threads and messages; arrows and Enter open; g-letter jumps to a page', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await page.keyboard.press('Control+k');
  const palette = page.getByTestId('search-palette');
  await expect(palette).toBeVisible();
  await palette.locator('input').fill('deflector');
  await expect(palette.getByTestId('palette-hit').filter({ hasText: 'What do we know about the deflector' })).toBeVisible();
  await palette.locator('input').fill('inbox');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/inbox`));
  await expect(palette).toHaveCount(0);
  await page.keyboard.press('g'); await page.keyboard.press('v');
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/evolution`));
  await page.keyboard.press('g'); await page.keyboard.press('b');
  await expect(page.getByTestId('page-branches')).toBeVisible();
  await expect(page.getByTestId('export-thread').first()).toHaveAttribute('href', `/api/v1/threads/${THREAD_ID}/export`);
  await page.keyboard.press('g'); await page.keyboard.press('v');
  await expect(page.getByTestId('export-graph')).toHaveAttribute('href', '/api/v1/campaigns/demo/evolution/export');
  await expect.poll(async () => { await page.evaluate(() => (window as any).dispatchEvent(new Event('pagehide'))); return recorded.uiEvents.map((e: any) => e.kind); }).toContain('search.open');
});
