import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;
const WID = 'development_bakery';
export const workspace = {
  id: WID, campaign_id: CAMPAIGN_ID, title: 'Adjacent swap search', hypothesis_id: 'hypothesis_a', hypothesis_ids: ['hypothesis_a', 'hypothesis_b'],
  status: 'running', desired_status: 'running', created_at: '2026-10-27T03:10:32Z', started_at: '2026-10-27T03:10:40Z',
  last_activity_at: new Date(Date.now() - 60_000).toISOString(), cpu_budget_seconds: 300, usage: { container_cpu_seconds: 120 },
  opened_by: { actor: 'lead', role: 'implementation_lead' }, ide_url: '/implementation-workspaces/development_bakery/ide/?folder=/work/repo',
  checkpoints: [{ at: '2026-10-27T03:19:38Z', summary: 'Implemented the library; **32 tests** pass.', next_steps: 'Commit and submit', blocker: 'The evaluator is not commissioned' }],
  last_error_at: '2026-10-27T03:21:40Z', questions: [], submissions: [],
};
const entries = [
  { at: '2026-10-27T03:22:04Z', kind: 'delivery', title: 'Delivered commit 2a3eb08', detail: '32 passed', tone: 'ok', ref: 'development_submission_1', items: [] },
  { at: '2026-10-27T03:21:40Z', kind: 'refused', title: 'Refused: 8 validation errors for SubmissionManifest', detail: 'library_path: extra', tone: 'warn', ref: null, items: [] },
  { at: '2026-10-27T03:20:00Z', kind: 'work', title: 'Worked 12 min · 74 tool calls · 1 failed', detail: 'Both methods pass.', tone: '', ref: null, items: ['bash: FAILED test_replay (exit 1)'] },
];
const opened = { at: '2026-10-27T03:10:32Z', kind: 'opened', title: 'Opened by the implementation lead under your go-ahead', detail: 'Approved plan: build four methods', tone: 'info', ref: 'approval_1', items: [] };

