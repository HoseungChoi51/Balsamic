import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID } from './mocks/fixtures';

test('the Packages page lists each code package with its versions, methods and the campaigns that use them (roadmap L2)', async ({ page }) => {
  await mockWorkspace(page);
  await page.route('**/api/libraries', route => route.fulfill({ json: { libraries: [
    { name: 'bakery', package: 'bakery-search', latest: '0.2.0', versions: 2, methods: ['bakery_dp', 'bakery_greedy'], problems: ['baking_order'], updated_at: '2026-10-28T04:00:00Z' }] } }));
  await page.route('**/api/libraries/bakery', route => route.fulfill({ json: { name: 'bakery', package: 'bakery-search', latest: '0.2.0',
    versions: [
      { id: 'v2', version: '0.2.0', tag: 'v0.2.0', commit: '2a3eb0899a', parent_version: '0.1.0', methods: ['bakery_dp', 'bakery_greedy'], problems: ['baking_order'],
        methods_added: ['bakery_greedy'], methods_removed: ['bakery_old'], problems_added: [], problems_removed: [], created_at: '2026-10-28T04:00:00Z',
        source: { campaign_id: 'campaign_b', workspace_id: 'development_b' } },
      { id: 'v1', version: '0.1.0', tag: 'v0.1.0', commit: '1b2c3d4e5f', parent_version: null, methods: ['bakery_dp', 'bakery_old'], problems: ['baking_order'],
        methods_added: ['bakery_dp', 'bakery_old'], methods_removed: [], problems_added: ['baking_order'], problems_removed: [], created_at: '2026-10-27T04:00:00Z',
        source: { campaign_id: 'campaign_a', workspace_id: 'development_a' } }],
    methods: [
      { id: 'bakery_dp', since: '0.1.0', in_latest: true, campaigns: [{ id: 'campaign_a', name: 'First bakery' }, { id: 'campaign_b', name: 'Second bakery' }] },
      { id: 'bakery_greedy', since: '0.2.0', in_latest: true, campaigns: [] },
      { id: 'bakery_old', since: '0.1.0', in_latest: false, campaigns: [] }],
    problems: [{ id: 'baking_order', since: '0.1.0', in_latest: true, campaigns: [{ id: 'campaign_a', name: 'First bakery' }] }] } }));
  await page.goto(`/#t/${THREAD_ID}/packages`);
  const card = page.getByTestId('package');
  await expect(card).toContainText('bakery-search');
  await expect(card).toContainText('2 versions · 2 methods · problems baking_order · libraries/bakery');
  await card.getByTestId('package-open').click();
  const rows = card.getByTestId('package-methods-row');
  await expect(rows.first()).toContainText('bakery_dp');
  await expect(rows.first()).toContainText('First bakery, Second bakery');
  await expect(rows.nth(2)).toContainText('removed');
  const versions = card.getByTestId('package-version');
  await expect(versions.first()).toContainText('0.2.0 2a3eb08 · adds bakery_greedy · removes bakery_old · from workspace development_b of campaign campaign_b');
  await expect(versions.nth(1)).toContainText('0.1.0');
});
