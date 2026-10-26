import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';

test('the researcher sets how many runs go at once and how many on the GPU, without a restart', async ({ page }) => {
  const slots = { workers: 11, gpu_workers: 1, sizes: { cuda: 1, cpu: 10 }, launcher: { workers: 11, gpu_workers: 1 }, chosen_by: null };
  const recorded = await mockWorkspace(page);
  await page.route('**/api/v1/resources?*', route => route.fulfill({ json: { host: {}, workers: { running_count: 2, configured_limit: 11 }, admission: { level: 'balanced', levels: [] }, slots } }));
  await page.goto(`/#t/${THREAD_ID}/monitor/resources`);
  await expect(page.getByTestId('slots-now')).toContainText('Now 11 runs at once: 1 on the GPU, 10 on CPU.');
  await expect(page.getByTestId('slots-apply')).toBeDisabled();
  await page.getByTestId('slots-gpu').fill('2');
  await page.getByTestId('slots-apply').click();
  await expect.poll(() => recorded.commands.find(c => c.slots)?.slots).toMatchObject({ workers: 11, gpu_workers: 2 });
});

test('a queued run is placed on the GPU or CPU before it starts; a started run shows where it computes', async ({ page }) => {
  const queued = { ...f.experiments.short[0], id: 'trial_q', status: 'queued', device: null, control_revision: 0 };
  const recorded = await mockWorkspace(page, { '/api/v1/experiments/trial_q': { trial: queued, chain_trial_ids: ['trial_q'], validations: [], race: null },
    [`/api/v1/campaigns/${CAMPAIGN_ID}/experiments`]: { ...f.experiments, short: [queued] } });
  await page.goto(`/#t/${THREAD_ID}/experiments/trial_q`);
  await page.getByTestId('place-device').selectOption('cuda');
  await expect.poll(() => recorded.commands.find(c => c.operation === 'trial.control')?.payload).toMatchObject({ trial_id: 'trial_q', action: 'place', device: 'cuda' });
});
