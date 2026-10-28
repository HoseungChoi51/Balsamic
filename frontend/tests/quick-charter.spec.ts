import { test, expect, type Page } from '@playwright/test';
import { mockWorkspace, type Recorded } from './mocks/workspace';
import { CAMPAIGN_ID, THREAD_ID } from './mocks/fixtures';
import * as f from './mocks/fixtures';

// The quick path's screens (roadmap P5): the lead wrote the charter of the baking order (S20) from the researcher's words.
const NOTE_ID = `note_${CAMPAIGN_ID}`;
const written = { ...f.noteView.revision.sections, noise: { text: 'Deterministic: a design always gets the same score.', items: [], latex: [] }, confounders: { text: 'None named.', items: [], latex: [] } };
const assumption = { key: 'assumption.unaccepted:statement0', code: 'assumption.unaccepted', severity: 'blocking', message: 'Assumption: The oven starts at time 0 and the bakes run back to back.', about: [], waivable: false };
const charter = (extra: Record<string, unknown> = {}, doc: Record<string, unknown> = {}) => ({
  id: 'charter_1', title: 'Baking order', status: 'draft', revision: 3, blocking: 1, writer: 'lead', confirmed_revision: null, question_rounds: 0, question_rounds_max: 1, proposals: [], history: [],
  values: { n_bakes: 8 }, errors: {}, findings: [assumption],
  rendered: { summary: 'Order the 8 bakes of one oven to minimize their total lateness.', objective: 'The sum over bakes of how late each ends after its due time, in minutes.' },
  charter: { title: 'Baking order', summary: 'Order the {n_bakes} bakes of one oven to minimize their total lateness.', text: '', waivers: [],
    assumptions: [{ statement: 'The oven starts at time 0 and the bakes run back to back.', accepted: false }],
    quantities: {
      n_bakes: { description: 'Bakes to order', kind: 'integer', role: 'input', value: 8, expression: null, units: '1', origin: 'source' },
      durations: { description: 'Duration of each bake, bake 0 to 7', kind: 'data', role: 'input', value: [30, 45, 20, 60, 35, 25, 50, 40], expression: null, units: 'min', origin: 'source' },
      due_times: { description: 'Due time of each bake, from the oven start', kind: 'data', role: 'input', value: [210, 130, 200, 110, 190, 100, 40, 120], expression: null, units: 'min', origin: 'source' } },
    variables: [{ name: 'order', description: 'The order the bakes go in', representation: 'permutation', shape: ['n_bakes'], lower: null, upper: null, values: [], units: '1', meaning: 'Entry k is the bake that goes k-th.' }],
    constraints: [], metrics: [],
    objective: { name: 'total_lateness', direction: 'minimize', units: 'min', definition: 'The sum over bakes of how late each ends after its due time.' },
    evaluator: { kind: 'declared', problem_id: 'baking_order', notes: 'Runs the bakes back to back in the given order from time 0 and sums how late each ends.', deterministic: true },
    questions: [], ...doc },
  ...extra });
const criteria = [
  { id: 'conversation', label: 'Given in the conversation', holds: true, detail: "From the researcher's words in the conversation" },
  { id: 'evaluator', label: 'An evaluator in closed form', holds: true, detail: 'A new problem baking_order, white box' },
  { id: 'size', label: 'At most 3 decision variables and 10 inputs', holds: true, detail: '1 decision variable, 3 inputs' },
  { id: 'reading', label: "The researcher's words read against the charter", holds: true, detail: 'Read at revision 3: no difference' }];
const reading = (mismatches: unknown[] = []) => ({ id: 'charter_reading_charter_1_r3', revision: 3, status: 'completed', model: { provider: 'deepseek', model: 'deepseek-v4-pro' }, mismatches });
const DUE = { id: 'm1', kind: 'different', path: 'quantities.due_times.value', explanation: 'The fourth due time is 120 in the charter; you said 110.', verbatim: true,
  quote: 'Their due times, in minutes from the oven\'s start: 210, 130, 200, 110, 190, 100, 40, 120.', settled: null };
const START = { id: 'm2', kind: 'added', path: 'assumptions.0', explanation: 'You did not say when the oven starts.', verbatim: true, quote: '', settled: null };
const note = (extra: Record<string, unknown> = {}, quick: Record<string, unknown> = {}, confirmation: Record<string, unknown> | null = { revision: 3, confirmed: false, why: null }) => ({
  ...f.noteView, skips: { skipped: {}, proposals: [] }, charter: { charter: { status: 'draft' } }, confirmation,
  note: { ...f.noteView.note, path: 'quick', charter_id: 'charter_1', status: 'drafting', quick: { holds: true, revision: 3, criteria, reading: reading(), ...quick }, ...extra },
  revision: { ...f.noteView.revision, revision: 3, author: 'lead', reason: 'Read from the charter, revision 3', sections: written } });
