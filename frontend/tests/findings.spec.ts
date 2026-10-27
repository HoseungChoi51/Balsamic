import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { CAMPAIGN_ID, THREAD_ID, files } from './mocks/fixtures';

const finding = (id: string, statement: string, extra: Record<string, unknown> = {}) => ({
  id, kind: 'finding', content: `Finding ${id}.`, statement, links: [], source_ids: ['trial_1'], created_at: '2026-10-27T09:00:00Z',
  measurement_ids: statement === 'promise' ? [] : ['trial_1'], support: { measurement_ids: statement === 'promise' ? [] : ['trial_1'], supporters: [] },
  superseded_by: [], restates: [], ...extra,
});

test('findings show what they state, count distinct measurements, mark restatements and keep superseded ones apart', async ({ page }) => {
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/files`]: { ...files,
    findings: [
      finding('finding_claim', 'evidence', { support: { measurement_ids: ['trial_1'], supporters: [
        { id: 'finding_echo', depth: 1, statement: 'evidence', restates: true }, { id: 'finding_echo_2', depth: 1, statement: 'evidence', restates: true }] } }),
      finding('finding_echo', 'evidence', { links: [{ id: 'finding_claim', relation: 'supports' }], restates: ['finding_claim'] }),
      finding('finding_echo_2', 'evidence', { links: [{ id: 'finding_claim', relation: 'supports' }], restates: ['finding_claim'] }),
      finding('finding_hope', 'promise', { source_ids: ['hypothesis_b'], links: [{ id: 'finding_claim', relation: 'qualifies' }] }),
    ],
    superseded_findings: [finding('finding_early', 'evidence', { superseded_by: ['finding_claim'] })] } });
  await page.goto(`/#t/${THREAD_ID}/files/assets`);
  const cards = page.getByTestId('finding');
  const claim = cards.filter({ hasText: 'Finding finding_claim.' });
  await expect(claim).toContainText('evidence');
  await expect(claim.getByTestId('finding-measurements')).toHaveText('1 distinct measurement behind it and its supporting findings');
  await expect(claim.getByTestId('finding-supporters')).toHaveText('Supported by finding_echo (restates), finding_echo_2 (restates)');
  const echo = cards.filter({ hasText: 'Finding finding_echo.' });
  await expect(echo).toContainText('restates');
  await expect(echo.getByTestId('finding-links')).toHaveText('supports finding_claim');
  const hope = cards.filter({ hasText: 'Finding finding_hope.' });
  await expect(hope).toContainText('promise · not measured');
  await expect(hope.getByTestId('finding-measurements')).toHaveCount(0);
  await expect(hope.getByTestId('finding-links')).toHaveText('qualifies finding_claim');
  // The superseded finding is out of the default view, one click away, and opens when linked to by id.
  const superseded = page.getByTestId('superseded-findings');
  await expect(superseded).toContainText('Superseded findings (1)');
  await expect(superseded.getByText('Finding finding_early.')).toBeHidden();
  await page.goto(`/#t/${THREAD_ID}/files/assets/finding_early`);
  await expect(superseded.getByText('Finding finding_early.')).toBeVisible();
  await expect(superseded).toContainText('Superseded by finding_claim');
});
