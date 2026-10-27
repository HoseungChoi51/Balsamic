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

test('the card shows the workspace\'s walls: its deadline, its limits and the only hosts it can reach', async ({ page }) => {
  const deadline = new Date(Date.now() + 50 * 60_000).toISOString();
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, wall_seconds: 3600, deadline_at: deadline, limits: { cpus: 4, memory_gb: 8, gpus: 0 },
      egress: { model: ['chatgpt.com'], package_index: ['pypi.org', 'files.pythonhosted.org'], named: ['github.com'] } },
    { ...workspace, id: 'development_paused', title: 'Paused one', status: 'paused', desired_status: 'paused', deadline_at: '2026-10-27T04:10:40Z',
      error: 'The workspace reached its deadline (2026-10-27 04:10 UTC) and is paused. Its session and work are saved; going on is a new go-ahead.' }] } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  await expect(card.getByTestId('workspace-deadline')).toContainText(/pauses then, in (49|50) min/);
  await expect(card.getByTestId('workspace-limits')).toHaveText('4 CPUs · 8 GB memory · no GPU');
  await expect(card.getByTestId('workspace-egress')).toHaveText('only chatgpt.com (model), pypi.org (packages), files.pythonhosted.org (packages), github.com (approved)');
  const paused = page.locator('[data-workspace="development_paused"]');
  await expect(paused.getByTestId('workspace-deadline')).toContainText('passed');
  await expect(paused.getByTestId('workspace-error')).toContainText('reached its deadline');
  await expect(card.getByTestId('workspace-go-on')).toHaveCount(0);
  // Going on is the researcher's new go-ahead: how long it may run from now.
  let sent: Record<string, unknown> | null = null;
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/development_paused/controls`, route => {
    sent = route.request().postDataJSON(); return route.fulfill({ json: {} });
  });
  await paused.getByTestId('workspace-go-on').locator('select').selectOption('2');
  await paused.getByTestId('workspace-go-on').getByRole('button', { name: 'Resume' }).click();
  await expect.poll(() => sent).toMatchObject({ action: 'resume', wall_seconds: 7200 });
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
            skipped: [{ hypothesis_id: 'hypothesis_b', reason: 'Already bound to random by the researcher' }],
            launched: [{ hypothesis_id: 'hypothesis_a', seed: 0, trial_id: 'trial_1', task_id: 'task_1', consent_id: 'compute_consent_1' }] }
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
  // and started the run the researcher's go-ahead listed for the proposal it bound.
  await expect(bindings).toContainText('started hypothesis_a seed 0: an approved run, by Balsamic');
});

test('an installed library that provides a problem names the problem it added', async ({ page }) => {
  const submission = { id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report,
    manifest: { files: ['libraries/baking-order/pyproject.toml'] } };
  const install = { id: 'library_install_1', submission_id: 's1', requested_at: '2026-10-27T04:00:00Z', finished_at: '2026-10-27T04:01:00Z',
    status: 'installed', actor: 'balsamic', package: 'baking-order', version: '0.1.0', path: 'libraries/baking-order', changes: [],
    entry_points: {}, problem_entry_points: { baking_order: 'baking_order.problem:Problem' }, methods_added: [], missing_methods: [],
    problems_added: ['baking_order'], missing_problems: [] };
  await mockWorkspace(page);
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`, route => route.fulfill({ json: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      submissions: [submission], installs: [install] }] } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const added = page.getByTestId('install-box').getByTestId('install-added');
  await expect(added).toContainText('baking-order 0.1.0 · problems baking_order');
  await expect(added).not.toContainText('methods');
});