const card = (revision: number) => ({ id: `message_charter_confirm_r${revision}`, campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lab_event', kind: 'charter_confirm', note_id: NOTE_ID,
  charter_id: 'charter_1', charter_revision: revision, thread_id: THREAD_ID, created_at: `2026-10-28T10:0${revision}:00Z`,
  content: `The lead wrote the charter from your words (revision ${revision}): confirm it here or on the Charter tab` });

/** The workspace with the quick note and its charter answered by the given functions, which see what was sent so far. */
async function quickWorkspace(page: Page, views: { note: (r: Recorded) => unknown; charter: (r: Recorded) => unknown; cards?: number[] }) {
  const recorded = await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: { ...f.messages, messages: [...f.messages.messages, ...(views.cards || []).map(card)] } });
  await page.route(`**/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`, route => route.fulfill({ json: views.note(recorded) }));
  await page.route('**/api/v1/problem-charters/charter_1**', route => {
    const request = route.request();
    if (request.method() === 'POST') recorded.commands.push({ charter: new URL(request.url()).pathname.split('/').pop(), body: request.postDataJSON() });
    return route.fulfill({ json: views.charter(recorded) });
  });
  return recorded;
}
const sent = (r: Recorded, operation: string) => r.commands.some(c => (c as { operation?: string }).operation === operation);

test('a quick note is read-only with no Adopt and says whether the quick path holds; "Use the full path" makes it a note to edit and adopt', async ({ page }) => {
  const full = { ...f.noteView, skips: { skipped: {}, proposals: [] }, confirmation: null, charter: null, revision: { ...f.noteView.revision, revision: 4, author: 'lead', sections: written },
    note: { ...f.noteView.note, path: 'full', charter_id: null, current_revision: 4, quick: { holds: false, ended: 'the researcher chose the full path', ended_by: 'researcher', criteria, revision: 3, charter_id: 'charter_1' } } };
  const recorded = await quickWorkspace(page, { note: r => sent(r, 'problem_note.full_path') ? full : note(), charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const panel = page.getByTestId('quick-path');
  await expect(panel).toContainText('holds');
  await expect(panel.getByTestId('quick-criterion')).toHaveCount(4);
  await expect(panel.getByTestId('quick-criterion').filter({ hasText: 'read against the charter' })).toHaveAttribute('data-holds', 'true');
  await expect(page.getByTestId('note-source')).toContainText('read from charter revision 3');
  await expect(page.getByTestId('adopt')).toHaveCount(0);
  await expect(page.getByTestId('section-edit')).toHaveCount(0);
  // Taking the full path is said before it is done: it does not come back.
  await panel.getByTestId('use-full-path').click();
  await expect(panel).toContainText('The quick path does not come back');
  expect(recorded.commands).toHaveLength(0);
  await panel.getByTestId('use-full-path-confirm').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'problem_note.full_path', payload: { note_id: NOTE_ID }, origin: { thread_id: THREAD_ID } });
  // Now the note is the researcher's to edit and adopt, and says why the quick path ended.
  await expect(page.getByTestId('quick-path')).toHaveCount(0);
  await expect(page.getByTestId('quick-ended')).toContainText('The quick path ended: the researcher chose the full path');
  await expect(page.getByTestId('adopt')).toBeEnabled();
  await expect(page.getByTestId('section-edit').first()).toBeVisible();
});

