import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';

const plan = { warnings: ['H12 · cyclic_geometric_vnd: each run writes about 4.2 GB (1 run: 4.2 GB).'],
  totals: { runs: 1, worker_seconds: 21600, disk_bytes: 4.5e9, max_workers: 2 },
  runs: [{ label: 'H12 · cyclic_geometric_vnd', method: 'cyclic_geometric_vnd', task_id: 'task_1', task: '256×128 Si/air beam deflector', design: '32,768 binary values',
    seeds: [2], device: 'cuda', wall_seconds: 21600, max_evaluations: 1000000, speed: { seconds_per_evaluation: 0.21, basis: 'measured on trial_7 (18,064 evaluations, cyclic_geometric_vnd, cuda)' },
    evaluations: { expected: 104405, ends_by: 'its wall time' }, other_bytes: 1500000, disk_bytes: 4.5e9,
    outputs: [{ file: 'metrics.jsonl', what: 'progress after each evaluation', bytes: 4.4e9 }, { file: 'observations.jsonl', what: 'every evaluated design with its scores', bytes: 9e7 }] }] };

test('a go-ahead request for experiments shows their plan: speed, evaluations and disk use measured on earlier runs', async ({ page }) => {
  const decision = { ...f.inbox.decisions[0], id: 'approval_1', title: 'Start this work now? About 6 h until results', proposal: 'The lead agent asks to start: one long H12 run.', plan };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, decisions: [decision] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  const card = page.getByTestId('plan-card');
  await expect(card.getByTestId('plan-warnings')).toContainText('each run writes about 4.2 GB');
  await expect(card).toContainText('0.21 s per evaluation, measured on trial_7');
  await expect(card).toContainText('about 104,405 per run, ended by its wall time');
  await expect(card).toContainText('metrics.jsonl');
  await expect(card).toContainText('at most 2 runs go at once on this server');
});

test('a draft opens as its plan: what it asks, whether it can start, and what it will cost', async ({ page }) => {
  const draft = { id: 'draft_1', campaign_id: CAMPAIGN_ID, title: 'Screen H12 at matched cost', revision: 2, status: 'draft',
    procedure: { task_id: 'task_1', seed: 0, wall_seconds: 590, max_steps: 160, question: 'Does H12 beat H13 at **160 evaluations**?' } };
  await mockWorkspace(page, {
    [`/api/v1/campaigns/${CAMPAIGN_ID}/experiments`]: { ...f.experiments, drafts: [draft] },
    '/api/v1/drafts/draft_1': { draft, readiness: { ready: false, blockers: [{ code: 'runtime_profile', message: 'Measure how fast this problem evaluates first.' }] }, plan },
  });
  await page.goto(`/#t/${THREAD_ID}/experiments/drafts`);
  await page.getByTestId('draft-row').click();
  const view = page.getByTestId('draft-view');
  await expect(view).toContainText('Does H12 beat H13 at 160 evaluations?');
  await expect(view.getByTestId('draft-blockers')).toContainText('Measure how fast this problem evaluates first.');
  await expect(view.getByTestId('plan-card')).toContainText('H12 · cyclic_geometric_vnd');
});
