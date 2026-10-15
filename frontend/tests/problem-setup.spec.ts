import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Views of a flow-reactor charter written by the real charter service (scripts/charter_test_fixtures.py):
// every value, text, finding and difference below was computed by the backend, not by this test.
const fixtures = JSON.parse(readFileSync(new URL('./fixtures/reactor-charter.json', import.meta.url), 'utf8'));
const id = fixtures.id;

async function mock(page: Page) {
  const posts: { path: string; body: any }[] = [];
  let current = fixtures.initial;
  const state: any = { workspace_id: 'w1', campaigns: [], campaign: null, tasks: [], hypotheses: [], trials: [], decisions: [], messages: [], events: [],
    research_runs: [], algorithms: [], settings: { llm_configured: true }, event_cursor: 1 };
  await page.addInitScript(() => { (window as any).EventSource = class extends EventTarget { close() {} }; });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    const body = method === 'POST' ? request.postDataJSON() : undefined;
    if (method === 'POST') posts.push({ path, body });
    const json = (value: any) => route.fulfill({ json: value });
    if (path === '/api/state') return json(state);
    if (path === '/api/v1/problem-examples') return json({ examples: [{ id: 'reactor_example', name: 'Flow reactor', summary: 'Yield of a flow reaction.', instances: [] }] });
    if (path === '/api/v1/problem-charters' && method === 'GET') return json({ charters: [] });
    if (path === '/api/v1/model-tiers') return json({ tiers: [{ id: 'strong', label: 'Strong', model: { provider: 'deepseek', model: 'deepseek-v4-pro', effort: 'max' } }],
      roles: { problem_importer: 'strong' }, providers: { deepseek: { billing: 'api' } } });
    if (path === '/api/v1/problem-charters/from-example') return json(current);
    if (path === `/api/v1/problem-charters/${id}` && method === 'GET') return json(current);
    if (path.endsWith('/preview')) return json(fixtures.preview_flow4);
    if (path.endsWith('/edit')) { current = fixtures.saved; return json(current); }
    if (path.endsWith('/answers')) { current = fixtures.answered; return json(current); }
    if (path.endsWith('/accept-assumptions')) { current = fixtures.ready; return json(current); }
    if (path.endsWith('/requests')) { current = fixtures.proposed; return json(current); }
    if (path.endsWith('/decision')) { current = fixtures.accepted; return json(current); }
    if (path.endsWith('/text-check')) return json({ findings: body.text.includes('80 C') ? [{ key: 'k', code: 'text.literal', severity: 'warning',
      message: 'The research question states 80 C; write {temperature_c} so it follows the value.' }] : [] });
    if (path.endsWith('/confirm')) return json(fixtures.confirmed);
    if (path === '/api/v1/commands') {
      const campaign = { id: body.campaign_id, version: 1, name: body.payload.name, objective: 'x', compute_budget_seconds: 7200, llm_budget_usd: 5, autonomy: 'guided' };
      return json({ id: body.id, request: body, actor: 'researcher', status: 'completed', outcome: { campaign } });
    }
    return route.fulfill({ status: 404, json: { detail: 'Not in this mock' } });
  });
  return { posts };
}

