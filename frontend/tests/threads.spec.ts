import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, BRANCH_ID } from './mocks/fixtures';

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
  expect(recorded.commands[2]).toMatchObject({ operation: 'agent.message', payload: { page_agent: 'discussion_moderator' } });
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
