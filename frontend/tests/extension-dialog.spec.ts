import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

// An extension of an agent's session asks the researcher something (harness plan, Phase 4): the answer goes back to the
// waiting extension with agent.ui_respond, not as a message that starts a turn.
const dialog = (method: string, extra: Record<string, unknown>) => ({ id: 'question_ui_1', agent_id: 'lead_demo', kind: 'extension_dialog', status: 'pending',
  question: 'Which source should I trust?', created_at: '2026-10-22T09:00:00Z', deadline_at: 1792656000, dialog: { method, title: 'Which source should I trust?', ...extra } });

test('an extension dialog is answered with one of its options, and can be cancelled', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${f.CAMPAIGN_ID}/inbox`]: { ...f.inbox, questions: [dialog('select', { options: ['arXiv', 'Crossref'] })] } });
  await page.goto(`/#t/${f.THREAD_ID}/inbox`);
  const card = page.getByTestId('extension-dialog');
  await expect(card).toContainText('Which source should I trust?');
  await card.getByRole('button', { name: 'Crossref' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'agent.ui_respond', payload: { question_id: 'question_ui_1', value: 'Crossref' } });
  await card.getByRole('button', { name: 'Cancel the dialog' }).click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'agent.ui_respond', payload: { question_id: 'question_ui_1', cancelled: true } });
});

test('a confirm dialog takes yes or no, and a text dialog its text', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${f.CAMPAIGN_ID}/inbox`]: { ...f.inbox,
    questions: [dialog('confirm', { message: 'It reads 40 pages.' }), { ...dialog('input', { placeholder: 'a name' }), id: 'question_ui_2' }] } });
  await page.goto(`/#t/${f.THREAD_ID}/inbox`);
  const [confirm, input] = [page.getByTestId('extension-dialog').nth(0), page.getByTestId('extension-dialog').nth(1)];
  await expect(confirm).toContainText('It reads 40 pages.');
  await confirm.getByRole('button', { name: 'No' }).click();
  await input.getByTestId('extension-dialog-input').fill('Seo 2022');
  await input.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[0]).toMatchObject({ operation: 'agent.ui_respond', payload: { question_id: 'question_ui_1', value: false } });
  expect(recorded.commands[1]).toMatchObject({ operation: 'agent.ui_respond', payload: { question_id: 'question_ui_2', value: 'Seo 2022' } });
});
