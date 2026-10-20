import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID, AGENTS_THREAD_ID } = f;

test('earlier exchanges fold under a one-sentence title; the last two stay open; expand all opens them', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: f.foldedMessages });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const chat = page.getByTestId('thread-chat');
  await expect(chat.getByTestId('fold')).toHaveCount(2);
  await expect(chat.getByTestId('fold').first()).toContainText('Asked what is known; two proposals and one run exist');
  await expect(chat.getByTestId('fold').nth(1)).toContainText('Try the second one with a warm start.');
  await expect(chat.getByTestId('fold-bar')).toContainText('2 earlier exchanges folded');
  await expect(chat.locator('[data-message-id="message_2"]')).toHaveCount(0);
  await expect(chat.locator('[data-message-id="message_8"]')).toBeVisible();
  await chat.getByTestId('fold').first().locator('summary').click();
  await expect(chat.locator('[data-message-id="message_2"]')).toBeVisible();
  await chat.getByTestId('fold-all').click();
  await expect(chat.locator('[data-message-id="message_4"]')).toBeVisible();
  await expect(chat.getByTestId('fold-all')).toHaveText('Fold all');
});

test('the agents\' side conversation is linked from the request and listed apart in the switcher', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: f.foldedMessages, [`/api/v1/campaigns/${CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [f.thread, f.branch, f.agentsThread] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const chat = page.getByTestId('thread-chat');
  await expect(chat.getByTestId('agents-link')).toContainText('Agents are working on this request in a side conversation');
  await expect(chat.getByTestId('agents-group').locator('option')).toHaveText(['Review of the proposals']);
  await chat.getByTestId('open-agents-thread').click();
  await expect(page).toHaveURL(new RegExp(`#t/${AGENTS_THREAD_ID}/hypotheses`));
  await expect(chat).toContainText('agents');
  await expect(chat.getByTestId('turn').nth(0)).toContainText('to an agent');
  await expect(chat.getByTestId('turn').nth(1)).toContainText('proposal reviewer');
});

test('detaching the chat opens it in its own window and the page fills the main one; reattach brings it back', async ({ page, context }) => {
  await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.getByTestId('thread-chat').getByTestId('toggle-detach')).toBeVisible();
  const popup = context.waitForEvent('page');
  // The button unmounts with the chat column as soon as the window opens, so the click is dispatched without actionability waits.
  await page.getByTestId('thread-chat').getByTestId('toggle-detach').dispatchEvent('click');
  const chatWindow = await popup;
  await mockWorkspace(chatWindow);
  await expect(chatWindow).toHaveURL(new RegExp(`#t/${THREAD_ID}/chat`));
  await expect(chatWindow.getByTestId('shell-detached')).toBeVisible();
  await expect(chatWindow.getByTestId('thread-chat')).toBeVisible();
  await expect(page.locator('.main')).toHaveAttribute('data-detached', '1');
  await expect(page.getByTestId('thread-chat')).toHaveCount(0);
  await expect(page.getByTestId('chat-strip')).toBeVisible();
  // A page link clicked in the detached chat opens the page in the main window, not in the chat window.
  await chatWindow.getByTestId('thread-chat').locator('a', { hasText: '#inbox' }).first().click();
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/inbox`));
  await expect(chatWindow).toHaveURL(new RegExp(`#t/${THREAD_ID}/chat`));
  await page.getByTestId('reattach-strip').click();
  await expect(page.getByTestId('thread-chat')).toBeVisible();
  await expect(page.getByTestId('thread-chat').getByTestId('toggle-detach')).toBeVisible();
  await expect(page.getByTestId('chat-strip')).toHaveCount(0);
});

test('suggestions come from the housekeeper after the last reply; stale ones are not shown', async ({ page }) => {
  const live = { items: [{ label: 'Try the first candidate', text: 'Run the first candidate as a short screening run.' }, { label: 'Why two?', text: 'Why only two candidates?' }], as_of_message_id: 'message_2' };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [{ ...f.thread, suggestions: live }, f.branch] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const suggestions = page.getByTestId('suggestions');
  await expect(suggestions.locator('button')).toHaveText(['Try the first candidate', 'Why two?']);
  await expect(suggestions).toHaveAttribute('data-live', '1');
  await suggestions.locator('button').first().click();
  await expect(page.getByTestId('composer')).toHaveValue('Run the first candidate as a short screening run.');
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/threads`]: { ...f.threads, threads: [{ ...f.thread, suggestions: { ...live, as_of_message_id: 'message_0' } }, f.branch] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.getByTestId('suggestions')).toHaveCount(0);
});
