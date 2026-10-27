import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

const { version } = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

test('the bare address is the home page: the logo, the name, the version and what Balsamic is', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto('/');
  const home = page.getByTestId('home');
  await expect(home.getByTestId('home-logo')).toBeVisible();
  await expect(home.getByRole('heading', { name: 'Balsamic' })).toBeVisible();
  await expect(page.getByTestId('home-version')).toHaveText(`v${version}`);
  await expect(home).toContainText('lead agent');
  await expect(page.getByTestId('shell')).toHaveCount(0);
  // The home page stays at the bare address; it opens the workspace with no campaign chosen, and the brand in the top bar leads back.
  await expect(page).toHaveURL(/\/$/);
  await page.getByTestId('home-open').click();
  await expect(page).toHaveURL(/#monitor$/);
  await expect(page.getByTestId('campaign-switch')).toHaveValue('');
  await page.getByTestId('brand').click();
  await expect(page).toHaveURL(/#home$/);
  await expect(page.getByTestId('home')).toBeVisible();
});