test('the card in the conversation shows the lead\'s charter in plain words and confirms it in one click; then the gate is open', async ({ page }) => {
  const confirmed = () => charter({ status: 'confirmed', confirmed_revision: 3, findings: [] });
  const recorded = await quickWorkspace(page, { cards: [3],
    note: r => sent(r, 'problem_note.confirm') ? note({ status: 'confirmed' }, {}, { revision: 3, confirmed: true, why: null }) : note(),
    charter: r => sent(r, 'problem_note.confirm') ? confirmed() : charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const box = page.getByTestId('confirm-card');
  await expect(box).toHaveAttribute('data-state', 'live');
  await expect(box.getByTestId('card-objective')).toContainText('Minimize total_lateness (min): The sum over bakes of how late each ends after its due time, in minutes.');
  await expect(box.getByTestId('card-variables')).toContainText('an order of n_bakes = 8, each item once');
  await expect(box.getByTestId('card-inputs')).toContainText('durations = 30, 45, 20, 60, 35, 25, 50, 40 min');
  await expect(box.getByTestId('card-inputs')).toContainText('due_times = 210, 130, 200, 110, 190, 100, 40, 120 min');
  await expect(box.getByTestId('card-constraints')).toContainText('None beyond the bounds of what is chosen');
  await expect(box.getByTestId('card-evaluator')).toContainText('A new problem, baking_order, built for this campaign');
  await expect(box.getByTestId('card-assumptions')).toContainText('Confirming accepts this assumption');
  await expect(box.getByTestId('card-assumptions')).toContainText('The oven starts at time 0');
  await expect(box.getByTestId('differences-lead')).toContainText('found no difference');
  await box.getByTestId('confirm-card-confirm').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'problem_note.confirm', payload: { note_id: NOTE_ID, charter_id: 'charter_1', revision: 3 }, origin: { thread_id: THREAD_ID } });
  await expect(box).toHaveAttribute('data-state', 'confirmed');
  await expect(box.getByTestId('confirm-card-confirmed')).toContainText('the gate is open');
  await expect(box.getByTestId('confirm-card-confirm')).toHaveCount(0);
});

