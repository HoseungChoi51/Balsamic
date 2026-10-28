import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, CAMPAIGN_ID, evolution } from './mocks/fixtures';

// Roadmap N13: per task the best value, the best bound and the gap; a proof is "proved" only when something checks it.
const proved = { ...evolution,
  optimality: [{ task_id: 'task_1', task_name: 'Quadratic', direction: 'maximize', best_value: 0.52, best_bound: 0.55, bound_algorithm: 'branch_and_bound',
    gap: 0.03, relative_gap: 0.03 / 0.55, optimum: { value: 0.52, status: 'claimed', claimed_by: ['dp'] } }],
  nodes: evolution.nodes.map((node, index) => index === 0
    ? { ...node, proof: { status: 'checked', value: 0.41, algorithm: 'enumerate', trial_id: 'trial_1', checked_by: 'enumerate', task_id: 'task_1', task_name: 'Quadratic', fully_assessed: true } }
    : index === 1 ? { ...node, proof: { status: 'claimed', value: 0.52, algorithm: 'dp', trial_id: 'trial_2', task_id: 'task_1', fully_assessed: false } }
    : { ...node, proof: { status: 'contradicted', value: 0.3, algorithm: 'greedy', trial_id: 'trial_3', task_id: 'task_1', fully_assessed: false } }) };

test('the frontier shows each task\'s bound and gap, and proves only what is checked', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: proved });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const task = page.getByTestId('optimality').locator('tr[data-task-id="task_1"]');
  await expect(task).toContainText('0.5500 from branch_and_bound');
  await expect(task).toContainText('0.0300 (5.45%)');
  await expect(task).toContainText('0.5200 claimed by dp');
  const table = page.getByTestId('frontier');
  await expect(table.locator('tr[data-record-id="hypothesis_a"]')).toContainText('proved optimal');
  await expect(table.locator('tr[data-record-id="hypothesis_b"]')).toContainText('optimal: claimed by dp');
  await expect(table.locator('tr[data-record-id="hypothesis_b"]')).not.toContainText('proved optimal');
  await expect(table.locator('tr[data-record-id="hypothesis_c"]')).toContainText('optimality claim contradicted');
});

test('a campaign with no bound or proof shows no optimality table', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  await expect(page.getByTestId('frontier')).toBeVisible();
  await expect(page.getByTestId('optimality')).toHaveCount(0);
});
