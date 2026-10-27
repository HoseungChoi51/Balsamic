import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;

test('a proposal the researcher asked for or approved says so, with a link to the message or the go-ahead', async ({ page }) => {
  const asked = { requested_by: { thread_id: THREAD_ID, message_id: 'message_ask' }, approved_by: { decision_id: 'approval_plan', consent_id: 'compute_consent_1' } };
  await mockWorkspace(page, {
    [`/api/v1/campaigns/${CAMPAIGN_ID}/hypotheses`]: { ...f.hypotheses, hypotheses: f.hypotheses.hypotheses.map(h => h.id === 'hypothesis_b'
      ? { ...h, ...asked, readiness: { state: 'not_required', eligible: true, reason: 'Asked for by the researcher.' } } : h) },
    '/api/v1/hypotheses/hypothesis_b': { ...f.hypothesisCard, hypothesis: { ...f.hypothesisCard.hypothesis, ...asked } },
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/hypothesis_b`);
  const card = page.getByTestId('hypothesis-card');
  await expect(card.getByTestId('asked-for').locator('a')).toHaveAttribute('href', `#t/${THREAD_ID}/chat?sel=message_ask`);
  await expect(card.getByTestId('approved').locator('a')).toHaveAttribute('href', `#t/${THREAD_ID}/inbox/approval_plan`);
  await expect(card).toContainText('no concept review needed');
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  await expect(page.locator('[data-testid="hypothesis"][data-record-id="hypothesis_b"]')).toContainText('asked for');
});
