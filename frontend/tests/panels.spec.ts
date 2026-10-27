import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;

test('a panel the formulator composed renders on its page from the catalog; fields write through the panel and buttons through the bus', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView, [`/api/v1/campaigns/${CAMPAIGN_ID}/panels`]: { campaign_id: CAMPAIGN_ID, panels: [f.panel] } });
  const sets: unknown[] = [];
  await page.route('**/api/v1/problem-charters/charter_1', route => route.fulfill({ json: f.charterView }));
  await page.route('**/api/v1/panels/panel_1/set', async route => { const body = route.request().postDataJSON(); sets.push(body);
    await route.fulfill({ json: { ...f.panel, data: { ...f.panel.data, budget: { value: body.value, units: 'token', revision: 3 }, facts: { rows: [{ label: 'Per user', value: 10000000, units: 'token' }] } } } }); });
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('panels-bottom').getByTestId('panel');
  await expect(panel).toHaveAttribute('data-panel-id', 'panel_1');
  await expect(panel).toContainText('Seat budget');
  await expect(panel).toContainText('Seats share one monthly budget.');
  await expect(panel.getByTestId('panel-table').locator('tbody tr')).toHaveCount(2);
  await expect(panel.getByTestId('panel-chart').locator('svg')).toBeVisible();
  await expect(panel.getByTestId('panel-select')).toContainText('Value scoring');
  await panel.getByTestId('panel-budget').fill('120,000,000');
  await panel.getByTestId('panel-budget').press('Enter');
  await expect.poll(() => sets.length).toBe(1);
  expect(sets[0]).toEqual({ component_id: 'budget', value: 120000000 });
  await panel.getByTestId('panel-gen').click();
  await expect.poll(() => recorded.commands.length).toBeGreaterThan(0);
  expect(recorded.commands.at(-1)).toMatchObject({ operation: 'research.generate', payload: { count: 3 }, origin: { thread_id: THREAD_ID } });
  await expect(panel.locator('a', { hasText: 'Hypotheses' })).toHaveAttribute('href', `#t/${THREAD_ID}/hypotheses`);
  // A refused value is reported on the panel.
  await page.route('**/api/v1/panels/panel_1/set', route => route.fulfill({ status: 422, json: { detail: 'Monthly budget is at least 0' } }));
  await panel.getByTestId('panel-budget').fill('-1');
  await panel.getByTestId('panel-budget').press('Enter');
  await expect(panel.getByTestId('panel-error')).toContainText('Monthly budget is at least 0');
});

test('a field bound to the charter shows the charter\'s unit, and a panel label in another unit is called out', async ({ page }) => {
  const scaled = { ...f.panel, components: f.panel.components.map(c => c.type === 'number' ? { ...c, units: 'M token' } : c) };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView, [`/api/v1/campaigns/${CAMPAIGN_ID}/panels`]: { campaign_id: CAMPAIGN_ID, panels: [scaled] } });
  await page.route('**/api/v1/problem-charters/charter_1', route => route.fulfill({ json: f.charterView }));
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const field = page.getByTestId('panels-bottom').getByTestId('panel-number');
  await expect(field.locator('span.faint.small').first()).toHaveText('token');
  await expect(field.getByTestId('panel-unit-mismatch')).toHaveText('the panel says M token; the charter keeps this in token: type it in token');
});

test('a panel the lead made in the conversation shows as a card in the thread with a link to its page', async ({ page }) => {
  const link = { id: 'message_panel_panel_1', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lab_event', kind: 'panel_link', panel_id: 'panel_1', content: 'The lead added a panel to #note/charter: Seat budget', created_at: '2026-10-19T08:06:00Z' };
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: { ...f.messages, messages: [...f.messages.messages, link] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const card = page.getByTestId('panel-card');
  await expect(card).toContainText('The lead added a panel');
  await expect(card.getByTestId('panel')).toContainText('Seat budget');
  await expect(card.getByTestId('panel-number')).toBeVisible();
  await expect(card.getByTestId('open-panel-page')).toHaveAttribute('href', `#t/${THREAD_ID}/note/charter`);
});
