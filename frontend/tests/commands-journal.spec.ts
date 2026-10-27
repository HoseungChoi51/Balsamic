import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('a decision resolves through the bus and the command is journaled locally with its outcome', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  const decision = page.getByTestId('decision');
  await expect(decision).toContainText('Extend trial trial_1');
  await decision.getByRole('button', { name: 'Extend by 120 s' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  const command = recorded.commands[0] as any;
  expect(command.operation).toBe('decision.resolve');
  expect(command.payload).toMatchObject({ decision_id: 'extension_1', choice: '0', expected_resolution_revision: 0 });
  const journal = await page.evaluate(() => JSON.parse(localStorage.getItem('balsamic.commands') || '[]'));
  expect(journal).toHaveLength(1);
  expect(journal[0]).toMatchObject({ id: command.id, operation: 'decision.resolve', status: 'completed' });
});

test('a rejected command shows the server\'s reason and stays in the journal as rejected', async ({ page }) => {
  await mockWorkspace(page);
  await page.route('**/api/v1/commands', route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Researcher guidance changed since this command was prepared' }) }));
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await page.getByTestId('decision').getByRole('button', { name: 'Extend by 120 s' }).click();
  await expect(page.getByTestId('decision')).toContainText('Researcher guidance changed');
  const journal = await page.evaluate(() => JSON.parse(localStorage.getItem('balsamic.commands') || '[]'));
  expect(journal[0].status).toBe('rejected');
});

test('telemetry records page opens and chip opens, never message text', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor`);
  await page.getByTestId('thread-chat').locator('a.chip', { hasText: '#inbox' }).first().click();
  await expect(page.getByTestId('page-inbox')).toBeVisible();
  await page.evaluate(() => (window as any).dispatchEvent(new Event('pagehide')));
  await expect.poll(() => recorded.uiEvents.length).toBeGreaterThan(1);
  const kinds = recorded.uiEvents.map((e: any) => e.kind);
  expect(kinds).toContain('page.open'); expect(kinds).toContain('chip.open');
  for (const event of recorded.uiEvents as any[]) expect(JSON.stringify(event)).not.toContain('What do we know');
});
