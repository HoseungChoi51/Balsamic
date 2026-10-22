import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the note shows its sections with math, the glossary and the revisions; Adopt is a command', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/note`);
  const objective = page.getByTestId('section-objective');
  await expect(objective).toContainText('Maximize the first-order efficiency');
  await expect(objective.locator('.katex')).toHaveCount(2);
  await expect(page.getByTestId('section-knobs')).toContainText('fill factor f');
  // Unwritten sections are marked: the gate needs every one before proposals or autopilot.
  await expect(page.getByTestId('section-noise')).toHaveAttribute('data-empty', '1');
  await expect(page.getByTestId('section-noise')).toContainText('not written');
  await expect(page.getByTestId('section-knobs')).not.toHaveAttribute('data-empty', '1');
  await expect(page.getByTestId('page-note')).toContainText('revision 2');
  // The outline says which sections are still to write; written ones fold away to leave them in view.
  await expect(page.getByTestId('outline-item').filter({ hasText: 'Noise' })).toHaveAttribute('data-state', 'missing');
  await expect(page.getByTestId('outline-item').filter({ hasText: 'Objective' })).toHaveAttribute('data-state', 'written');
  await expect(page.getByTestId('outline')).toContainText('still to write');
  await page.getByRole('button', { name: 'Fold written' }).click();
  await expect(objective).toHaveAttribute('data-folded', '1');
  await expect(page.getByTestId('section-noise')).not.toHaveAttribute('data-folded', '1');
  await objective.getByTestId('section-fold').click();
  await expect(objective).not.toHaveAttribute('data-folded', '1');
  await page.getByTestId('adopt').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'problem_note.adopt', payload: { note_id: 'note_demo', revision: 2 }, origin: { thread_id: THREAD_ID } });
  await page.evaluate(() => { location.hash = `#t/${location.hash.split('/')[1]}/note/revisions`; });
  await expect(page.getByTestId('page-note')).toContainText('first draft');
  await expect(page.getByTestId('page-note')).toContainText('the campaign question');
});

test('a proposed edit from the lead is accepted or rejected by the researcher; it never applies by itself', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/note`);
  const annotation = page.getByTestId('annotation');
  await expect(annotation).toContainText('Depth is fixed by the process');
  await expect(annotation.getByTestId('proposed-edit')).toContainText('depth fixed at 300 nm');
  await expect(page.getByTestId('section-constraints')).not.toContainText('300 nm');
  await annotation.getByRole('button', { name: 'Accept into the note' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'note.resolve', payload: { annotation_id: 'annotation_1', choice: 'accept' } });
});

test('Define answers from the glossary without the bus; Challenge goes through note.ask', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/note`);
  const knobs = page.getByTestId('section-knobs');
  const select = async () => { await knobs.locator('li').first().evaluate(el => { const range = document.createRange(); range.selectNodeContents(el); const sel = window.getSelection(); sel?.removeAllRanges(); sel?.addRange(range); }); await knobs.locator('li').first().dispatchEvent('mouseup'); };
  await select();
  const menu = page.getByTestId('annotation-menu');
  await expect(menu).toContainText('period p');
  await menu.getByRole('button', { name: 'Define' }).click();
  await page.getByTestId('annotation-question').fill('What is efficiency?');
  await menu.getByRole('button', { name: 'Ask' }).click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ ask: { kind: 'define', question: 'What is efficiency?', anchor: { section: 'knobs', revision: 2 } } });
  await select();
  await page.getByTestId('annotation-menu').getByRole('button', { name: 'Challenge' }).click();
  await page.getByTestId('annotation-question').fill('Why not depth?');
  await page.getByTestId('annotation-menu').getByRole('button', { name: 'Ask' }).click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'note.ask', payload: { kind: 'challenge', question: 'Why not depth?' }, origin: { thread_id: THREAD_ID } });
});

test('the draft says it can be questioned and edited before adopting; Ask needs no selection and Edit saves a revision as a command', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/note`);
  const guide = page.getByTestId('note-guide');
  await expect(guide).toContainText('not yet adopted');
  await expect(guide).toContainText('Ask about this');
  await expect(guide).toContainText('Edit');
  const knobs = page.getByTestId('section-knobs');
  await knobs.getByTestId('section-ask').click();
  await expect(page.getByTestId('annotation-menu')).toContainText('period p');   // the section's opening words stand as the quote
  await knobs.getByTestId('section-edit').click();
  await expect(page.getByTestId('annotation-menu')).toHaveCount(0);
  const editor = knobs.getByTestId('section-editor');
  await editor.getByTestId('section-editor-text').fill('The period p and the fill factor f.');
  await editor.getByTestId('section-editor-items').fill('period p\nfill factor f');
  await editor.getByTestId('section-editor-save').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'problem_note.revise', payload: { note_id: 'note_demo', sections: { knobs: { text: 'The period p and the fill factor f.', items: ['period p', 'fill factor f'], latex: [] } } }, origin: { thread_id: THREAD_ID } });
  await expect(knobs.getByTestId('section-editor')).toHaveCount(0);
});
