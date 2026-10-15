import { test, expect } from '@playwright/test';

test('study monitor links open the exact run and read its curve as a bounded number of points', async ({ page }) => {
  const campaign = { id: 'campaign-monitor', name: 'Optimizer comparison', active_study_id: 'main-study',
    compute_budget_seconds: 18500, validation_reserve_seconds: 180, objective: 'Compare finalists', version: 4 };
  const problem = { definition_id: 'bounded_continuous', primary_objective: { name: 'loss', direction: 'minimize' } };
  const trial = (id: string, study: string, algorithm: string, seed: number) => ({ id, study_id: study, campaign_id: campaign.id,
    task_id: 'task-one', algorithm, seed, problem, status: 'running', max_steps: 100000, wall_seconds: 1800,
    progress: { step: 9000, evaluations: 9000, best_objective: 0.04, elapsed_seconds: 100 } });
  const state = { workspace_id: 'monitor-workspace', campaign, campaigns: [campaign],
    tasks: [{ id: 'task-one', name: 'Quadratic', problem }], studies: [{ id: 'main-study', scope: 'confirmation' }, { id: 'prototype-study', scope: 'exploratory' }],
    trials: [trial('trial-final', 'main-study', 'coordinate', 100), trial('trial-source', 'prototype-study', 'random', 1)],
    hypotheses: [], decisions: [], messages: [], events: [], algorithms: [], research_runs: [], settings: { llm_configured: false } };
  const writes: string[] = [], metricLimits: string[] = [];
  await page.addInitScript(() => { (window as any).EventSource = class extends EventTarget { close() {} }; });
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() !== 'GET') writes.push(request.url());
    if (url.pathname === '/api/state') return route.fulfill({ json: state });
    if (url.pathname.endsWith('/metrics')) {
      metricLimits.push(url.searchParams.get('points') || 'unbounded');
      return route.fulfill({ json: [{ step: 9000, evaluations: 9000, objective: 0.08, best_objective: 0.04 }] });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto('/#experiments/trial-final');
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'coordinate · seed 100' })).toBeVisible();
  await expect(dialog).toContainText('9000 of 100000');
  await expect.poll(() => [...new Set(metricLimits)]).toEqual(['400']);
  await page.reload();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'coordinate · seed 100' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close dialog' }).click();
  await expect(page).toHaveURL(/#experiments$/);
  await expect(page.getByLabel('Study', { exact: true })).toHaveValue('main-study');
  await expect(page.getByRole('button', { name: 'coordinate · seed 100', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'random · seed 1', exact: true })).toHaveCount(0);
  await page.getByLabel('Study', { exact: true }).selectOption('all');
  await expect(page.getByRole('button', { name: 'random · seed 1', exact: true })).toBeVisible();
  await page.evaluate(() => { location.hash = '#experiments/trial-source'; });
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'random · seed 1' })).toBeVisible();
  expect(writes).toEqual([]);
});
