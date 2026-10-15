import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// A campaign whose design is a 4 x 8 binary grid: short runs, a long run, a speed probe, and the operator's rules.
const problem = { definition_id: 'meent_2d_dual_polarization_deflector', candidate_schema: { representation: 'binary', dimensions: 32 },
  configuration: { grid_x: 8, grid_y: 4 }, primary_objective: { name: 'mean_plus1_transmission', direction: 'maximize', units: 'fraction of incident power' } };
const design = Array.from({ length: 32 }, (_, index) => (index % 8 < 3 ? 1 : 0));
function run(id: string, kind: string, status: string, more: any = {}) {
  return { id, campaign_id: 'c1', task_id: 'task', algorithm: 'coordinate', seed: 1, status, max_steps: 5000, wall_seconds: kind === 'long' ? 14400 : 300,
    priority: 0, created_at: '2026-10-14T06:00:00+00:00', control_revision: 2, problem, run_kind: kind, study_id: 'study', algorithm_config: { step: 0.1 },
    question: `${kind === 'long' ? 'Long' : 'Screen'} · H1 · coordinate · seed 1\nDoes coordinate search beat the floor?`,
    progress: { evaluations: 4000, solver_calls: 4000, elapsed_seconds: 250, best_objective: 0.62, best_design: design,
      best_objectives: { mean_plus1_transmission: 0.62, te_plus1_transmission: 0.55, tm_plus1_transmission: 0.69 } }, ...more };
}
function fixture() {
  const campaign = { id: 'c1', version: 1, name: '2D deflector', autonomy: 'delegated', objective: 'Find a good design', compute_budget_seconds: 100000, active_study_id: 'study' };
  return { workspace_id: 'w1', campaign, campaigns: [campaign], tasks: [{ id: 'task', name: 'Deflector', split: 'development', problem, evaluator_readiness: { runnable: true } }],
    hypotheses: [], decisions: [], messages: [], events: [], research_runs: [], budget: {}, event_cursor: 1, studies: [{ id: 'study', scope: 'exploratory', goal: 'Screen' }],
    algorithms: [{ id: 'coordinate', name: 'Coordinate search', representations: ['binary'] }],
    trials: [run('t-done', 'short', 'completed'), run('t-failed', 'short', 'failed', { reason: 'CUDA out of memory' }), run('t-queued', 'short', 'queued', { progress: {} }),
      run('t-long', 'long', 'running'), run('t-probe', 'check', 'completed', { question: 'Runtime profile probe' }),
      run('t-old', 'short', 'failed', { hidden: { by: 'manager', reason: 'Ran again after the memory fix' } })],
    settings: { llm_configured: true, max_workers: 4 },
    experiment_rules: { revision: 3, naming: '{stage} · {proposal} · {method} · seed {seed}', short_run_seconds: 600, max_concurrent: 2, strategy: 'Screen first.',
      updated_by: 'manager', rationale: 'GPU memory allows two', presentation_chosen: true,
      presentation: { list_columns: ['thumbnail', 'name', 'status', 'best', 'objectives'], entry_sections: ['design', 'curve', 'objectives', 'settings'],
        curve_x: 'evaluations', objectives: ['te_plus1_transmission', 'tm_plus1_transmission'],
        design: { render: 'mask', rows: 4, cols: 8, on_label: 'silicon', off_label: 'air' }, rationale: 'The lead says the shape and the TE/TM balance matter most' } },
    agent_runtime: { configuration: { enabled: true, status: 'running', control_revision: 1, provider: { configured: true } },
      agents: [{ id: 'lead', role: 'lead', status: 'waiting', model: 'm', objective: 'x', control_revision: 0 }], questions: [], aliases: [] } };
}
async function mock(page: Page, state: any) {
  const writes: any[] = [], metrics: string[] = [];
  await page.addInitScript(() => { (window as any).EventSource = class extends EventTarget { close() {} }; });
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'POST') { writes.push(request.postDataJSON()); return route.fulfill({ json: { status: 'completed', outcome: { trial_id: 't-new' } } }); }
    if (url.pathname === '/api/state') return route.fulfill({ json: state });
    if (url.pathname.endsWith('/metrics')) { metrics.push(url.search); return route.fulfill({ json: [1, 1000, 2000, 4000].map((n, i) => ({ evaluations: n, elapsed_seconds: n / 16, best_objective: 0.2 + i * 0.14 })) }); }
    if (url.pathname.startsWith('/api/v1/problems')) return route.fulfill({ json: { problems: [] } });
    if (url.pathname === '/api/v1/inference-adapters') return route.fulfill({ json: { adapters: [] } });
    return route.fulfill({ status: 404, json: { detail: 'Not in this mock' } });
  });
  return { writes, metrics };
}

