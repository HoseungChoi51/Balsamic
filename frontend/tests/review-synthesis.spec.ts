import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;

test("a round shows the moderator's synthesis beside the reviewers' tally, with a badge on each standing against it", async ({ page }) => {
  const round = { number: 1, owner: 'discussion_moderator', trigger: { kind: 'lead', text: 'Review H01 and H02.' }, assistants: [],
    synthesis: { id: 'artifact_synthesis', summary: 'H01 stands; H02 is rejected.', omitted: [], proposals: [
      { hypothesis_id: 'hypothesis_a', title: 'Coordinate search', standing: 'stands', reason: 'The objection is minor.',
        tally: { test: 0, revise: 0, reject: 1 }, against_tally: true, overrides: ['artifact_review_1'] },
      { hypothesis_id: 'hypothesis_b', title: 'Random restarts', standing: 'rejected', reason: 'The reviewer rejected it.',
        tally: { test: 0, revise: 0, reject: 1 } }] },
    status_flags: [{ hypothesis_id: 'hypothesis_b', title: 'Random restarts', status: 'investigating', overrides: ['artifact_review_2'] }] };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/hypotheses`]: { ...f.hypotheses, rounds: { rounds: [round] } } });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/rounds`);
  const synthesis = page.getByTestId('round-synthesis');
  await expect(synthesis).toContainText('H01 stands; H02 is rejected.');
  const standings = synthesis.getByTestId('synthesis-standing');
  await expect(standings).toHaveCount(2);
  await expect(standings.nth(0)).toContainText('reject 1');
  await expect(standings.nth(0).getByText('against the verdicts')).toHaveAttribute('title', 'Goes against artifact_review_1');
  await expect(standings.nth(1).getByText('against the verdicts')).toHaveCount(0);
  await expect(synthesis.getByTestId('status-flag')).toContainText('set to investigating');
});
