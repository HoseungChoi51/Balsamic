import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, BRANCH_ID, CAMPAIGN_ID, evolution } from './mocks/fixtures';

test('the frontier table shows stages honestly and sends a batched stop with its reason', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await expect(table.locator('tr[data-record-id="hypothesis_c"]')).toContainText('stopped');
  await expect(table.locator('tr[data-record-id="hypothesis_c"]')).toHaveAttribute('data-stage', 'stopped');
  await expect(table.locator('tr[data-record-id="hypothesis_c"]')).toContainText('autopilot');
  await expect(page.getByTestId('page-evolution')).toContainText('best so far 0.5200');
  await table.locator('tr[data-record-id="hypothesis_a"] input[type=checkbox]').check();
  await table.locator('tr[data-record-id="hypothesis_b"] input[type=checkbox]').check();
  await page.getByTestId('interventions').getByRole('button', { name: 'Stop…' }).click();
  await page.getByTestId('stop-reason').fill('both dominated by H03\'s parent');
  await page.getByTestId('interventions').getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  const command = recorded.commands[0] as any;
  expect(command.operation).toBe('intervention.batch');
  expect(command.payload.items).toHaveLength(2);
  expect(command.payload.items[0]).toMatchObject({ operation: 'hypothesis.status', payload: { status: 'archived', stop_reason: "both dominated by H03's parent" } });
  expect(command.payload.all_or_nothing).toBe(true);
  await expect.poll(async () => { await page.evaluate(() => (window as any).dispatchEvent(new Event('pagehide'))); return recorded.uiEvents.map((e: any) => e.kind); }).toContain('intervention.send');
});

test('the frontier lists the highest score first when maximizing', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await expect(table.locator('tbody tr')).toHaveCount(3);
  expect(await table.locator('tbody tr').evaluateAll(rows => rows.map(r => r.getAttribute('data-record-id')))).toEqual(['hypothesis_b', 'hypothesis_a', 'hypothesis_c']);
  await expect(table.getByTestId('lower-is-better')).toHaveCount(0);
});

test('the frontier lists the lowest score first and says lower is better when minimizing', async ({ page }) => {
  const minimizing = { ...evolution, progress: { ...evolution.progress, best_so_far: 0.1, direction: 'minimize' },
    nodes: evolution.nodes.map(n => ({ ...n, best: { ...n.best, direction: 'minimize' } })) };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: minimizing });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await expect(table.getByTestId('lower-is-better')).toBeVisible();
  expect(await table.locator('tbody tr').evaluateAll(rows => rows.map(r => r.getAttribute('data-record-id')))).toEqual(['hypothesis_c', 'hypothesis_a', 'hypothesis_b']);
  await expect(page.getByTestId('page-evolution')).toContainText('best so far 0.1000');
});

test('the lineage tree draws rounds as columns with typed edges; a node opens its card', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution/lineage`);
  const lineage = page.getByTestId('lineage');
  await expect(lineage.locator('svg text', { hasText: 'round 1' })).toBeVisible();
  await expect(lineage.locator('path[data-kind="variant"]')).toHaveCount(1);
  await expect(lineage.locator('[data-record-id="hypothesis_b"] text')).toHaveText('H02 Warm-start CMA-ES');
  const legend = lineage.getByTestId('lineage-legend');
  await expect(legend.locator('svg path')).toHaveCount(4);
  await expect(legend).not.toContainText('Solid:');
  await expect(lineage.locator('g[data-record-id="hypothesis_c"]')).toHaveAttribute('data-stage', 'stopped');
  await lineage.locator('g[data-record-id="hypothesis_b"]').dblclick();
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/hypotheses/hypothesis_b`));
  const card = page.getByTestId('hypothesis-card');
  await expect(card).toContainText('CMA-ES with warm start');
  await expect(card).toContainText('Random restarts');
  await page.getByTestId('trace-origin-button').click();
  const trace = page.getByTestId('trace-origin');
  await expect(trace.getByTestId('hop')).toHaveCount(6);
  await expect(trace).toContainText('lead on gpt-5');
  await page.getByTestId('open-in-graph').click();
  await expect(page).toHaveURL(/evolution\/lineage\?sel=hypothesis_b/);
});

test('curves and the experiment log read a run honestly; Discuss forks a branch anchored on the strategy', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution/curves`);
  await expect(page.getByTestId('page-evolution').locator('svg.curve')).toHaveCount(2);
  await page.goto(`/#t/${THREAD_ID}/hypotheses/hypothesis_b`);
  await page.getByTestId('discuss').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'thread.fork', payload: { thread_id: THREAD_ID, message_id: 'message_2', anchors: ['hypothesis_b'] } });
  await expect(page).toHaveURL(new RegExp(`#t/${BRANCH_ID}/hypotheses/hypothesis_b`));
  await page.goto(`/#t/${THREAD_ID}/experiments/trial_1`);
  await expect(page.getByTestId('page-experiments')).toContainText('single run');
  await page.getByTestId('trace-origin-button').click();
  await expect(page.getByTestId('trace-origin').getByTestId('hop')).toHaveCount(5);
});
