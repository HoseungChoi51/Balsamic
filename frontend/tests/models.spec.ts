import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the Models page assigns a tier per role and a model per tier, saved with the revision', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor/models`);
  await expect(page.getByTestId('page-monitor')).toContainText('deepseek (api)');
  await expect(page.getByTestId('tier-row')).toHaveCount(2);
  await page.getByLabel('tier of proposal_reviewer').selectOption('fast');
  await page.getByLabel('model of fast').selectOption('deepseek/deepseek-v4-pro');
  await page.getByLabel('thinking of fast').selectOption('low');
  await page.getByTestId('save-tiers').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  const body = (recorded.commands[0] as any).tiers;
  expect(body.expected_revision).toBe(0);
  expect(body.roles.proposal_reviewer).toBe('fast');
  expect(body.tiers[1]).toEqual({ id: 'fast', label: 'Fast', model: { provider: 'deepseek', model: 'deepseek-v4-pro', effort: 'low' } });
  await expect(page.getByTestId('page-monitor')).toContainText('1 running agents switched');
});