test('short runs, long runs and checks are listed apart; obsolete runs are hidden with a reason and can come back', async ({ page }) => {
  const { writes } = await mock(page, fixture());
  await page.goto('/#experiments');
  await expect(page.getByRole('tab', { name: 'Short runs · 3' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tab', { name: 'Long runs · 1' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Checks · 1' })).toBeVisible();
  const table = page.locator('.run-table');
  await expect(table.locator('tbody tr')).toHaveCount(3);
  await expect(table.locator('thead th')).toHaveText(['Select', 'Design', 'Name', 'Status', 'Best', 'Other objectives']);
  await expect(table.getByRole('img').first()).toHaveAttribute('aria-label', '4 × 8 design: 38% silicon');
  await expect(table.locator('tbody tr').first()).toContainText('te plus1 transmission 55.0%');
  // A queued run cannot be selected for hiding; finished ones can.
  await expect(page.getByLabel('Select Screen · H1 · coordinate · seed 1')).toHaveCount(2);
  await page.getByLabel('Show 1 hidden').check();
  await expect(table).toContainText('Hidden: Ran again after the memory fix');
  await page.getByLabel('Show 1 hidden').uncheck();
  await page.getByLabel('Select Screen · H1 · coordinate · seed 1').nth(1).check();
  const bar = page.getByRole('region', { name: 'Hide selected runs' });
  await bar.getByLabel('Why these runs are obsolete').fill('Out of GPU memory; run again');
  await bar.getByRole('button', { name: 'Hide from this page' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ operation: 'trial.hide', payload: { trial_ids: ['t-failed'], hidden: true, reason: 'Out of GPU memory; run again' } });
  await page.getByRole('tab', { name: 'Long runs · 1' }).click();
  await expect(page).toHaveURL(/#experiments\/long$/);
  await expect(table.locator('tbody tr')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('a run opens with the sections the rules choose: its design as an image and its learning curve, read as a few points', async ({ page }) => {
  const { metrics } = await mock(page, fixture());
  await page.goto('/#experiments/t-long');
  const entry = page.getByRole('dialog');
  await expect(entry.getByRole('heading', { name: 'Long · H1 · coordinate · seed 1' })).toBeVisible();
  await expect(entry.locator('.run-section h3')).toHaveText(['Best design', 'Learning curve', 'Objectives', 'Settings']);
  await expect(entry.getByRole('img', { name: '4 × 8 design: 38% silicon' })).toBeVisible();
  await expect(entry).toContainText('4 × 8 cells · 37.5% silicon');
  await expect(entry.getByRole('img', { name: 'Best mean_plus1_transmission against evaluations' })).toBeVisible();
  expect(metrics[0]).toContain('points=400');
  await expect(entry).toContainText('tm plus1 transmission');
  await expect(entry.getByRole('table')).toHaveCount(0);   // no design listed value by value
  await expect(page.getByRole('tab', { name: 'Long runs · 1' })).toHaveAttribute('aria-selected', 'true');
});

test('a queued run is edited in the same form and replaced; a finished one is run again with changes', async ({ page }) => {
  const { writes } = await mock(page, fixture());
  await page.goto('/#experiments/t-queued');
  await page.getByRole('dialog').getByRole('button', { name: 'Edit', exact: true }).click();
  const form = page.getByRole('dialog');
  await expect(form.getByRole('heading', { name: 'Edit the queued run' })).toBeVisible();
  await expect(form.getByLabel('Time cap (minutes)')).toHaveValue('5');
  await expect(form.getByLabel('Algorithm parameters (JSON)')).toHaveValue(/"step": 0.1/);
  await form.getByLabel('Time cap (minutes)').fill('8');
  await form.getByLabel('Random seed').fill('7');
  await form.getByRole('button', { name: 'Launch experiment' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[0]).toMatchObject({ operation: 'trial.create', payload: { wall_seconds: 480, seed: 7, max_steps: 5000, algorithm: 'coordinate', algorithm_config: { step: 0.1 },
    question: 'Screen · H1 · coordinate · seed 1\nDoes coordinate search beat the floor?' } });
  expect(writes[0].payload).not.toHaveProperty('progress');
  expect(writes[1]).toMatchObject({ operation: 'trial.control', payload: { trial_id: 't-queued', action: 'stop', expected_control_revision: 2 } });
  await page.goto('/#experiments/t-done');
  await page.getByRole('dialog').getByRole('button', { name: 'Run again with changes' }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Run again with changes' })).toBeVisible();
  await page.getByRole('dialog').getByLabel('Unit of time cap').selectOption('s');
  await expect(page.getByRole('dialog').getByLabel('Time cap (seconds)')).toHaveValue('300');
});

test('the rules say who changed them and why; the researcher changes the limit and what the page shows', async ({ page }) => {
  const { writes } = await mock(page, fixture());
  await page.goto('/#experiments/rules');
  const rules = page.locator('.experiment-rules');
  await expect(rules).toContainText('Revision 3, last changed by an agent: GPU memory allows two');
  await expect(rules).toContainText('Why: The lead says the shape and the TE/TM balance matter most');
  await expect(rules.getByLabel('Short runs are allotted less than (minutes)')).toHaveValue('10');
  await rules.getByLabel('Runs of this campaign at once').fill('3');
  await rules.getByLabel('Method').check();
  await rules.getByLabel('Why the change').fill('More GPU memory after the upgrade');
  await rules.getByRole('button', { name: 'Save the rules' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ operation: 'experiments.rules', payload: { max_concurrent: 3, expected_revision: 3, rationale: 'More GPU memory after the upgrade',
    presentation: { list_columns: ['thumbnail', 'name', 'method', 'status', 'best', 'objectives'], rationale: 'More GPU memory after the upgrade' } } });
});
