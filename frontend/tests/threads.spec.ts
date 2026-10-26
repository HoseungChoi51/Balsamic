import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, BRANCH_ID } from './mocks/fixtures';
import * as f from './mocks/fixtures';

test('fork here starts a branch and switches to it; the branch shows what it inherited, collapsed', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await page.getByTestId('fork-here').last().click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'thread.fork', payload: { thread_id: THREAD_ID, message_id: 'message_2' }, origin: { thread_id: THREAD_ID } });
  await expect(page).toHaveURL(new RegExp(`#t/${BRANCH_ID}/hypotheses`));
  await expect(page.getByTestId('inherited')).toContainText('Show 2 inherited turns from Demo campaign');
  await expect(page.getByTestId('thread-chat')).toContainText('What about the second coupling?');
  await page.getByTestId('inherited').getByRole('button').click();
  await expect(page.getByTestId('inherited')).toContainText('Hide 2 inherited');
  // The switcher lists every thread with its state; switching keeps the page.
  await page.getByTestId('thread-switch').selectOption(THREAD_ID);
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/hypotheses`));
});

test('edit and resend forks before the edited message and sends the new wording there', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await page.getByTestId('edit-resend').first().click();
  await expect(page.getByTestId('composer')).toHaveValue('What do we know about the deflector so far?');
  await page.getByTestId('composer').fill('What do we know about the deflector at 1100 nm?');
  await page.getByTestId('send').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  // The edited message is the first of the thread: the resend goes into the same thread, marked as an edit.
  expect(recorded.commands[0]).toMatchObject({ operation: 'agent.message', payload: { message: 'What do we know about the deflector at 1100 nm?', edit_of_message_id: 'message_1' } });
});

test('slash commands reach the bus as the commands they name; /help lists them', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/evolution`);
  const sendText = async (text: string) => { await page.getByTestId('composer').fill(text); await page.getByTestId('send').click(); };
  await sendText('/generate 2 hybrid of H01 H02 keep them cheap');
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'research.generate', payload: { count: 2, operation: 'hybrid', parent_ids: ['hypothesis_a', 'hypothesis_b'], note: 'keep them cheap' } });
  await sendText('/park');
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'thread.park', payload: { thread_id: THREAD_ID } });
  await sendText('/review H01');
  await expect.poll(() => recorded.commands.length).toBe(3);
  expect(recorded.commands[2]).toMatchObject({ operation: 'agent.message', payload: { message: 'Ask the discussion moderator to review hypothesis_a in a round and report the verdicts to me.' } });
  expect((recorded.commands[2] as any).payload.page_agent).toBeUndefined();
  await sendText('/help');
  await expect(page.getByTestId('thread-chat')).toContainText('/merge into <thread> <note>');
});

test('the branch map shows lanes with summary cards and activity strips; parking and merging are commands', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/branches`);
  const cards = page.getByTestId('thread-card');
  await expect(cards).toHaveCount(3);
  const parked = page.locator('[data-testid="thread-card"][data-status="parked"]');
  await expect(parked).toContainText('activity only, no model call');
  await expect(parked.locator('[aria-label="activity strip"]')).toHaveText('•▶');
  await page.locator(`[data-thread-id="${BRANCH_ID}"]`).getByRole('button', { name: 'Park' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'thread.park', payload: { thread_id: BRANCH_ID } });
  await page.locator(`[data-thread-id="${BRANCH_ID}"]`).getByRole('button', { name: 'Merge into…' }).click();
  await page.getByTestId('merge-dialog').locator('textarea').fill('The second coupling loses; keep the first.');
  await page.getByTestId('merge-dialog').getByRole('button', { name: 'Merge' }).click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'thread.merge', payload: { thread_id: BRANCH_ID, into_thread_id: THREAD_ID, note: 'The second coupling loses; keep the first.' } });
});

test('the context chip opens the drawer with the three layers and pins through the bus', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await expect(page.getByTestId('context-chip')).toContainText('Context 2.5 KiB · 1 pinned · 1 lab events');
  await page.getByTestId('context-chip').click();
  const drawer = page.getByTestId('context-drawer');
  await expect(drawer).toContainText('Project layer');
  await expect(drawer).toContainText('Estimated from the saved messages');
  await expect(drawer.getByTestId('context-item')).toContainText('Random restarts');
  await drawer.getByTestId('context-item').getByRole('button', { name: 'Exclude' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'thread.pin', payload: { thread_id: THREAD_ID, record_id: 'hypothesis_a', excluded: true } });
  await expect.poll(async () => { await page.evaluate(() => (window as any).dispatchEvent(new Event('pagehide'))); return recorded.uiEvents.map((e: any) => e.kind); }).toContain('context.exclude');
});

test('the chat suggests the next request by stage until the lead has spoken: proposal generation once a problem is set', async ({ page }) => {
  // Once the lead has replied, only live suggestions (from the housekeeper) are shown; stale stage defaults are not.
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.getByTestId('turn')).toHaveCount(2);
  await expect(page.getByTestId('suggestions')).toHaveCount(0);
  const recorded = await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: { ...f.messages, messages: f.messages.messages.slice(0, 1) } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await page.reload();
  const suggestions = page.getByTestId('suggestions');
  await expect(suggestions).toContainText('Three more strategies');
  await suggestions.getByRole('button', { name: 'Three more strategies' }).click();
  await expect(page.getByTestId('composer')).toHaveValue('/generate 3');
  await page.getByTestId('send').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'research.generate', payload: { count: 3, operation: 'diversify' } });
});

test('closed agents\' conversations leave the switcher and are folded apart on the branch map', async ({ page }) => {
  const closedSide = { ...f.agentsThread, id: 'thread_agents_closed0001_' + f.CAMPAIGN_ID, title: 'Screening of H12', status: 'closed',
    summary: { text: '3 messages between the agents. Last: Screens done.', strip: [], as_of_message_id: 'x', written_by: 'activity_only', stale: false, edited: false, reason: 'closed' } };
  await mockWorkspace(page, { [`/api/v1/campaigns/${f.CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [f.thread, f.agentsThread, closedSide] } });
  await page.goto(`/#t/${THREAD_ID}/branches`);
  await expect(page.getByTestId('agents-group').locator('option')).toHaveText(['Review of the proposals']);
  await expect(page.getByText('2 active · 0 parked · 0 merged · 1 closed')).toBeVisible();
  const folded = page.getByTestId('closed-threads');
  await expect(folded).toContainText("1 closed agents' conversation: the work on their requests has ended");
  await expect(folded.getByTestId('thread-card')).toBeHidden();
  await folded.locator('summary').click();
  await expect(folded.getByTestId('thread-card')).toContainText('3 messages between the agents');
});
