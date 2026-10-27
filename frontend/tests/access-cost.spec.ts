import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;
const metrics = [{ evaluations: 1, elapsed_seconds: 4, best_objective: .5 }, { evaluations: 2, elapsed_seconds: 30, best_objective: .2 }];

async function open(page: import('@playwright/test').Page, trial: Record<string, unknown>) {
  await mockWorkspace(page, { [`/api/v1/experiments/${trial.id}`]: { trial, chain_trial_ids: [trial.id], validations: [], race: null },
    [`/api/v1/experiments/${trial.id}/metrics`]: metrics, [`/api/v1/experiments/${trial.id}/logs`]: { text: '' } });
  await page.goto(`/#t/${THREAD_ID}/experiments/${trial.id}`);
}

test('a white-box run is charted over its time, with a switch to evaluations', async ({ page }) => {
  await open(page, { ...f.experiments.short[0], id: 'trial_w', access: 'white_box' });
  await expect(page.getByTestId('run-access')).toContainText('white box');
  await expect(page.getByTestId('curve-axis')).toHaveText('seconds');
  await expect(page.getByRole('img', { name: 'best score over seconds' })).toBeVisible();
  await page.getByTestId('curve-axis-switch').click();
  await expect(page.getByTestId('curve-axis')).toHaveText('evaluations');
});

test('a white-box run on two threads is charted over core-seconds; an oracle run over evaluations', async ({ page }) => {
  await open(page, { ...f.experiments.short[0], id: 'trial_t', access: 'white_box', numerical_threads: 2 });
  await expect(page.getByTestId('curve-axis')).toHaveText('core-seconds');
  await open(page, { ...f.experiments.short[0], id: 'trial_o' });
  await expect(page.getByTestId('run-access')).toContainText('oracle');
  await expect(page.getByTestId('curve-axis')).toHaveText('evaluations');
});

test('the charter page shows the access and the cost axis and sets them before confirmation', async ({ page }) => {
  const posts: { path: string; body: { changes: unknown[] } }[] = [];
  const view = { ...JSON.parse(JSON.stringify(f.charterView)),
    access: { access: 'white_box', cost_axis: null, problem: { access: 'white_box', cost_axis: null }, charter: { access: null, cost_axis: null } } };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  await page.route('**/api/v1/problem-charters/charter_1**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: view });
    posts.push({ path: new URL(route.request().url()).pathname.split('/').at(-1)!, body: route.request().postDataJSON() });
    view.access = { ...view.access, access: 'oracle', charter: { access: 'oracle', cost_axis: null } };
    return route.fulfill({ json: view });
  });
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const section = page.getByTestId('charter-access');
  await expect(section).toContainText("the problem's own: white box");
  await expect(page.getByTestId('access-why')).toContainText('judged by the time they take');
  await page.getByTestId('access-select').selectOption('oracle');
  await expect.poll(() => posts.find(p => p.path === 'edit')?.body.changes).toEqual([{ op: 'set', path: 'evaluator.access', value: 'oracle' }]);
  await expect(page.getByTestId('access-why')).toContainText('counted by what they ask the evaluator');
});
