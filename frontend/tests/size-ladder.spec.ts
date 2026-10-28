import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, CAMPAIGN_ID, evolution } from './mocks/fixtures';

test('extend on a strategy that finished on its own proposes the next size and sends its task', async ({ page }) => {
  const next = { task_id: 'task_12', task_name: '12 jobs', name: 'jobs', value: 12, after: 8 };
  const sized = { ...evolution, nodes: evolution.nodes.map(n => n.id === 'hypothesis_a' ? { ...n, next_size: next } : n) };
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: sized });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await table.locator('tr[data-record-id="hypothesis_a"] input[type=checkbox]').check();
  const bar = page.getByTestId('interventions');
  await expect(bar.getByTestId('allocate')).toHaveText('Run on the next size…');
  await bar.getByTestId('allocate').click();
  await expect(bar.getByTestId('next-size')).toContainText('jobs = 12 (12 jobs)');
  await bar.getByPlaceholder('Why (one line)').fill('see where it stops finishing');
  await bar.getByRole('button', { name: 'Run on the next size', exact: true }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  const command = recorded.commands[0] as any;
  expect(command.payload.items[0]).toMatchObject({ operation: 'hypothesis.allocate', payload: { hypothesis_id: 'hypothesis_a', task_id: 'task_12' } });
  // A strategy with no next size beside it: time, as before.
  await table.locator('tr[data-record-id="hypothesis_a"] input[type=checkbox]').check();
  await table.locator('tr[data-record-id="hypothesis_b"] input[type=checkbox]').check();
  await expect(page.getByTestId('interventions').getByTestId('allocate')).toHaveText('Allocate time…');
});
