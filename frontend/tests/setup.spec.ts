import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';

test('a campaign is set up as a conversation: typed answers and choices fill the draft, the identity follows the name, Create goes through setup', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto('/#new');
  await expect(page).toHaveURL(/#new\/setup_\d+$/);
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

test('a setup can be abandoned and started over; a created campaign can be removed from the overview with what to keep', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto('/#new');
  await expect(page).toHaveURL(/#new\/setup_\d+$/);
  const first = page.url();
  await page.getByTestId('setup-composer').fill('Wrong one');
  await page.getByTestId('setup-composer-send').click();
  await page.getByTestId('start-over').click();
  await expect.poll(() => recorded.commands.some((c: any) => c.setup_abandon)).toBe(true);
  await expect.poll(() => page.url()).toMatch(/#new\/setup_\d+$/);
  await expect.poll(() => page.url()).not.toBe(first);
  await expect(page.getByTestId('setup-chat')).not.toContainText('Wrong one');
  await page.goto('/#t/thread_main_demo/overview');
  await expect(page.getByTestId('overview')).toContainText('Demo campaign');
  await page.getByTestId('remove-campaign').click();
  await expect(page.getByTestId('removal-plan')).toContainText('keep records (2.5 MB)');
  await page.getByTestId('removal-plan').locator('input[type=radio]').first().check();
  await page.getByTestId('confirm-removal').click();
  await expect.poll(() => recorded.commands.some((c: any) => c.removal)).toBe(true);
  expect((recorded.commands.find((c: any) => c.removal) as any).removal).toEqual({ keep: 'nothing' });
  await expect(page).toHaveURL(/#new/);
});