test('a coding workspace is a card with what it is for, how it is going and its history, newest first', async ({ page }) => {
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [workspace] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/timeline**`, route => {
    const before = new URL(route.request().url()).searchParams.get('before');
    return route.fulfill({ json: before ? { entries: [opened], next_before: null } : { entries, next_before: entries[2].at } });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.getByTestId('workspace-card');
  await expect(card).toHaveAttribute('data-status', 'running');
  await expect(card).toContainText('working');
  await expect(card.locator('a.chip')).toHaveCount(2);   // the library serves both proposals
  await expect(card).toContainText('by the implementation lead');
  await expect(card).toContainText('120 of 300 s');
  await expect(card.getByTestId('workspace-checkpoint')).toContainText('32 tests');
  await expect(card.getByTestId('workspace-checkpoint')).toContainText('Blocker: The evaluator is not commissioned');
  await card.getByTestId('workspace-history').locator('summary').first().click();
  const history = card.getByTestId('history-entry');
  await expect(history).toHaveCount(3);
  await expect(history.first()).toContainText('Delivered commit 2a3eb08');
  await expect(history.nth(1)).toHaveAttribute('data-kind', 'refused');
  await history.nth(2).locator('details summary').click();
  await expect(history.nth(2)).toContainText('bash: FAILED test_replay (exit 1)');
  await card.getByTestId('history-older').click();
  await expect(history).toHaveCount(4);
  await expect(history.last()).toContainText('Opened by the implementation lead under your go-ahead');
  await expect(card.getByTestId('history-older')).toHaveCount(0);
});

test('a link to a workspace opens its card with its history', async ({ page }) => {
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [workspace] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/timeline**`, route => route.fulfill({ json: { entries, next_before: null } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations/${WID}`);
  await expect(page.getByTestId('history-entry')).toHaveCount(3);
});

const report = {
  verdict: 'ready_with_limits', summary: 'Four methods and the evaluator work; the evaluator still needs commissioning.',
  methods: [{ method_id: 'bakery_adjacent', hypothesis_id: 'hypothesis_a', state: 'implemented', conformance: 'passed', tests: { passed: 8, failed: 0 } },
            { method_id: 'bakery_dp', hypothesis_id: 'hypothesis_b', state: 'implemented', conformance: 'not_run', tests: { passed: 8, failed: 0 } }],
  tests: { passed: 32, failed: 0, skipped: 0, command: 'pytest libraries/baking-order-search' },
  limitations: ['The evaluator is not commissioned'], next_actions: [{ owner: 'researcher', action: 'Install the library' }, { owner: 'lead', action: 'Commission the evaluator' }],
};

test('while it works the card says its phase, its tests and the coding agent\'s own estimate, said as its own', async ({ page }) => {
  const given = new Date(Date.now() - 2 * 60_000).toISOString();
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, phase: 'testing', tests: { passed: 30, failed: 2 }, estimate: { remaining_minutes: 8, given_at: given, source: 'coding agent' } },
    { ...workspace, id: 'development_late', title: 'Late one', created_at: '2026-10-27T02:00:00Z', estimate: { remaining_minutes: 5, given_at: '2026-10-27T02:10:00Z', source: 'coding agent' } }] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  await expect(card).toContainText('testing');
  await expect(card.getByTestId('workspace-estimate')).toContainText(/about [56] min left: the coding agent's estimate at/);
  await expect(card).toContainText('30 passed, 2 failed');
  await expect(page.locator('[data-workspace="development_late"]').getByTestId('workspace-estimate')).toContainText('has passed; it has given no newer one');
});

test('a delivery shows the coding agent\'s verdict, each method, the limitations and who does what next; the researcher can message it', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      estimate: { remaining_minutes: 4, given_at: '2026-10-27T03:19:38Z', source: 'coding agent' },
      submissions: [{ id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report }] },
    { ...workspace, id: 'development_old', title: 'Old one', status: 'idle', outcome: { state: 'delivered', verdict: 'unreported', submission_id: 's0', commit: '1111111', at: '2026-10-26T00:00:00Z' },
      submissions: [{ id: 's0', commit: '1111111', status: 'submitted', created_at: '2026-10-26T00:00:00Z', notes: 'NOT attach-ready' }] }] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/messages`, async route => {
    recorded.commands.push({ workspace_message: route.request().postDataJSON() }); return route.fulfill({ json: { id: 'cmd' } });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  const outcome = card.getByTestId('workspace-outcome');
  await expect(outcome).toHaveAttribute('data-verdict', 'ready_with_limits');
  await expect(outcome).toContainText('ready, with limits');
  await expect(outcome.getByTestId('outcome-methods').locator('tbody tr')).toHaveCount(2);
  await expect(outcome.getByTestId('outcome-methods')).toContainText('not run');
  await expect(outcome.getByTestId('outcome-limitations')).toContainText('The evaluator is not commissioned');
  await expect(outcome.getByTestId('outcome-next')).toContainText('You Install the library');
  await expect(card.getByTestId('workspace-estimate')).toHaveCount(0);   // the estimate is older than the delivery
  await expect(page.locator('[data-workspace="development_old"]').getByTestId('workspace-outcome')).toContainText('No delivery report');
  await card.getByTestId('workspace-message').fill('What is left?');
  await card.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => recorded.commands.find(c => 'workspace_message' in c)).toMatchObject({ workspace_message: { message: 'What is left?', mode: 'steer' } });
});

test('each implementation result is news in the inbox, linked to its workspace', async ({ page }) => {
  const row = { workspace_id: WID, workspace_title: 'Adjacent swap search', state: 'delivered', verdict: 'ready_with_limits', at: '2026-10-27T03:22:04Z',
    title: 'Implementation delivered: Adjacent swap search: ready, with limits, 32 passed, 0 failed' };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, implementations: [row],
    unacknowledged: [{ key: `implementation:${WID}:delivered:s1`, kind: 'implementation', id: WID, title: row.title, at: row.at }] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await expect(page.getByTestId('inbox-notice')).toContainText(`Implementation: ${row.title}`);
  const item = page.getByTestId('implementation-outcome');
  await expect(item).toContainText('new');
  await expect(item.getByRole('link')).toHaveAttribute('href', new RegExp(`hypotheses/implementations/${WID}`));
});

test('the Algorithms section says what can run, what waits to be installed and by whom, and why the rest cannot', async ({ page }) => {
  const methods = {
    tasks: [{ id: 'task_1', name: 'Bakery schedule', blocker: 'This problem requires a validated evaluator.' }],
    building: [{ workspace_id: 'development_dp', title: 'Subset DP', phase: 'testing', hypothesis_ids: ['hypothesis_b'] }],
    methods: [
      { id: 'random', name: 'Uniform random', source: 'bundled', state: 'runnable', tasks: [{ task_id: 'task_1', runnable: true, reason: null }],
        proposals: [{ hypothesis_id: 'hypothesis_a', bound: true, default: false }], next_action: null },
      { id: 'hillclimb', name: 'Hill climb', source: 'bundled', state: 'runnable', tasks: [{ task_id: 'task_1', runnable: true, reason: null }], proposals: [], next_action: null },
      { id: 'bakery_adjacent', name: 'bakery_adjacent', source: 'submitted', state: 'not_installed', reported: true, verdict: 'ready_with_limits',
        package: { name: 'baking-order-search', version: null, commit: '2a3eb0899a', install_id: null }, workspace_id: WID, submission_id: 's1',
        tasks: [{ task_id: 'task_1', runnable: false, reason: 'Not installed' }], proposals: [{ hypothesis_id: 'hypothesis_b', bound: false, default: false }],
        next_action: { owner: 'researcher', text: 'Install the library on this page' } },
      { id: 'conditional_mirror_search', name: 'Mirror search', source: 'library', state: 'incompatible', package: { name: 'grating-mask-search', version: '0.1.2' },
        tasks: [{ task_id: 'task_1', runnable: false, reason: "Mirror search runs only on meent_2d; this task's problem is bakery" }], proposals: [{ hypothesis_id: 'hypothesis_a', bound: true, default: false }], next_action: null },
    ],
    other: [{ id: 'replay', name: 'Replay', source: 'bundled', reason: 'A procedure for reference evaluation, not a search method' }], other_count: 1,
  };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/methods`]: methods });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const section = page.getByTestId('algorithms');
  await expect(section.getByTestId('task-blocker')).toContainText('Bakery schedule cannot run any method yet: This problem requires a validated evaluator.');
  await expect(section.getByTestId('algorithm-building')).toContainText('Subset DP');
  const rows = section.getByTestId('algorithm');
  await expect(rows).toHaveCount(3);   // the unused bundled method is folded away
  await expect(section.locator('[data-method="random"]')).toContainText('can run');
  const adjacent = section.locator('[data-method="bakery_adjacent"]');
  await expect(adjacent).toContainText('delivered, not installed');
  await expect(adjacent).toContainText('library baking-order-search, delivered in commit 2a3eb08');
  await expect(adjacent).toContainText('(not bound)');
  await expect(adjacent).toContainText('You Install the library on this page');
  await expect(section.locator('[data-method="conditional_mirror_search"]')).toContainText("runs only on meent_2d; this task's problem is bakery");
  await expect(section).toContainText('1 more bundled methods that can run here');
  await expect(section).toContainText('1 methods that cannot run here, or are procedures');
});

test('the researcher installs a delivered library from its card, after a confirmation that says what installing does', async ({ page }) => {
  const submission = { id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report,
    manifest: { files: ['libraries/baking-order-search/pyproject.toml', 'libraries/baking-order-search/src/bakery/dp.py'] } };
  const delivered = { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
    submissions: [submission], installs: [] as Record<string, unknown>[] };
  const posted: Record<string, unknown>[] = [];
  await mockWorkspace(page);
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`, route => route.fulfill({ json: { enabled: true, workspaces: [delivered] } }));
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/submissions/s1/install`, async route => {
    const body = route.request().postDataJSON(); posted.push(body);
    delivered.installs = [{ id: 'library_install_1', submission_id: 's1', requested_at: '2026-10-27T04:00:00Z', package: 'baking-order-search', version: '0.2.0',
      path: 'libraries/baking-order-search', methods_added: [], missing_methods: [], ...(body.confirm_changes
        ? { status: 'installed', methods_added: ['bakery_adjacent', 'bakery_dp'], changes: [{ name: 'numpy', from: '2.1.0', to: '2.3.0' }],
            bindings: [{ hypothesis_id: 'hypothesis_a', title: 'Adjacent swaps', method: 'bakery_adjacent', task_id: 'task_1', binding_id: 'builtin_binding_1' }],
            skipped: [{ hypothesis_id: 'hypothesis_b', reason: 'Already bound to random by the researcher' }] }
        : { status: 'needs_confirmation', changes: [{ name: 'numpy', from: '2.1.0', to: '2.3.0' }] }) }];
    return route.fulfill({ json: delivered.installs[0] });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const box = page.getByTestId('install-box');
  await box.getByTestId('install-open').click();
  const confirm = box.getByTestId('install-confirm');
  await expect(confirm).toContainText('Install libraries/baking-order-search from commit 2a3eb08: the coding agent reports it ready, with limits');
  await expect(confirm).toContainText('The evaluator is not commissioned');
  await expect(confirm).toContainText("Its code runs in the lab's workers");
  await confirm.getByTestId('install-go').click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toMatchObject({ confirm_changes: false, accept_not_ready: false });
  await expect(box.getByTestId('install-changes')).toContainText('numpy 2.1.0 → 2.3.0');
  await box.getByTestId('install-confirm-changes').click();
  await expect.poll(() => posted.length).toBe(2);
  expect(posted[1]).toMatchObject({ confirm_changes: true });
  await expect(box).toContainText('installed');
  await expect(box).toContainText('methods bakery_adjacent, bakery_dp');
  // Balsamic bound what it could by itself and says why it left the rest.
  const bindings = box.getByTestId('install-bindings');
  await expect(bindings).toContainText('bound Adjacent swaps → bakery_adjacent by Balsamic');
  await expect(bindings).toContainText('not bound hypothesis_b: Already bound to random by the researcher');
});

test('a library the coding agent reported not ready installs only once the researcher says so; loose files cannot be installed', async ({ page }) => {
  const notReady = { ...report, verdict: 'not_ready', limitations: [], next_actions: [{ owner: 'lead', action: 'Fix the seed replay' }] };
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'not_ready', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      submissions: [{ id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report: notReady, manifest: { files: ['libraries/bakery/pyproject.toml'] } }] },
    { ...workspace, id: 'development_loose', title: 'Loose', status: 'idle', outcome: { state: 'delivered', verdict: 'unreported', submission_id: 's0', commit: '1111111', at: '2026-10-26T00:00:00Z' },
      submissions: [{ id: 's0', commit: '1111111', status: 'submitted', created_at: '2026-10-26T00:00:00Z', manifest: { files: ['h12_optimizer.py'] } }] }] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  await card.getByTestId('install-open').click();
  await expect(card.getByTestId('install-go')).toBeDisabled();
  await card.getByTestId('install-not-ready').check();
  await expect(card.getByTestId('install-go')).toBeEnabled();
  await expect(page.locator('[data-workspace="development_loose"]').getByTestId('install-unavailable')).toContainText('cannot be installed as a library');
});

test('the status strip shows a coding agent at work with its phase and estimate, and a finished one until its result is acknowledged', async ({ page }) => {
  const given = new Date(Date.now() - 60_000).toISOString();
  const working = { ...workspace, phase: 'testing', estimate: { remaining_minutes: 6, given_at: given, source: 'coding agent' } };
  const done = { ...workspace, id: 'development_done', title: 'Subset DP', status: 'idle',
    outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' } };
  const quiet = { ...workspace, id: 'development_old', title: 'Old and seen', status: 'idle', outcome: { state: 'delivered', verdict: 'ready', submission_id: 's0', commit: '1', at: '2026-10-26T00:00:00Z' } };
  await mockWorkspace(page, {
    [`/api/v1/campaigns/${CAMPAIGN_ID}/agents`]: { ...f.agents, development: { enabled: true, workspaces: [working, done, quiet] } },
    [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, unacknowledged: [{ key: 'implementation:development_done:delivered:s1', kind: 'implementation', id: 'development_done', title: 'Implementation delivered', at: done.outcome.at }] },
  });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  const bar = page.getByTestId('now-toggle');
  await expect(bar).toContainText('coding agent working');
  await bar.click();
  const rows = page.getByTestId('now-coding');
  await expect(rows).toHaveCount(2);   // the one already acknowledged is not shown
  await expect(rows.first()).toContainText('Coding agent · testing');
  await expect(rows.first()).toContainText(/about [56] min left, by its own estimate/);
  await expect(rows.first().getByRole('link')).toHaveAttribute('href', new RegExp(`hypotheses/implementations/${WID}`));
  await expect(rows.nth(1)).toContainText('Coding agent · delivered: ready, with limits');
});

test('a side conversation with implementation work opens on the Implementations page', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: { ...f.messages, messages: [...f.messages.messages,
    { id: 'message_agents_link_x', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lab_event', kind: 'agents_link', link_thread_id: f.AGENTS_THREAD_ID,
      link_page: 'hypotheses/implementations', content: 'Agents are working on this request in a side conversation: Build the library', created_at: '2026-10-27T03:07:19Z' }] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await expect(page.getByTestId('open-agents-thread')).toHaveAttribute('href', `#t/${f.AGENTS_THREAD_ID}/hypotheses/implementations`);
});
