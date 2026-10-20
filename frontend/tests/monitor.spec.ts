import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';
import * as f from './mocks/fixtures';

test('the monitor drawer shows measured and forecast budget, the GPU row and autopilot; the pill reads a digest when one waits', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/monitor`]: { ...f.monitor, pill: { state: 'digest', text: 'Away digest', row: 'digest' }, digest_id: 'digest_1' } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.getByTestId('monitor-pill')).toHaveText('Away digest');
  await page.getByTestId('monitor-pill').click();
  const rows = page.getByTestId('monitor-rows');
  await expect(rows).toContainText('54 s used, 2.0 min allocated of 60.0 min (measured)');
  await expect(rows).toContainText('forecast: measured use plus the remaining allotment of live runs');
  await expect(rows).toContainText('idle · 3 % · 1.0 of 24.0 GiB (measured by nvidia-smi)');
  await expect(rows).toContainText('Off: the lead acts on your requests.');
  await expect(rows.locator('svg.meter')).toHaveCount(2);
  await expect(rows.locator('svg.slots rect')).toHaveCount(2);
  await expect(rows.locator('svg.ring')).toHaveCount(2);
  await page.getByTestId('monitor-drawer').getByRole('link', { name: 'Away digest' }).click();
  await expect(page.getByTestId('page-monitor')).toContainText('While you were away');
  await expect(page.getByTestId('page-monitor')).toContainText('hypothesis_c (worse than the baseline at every rung; autopilot)');
  await expect(page.getByTestId('page-monitor')).toContainText('1 decisions, 0 questions');
  await expect.poll(() => recorded.commands.some((c: any) => c.seen)).toBe(true);
  await expect.poll(async () => { await page.evaluate(() => (window as any).dispatchEvent(new Event('pagehide'))); return recorded.uiEvents.map((e: any) => e.kind); }).toContain('digest.seen');
});

test('autopilot is turned on with a cap through the bus, and off again', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await expect(page.getByTestId('autopilot-toggle')).toHaveText('Autopilot off');
  await page.getByTestId('autopilot-toggle').click();
  await page.getByTestId('autopilot-cap').fill('1800');
  await page.getByTestId('autopilot-on').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'autopilot.set', payload: { enabled: true, compute_cap_seconds: 1800 }, origin: { thread_id: THREAD_ID } });
});

test('the merge dialog asks the lead for a draft and uses it', async ({ page }) => {
  const withDraft = { ...f.branch, merge_draft: { into_thread_id: THREAD_ID, text: 'The second coupling loses by 3 %; keep the first.', written_at: 'now' } };
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [f.thread, withDraft, f.parked] } });
  await page.goto(`/#t/${THREAD_ID}/branches`);
  await page.locator(`[data-thread-id="${f.BRANCH_ID}"]`).getByRole('button', { name: 'Merge into…' }).click();
  await page.getByTestId('draft-note').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'thread.merge_draft', payload: { thread_id: f.BRANCH_ID, into_thread_id: THREAD_ID } });
  await page.getByTestId('use-draft').click();
  await expect(page.getByTestId('merge-dialog').locator('textarea')).toHaveValue('The second coupling loses by 3 %; keep the first.');
  await page.getByTestId('merge-dialog').getByRole('button', { name: 'Merge' }).click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'thread.merge', payload: { note: 'The second coupling loses by 3 %; keep the first.' } });
});

test('during Optimize the iteration progress line shows the best so far and the live runs', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/summary`]: { ...f.summary, stage: { stage: 'optimize', pinned: false, basis: 'a race is running' } } });
  await page.goto(`/#t/${THREAD_ID}/evolution`);
  await expect(page.getByTestId('iteration-progress')).toContainText('best so far 0.5200 (measured)');
  await expect(page.getByTestId('iteration-progress')).toContainText('1 live run');
});

test('the resources, usage and agents tabs draw rings, slots, bars and cards from the snapshots', async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor/resources`);
  const stats = page.getByTestId('machine-stats');
  await expect(stats.locator('svg.ring')).toHaveCount(3);
  await expect(stats).toContainText('16 cores');
  await expect(stats.locator('svg.slots rect')).toHaveCount(3);
  await page.goto(`/#t/${THREAD_ID}/monitor/usage`);
  await expect(page.locator('.bars .bar-row')).toHaveCount(2);
  await expect(page.locator('svg.columns rect')).toHaveCount(1);
  await page.goto(`/#t/${THREAD_ID}/monitor/agents`);
  await expect(page.getByTestId('agent-cards').locator('.agent-card')).toHaveCount(1);
  await expect(page.getByTestId('agent-cards')).toContainText('Waiting for your request');
});
