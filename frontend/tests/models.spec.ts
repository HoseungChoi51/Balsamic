import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the Models page assigns a tier per role and a model per tier, saved with the revision', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor/models`);
  await expect(page.getByTestId('page-monitor')).toContainText('deepseek (api)');
  await expect(page.getByTestId('tier-row')).toHaveCount(2);
  // Roles are named as the pages name them; the ones the researcher talks with come first, accented.
  await expect(page.getByTestId('roles-direct').getByTestId('role-row')).toHaveCount(2);   // the mock lists lead, proposal_reviewer, formulator
  await expect(page.getByTestId('roles-direct').locator('[data-role="formulator"]')).toContainText('Formulator');
  await expect(page.getByTestId('roles-behind').locator('[data-role="proposal_reviewer"]')).toContainText('Proposal reviewer');
  await page.getByLabel('tier of proposal_reviewer').selectOption('fast');
  await page.getByLabel('model of fast').selectOption('deepseek/deepseek-v4-pro');
  // The thinking levels are the model's, as Pi's /thinking offers them; "default" names the level it comes to.
  await expect(page.getByLabel('thinking of fast')).toHaveValue('');
  await expect(page.getByLabel('thinking of fast').locator('option')).toHaveText(['default (medium)', 'off', 'low', 'medium', 'high']);
  await page.getByLabel('thinking of fast').selectOption('low');
  await page.getByTestId('save-tiers').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  const body = (recorded.commands[0] as any).tiers;
  expect(body.expected_revision).toBe(0);
  expect(body.roles.proposal_reviewer).toBe('fast');
  expect(body.tiers[1]).toEqual({ id: 'fast', label: 'Fast', model: { provider: 'deepseek', model: 'deepseek-v4-pro', effort: 'low' } });
  await expect(page.getByTestId('page-monitor')).toContainText('1 running agents switched');
});

test('ChatGPT is signed in from the Models page with a device code', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor/models`);
  await expect(page.getByTestId('provider-login')).toContainText('not signed in');
  await page.getByTestId('login-openai').click();
  await expect.poll(() => recorded.commands.some((c: any) => c.login)).toBe(true);
  await expect(page.getByTestId('login-code')).toHaveText('ABCD-1234');
  await expect(page.getByTestId('provider-login')).toContainText('https://auth.openai.com/device');
});
