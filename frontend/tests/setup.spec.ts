import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';

test('a campaign is set up as a conversation: typed answers and choices fill the draft, the identity follows the name, Create goes through setup', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto('/#new');
  await expect(page).toHaveURL(/#new\/setup_1$/);
  const chat = page.getByTestId('setup-chat');
  await expect(chat).toContainText('What shall we call the campaign?');
  await page.getByTestId('setup-composer').fill('Deflector v2');
  await page.getByTestId('setup-composer-send').click();
  await expect(page.getByTestId('page-new')).toContainText('Deflector v2');
  await expect(page.getByTestId('page-new')).toContainText('deflector-v2');
  await expect(chat).toContainText('What do you want to find out?');
  await page.getByTestId('setup-choices').locator('[data-choice="later"]').click();
  await expect(page.getByTestId('page-new')).toContainText('to be formulated with the lead');
  await page.getByTestId('setup-choices').locator('[data-choice="formulate"]').click();
  await expect(chat).toContainText('That is everything');
  await expect(page.getByTestId('create-campaign')).toBeEnabled();
  await page.getByTestId('setup-choices').locator('[data-choice="create"]').click();
  await expect.poll(() => recorded.commands.some((c: any) => c.setup_create)).toBe(true);
  await expect(page).toHaveURL(/#t\/thread_main_deflector-v2\/note/);
  expect((recorded.commands[0] as any).setup_answer).toEqual({ text: 'Deflector v2' });
});