test('a new campaign starts with no problem fields; a charter is reviewed, adjusted, asked about and confirmed', async ({ page }) => {
  const { posts } = await mock(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'New campaign', exact: true }).click();
  await expect(page).toHaveURL(/#new$/);
  await expect(page.getByRole('heading', { name: 'Set up the problem.' })).toBeVisible();
  await expect(page.getByLabel('Problem statement')).toBeVisible();
  await expect(page.getByRole('spinbutton')).toHaveCount(1);   // only the formulator's API budget: no problem field before a start is chosen
  await page.getByRole('button', { name: 'Use', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`#new/${id}$`));

  const text = page.getByRole('region', { name: 'The problem' });
  await expect(text).toContainText('A tubular reactor of 10 mL runs at 5 bar and 80 C.');
  await expect(page.getByRole('heading', { name: 'Flow reactor yield' })).toBeVisible();
  const confirm = page.getByRole('region', { name: 'Confirm' });
  await expect(confirm).toContainText('2 blocking findings');
  await expect(confirm.getByRole('button', { name: /Continue to campaign settings/ })).toBeDisabled();

  // Typing an input recomputes what follows from it, and the text, before anything is saved.
  const derived = page.locator('.charter-derived');
  await expect(derived).toContainText('300 s');
  await page.getByLabel(/^Flow rate/).fill('4');
  await expect(derived).toContainText('150 s');
  await expect(text).toContainText('The residence time follows from the flow rate: 150 s.');
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save' }).click();
  expect(posts.find(p => p.path.endsWith('/edit'))!.body).toEqual({ expected_revision: 1, changes: [{ op: 'set', path: 'quantities.flow_rate_ml_min.value', value: 4 }] });

  // A derived value is read-only; its only control asks for the change in words.
  await expect(derived.getByRole('spinbutton')).toHaveCount(0);
  await derived.getByRole('button', { name: 'Change…' }).first().click();
  await expect(page.getByLabel('Your request')).toHaveValue('Set residence time (residence_time_s) to ');

  // The formulator's question is answered in place; the assumption is accepted from its mark.
  const question = page.getByRole('group', { name: 'Is yield measured as isolated yield or by HPLC area?' });
  await question.getByRole('button', { name: 'Isolated yield' }).click();
  expect(posts.find(p => p.path.endsWith('/answers'))!.body).toEqual({ expected_revision: 2, question_id: 'objective_basis', answer: 'Isolated yield' });
  await page.locator('.charter-inputs').getByRole('button', { name: 'Accept' }).click();
  await expect(confirm).toContainText('Nothing blocks confirming revision 4.');

  // A request becomes options whose numbers were computed by the service.
  await page.getByLabel('Your request').fill('Make the residence time 200 s');
  await page.getByRole('button', { name: 'Ask the formulator' }).click();
  const proposal = page.getByRole('region', { name: 'Proposal: Make the residence time 200 s' });
  await expect(proposal.locator('.proposal-option').first()).toContainText('3 mL/min');
  await expect(proposal.locator('.proposal-option').first()).toContainText('computed');
  await proposal.getByRole('button', { name: 'Accept this option' }).first().click();
  expect(posts.find(p => p.path.endsWith('/decision'))!.body).toEqual({ option: 0 });
  await expect(derived).toContainText('200 s');

  await confirm.getByRole('button', { name: /Continue to campaign settings/ }).click();
  const settings = page.getByRole('form', { name: 'Campaign settings' });
  await expect(settings.getByLabel('Campaign name')).toHaveValue('Flow reactor study');
  await expect(settings.getByLabel('Research question')).toHaveValue('Which ligand gives the best yield?');
  await settings.getByLabel('Research question').fill('Which ligand gives the best yield at 80 C?');
  await expect(settings).toContainText('write {temperature_c} so it follows the value');
  await settings.getByRole('button', { name: 'Confirm revision 5 and create the campaign' }).click();
  await expect(page).toHaveURL(/#overview$/);
  expect(posts.find(p => p.path.endsWith('/confirm'))!.body).toEqual({ expected_revision: 5 });
  const created = posts.find(p => p.path === '/api/v1/commands')!.body;
  expect(created).toMatchObject({ operation: 'campaign.create', payload: { name: 'Flow reactor study', charter: fixtures.confirmed.charter,
    research_question: 'Which ligand gives the best yield at 80 C?', compute_budget_seconds: 7200, autonomy: 'guided' } });
  expect(created.payload).not.toHaveProperty('tasks');
});

test('the details of a charter are folded away, and the page fits a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto(`/#new/${id}`);
  await expect(page.getByRole('heading', { name: 'Flow reactor yield' })).toBeVisible();
  await page.getByText('Evaluator and fidelity').click();
  await expect(page.getByRole('cell', { name: 'flow_reactor_yield' })).toHaveCount(0);
  await expect(page.locator('.charter-details')).toContainText('declared · to be built');
  await page.getByText('Reference results').click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.goto('/#new');
  await expect(page.getByRole('heading', { name: 'Set up the problem.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
