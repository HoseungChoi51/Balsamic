import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';

const stuck = { id: 'issue_dep', code: 'dependency_incomplete', status: 'pending', revision: 1, options: ['Discuss with the lead', 'Defer'],
  created_at: '2026-10-22T20:18:34Z', affected: 'trial_b',
  message: 'trial_b is to start after trial_a, which ended without completing (wall budget exhausted), so it cannot start. Start them anyway in their order, or stop them.',
  actions: [{ id: 'start_anyway', label: 'Start them anyway', description: 'Each waiting run starts once the run before it has ended.' },
            { id: 'stop', label: 'Stop them', description: 'The waiting runs are stopped.' }] };
const asked = { id: 'question_1', status: 'pending', created_at: '2026-10-22T21:04:58Z', question: 'Two GPU runs no longer fit before 22:04. Which pair?',
  suggestion: 'Run the seed 101 pair now.', options: ['Run the seed 101 pair', 'Run both pairs past 22:04'] };

test('an issue offers what can be done about it, and a question comes with the lead\'s suggestion and one-click answers', async ({ page }) => {
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, issues: [stuck], questions: [asked] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await expect(page.getByTestId('issue-action')).toHaveText(['Start them anyway', 'Stop them']);
  await expect(page.getByTestId('issue')).toContainText('Mark as handled');
  await page.getByTestId('issue-action').first().click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'issue.resolve')?.payload).toMatchObject({ issue_id: 'issue_dep', choice: 'action', action: 'start_anyway' });
  await expect(page.getByTestId('question-suggestion')).toContainText('Run the seed 101 pair now.');
  await page.getByTestId('question-option').first().click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'agent.message')?.payload).toMatchObject({ message: 'Run the seed 101 pair', question_id: 'question_1' });
});

test('issues the lead closed as no longer holding are listed with its reason, and the researcher can reopen one', async ({ page }) => {
  const closed = { ...stuck, id: 'issue_old', code: 'implementation_job', status: 'resolved', resolved_by: 'lead', resolved_at: '2026-10-26T05:00:00Z', revision: 2, actions: [],
    message: 'Candidate attempts exhausted; inspect validation and review findings.', comment: 'Superseded: H12 is built as a library and bound.' };
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, closed_by_lead: [closed] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  const row = page.getByTestId('closed-issue');
  await expect(row).toContainText('Superseded: H12 is built as a library and bound.');
  await row.locator('summary').click();
  await expect(row).toContainText('Candidate attempts exhausted');
  await row.getByTestId('reopen-issue').click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'issue.reopen')?.payload).toEqual({ issue_id: 'issue_old' });
});

test('what waits in the inbox stays in front of the researcher on every page until they acknowledge it', async ({ page }) => {
  const unacknowledged = [{ key: 'issue_dep:1', kind: 'issue', id: 'issue_dep', title: 'trial_b is to start after trial_a, which ended without completing', at: '2026-10-22T20:18:34Z' },
    { key: 'question_1', kind: 'question', id: 'question_1', title: 'Two GPU runs no longer fit before 22:04. Which pair?', at: '2026-10-22T21:04:58Z' }];
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, issues: [stuck], questions: [asked], unacknowledged } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const notice = page.getByTestId('inbox-notice');
  await expect(notice).toContainText('2 new in your inbox');
  await expect(notice).toContainText('Issue: trial_b is to start after trial_a');
  await expect(notice).toContainText('and 1 more');
  await expect(page).toHaveTitle(/^\(2\) /);
  await expect(page.getByTestId('rail-inbox').locator('.count.waiting')).toBeVisible();   // the rail's count is the monitor's
  // Opening the inbox is not acknowledging: the notice stays, and the new items are marked.
  await notice.getByTestId('open-inbox').click();
  await expect(page.getByTestId('issue')).toContainText('new');
  await expect(page.getByTestId('inbox-notice')).toBeVisible();
  await page.getByTestId('acknowledge-all').click();
  await expect.poll(() => recorded.commands.find(c => c.acknowledge)?.acknowledge).toEqual({ keys: ['issue_dep:1', 'question_1'] });
});

test('a dense paragraph from an agent reads as short paragraphs; code and lists are left alone', async ({ page }) => {
  const dense = 'Researcher explicitly requests long experiments H12 and H13. Execute this scope, not screening. Prepare one long run each of the installed methods. '
    + 'Recommend 1499 s wall each, e.g. on the GPU in sequence. Do not silently allocate longer than that. Record the success criterion, not a promised outcome. '
    + 'Report the learning curves when both runs end.';
  const messages = { ...f.messages, messages: [{ id: 'message_d', campaign_id: CAMPAIGN_ID, role: 'assistant', origin: 'lead', content: dense + '\n\n- one `a. B` item\n- two', created_at: '2026-10-19T08:05:00Z' }] };
  await mockWorkspace(page, { [`/api/v1/threads/${THREAD_ID}/messages`]: messages });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const turn = page.locator('[data-message-id="message_d"] .md');
  await expect(turn.locator('p')).toHaveCount(2);   // three sentences, then the rest: a short last sentence is not left alone
  await expect(turn.locator('p').first()).toHaveText('Researcher explicitly requests long experiments H12 and H13. Execute this scope, not screening. Prepare one long run each of the installed methods.');
  await expect(turn.locator('p').nth(1)).toContainText('e.g. on the GPU in sequence');
  await expect(turn.locator('p').nth(1)).toContainText('Report the learning curves when both runs end.');
  await expect(turn.locator('li')).toHaveCount(2);
  await expect(turn.locator('li code')).toHaveText('a. B');
});

test('a mandate an agent proposes is one card with its envelope and three choices: approve, approve as Explore only, decline', async ({ page }) => {
  const mandate = { id: 'approval_m', title: 'Approve a Screen mandate for this request? About 15 min until results', status: 'pending', resolution_revision: 0, requested_by: 'lead',
    proposal: 'The lead agent proposes a Screen mandate for this request: Build H1 and screen it against coordinate search.\nEnvelope: up to 40 min of worker time and opens 1 coding workspace. Deadline: 120 min after you approve.',
    rationale: 'Build H1 and screen it against coordinate search.', created_at: '2026-10-27T12:00:00Z', recommendation: '0',
    approval_request: { kind: 'mandate', template: 'screen', worker_seconds: 2400, coding_workspaces: 1, model_usd: 2, deadline_minutes: 120 },
    options: [{ id: '0', label: 'Approve', description: 'The requester starts the work at once, within this envelope and deadline.' },
              { id: '1', label: 'Approve as Explore only', description: 'Only work up to your go-ahead threshold in total, with no coding workspace.' },
              { id: '2', label: 'Decline', description: 'The requester is told and nothing starts.' }],
    freshness: { state: 'ready', reason: '', blocked_choice_ids: [] }, presentation: {} };
  const recorded = await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, decisions: [mandate] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  const card = page.getByTestId('decision');
  await expect(card).toContainText('Build H1 and screen it against coordinate search');
  await expect(card.getByTestId('mandate-terms')).toContainText('Screen: the proposals, workspaces and runs the plan names; up to 40.0 min of worker time, 1 coding workspace, $2 of model spend, deadline 2.0 h after you approve.');
  await expect(card.getByRole('button')).toHaveText(['Approve', 'Approve as Explore only', 'Decline']);
  await card.getByRole('button', { name: 'Approve as Explore only' }).click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'decision.resolve')?.payload).toMatchObject({ decision_id: 'approval_m', choice: '1' });
});
