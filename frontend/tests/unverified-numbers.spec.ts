import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { CAMPAIGN_ID, THREAD_ID, files, messages } from './mocks/fixtures';

const finding = (id: string, extra: Record<string, unknown> = {}) => ({
  id, kind: 'finding', content: `Finding ${id}.`, statement: 'evidence', links: [], source_ids: ['trial_1'], created_at: '2026-10-27T09:00:00Z',
  measurement_ids: ['trial_1'], support: { measurement_ids: ['trial_1'], supporters: [] }, superseded_by: [], restates: [], ...extra,
});

test('a finding with a number none of its evidence holds shows a badge naming it; a sourced one shows none', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/files`]: { ...files,
    findings: [finding('finding_guess', { unverified_numbers: ['0.95'] }), finding('finding_sourced')], superseded_findings: [] } });
  await page.goto(`/#t/${THREAD_ID}/files/assets`);
  const cards = page.getByTestId('finding');
  await expect(cards.filter({ hasText: 'Finding finding_guess.' }).getByTestId('unverified-numbers')).toHaveText('1 unverified number: 0.95');
  await expect(cards.filter({ hasText: 'Finding finding_sourced.' }).getByTestId('unverified-numbers')).toHaveCount(0);
});

test('a reply with numbers nothing its request read holds shows a badge on the message', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: { ...messages, messages: [
    ...messages.messages,
    { id: 'message_3', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: 'The rate 0.005 is about 1/n, 0.0003.',
      unverified_numbers: ['0.0003'], created_at: '2026-10-19T08:06:00Z' },
  ] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const chat = page.getByTestId('thread-chat');
  await expect(chat.locator('[data-message-id="message_3"]').getByTestId('unverified-numbers')).toHaveText('1 unverified number: 0.0003');
  await expect(chat.locator('[data-message-id="message_2"]').getByTestId('unverified-numbers')).toHaveCount(0);
});
