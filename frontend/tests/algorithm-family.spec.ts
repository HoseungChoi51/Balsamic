import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;

test('a proposal shows its algorithm family on the list, the card and the lineage graph; one without a method asks for a choice', async ({ page }) => {
  const hypotheses = f.hypotheses.hypotheses.map(h => h.id === 'hypothesis_a' ? { ...h, algorithm: 'unchosen', algorithm_chosen: false }
    : { ...h, family: 'exact' });
  await mockWorkspace(page, {
    [`/api/v1/campaigns/${CAMPAIGN_ID}/hypotheses`]: { ...f.hypotheses, hypotheses },
    [`/api/v1/campaigns/${CAMPAIGN_ID}/evolution`]: { ...f.evolution, layout: f.evolution.layout.map(n => n.id === 'hypothesis_a' ? { ...n, family: 'local_search' } : n) },
    '/api/v1/hypotheses/hypothesis_b': { ...f.hypothesisCard, hypothesis: { ...f.hypothesisCard.hypothesis, family: 'exact' } },
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const exact = page.locator('[data-testid="hypothesis"][data-record-id="hypothesis_b"]');
  await expect(exact.getByTestId('family')).toHaveText('exact ·');
  const unchosen = page.locator('[data-testid="hypothesis"][data-record-id="hypothesis_a"]');
  await expect(unchosen.getByTestId('unchosen')).toHaveText('no method chosen');
  await expect(unchosen).not.toContainText('hillclimb');
  await page.goto(`/#t/${THREAD_ID}/hypotheses/hypothesis_b`);
  await expect(page.getByTestId('hypothesis-card')).toContainText(/Family\s*exact/);
  await page.goto(`/#t/${THREAD_ID}/evolution/lineage`);
  await expect(page.getByTestId('lineage').locator('g[data-record-id="hypothesis_a"]').getByTestId('lineage-family')).toHaveText('local search');
});
