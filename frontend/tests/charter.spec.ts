import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;

async function charterRoutes(page: import('@playwright/test').Page) {
  const posts: { path: string; body: unknown }[] = [];
  let view = JSON.parse(JSON.stringify(f.charterView));
  await page.route('**/api/v1/problem-charters/charter_1**', async route => {
    const url = new URL(route.request().url());
    if (route.request().method() === 'GET') return route.fulfill({ json: view });
    const path = url.pathname.split('/').at(-1)!;
    const body = route.request().postDataJSON();
    posts.push({ path, body });
    if (path === 'edit') {
      for (const change of body.changes as { op: string; path: string; value: unknown }[]) {
        const parts = change.path.split('.');
        let target: Record<string, unknown> = view.charter;
        for (const part of parts.slice(0, -1)) target = target[part] as Record<string, unknown>;
        target[parts.at(-1)!] = change.value;
      }
      const touched = (body.changes as { path: string }[]).map(c => { const parts = c.path.split('.'); return parts[0] === 'variables' ? view.charter.variables[Number(parts[1])].name : parts[1]; });
      view.findings = view.findings.filter((x: { about: string[] }) => !touched.includes(x.about[0]));
    }
    if (path === 'accept-assumptions') { view.charter.quantities.working_days_per_month.accepted = true; view.findings = view.findings.filter((x: { code: string }) => x.code !== 'assumption.unaccepted'); }
    if (path === 'answers') view.charter.questions.find((q: { id: string }) => q.id === body.question_id).answer = body.answer;
    if (path === 'confirm') { view = { ...view, status: 'confirmed' }; return route.fulfill({ json: view }); }
    if (path === 'requests') return route.fulfill({ json: view });   // a request changes nothing until the formulator answers
    view = { ...view, revision: view.revision + 1, blocking: view.findings.filter((x: { severity: string }) => x.severity === 'blocking').length };
    return route.fulfill({ json: view });
  });
  return posts;
}

test('the charter page is a form: findings are settled with numbers, acceptances and answers; Confirm waits for them', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const posts = await charterRoutes(page);
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('finding')).toHaveCount(3);
  await expect(panel.getByTestId('confirm-charter')).toBeDisabled();
  await expect(panel.getByTestId('confirm-why')).toContainText('3 checks to pass first');
  await expect(panel.getByTestId('quantities').getByTestId('quantity')).toHaveCount(4);
  await expect(panel.getByTestId('quantity').nth(1)).toContainText('12');
  // Accept the assumption with one click.
  await panel.getByTestId('accept-assumption').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('accept-assumptions');
  expect(posts.find(p => p.path === 'accept-assumptions')!.body).toEqual({ expected_revision: 2, names: ['working_days_per_month'] });
  await expect(panel.getByTestId('finding')).toHaveCount(2);
  // Type the missing value as a number (commas allowed) and press Enter.
  await panel.locator('[data-code="quantity.no_value"]').getByTestId('finding-value').fill('120,000,000');
  await panel.locator('[data-code="quantity.no_value"]').getByTestId('finding-value').press('Enter');
  await expect.poll(() => posts.map(p => p.path)).toContain('edit');
  expect(posts.find(p => p.path === 'edit')!.body).toMatchObject({ expected_revision: 3, changes: [{ op: 'set', path: 'quantities.monthly_budget_tokens.value', value: 120000000 }] });
  await expect(panel.getByTestId('finding')).toHaveCount(1);
  // Bounds of the decision variable.
  await panel.getByTestId('finding-upper').fill('8000000');
  await panel.getByTestId('finding-upper').press('Enter');
  await expect.poll(() => posts.filter(p => p.path === 'edit').length).toBe(2);
  expect(posts.filter(p => p.path === 'edit')[1].body).toMatchObject({ changes: [{ op: 'set', path: 'variables.0.upper', value: 8000000 }] });
  await expect(panel.getByTestId('finding')).toHaveCount(0);
  // The tables below follow the saved charter: the bound and the value typed on the findings now show there.
  await expect(panel.getByTestId('upper-daily_cap')).toHaveValue('8000000');
  await expect(panel.getByTestId('value-monthly_budget_tokens')).toHaveValue('120000000');
  await expect(panel.getByTestId('confirm-why')).toContainText('2 questions from the formulator to answer first');
  // The first open item is marked next; answering it sends it to the end, compact, and the next one takes the mark.
  await expect(panel.getByTestId('question').first()).toHaveAttribute('data-next', '1');
  await panel.getByTestId('question').first().getByTestId('question-option').first().click();
  await expect.poll(() => posts.map(p => p.path)).toContain('answers');
  expect(posts.find(p => p.path === 'answers')!.body).toMatchObject({ question_id: 'value_scoring', answer: 'Discrete 1-5 impact score' });
  await expect(panel.getByTestId('question').last()).toHaveAttribute('data-question-id', 'value_scoring');
  await expect(panel.getByTestId('question').last()).toContainText('answered');
  await expect(panel.getByTestId('question').last().getByTestId('question-option')).toHaveCount(0);
  await expect(panel.getByTestId('question').first()).toHaveAttribute('data-question-id', 'granularity');
  await expect(panel.getByTestId('question').first()).toHaveAttribute('data-next', '1');
  await expect(panel.getByTestId('questions-state')).toHaveText('1 of 2 to answer');
  await panel.getByTestId('question').first().getByTestId('question-option').first().click();
  await expect(panel.getByTestId('questions-state')).toHaveText('all answered');
  await expect(panel.getByTestId('confirm-charter')).toBeEnabled();
  await panel.getByTestId('confirm-charter').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('confirm');
  await expect.poll(() => recorded.commands.some((c: any) => c.operation === 'campaign.update')).toBe(true);
  // Asking the formulator sends the words alone and is shown as asked until it answers.
  await panel.getByTestId('charter-request').fill('Make the weekly limit follow from the monthly budget');
  await panel.getByTestId('charter-request-send').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('requests');
  expect(posts.find(p => p.path === 'requests')!.body).toEqual({ text: 'Make the weekly limit follow from the monthly budget' });
  await expect(panel.getByTestId('asked')).toContainText('Make the weekly limit follow from the monthly budget');
  await expect(panel.getByTestId('charter-request')).toHaveValue('');
  // A refused post says so beside the control that sent it.
  await page.route('**/api/v1/problem-charters/charter_1/requests', route => route.fulfill({ status: 422, json: { detail: 'The formulator is busy; wait for it to finish or stop it' } }));
  await panel.getByTestId('charter-request').fill('Another change');
  await panel.getByTestId('charter-request-send').click();
  await expect(panel.getByTestId('control-error')).toContainText('The formulator is busy');
  // A non-number is refused before it is sent; the raw charter wraps instead of scrolling sideways.
  await panel.getByTestId('value-n_users').fill('ten');
  await panel.getByTestId('value-n_users').press('Enter');
  await expect(panel.getByText('not a number')).toBeVisible();
  await panel.getByText('Raw charter (JSON)').click();
  const raw = panel.getByTestId('raw-charter');
  await expect(raw).toHaveCSS('white-space', 'pre-wrap');
  expect(await raw.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
});

