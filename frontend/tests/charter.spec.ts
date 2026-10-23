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
  // The formulator's model is named on the tab itself, with where to change it.
  await expect(panel.getByTestId('formulator-model')).toContainText('runs on centinels/gpt-6.1-sol (the "strong" tier; the formulator row under Monitor → Models), 15 calls so far');
  // Names stand apart in the prose and their meaning is written under the finding.
  await expect(panel.getByTestId('finding').first().locator('.qname').first()).toHaveText('working_days_per_month');
  await expect(panel.getByTestId('finding').first().getByTestId('finding-meaning')).toContainText('Working days in the month');
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
  await expect(panel.getByTestId('questions-send')).toHaveText('Leave all 2 to the formulator');   // no answer is required
  await expect(panel.getByTestId('question').first().getByTestId('question-option').first()).toContainText('recommended');
  await panel.getByTestId('question').first().getByTestId('question-option').first().click();
  await expect.poll(() => posts.map(p => p.path)).toContain('answers');
  expect(posts.find(p => p.path === 'answers')!.body).toMatchObject({ question_id: 'value_scoring', answer: 'Discrete 1-5 impact score' });
  // The answered question leaves the open list and folds away under "1 answered"; only the open one is in view.
  await expect(panel.getByTestId('open-questions').getByTestId('question')).toHaveCount(1);
  await expect(panel.getByTestId('open-questions').getByTestId('question')).toHaveAttribute('data-question-id', 'granularity');
  await expect(panel.getByTestId('open-questions').getByTestId('question')).toHaveAttribute('data-next', '1');
  await expect(panel.getByTestId('answered-questions')).toContainText('1 answered');
  await expect(panel.getByTestId('answered-questions').getByTestId('question')).toBeHidden();
  await panel.getByTestId('answered-questions').locator('summary').click();
  await expect(panel.getByTestId('answered-questions').getByTestId('question')).toContainText('Your answer: Discrete 1-5 impact score');
  await expect(panel.getByTestId('answered-questions').getByTestId('question-option')).toHaveCount(0);
  await expect(panel.getByTestId('questions-state')).toHaveText('round 1 of 2 · 1 of 2 open');
  await expect(panel.getByTestId('questions-lead')).toContainText('At most 1 more round of questions can follow');
  await expect(panel.getByTestId('questions-send')).toHaveText('Send 1 answer, leave 1 to the formulator');
  await panel.getByTestId('open-questions').getByTestId('question-option').first().click();
  await expect(panel.getByTestId('questions-state')).toHaveText('round 1 of 2 · all answered');
  await expect(panel.getByTestId('open-questions')).toHaveCount(0);
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
  await expect(panel.getByTestId('formulator-working')).toContainText('Revising the charter from your answers. At most one more round of questions can follow');
  await expect(panel.getByTestId('questions-state')).toContainText('the formulator is revising the charter');
  await expect(panel.getByTestId('question').first()).toContainText('formulator working');
  await expect(panel.getByTestId('question-option')).toHaveCount(0);
  await expect(panel.locator('[data-next="1"]')).toHaveCount(0);
});

