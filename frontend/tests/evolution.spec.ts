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
  // The stop's outcome reads in words, before its free-text reason.
  await expect(table.locator('tr[data-record-id="hypothesis_c"]').getByTestId('stop-outcome')).toHaveText('adequately assessed, deprioritized');
  await expect(table.locator('tr[data-record-id="hypothesis_c"] [title^="stopped: adequately assessed, deprioritized"]')).toHaveCount(1);
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
  await expect(lineage.locator('g[data-record-id="hypothesis_c"] title')).toContainText('stopped: adequately assessed, deprioritized: worse than the baseline');
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

test('the baking order (roadmap G1): four ways to order the bakes rank by total tardiness, least late first', async ({ page }) => {
  const rows: [string, string, string, number][] = [['hypothesis_edd', 'H01', 'Earliest due date', 415], ['hypothesis_swap', 'H02', 'Adjacent swap search', 330],
    ['hypothesis_restarts', 'H03', 'Random restarts', 295], ['hypothesis_exact', 'H04', 'Exact enumeration', 290]];
  const base = evolution.nodes[0];
  const nodes = rows.map(([id, label, title, score]) => ({ ...base, id, label, title, status: 'investigating', algorithm: id.replace('hypothesis_', 'bakery_'),
    live_trials: 0, trial_ids: [], stage: 'extended', best: { ...base.best, score, trial_id: null, direction: 'minimize' } }));
  const baking = { ...evolution, progress: { ...evolution.progress, best_so_far: 290, direction: 'minimize', live_trials: [] }, nodes, edges: [],
    layout: nodes.map((n, lane) => ({ id: n.id, round: 0, lane, stage: n.stage, label: n.label, title: n.title, autonomous: false, stop_reason: null })) };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: baking });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await expect(table.getByTestId('lower-is-better')).toBeVisible();
  await expect(table.locator('tbody tr')).toHaveCount(4);
  expect(await table.locator('tbody tr').evaluateAll(r => r.map(row => row.getAttribute('data-record-id'))))
    .toEqual(['hypothesis_exact', 'hypothesis_restarts', 'hypothesis_swap', 'hypothesis_edd']);
  await expect(page.getByTestId('page-evolution')).toContainText('best so far 290');
});

// Roadmap V5: the gates on the frontier. H01 ran once at its default settings on a problem that declares a fidelity check.
const ORDER_CHECK = { trial_id: 'trial_1', recipe_id: 'meent_2d_order_convergence:v1', parameters: { absolute_tolerance: 0.005 } };
const closedAssessment = { gate: 'assessment', transition: 'stop as inferior', state: 'closed', words: '1 of 3 configurations, 1 seed each', evidence_ids: ['trial_1'],
  why: "An agent's stop as inferior is refused: 1 of 3 configurations; 1 of 2 seeds.", unlock: { runs: 'Run the missing configurations or seeds (5 runs), or stop it as under-evaluated.', check: null, waive: true } };
const closedFidelity = { gate: 'fidelity', transition: 'finalist and library', state: 'closed', words: 'not checked', evidence_ids: ['trial_1'],
  why: 'An agent cannot make it a finalist, nor anyone publish it. meent_2d_order_convergence:v1 has not been checked on its best run (score 0.41).', unlock: { runs: null, check: ORDER_CHECK, waive: true } };
const gated = (assessment: Record<string, unknown>, cursor = 10) => ({ ...evolution, event_cursor: cursor, nodes: evolution.nodes.map(n => n.id !== 'hypothesis_a' ? n : { ...n,
  assessment: { adequate: false, configurations: 1, required_configurations: 3, seeds_per_configuration: 1, required_seeds: 2, stochastic: true, missing: ['1 of 3 configurations', '1 of 2 seeds'], words: '1 of 3 configurations, 1 seed each' },
  fidelity: { state: 'not_checked', trial_id: 'trial_1', score: 0.41, words: 'not checked: meent_2d_order_convergence:v1', checks: [{ ...ORDER_CHECK, state: 'not_checked', requirement_id: null, validation_result_id: null, waiver_id: null }] },
  gates: [assessment, closedFidelity] }) });