test('an install from the library generated from the charter names the generated files the coding agent changed', async ({ page }) => {
  const submission = { id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report,
    manifest: { files: ['libraries/baking_order/pyproject.toml'] } };
  const install = { id: 'library_install_1', submission_id: 's1', requested_at: '2026-10-27T04:00:00Z', finished_at: '2026-10-27T04:01:00Z',
    status: 'installed', actor: 'balsamic', package: 'baking-order', version: '0.1.1', path: 'libraries/baking_order', changes: [],
    entry_points: { baking_order: 'baking_order.adapter:method_plugin' }, methods_added: ['shuffle'], missing_methods: [],
    changed_generated_files: ['libraries/baking_order/pyproject.toml', 'libraries/baking_order/baking_order/harness.py'] };
  await mockWorkspace(page);
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`, route => route.fulfill({ json: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      submissions: [submission], installs: [install] }] } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  await expect(page.getByTestId('install-box').getByTestId('install-changed-generated'))
    .toHaveText('changed from the generated library: pyproject.toml, baking_order/harness.py');
});

test('an install says what Balsamic checked outside the box and names the method it did not install, with what failed', async ({ page }) => {
  const submission = { id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report,
    manifest: { files: ['libraries/baking_order/pyproject.toml'] } };
  const failing = ['conformance (check_function on baking_order): seed 0, evaluation 1: an invalid candidate', 'test_hidden.py::test_on_time[late_first]'];
  const install = { id: 'library_install_1', submission_id: 's1', requested_at: '2026-10-27T04:00:00Z', finished_at: '2026-10-27T04:01:00Z',
    status: 'installed', actor: 'balsamic', package: 'baking-order', version: '0.1.1', path: 'libraries/baking_order', changes: [],
    methods_added: ['shuffle'], missing_methods: [], refused_methods: [{ method_id: 'late_first', reported: 'passed', failing }],
    host_validation: { tests: { passed: 21, failed: 3 }, protected: { passed: 1, failed: 1 }, methods: [
      { method_id: 'shuffle', reported: 'passed', host: 'passed', failed_tests: [] },
      { method_id: 'late_first', reported: 'passed', host: 'failed', failed_tests: [] }] } };
  await mockWorkspace(page);
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`, route => route.fulfill({ json: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', outcome: { state: 'delivered', verdict: 'ready', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' },
      submissions: [submission], installs: [install] }] } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const host = page.getByTestId('install-box').getByTestId('install-host');
  await expect(host).toContainText('checked outside the box 21 tests passed, 3 failed · conformance passed for 1 of 2 methods · protected tests: 1 passed, 1 failed');
  await expect(host.getByTestId('install-refused')).toHaveText(
    `not installed late_first failed outside the box (the coding agent reported passed): ${failing.join('; ')}`);
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

