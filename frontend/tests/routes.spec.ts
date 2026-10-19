import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

const catalog = JSON.parse(readFileSync(new URL('../src/router/pages.json', import.meta.url), 'utf8'));

test('every old address opens its page in the current thread', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await expect(page.getByTestId('page-monitor')).toBeVisible();
  for (const [alias, target] of Object.entries(catalog.aliases as Record<string, string>)) {
    if (target === 'new') continue;
    await page.evaluate(hash => { location.hash = hash; }, '#' + alias);
    const [pageName, sub] = target.split('/');
    await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/${target.replace('/', '\\/')}`), { timeout: 5000 });
    await expect(page.locator(`main[data-page="${pageName}"]`)).toBeVisible();
    if (sub) await expect(page.locator(`main[data-sub="${sub}"]`)).toBeVisible();
  }
  // A record address keeps its record.
  await page.evaluate(() => { location.hash = '#experiments/trial_1'; });
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/experiments/trial_1`));
  await expect(page.getByTestId('page-experiments')).toContainText('worker started');
  // #new opens the campaign form without a thread.
  await page.evaluate(() => { location.hash = '#problem-import'; });
  await expect(page).toHaveURL(/#new$/);
  await expect(page.getByTestId('new-campaign')).toBeVisible();
});

test('every rail page has a title and a description, and each sub page is reachable', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  for (const name of catalog.rail as string[]) {
    const entry = catalog.pages[name];
    expect(entry.title.length).toBeGreaterThan(0); expect(entry.description.length).toBeGreaterThan(0);
    await page.getByTestId(`rail-${name}`).click();
    await expect(page.locator(`main[data-page="${name}"]`)).toBeVisible();
    for (const sub of Object.keys(entry.subs || {})) {
      await page.evaluate(hash => { location.hash = hash; }, `#t/${THREAD_ID}/${name}/${sub}`);
      await expect(page.locator(`main[data-page="${name}"][data-sub="${sub}"]`)).toBeVisible();
    }
  }
});
