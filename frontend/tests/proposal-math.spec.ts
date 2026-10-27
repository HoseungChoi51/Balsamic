import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import * as f from './mocks/fixtures';

const { THREAD_ID, CAMPAIGN_ID } = f;
const mechanism = 'Let $P(S)=\\sum_{i\\in S} p_i$ and \\(D(\\emptyset)=0\\). For every nonempty $S$:\n\\[D(S)=\\min_{j\\in S}\\,[D(S\\setminus\\{j\\})+\\max(0,P(S)-d_j)]\\]\n'
  + 'The code `\\(kept\\)` stays code, and a price of $20 or $30 stays text.';
const rationale = 'Found at least once in $K$ draws with probability\n\n$$1-\\left(1-\\frac{M}{40320}\\right)^K$$';

test('formulas in a proposal render as math, written between dollars or LaTeX delimiters, on the card and in the list', async ({ page }) => {
  await mockWorkspace(page, {
    [`/api/v1/campaigns/${CAMPAIGN_ID}/hypotheses`]: { ...f.hypotheses, hypotheses: f.hypotheses.hypotheses.map(h => h.id === 'hypothesis_b' ? { ...h, mechanism } : h) },
    '/api/v1/hypotheses/hypothesis_b': { ...f.hypothesisCard, hypothesis: { ...f.hypothesisCard.hypothesis, mechanism, rationale } },
  });
  await page.goto(`/#t/${THREAD_ID}/hypotheses/hypothesis_b`);
  const card = page.getByTestId('page-hypotheses');
  const shown = card.locator('h3:text-is("Mechanism") + .md');
  await expect(shown.locator('.katex-display')).toHaveCount(1);
  await expect(shown.locator('.katex')).toHaveCount(4);   // P(S), D(∅) and S inline, D(S) displayed
  await expect(shown.locator('code')).toHaveText('\\(kept\\)');
  await expect(shown).toContainText('a price of $20 or $30 stays text');
  await expect(card.locator('h3:text-is("Rationale") + .md .katex-display')).toHaveCount(1);
  // The list's preview renders the same formulas, cut short of a formula, never inside one.
  await page.goto(`/#t/${THREAD_ID}/hypotheses`);
  const preview = page.locator('[data-testid="hypothesis"][data-record-id="hypothesis_b"] .md');
  await expect(preview.locator('.katex').first()).toBeVisible();
  await expect(preview).not.toContainText('\\(D(');   // converted, not shown raw
});
