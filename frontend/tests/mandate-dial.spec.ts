import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';
import { CAMPAIGN_ID, THREAD_ID } from './mocks/fixtures';

// The mandate dial in the chat (roadmap R7): the chip beside Send, the envelope form, the bar above the chat with Close.
const MANDATE = `/api/v1/threads/${THREAD_ID}/mandate`;
const screen = { id: 'mandate_1', template: 'screen', label: 'Screen', status: 'active', standing: false, plan: 'Screen coordinate search with longer runs.', hypothesis_ids: [],
  deadline_at: '2026-10-19T10:05:00Z', granted: 'message', envelope: { worker_seconds: 2400, coding_workspaces: 1, model_usd: 2 },
  left: { worker_seconds: 2400, coding_workspaces: 1, model_usd: 2 }, summary: 'Screen (active)', closable: true, closed_by: null, created_at: '2026-10-19T08:05:00Z' };
const view = (current: unknown) => ({ thread_id: THREAD_ID, campaign_id: CAMPAIGN_ID, request: current ? { thread_id: THREAD_ID, message_id: 'message_x', run_id: 'pi_run_x' } : null,
  current, others: [], default_template: 'screen' });

test('a message sent with Screen asks for its envelope, grants the mandate shown above the chat, and Close sends the close command', async ({ page }) => {
  // The campaign's default template sets the dial: Screen here.
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/summary`]: { ...f.summary, row: { ...f.campaignRow, default_template: 'screen' } } });
  const sent = (operation: string) => recorded.commands.find(c => c.operation === operation) as any;
  await page.route(`**${MANDATE}`, route => route.fulfill({ json: view(sent('mandate.close') ? { ...screen, status: 'closed', closable: false, closed_by: 'researcher' }
    : sent('agent.message') ? screen : null) }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.getByTestId('mandate-chip')).toHaveValue('screen');
  await expect(page.getByTestId('mandate-bar')).toHaveCount(0);
  // Send opens the envelope form first; nothing is sent until the researcher grants it.
  await page.getByTestId('composer').fill('Screen coordinate search with longer runs.');
  await page.getByTestId('send').click();
  const form = page.getByTestId('mandate-form');
  await expect(form).toContainText('Screen for this request');
  await expect(page.getByTestId('mandate-minutes')).toHaveValue('30');
  await expect(page.getByTestId('send')).toHaveText('Grant and send');
  expect(recorded.commands).toEqual([]);
  await page.getByTestId('mandate-minutes').fill('40');
  await page.getByTestId('mandate-coding').fill('1');
  await page.getByTestId('mandate-usd').fill('2');
  await page.getByTestId('send').click();
  await expect.poll(() => sent('agent.message')?.payload).toEqual({ message: 'Screen coordinate search with longer runs.', thread_id: THREAD_ID,
    mandate: { template: 'screen', worker_seconds: 2400, coding_workspaces: 1, model_usd: 2, deadline_minutes: 120 } });
  await expect(form).toHaveCount(0);
  // Above the chat: the request's mandate, what is left and its deadline.
  const bar = page.getByTestId('mandate-current');
  await expect(bar).toContainText('Screen');
  await expect(bar).toContainText('This request · left: 40.0 min of worker time, 1 coding workspace, $2.00 of model spend · deadline');
  await expect(bar).toContainText('granted with your message');
  await bar.getByTestId('mandate-close').click();
  await expect.poll(() => sent('mandate.close')).toMatchObject({ campaign_id: CAMPAIGN_ID, payload: { mandate_id: 'mandate_1' }, origin: { thread_id: THREAD_ID } });
  await expect(bar).toContainText('closed by you: new work is refused');
  await expect(bar.getByTestId('mandate-close')).toHaveCount(0);
});

test('Answer and Explore send at once with the message; a slash command carries no mandate; Cancel keeps the text', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const chip = page.getByTestId('mandate-chip');
  await expect(chip).toHaveValue('explore');          // the campaign has no default of its own here: Explore, as by default
  await chip.selectOption('answer');
  await page.getByTestId('composer').fill('Which methods are installed?');
  await page.getByTestId('send').click();
  await expect.poll(() => (recorded.commands.at(-1) as any)?.payload).toEqual({ message: 'Which methods are installed?', thread_id: THREAD_ID, mandate: { template: 'answer' } });
  await expect(chip).toHaveValue('explore');          // back to the default for the next request
  await chip.selectOption('run_campaign');
  await page.getByTestId('composer').fill('/probe');
  await page.getByTestId('send').click();
  await expect.poll(() => (recorded.commands.at(-1) as any)?.operation).toBe('runtime.profile');
  await expect(page.getByTestId('mandate-form')).toHaveCount(0);
  await chip.selectOption('run_campaign');
  await page.getByTestId('composer').fill('Take it from here.');
  await page.getByTestId('send').click();
  await expect(page.getByTestId('mandate-deadline')).toHaveValue('24');
  await page.getByTestId('mandate-cancel').click();
  await expect(page.getByTestId('mandate-form')).toHaveCount(0);
  await expect(page.getByTestId('composer')).toHaveValue('Take it from here.');
  expect(recorded.commands.filter(c => c.operation === 'agent.message')).toHaveLength(1);
});

test('the campaign\'s default mandate is set on the Resources page', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/summary`]: { ...f.summary, row: { ...f.campaignRow, default_template: 'screen' } } });
  await page.goto(`/#t/${THREAD_ID}/monitor/resources`);
  const setting = page.getByTestId('default-template');
  await expect(setting).toHaveAttribute('data-template', 'screen');
  await expect(setting).toContainText('Run the campaign');
  await expect(page.getByText("Not chosen yet, so it follows the campaign's delegation (delegated).")).toBeVisible();
  await page.getByTestId('default-explore').click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'campaign.update')?.payload).toMatchObject({ default_template: 'explore' });
});
