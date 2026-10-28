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

test('a split shows the method package, the problem package that depends on it, and the methods it moved (roadmap L6)', async ({ page }) => {
  await mockWorkspace(page);
  await page.route('**/api/libraries', route => route.fulfill({ json: { libraries: [
    { name: 'bakery', package: 'bakery-search', kind: 'problem', latest: '0.3.0', versions: 3, methods: ['bakery_dp'], problems: ['baking_order'],
      depends_on: ['bakery-search-methods'], used_by: [], updated_at: '2026-10-28T05:00:00Z' },
    { name: 'bakery-methods', package: 'bakery-search-methods', kind: 'method', latest: '0.1.0', versions: 1, methods: ['bakery_greedy'], problems: [],
      depends_on: [], used_by: ['bakery-search'], updated_at: '2026-10-28T05:00:00Z' }] } }));
  await page.route('**/api/libraries/bakery', route => route.fulfill({ json: { name: 'bakery', package: 'bakery-search', latest: '0.3.0', kind: 'problem',
    depends_on: ['bakery-search-methods'], used_by: [], methods: [], problems: [],
    versions: [{ id: 'v3', version: '0.3.0', tag: 'v0.3.0', commit: '3c4d5e6f70', parent_version: '0.2.0', methods: ['bakery_dp'], problems: ['baking_order'],
      methods_added: [], methods_removed: ['bakery_greedy'], problems_added: [], problems_removed: [], created_at: '2026-10-28T05:00:00Z',
      depends_on: ['bakery-search-methods'], moved: { package: 'bakery-search-methods', methods: ['bakery_greedy'] },
      source: { campaign_id: 'campaign_b', workspace_id: 'development_split' } }] } }));
  await page.goto(`/#t/${THREAD_ID}/packages`);
  const [problem, methods] = [page.getByTestId('package').first(), page.getByTestId('package').nth(1)];
  await expect(problem.getByTestId('package-depends')).toHaveText('Depends on bakery-search-methods');
  await expect(methods).toContainText('method package');
  await expect(methods.getByTestId('package-used-by')).toHaveText('Used by bakery-search');
  await problem.getByTestId('package-open').click();
  await expect(problem.getByTestId('package-version').first()).toContainText('removes bakery_greedy · moves bakery_greedy to bakery-search-methods');
});