test('a card the lead wrote over is disabled and points at the newest card, or at the Charter tab when there is none', async ({ page }) => {
  await quickWorkspace(page, { cards: [2, 3], note: () => note(), charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const old = page.locator('[data-testid="confirm-card"][data-revision="2"]');
  const newest = page.locator('[data-testid="confirm-card"][data-revision="3"]');
  await expect(old).toHaveAttribute('data-state', 'stale');
  await expect(old).toContainText('This card is out of date: the lead wrote revision 3 since');
  await expect(old.getByTestId('confirm-card-confirm')).toHaveCount(0);
  await expect(newest).toHaveAttribute('data-state', 'live');
  await old.getByTestId('confirm-card-newest').click();
  await expect(newest).toBeInViewport();
});

test('a stale card with no newer card opens the Charter tab', async ({ page }) => {
  // The lead's revision 3 was not read (a blocking finding of its own), so it has no card: the Charter tab shows it.
  await quickWorkspace(page, { cards: [2], note: () => note({}, { reading: null }), charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const old = page.getByTestId('confirm-card');
  await expect(old).toHaveAttribute('data-state', 'stale');
  await old.getByTestId('confirm-card-newest').click();
  await expect(page).toHaveURL(/note\/charter/);
  await expect(page.getByTestId('charter-panel')).toBeVisible();
});

test('a question of the lead\'s is answered on the card, and the card waits for the revision the lead writes from the answer', async ({ page }) => {
  const asked = [{ id: 'ties', question: 'When two orders are equally late, which goes first?', options: ['The earlier due time first', 'The lower bake number first'], answer: null }];
  const answered = [{ ...asked[0], answer: 'The earlier due time first', sent: true }];
  const waiting = "Answer the lead's questions on the Charter tab (#note/charter) first, or leave them to the lead: When two orders are equally late, which goes first?";
  const revising = 'The lead is revising the charter from what you sent it (your answers, a request or a difference to fix): confirm the revision it writes next';
  const recorded = await quickWorkspace(page, { cards: [3],
    note: r => note({}, {}, { revision: r.commands.length ? 4 : 3, confirmed: false, why: r.commands.length ? revising : waiting }),
    charter: r => r.commands.length ? charter({ revision: 4 }, { questions: answered }) : charter({}, { questions: asked }) });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const box = page.getByTestId('confirm-card');
  await expect(box.getByTestId('confirm-card-confirm')).toBeDisabled();
  await expect(box.getByTestId('confirm-card-why')).toContainText("Answer the lead's questions on the Charter tab first");
  await expect(box.getByTestId('card-question')).toContainText('which goes first?');
  await box.getByTestId('card-question-option').first().click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ charter: 'answers', body: { expected_revision: 3, question_id: 'ties', answer: 'The earlier due time first' } });
  // The answer went to the lead with the round: the card follows the charter, and its one click waits for the lead's next write.
  await expect(box.getByTestId('card-question')).toHaveCount(0);
  await expect(box.getByTestId('card-question-done')).toContainText('Your answer: The earlier due time first');
  await expect(box.getByTestId('confirm-card-why')).toContainText('The lead is revising the charter from what you sent it');
  await expect(box.getByTestId('confirm-card-confirm')).toBeDisabled();
  await expect(box).toHaveAttribute('data-state', 'live');
});

test('what the second reading found is settled on the card: the charter is right, or the lead fixes it; the Charter tab shows the same', async ({ page }) => {
  const why = "Settle each difference the second reading found between your words and the charter first (#note/charter): the charter is right, or ask the lead to fix it. m1 (quantities.due_times.value): The fourth due time is 120 in the charter; you said 110.";
  const recorded = await quickWorkspace(page, { cards: [3], note: () => note({}, { reading: reading([DUE, START]) }, { revision: 3, confirmed: false, why }), charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const box = page.getByTestId('confirm-card');
  await expect(box.getByTestId('differences-lead')).toContainText('found 2 differences');
  await expect(box.getByTestId('confirm-card-confirm')).toBeDisabled();
  await expect(box.getByTestId('confirm-card-why')).toContainText('Settle each difference the second reading found between your words and the charter first: the charter is right');
  const due = box.locator('[data-testid="difference"][data-id="m1"]');
  await expect(due).toContainText('differs');
  await expect(due).toContainText('quantities.due_times.value');
  await expect(due).toContainText('Your words: “Their due times');
  await due.getByTestId('difference-ask').click();
  await due.getByTestId('difference-text').fill('The fourth due time is 110.');
  await due.getByTestId('difference-send').click();
  await expect.poll(() => recorded.commands.length).toBe(1);
  expect(recorded.commands[0]).toMatchObject({ operation: 'problem_note.settle', payload: { note_id: NOTE_ID, revision: 3, mismatches: { m1: 'ask_lead' }, text: 'The fourth due time is 110.' }, origin: { thread_id: THREAD_ID } });
  await box.locator('[data-testid="difference"][data-id="m2"]').getByTestId('difference-right').click();
  await expect.poll(() => recorded.commands.length).toBe(2);
  expect(recorded.commands[1]).toMatchObject({ operation: 'problem_note.settle', payload: { note_id: NOTE_ID, revision: 3, mismatches: { m2: 'right' } } });
  expect((recorded.commands[1] as { payload: Record<string, unknown> }).payload).not.toHaveProperty('text');
  // The Charter tab lists the same differences and says why its Confirm waits.
  await page.evaluate(() => { location.hash = `#t/${location.hash.split('/')[1]}/note/charter`; });
  const panel = page.getByTestId('charter-panel');
  await expect(panel.getByTestId('difference')).toHaveCount(2);
  await expect(panel.getByTestId('confirm-why')).toContainText('Settle each difference the second reading found');
  await expect(panel.getByTestId('confirm-why')).not.toContainText('#note/charter');
  await expect(panel.getByTestId('confirm-charter')).toBeDisabled();
});

test('a settled difference shows how it was settled and offers nothing more to settle', async ({ page }) => {
  const settled = [{ ...DUE, settled: { how: 'right', by: 'researcher', at: '2026-10-28T10:05:00Z', carried_from: 2 } }, { ...START, settled: { how: 'ask_lead', by: 'researcher', at: '2026-10-28T10:06:00Z' } }];
  await quickWorkspace(page, { cards: [3], note: () => note({}, { reading: reading(settled) }), charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const box = page.getByTestId('confirm-card');
  await expect(box.locator('[data-testid="difference"][data-id="m1"]')).toHaveAttribute('data-settled', 'right');
  await expect(box.locator('[data-testid="difference"][data-id="m1"]')).toContainText('the charter is right · from r2');
  await expect(box.locator('[data-testid="difference"][data-id="m2"]')).toContainText('the lead is fixing it');
  await expect(box.getByTestId('difference-right')).toHaveCount(0);
});

test('once the quick path ended, its card says why and points at the note', async ({ page }) => {
  const ended = { ...note({ path: 'full', charter_id: null }, { holds: false, ended: 'it has 4 decision variables (the quick path takes at most 3)', ended_by: 'lead' }), confirmation: null };
  await quickWorkspace(page, { cards: [3], note: () => ended, charter: () => charter() });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const box = page.getByTestId('confirm-card');
  await expect(box).toHaveAttribute('data-state', 'ended');
  await expect(box.getByTestId('confirm-card-ended')).toContainText('The quick path ended: it has 4 decision variables');
  await expect(box.getByTestId('confirm-card-confirm')).toHaveCount(0);
});