test('while the formulator works on the answers, the questions say so and nothing asks to be answered again', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: { ...f.adoptedNoteView, charter: { ...f.adoptedNoteView.charter, status: 'running' } } });
  const answered = { ...f.charterView, charter: { ...f.charterView.charter, questions: f.charterView.charter.questions.map(q => ({ ...q, answer: q.options[0] })) }, findings: [] };
  await page.route('**/api/v1/problem-charters/charter_1', route => route.fulfill({ json: answered }));
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('formulator-working')).toContainText('Working on your answers');
  await expect(panel.getByTestId('questions-state')).toContainText('the formulator is revising the charter');
  await expect(panel.getByTestId('question').first()).toContainText('formulator working');
  await expect(panel.getByTestId('question-option')).toHaveCount(0);
  await expect(panel.locator('[data-next="1"]')).toHaveCount(0);
});

test('a finding offers suggested ways out: one click sends the worded request, and the ask box starts from it', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const posts = await charterRoutes(page);
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByRole('heading', { name: 'Checks to pass before confirming' })).toBeVisible();
  const bounds = panel.locator('[data-code="variable.bounds"]');
  await expect(bounds.getByTestId('finding-suggestion')).toHaveCount(1);
  await expect(bounds.getByTestId('finding-suggestion')).toHaveText('Ask the formulator for the bounds of daily_cap');
  // The ask box opens with the suggested words, ready to edit or send.
  await bounds.getByTestId('finding-ask').click();
  await expect(bounds.getByTestId('finding-request')).toHaveValue('daily_cap needs a lower and an upper bound. Take them from the sources.');
  await bounds.getByTestId('finding-ask').click();
  // The suggestion itself is one click.
  await bounds.getByTestId('finding-suggestion').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('requests');
  expect(posts.find(p => p.path === 'requests')!.body).toEqual({ text: 'daily_cap needs a lower and an upper bound. Take them from the sources.' });
  await expect(panel.getByTestId('asked')).toContainText('daily_cap needs a lower and an upper bound');
});
