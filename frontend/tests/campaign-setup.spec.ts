import { test, expect } from '@playwright/test';
import { emptyWorkspace } from './setupFixtures';

test('creating a campaign opens the problem setup, where no problem field exists before a start is chosen', async ({ page }) => {
  await emptyWorkspace(page, path => path === '/api/v1/problem-charters' ? { charters: [] } : path === '/api/v1/model-tiers'
    ? { tiers: [{ id: 'strong', label: 'Strong', model: { provider: 'deepseek', model: 'deepseek-v4-pro', effort: 'max' } }], roles: { problem_importer: 'strong' }, providers: {} } : undefined);
  await page.goto('/');
  await page.getByRole('button', { name: 'Create campaign', exact: true }).click();
  await expect(page).toHaveURL(/#new$/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('list', { name: 'Steps' })).toContainText('Start');
  await expect(page.getByLabel('Problem statement')).toBeVisible();
  await expect(page.getByText('1D binary grating · 1100 nm, 50° deflector')).toBeVisible();
  await expect(page.getByLabel('wavelength_nm', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Problem adapter')).toHaveCount(0);
});

test('a campaign made from a charter edits its settings and research question; the problem stays with the charter', async ({ page }) => {
  const charter = { id: 'problem_charter_1', revision: 3 };
  const { commands } = await emptyWorkspace(page, path => {
    if (path === '/api/v1/problem-charters/problem_charter_1') return { id: 'problem_charter_1', revision: 3, status: 'confirmed', confirmed_revision: 3,
      charter: { title: 'Flow reactor yield', quantities: { temperature_c: { description: 'Reaction temperature', kind: 'number', role: 'input', value: 80, units: 'C', origin: 'researcher' } }, citations: [] },
      values: { temperature_c: 80 }, rendered: { text: 'Run at 80 C.', summary: '' } };
    return undefined;
  });
  await page.route('**/api/state', route => route.fulfill({ json: {
    workspace_id: 'setup-workspace', campaigns: [], hypotheses: [], trials: [], decisions: [], messages: [], events: [], research_runs: [], algorithms: [],
    settings: { llm_configured: false }, event_cursor: 1,
    campaign: { id: 'c1', name: 'Reactor', version: 2, objective: 'Which ligand?\n\nRun at 80 C.', research_question: 'Which ligand?', charter,
      compute_budget_seconds: 3600, llm_budget_usd: 5, validation_reserve_seconds: 0, delegated_trial_seconds: 60, autonomy: 'guided' },
    tasks: [{ id: 't1', name: 'Base', split: 'development', problem: { primary_objective: { name: 'isolated_yield', direction: 'maximize', units: 'fraction' },
      candidate_schema: { representation: 'continuous', dimensions: 3 } } }] } }));
  await page.goto('/#problem');
  await expect(page.getByRole('region', { name: 'Problem charter' }).or(page.locator('.panel', { hasText: 'Problem charter' })).first()).toContainText('Run at 80 C.');
  await expect(page.getByText('Which ligand?')).toBeVisible();
  await page.getByRole('button', { name: 'Campaign settings' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Campaign settings' })).toBeVisible();
  await expect(dialog.getByLabel('Research question')).toHaveValue('Which ligand?');
  await expect(dialog.getByText('Problem instances')).toHaveCount(0);
  await dialog.getByLabel('Research question').fill('Which ligand, at what loading?');
  await dialog.getByRole('button', { name: 'Save new version' }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].operation).toBe('campaign.update');
  expect(commands[0].payload.research_question).toBe('Which ligand, at what loading?');
  expect(commands[0].payload).not.toHaveProperty('tasks');
  expect(commands[0].payload).not.toHaveProperty('objective');
});
