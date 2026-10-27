import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';

test('the researcher sets the two compute thresholds of the campaign on the Resources page', async ({ page }) => {
  const recorded = await mockWorkspace(page);
  await page.goto(`/#t/${THREAD_ID}/monitor/resources`);
  await expect(page.getByTestId('thresholds-now')).toContainText('up to 60 s starts freely; up to 5.0 min starts with a notice in your inbox');
  await expect(page.getByTestId('thresholds-apply')).toBeDisabled();
  await page.getByTestId('threshold-notice').fill('12');
  await expect(page.getByTestId('thresholds-apply')).toBeDisabled();   // the notice threshold cannot be above the go-ahead threshold
  await page.getByTestId('threshold-notice').fill('2');
  await page.getByTestId('threshold-gate').fill('10');
  await page.getByTestId('thresholds-apply').click();
  await expect.poll(() => recorded.commands.find(c => c.operation === 'campaign.update')?.payload).toMatchObject({ compute_notice_seconds: 120, compute_gate_seconds: 600 });
});

test('work started without a go-ahead shows in the inbox and in front of the researcher until they acknowledge it', async ({ page }) => {
  const notice = { id: 'compute_notice_1', title: 'The experiment operator started a run, about 4 min of compute', what: 'a run', seconds: 240, role: 'experiment_operator', agent_id: 'agent_operator', thread_id: THREAD_ID,
    subjects: ['trial_1'], created_at: '2026-10-19T08:06:00Z' };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/inbox`]: { ...f.inbox, notices: [notice], thresholds: { notice_seconds: 60, gate_seconds: 300 },
    unacknowledged: [{ key: notice.id, kind: 'notice', id: notice.id, title: 'The experiment operator started a run, about 4 min of compute', at: notice.created_at }] } });
  await page.goto(`/#t/${THREAD_ID}/inbox`);
  await expect(page.getByTestId('inbox-notice')).toContainText('Started with a notice: The experiment operator started a run, about 4 min of compute');
  const row = page.getByTestId('compute-notice');
  await expect(row).toContainText('The experiment operator started a run, about 4 min of compute');
  await expect(row).toContainText('new');
  await expect(row.getByRole('link', { name: 'trial_1' })).toHaveAttribute('href', /experiments\/trial_1/);
  await expect(page.getByTestId('compute-thresholds')).toContainText('Longer than 5.0 min, and any coding workspace, waits for your go-ahead.');
});