test('a gated row shows its state, why it is closed and what unlocks it; a waiver from the row unlocks the transition', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  // The graph answers with the waived gate once the researcher's waiver is sent.
  await page.route(`**/api/v1/campaigns/${CAMPAIGN_ID}/evolution*`, route => {
    const waived = recorded.commands.some(c => c.operation === 'validation.waive');
    const after = Number(new URL(route.request().url()).searchParams.get('after') || 0);
    const body = waived ? gated({ ...closedAssessment, state: 'waived', waiver_id: 'waiver_1', why: undefined, unlock: undefined }, 11) : gated(closedAssessment);
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(after >= body.event_cursor ? { unchanged: true, event_cursor: after } : body) });
  });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const row = page.getByTestId('frontier').locator('tr[data-record-id="hypothesis_a"]');
  await expect(row.getByTestId('gate-assessment')).toHaveAttribute('data-state', 'closed');
  await expect(row.getByTestId('gate-assessment')).toContainText('1 of 3 configurations, 1 seed each');
  await expect(row.getByTestId('gate-fidelity')).toHaveAttribute('data-state', 'closed');
  await expect(row.getByTestId('gate-fidelity')).toContainText('fidelity not checked');
  // A row without gates shows none.
  await expect(page.getByTestId('frontier').locator('tr[data-record-id="hypothesis_b"]').getByTestId('gate-assessment')).toHaveCount(0);
  await row.getByTestId('gate-toggle').click();
  const details = page.getByTestId('gate-details');
  const assessment = details.getByTestId('gate-detail-assessment');
  await expect(assessment.getByTestId('gate-why')).toContainText("An agent's stop as inferior is refused: 1 of 3 configurations; 1 of 2 seeds.");
  await expect(assessment.getByTestId('gate-unlock-runs')).toContainText('Run the missing configurations or seeds (5 runs)');
  await expect(assessment.locator('a', { hasText: 'trial_1' })).toHaveAttribute('href', new RegExp('experiments/trial_1'));
  // The fidelity check to run is one click: validation.run on the best run.
  await details.getByTestId('gate-detail-fidelity').getByTestId('gate-run-check').click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'validation.run')?.payload).toEqual(ORDER_CHECK);
  // A waiver needs the researcher's reason.
  await expect(assessment.getByTestId('waive-assessment')).toBeDisabled();
  await assessment.getByTestId('waive-reason-assessment').fill('its default is the paper\'s setting');
  await assessment.getByTestId('waive-assessment').click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'validation.waive')?.payload)
    .toEqual({ tuning_hypothesis_id: 'hypothesis_a', rationale: "its default is the paper's setting", evidence_ids: ['trial_1'] });
  await expect(row.getByTestId('gate-assessment')).toHaveAttribute('data-state', 'waived');
  await expect(details.getByTestId('gate-detail-assessment')).toContainText('waived by you');
  await expect(details.getByTestId('gate-detail-assessment').getByTestId('waive-assessment')).toHaveCount(0);
  await expect(row.getByTestId('gate-fidelity')).toHaveAttribute('data-state', 'closed');
});

test('the researcher stops with an outcome; a stop as inferior on too few runs says so before it goes through', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: gated(closedAssessment) });
  await page.goto(`/#t/${THREAD_ID}/evolution/frontier`);
  const table = page.getByTestId('frontier');
  await table.locator('tr[data-record-id="hypothesis_a"] input[type=checkbox]').check();
  const bar = page.getByTestId('interventions');
  // Promoting it past its unchecked fidelity is recorded with a warning.
  await expect(bar.getByTestId('promote-unchecked')).toContainText('H01: not checked: meent_2d_order_convergence:v1');
  await bar.getByRole('button', { name: 'Stop…' }).click();
  await expect(bar.getByTestId('stop-thin')).toHaveCount(0);
  await bar.getByTestId('stop-outcome-choice').selectOption('configuration_unpromising');
  await expect(bar.getByTestId('stop-thin')).toContainText('H01: 1 of 3 configurations, 1 seed each');
  await page.getByTestId('stop-reason').fill('lost to H02');
  await bar.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(() => (recorded.commands[0] as any)?.payload.items[0].payload)
    .toMatchObject({ hypothesis_id: 'hypothesis_a', status: 'archived', stop_reason: 'lost to H02', outcome: 'configuration_unpromising' });
});
