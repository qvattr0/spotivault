// History › Logs against the real controller in fake mode (demo project): fake mode writes the
// controller's log as s6-log would (logs.S6StyleFile) and the fake recorder writes Spytify's item
// log, so a run's page links to its lines from both. The live tail follows a run going on.
// The demo controller is shared: it's left with no run going (stopAnyRun in afterEach).

import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { demoReady, openPage, startRun, stopAnyRun } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

test("a run's page opens its logs: the controller's lines and Spytify's", async ({ page, request }) => {
  test.setTimeout(120_000);
  const runId = await startRun(request, ['liked']);

  // While it records, the tab follows the run's lines live.
  await openPage(page, `/history/logs?run=${runId}`);
  const log = page.getByRole('log', { name: 'Log lines' });
  await expect(log.locator('[data-source="controller"]').filter({ hasText: `runs: run ${runId}: Liked Songs` }).first()).toBeVisible({
    timeout: 20_000,
  });

  await stopAnyRun(request);
  await openPage(page, `/history/runs/${runId}`);
  await page.getByRole('link', { name: 'Logs for this run' }).click();
  await expect(page).toHaveURL(new RegExp(`/history/logs\\?run=${runId}$`));
  // Spytify's log for the item is written when its recorder ends.
  await expect(log.locator('[data-source="spytify"]').filter({ hasText: 'listening on unix' }).first()).toBeAttached({ timeout: 20_000 });
  await expect(log.locator('[data-source="controller"]').first()).toBeAttached();

  // The Spytify chip leaves only this run's Spytify lines.
  await page.getByRole('group', { name: 'Source' }).getByRole('button', { name: 'Spytify' }).click();
  await expect(log.locator('[data-line-id]:not([data-source="spytify"])')).toHaveCount(0);
  await expect(log.locator('[data-line-id]').first()).toBeAttached();
});

test('Download saves a zip with the controller log in it', async ({ page }) => {
  await openPage(page, '/history/logs');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download last 7 days (.zip)' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^spotivault-logs-\d{8}-\d{4}\.zip$/);
  const bytes = await readFile(await file.path());
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
  expect(bytes.includes(Buffer.from('controller/current'))).toBe(true);
});