test('the baking order (roadmap G1): Balsamic installs the library that provides the problem, binds the four proposals and starts the 8 approved runs', async ({ page }) => {
  const methods = [['hypothesis_edd', 'Earliest due date', 'bakery_edd'], ['hypothesis_swap', 'Adjacent swap search', 'bakery_swap'],
    ['hypothesis_restarts', 'Random restarts', 'bakery_restarts'], ['hypothesis_exact', 'Exact enumeration', 'bakery_exact']];
  const submission = { id: 's1', commit: '2a3eb0899a', status: 'submitted', created_at: '2026-10-27T03:22:04Z', report,
    manifest: { files: ['libraries/baking-order/pyproject.toml', 'libraries/baking-order/src/baking_order/problem.py'] } };
  const install = { id: 'library_install_1', submission_id: 's1', requested_at: '2026-10-27T04:00:00Z', finished_at: '2026-10-27T04:01:00Z',
    status: 'installed', actor: 'balsamic', package: 'baking-order', version: '0.1.0', path: 'libraries/baking-order', changes: [],
    entry_points: Object.fromEntries(methods.map(([, , m]) => [m, `baking_order.methods:${m}`])), problem_entry_points: { baking_order: 'baking_order.problem:Problem' },
    methods_added: methods.map(([, , m]) => m), missing_methods: [], problems_added: ['baking_order'], missing_problems: [],
    bindings: methods.map(([h, title, m], i) => ({ hypothesis_id: h, title, method: m, task_id: 'task_1', binding_id: `builtin_binding_${i}` })), skipped: [],
    launched: methods.flatMap(([h], i) => [0, 1].map(seed => ({ hypothesis_id: h, seed, trial_id: `trial_${i}_${seed}`, task_id: 'task_1', consent_id: 'compute_consent_1' }))) };
  await mockWorkspace(page);
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`, route => route.fulfill({ json: { enabled: true, workspaces: [
    { ...workspace, title: 'Baking order', hypothesis_ids: methods.map(([h]) => h), status: 'idle',
      outcome: { state: 'delivered', verdict: 'ready', submission_id: 's1', commit: '2a3eb0899a', at: '2026-10-27T03:22:04Z' }, submissions: [submission], installs: [install] }] } }));
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const box = page.getByTestId('install-box');
  await expect(box.getByTestId('install-added')).toContainText('problems baking_order');
  const bindings = box.getByTestId('install-bindings');
  for (const [h, title, m] of methods) {
    await expect(bindings).toContainText(`bound ${title} → ${m} by Balsamic`);
    for (const seed of [0, 1]) await expect(bindings).toContainText(`started ${h} seed ${seed}: an approved run, by Balsamic`);
  }
  await expect(bindings).not.toContainText('not bound');
});

test('the researcher makes a token on the card, sees it once with the commands to deliver from their own coding agent, and a stopped workspace offers none (roadmap H3)', async ({ page }) => {
  let state: Record<string, unknown> = { issued_at: null, last_used_at: null, active: false, revoked: null, stopped: false };
  const made: string[] = [];
  const cli = '/srv/balsamic/deploy/implementation-workspace/balsamic-workspace.mjs';
  const own = { id: 's9', commit: '9f8e7d6c5b', status: 'submitted', created_at: '2026-10-27T05:00:00Z', report, source: 'own_session',
    manifest: { files: ['libraries/oven_trays/pyproject.toml'] } };
  await mockWorkspace(page, { [`/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces`]: { enabled: true, workspaces: [
    { ...workspace, status: 'idle', library: { name: 'oven_trays' }, submissions: [own], installs: [],
      outcome: { state: 'delivered', verdict: 'ready_with_limits', submission_id: 's9', commit: '9f8e7d6c5b', at: '2026-10-27T05:00:00Z' } },
    { ...workspace, id: 'development_stopped', title: 'Stopped one', created_at: '2026-10-27T01:00:00Z', status: 'stopped', desired_status: 'stopped' }] } });
  await page.route(`**/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}/session-token`, route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: state });
    made.push(route.request().method());
    state = { issued_at: new Date().toISOString(), last_used_at: null, active: true, revoked: null, stopped: false };
    return route.fulfill({ json: { token: 'bws_shown_once', issued_at: state.issued_at, workspace_id: WID, cli } });
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/implementations`);
  const card = page.locator(`[data-workspace="${WID}"]`);
  // A delivery from the researcher's own session says so.
  await expect(card.getByTestId('workspace-outcome')).toContainText('Delivered commit 9f8e7d6 from your own session');
  const section = card.getByTestId('own-session');
  await section.locator('summary').click();
  await expect(section.getByTestId('own-token-state')).toHaveText('No token yet.');
  await expect(section.getByTestId('own-token-make')).toHaveText('Make a token');
  await section.getByTestId('own-token-make').click();
  const commands = section.getByTestId('own-commands');
  await expect(commands).toContainText('export BALSAMIC_WORKSPACE_TOKEN=bws_shown_once');
  await expect(commands).toContainText(new RegExp(`export BALSAMIC_WORKSPACE_URL=http://[^\\s]+/api/campaigns/${CAMPAIGN_ID}/implementation-workspaces/${WID}\\n`));
  await expect(commands).toContainText(`node ${cli} clone oven_trays`);
  await expect(commands).toContainText(`node ${cli} submit HEAD --report report.json`);
  await expect(section.getByTestId('own-token-state')).toContainText('it is shown only this once');
  await expect(section.getByTestId('own-token-make')).toHaveText('Make a new token');
  expect(made).toHaveLength(1);
  // Opened again later, the card says a token is active and does not show it.
  await page.reload();
  const again = page.locator(`[data-workspace="${WID}"]`).getByTestId('own-session');
  await again.locator('summary').click();
  await expect(again.getByTestId('own-token-state')).toContainText('A token made just now opens this workspace. It is not shown again');
  await expect(again.getByTestId('own-commands')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('bws_shown_once');
  // A stopped workspace offers no token.
  const stopped = page.locator('[data-workspace="development_stopped"]').getByTestId('own-session');
  await stopped.locator('summary').click();
  await expect(stopped.getByTestId('own-session-stopped')).toContainText('The workspace is stopped, so no token opens it');
  await expect(stopped.getByTestId('own-token-make')).toHaveCount(0);
});
