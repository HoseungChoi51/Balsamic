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
    if (path === 'answers') view.charter.questions[0].answer = body.answer;
    if (path === 'confirm') { view = { ...view, status: 'confirmed' }; return route.fulfill({ json: view }); }
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
  await expect(panel.getByTestId('confirm-why')).toContainText('3 blocking findings to settle first');
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
  await expect(panel.getByTestId('confirm-why')).toContainText('1 question from the formulator to answer first');
  // Answer the formulator's question from its options.
  await panel.getByTestId('question-option').first().click();
  await expect.poll(() => posts.map(p => p.path)).toContain('answers');
  expect(posts.find(p => p.path === 'answers')!.body).toMatchObject({ question_id: 'value_scoring', answer: 'Discrete 1-5 impact score' });
  await expect(panel.getByTestId('confirm-charter')).toBeEnabled();
  await panel.getByTestId('confirm-charter').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('confirm');
  await expect.poll(() => recorded.commands.some((c: any) => c.operation === 'campaign.update')).toBe(true);
  // A non-number is refused before it is sent; the raw charter wraps instead of scrolling sideways.
  await panel.getByTestId('value-n_users').fill('ten');
  await panel.getByTestId('value-n_users').press('Enter');
  await expect(panel.getByText('not a number')).toBeVisible();
  await panel.getByText('Raw charter (JSON)').click();
  const raw = panel.getByTestId('raw-charter');
  await expect(raw).toHaveCSS('white-space', 'pre-wrap');
  expect(await raw.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
});