test('while the formulator revises the charter nothing takes input, and the page opens again when its revision is saved', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const questions = [{ id: 'grids', question: 'The lab cannot pass a different grid per variable. How should the grids be handled?',
    options: ['The evaluator rounds each variable to its grid', 'Keep the exact grids; nothing runs until the lab supports them'], unrunnable_options: [1], answer: null }];
  let view = { ...f.charterView, formulator: { status: 'running', listening: false }, charter: { ...f.charterView.charter, questions } };
  await page.route('**/api/v1/problem-charters/charter_1', route => route.fulfill({ json: view }));
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('formulator-busy')).toContainText('answers, values and choices wait until it has saved its revision');
  for (const control of [panel.getByTestId('question-option').first(), panel.getByTestId('value-n_users'), panel.getByTestId('confirm-charter'),
                         panel.getByTestId('charter-request'), panel.getByTestId('accept-assumption'), panel.getByTestId('finding-suggestion'), panel.getByTestId('finding-ask').first()])
    await expect(control).toBeDisabled();
  // Its turn ends: the page reads again by itself and everything opens.
  view = { ...view, revision: view.revision + 1, formulator: { status: 'ready', listening: true } };
  await expect(panel.getByTestId('formulator-busy')).toHaveCount(0, { timeout: 6000 });
  await expect(panel.getByTestId('question-option').first()).toBeEnabled();
  await expect(panel.getByTestId('value-n_users')).toBeEnabled();
  // The first option is the recommendation; the one under which nothing can run is never called that.
  await expect(panel.getByTestId('question-option').first()).toContainText('· recommended');
  await expect(panel.locator('[data-unrunnable="1"]')).toContainText('· nothing can run');
  await expect(panel.locator('[data-unrunnable="1"]')).not.toContainText('recommended');
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

test('a proposal reads as an answer: the request in your words, each option with its reason, the computed changes folded, no raw JSON', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  let view = { ...f.charterView, proposals: [f.charterProposal, { ...f.charterProposal, id: 'charter_proposal_old', status: 'rejected' }] };
  const decisions: unknown[] = [];
  await page.route('**/api/v1/problem-charters/charter_1', route => route.fulfill({ json: view }));
  await page.route('**/api/v1/problem-charter-proposals/charter_proposal_1/decision', async route => {
    decisions.push(route.request().postDataJSON());
    view = { ...view, proposals: view.proposals.map(p => p.id === 'charter_proposal_1' ? { ...p, status: 'accepted', accepted_option: 0 } : p) };
    return route.fulfill({ json: view });
  });
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  const proposal = panel.locator('[data-testid="proposal"][data-status="open"]');
  await expect(proposal).toHaveCount(1);
  await expect(proposal).toContainText('Answers your request: “Make the weekly limit follow from the monthly budget”');
  await expect(proposal).not.toContainText('Resolve the weekly-limit request from the sources');   // the formulator's own phrasing stays out
  await expect(proposal.getByTestId('proposal-option')).toHaveCount(2);
  await expect(proposal.getByTestId('proposal-option').first()).toContainText('Derive it from the monthly budget');
  await expect(proposal.getByTestId('proposal-option').first()).toContainText('The monthly budget is the only sourced figure.');
  await expect(proposal).not.toContainText('"op"');   // the changes are described, never dumped as JSON
  await expect(proposal.getByTestId('proposal-option').first().locator('summary')).toContainText('What changes (2)');
  await expect(proposal.getByTestId('proposal-option').first().locator('li').first()).toBeHidden();
  await proposal.getByTestId('proposal-option').first().locator('summary').first().click();
  await expect(proposal.getByTestId('proposal-option').first().locator('li').first()).toContainText('changes quantity weekly_limit_per_seat: 2400000 → monthly_budget_tokens / n_seats / 4');
  await expect(proposal.getByTestId('proposal-option').nth(1)).toContainText('Leaves 1 check open');
  // Earlier proposals are folded away; the open one is the only one in view.
  await expect(panel.getByTestId('decided-proposals')).toContainText('1 earlier proposal');
  await expect(panel.locator('[data-testid="proposal"][data-status="rejected"]')).toBeHidden();
  await proposal.getByTestId('proposal-choose').first().click();
  await expect.poll(() => decisions).toEqual([{ option: 0 }]);
  await expect(panel.locator('[data-testid="proposal"][data-status="open"]')).toHaveCount(0);
  await expect(panel.getByTestId('decided-proposals')).toContainText('2 earlier proposals');
});

