// History against the real controller in fake mode (demo project): a backup started and stopped
// shows in History as Stopped, and its run page lists its items and their tracks.
// The demo controller is shared: it's left with no run going (stopAnyRun in afterEach).

import { expect, test } from '@playwright/test';
import { demoReady, openPage, startRun, stopAnyRun } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

test('a backup that is stopped shows in History, and its run page lists its items', async ({ page, request }) => {
  test.setTimeout(120_000);
  await startRun(request, ['liked']);

  // While it records, the controller lists it with no outcome: History shows it Running.
  await openPage(page, '/history/runs');
  const table = page.getByRole('table', { name: 'Runs' });
  const top = table.getByRole('row').nth(1);
  await expect(top.getByRole('link', { name: 'Running' })).toHaveAttribute('href', '/dashboard');

  await stopAnyRun(request);
  await expect(top).toContainText('Stopped', { timeout: 20_000 });
  await expect(top.getByRole('cell', { name: 'Run now', exact: true })).toBeVisible();

  await top.getByRole('link').click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText(' · Run now');
  await expect(page.getByText('Stopped', { exact: true }).first()).toBeVisible();
  const liked = page.getByRole('button', { name: 'Liked Songs', exact: true });
  await expect(liked).toBeVisible();
  await liked.click();
  await expect(page.getByRole('table', { name: 'Tracks of Liked Songs' }).or(page.getByText('No tracks in this run.'))).toBeVisible();
});
