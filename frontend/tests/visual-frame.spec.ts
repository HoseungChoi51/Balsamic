import { test, expect } from '@playwright/test';
import { mockWorkspace } from './mocks/workspace';
import { THREAD_ID, CAMPAIGN_ID } from './mocks/fixtures';
import * as f from './mocks/fixtures';

test('a visual renders in a sandboxed frame; it can only ask to open a page', async ({ page }) => {
  const html = `<svg viewBox='0 0 10 10'><rect width='5' height='10'/></svg><script>parent.postMessage({open: '#experiments/trial_1'}, '*'); try { fetch('/api/health'); } catch (e) {}</script>`;
  const withVisual = { ...f.noteView, annotations: [{ ...f.noteView.annotations[0], visual_id: 'visual_1', proposed_edit: null }] };
  await mockWorkspace(page, { [`/api/v1/campaigns/${CAMPAIGN_ID}/problem-note`]: withVisual, [`/api/v1/campaigns/${CAMPAIGN_ID}/agents/records/visual_1`]: { kind: 'agent_artifact', data: { id: 'visual_1', title: 'Cross-section', content: { html } } } });
  await page.goto(`/#t/${THREAD_ID}/note`);
  const frame = page.getByTestId('visual-frame');
  await expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
  await expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  // The frame's postMessage opened the page it asked for, in this thread.
  await expect(page).toHaveURL(new RegExp(`#t/${THREAD_ID}/experiments/trial_1`));
});