test('the last round says so, and the round can be sent with questions left to the formulator', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const posts: { path: string; body: unknown }[] = [];
  const view = { ...f.charterView, question_rounds: 2 };
  await page.route('**/api/v1/problem-charters/charter_1**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: view });
    posts.push({ path: new URL(route.request().url()).pathname.split('/').at(-1)!, body: route.request().postDataJSON() });
    return route.fulfill({ json: view });
  });
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('questions-state')).toHaveText('round 2 of 2 · 2 of 2 open');
  await expect(panel.getByTestId('questions-lead')).toContainText('This is the last round: no further questions can follow.');
  await expect(panel.getByTestId('questions-lead')).toContainText('You are not expected to know every answer');
  await panel.getByTestId('questions-send').click();
  await expect.poll(() => posts.map(p => p.path)).toContain('send-answers');
  expect(posts.find(p => p.path === 'send-answers')!.body).toMatchObject({ expected_revision: 2 });
});

test('a question sent without an answer is shown as left to the formulator, with nothing to answer', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const [first, second] = f.charterView.charter.questions;
  const view = { ...f.charterView, charter: { ...f.charterView.charter, questions: [{ ...first, answer: first.options[0], sent: true }, { ...second, sent: true }] }, findings: [] };
  await page.route('**/api/v1/problem-charters/charter_1**', route => route.fulfill({ json: view }));
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('questions-state')).toHaveText('round 1 of 2 · 1 left to the formulator');
  await expect(panel.getByTestId('left-questions').getByTestId('question')).toHaveAttribute('data-left', '1');
  await expect(panel.getByTestId('left-questions')).toContainText('left to the formulator');
  await expect(panel.getByTestId('question-option')).toHaveCount(0);
  await expect(panel.getByTestId('questions-send')).toHaveCount(0);
});

test('a suggested edit applies computed changes as the researcher, in one click', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: f.adoptedNoteView });
  const posts: { path: string; body: any }[] = [];
  const finding = { key: 'evaluator.mixed_values:variables', code: 'evaluator.mixed_values', severity: 'blocking', about: ['daily_cap'], waivable: false,
    message: 'The lab can give an evaluator that is still to be built only one list of permitted values, shared by every discrete variable, and these have different lists: daily_cap takes 1, 2, 5. This is a limit of the lab, not of your problem.',
    suggestions: [{ label: 'Write them as ranges; the evaluator rounds to each grid', action: 'edit', changes: [{ op: 'set', path: 'variables.0.representation', value: 'continuous' }, { op: 'set', path: 'variables.0.lower', value: 1 }, { op: 'set', path: 'variables.0.upper', value: 5 }],
      rationale: 'Discrete variables written as ranges the evaluator rounds', text: 'Each discrete variable becomes a range from its lowest to its highest permitted value.' },
      { label: 'Ask the formulator for another way to encode them', action: 'request', text: 'Propose another encoding.' }] };
  const view = { ...f.charterView, findings: [finding], blocking: 1 };
  await page.route('**/api/v1/problem-charters/charter_1**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: view });
    posts.push({ path: new URL(route.request().url()).pathname.split('/').at(-1)!, body: route.request().postDataJSON() });
    return route.fulfill({ json: { ...view, findings: [], blocking: 0 } });
  });
  await page.goto(`/#t/${THREAD_ID}/note/charter`);
  const panel = page.getByTestId('charter-panel');
  const row = panel.getByTestId('finding').first();
  await expect(row).toContainText('a limit of the lab, not of your problem');
  await expect(row.getByTestId('finding-suggestions')).toContainText('Each discrete variable becomes a range');
  const fix = row.getByTestId('finding-suggestion').first();
  await expect(fix).toHaveAttribute('data-action', 'edit');
  await expect(fix).toHaveClass(/primary/);
  await fix.click();
  await expect.poll(() => posts.map(p => p.path)).toContain('edit');
  expect(posts.find(p => p.path === 'edit')!.body).toMatchObject({ expected_revision: 2, rationale: 'Discrete variables written as ranges the evaluator rounds', changes: [{ path: 'variables.0.representation', value: 'continuous' }, { path: 'variables.0.lower', value: 1 }, { path: 'variables.0.upper', value: 5 }] });
});
