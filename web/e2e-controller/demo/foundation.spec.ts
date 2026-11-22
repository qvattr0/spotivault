// The UI against the real controller in fake mode, `demo` project (playwright.controller.config.ts):
// set up at start-up, with a library. These run first in the project (the builders' files sort
// after "foundation"), and check that the app's pages open and the helpers work.

import { expect, test } from '@playwright/test';
import type { LibraryItem } from '../../src/api/types.ts';
import { demoReady, endsWith, getJson, openPage, startRun, stopAnyRun, waitForRunState } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

test('the demo is set up: / opens the Dashboard, and every app page opens', async ({ page }) => {
  await openPage(page, '/');
  await expect(page).toHaveURL(endsWith('/dashboard'));
  for (const [path, title] of [
    ['/dashboard', 'Dashboard'],
    ['/library', 'Library'],
    ['/albums', 'Albums'],
    ['/history/runs', 'History'],
    ['/settings', 'Settings'],
    ['/player', 'Player'],
  ]) {
    await openPage(page, path);
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
  }
});

test('a run starts and stops, and the shell follows it live', async ({ page, request }) => {
  await openPage(page, '/library');
  const items = (await getJson<{ items: LibraryItem[] }>(request, '/api/library')).items;
  expect(items[0]?.id).toBe('liked');
  await startRun(request, ['liked']);
  await expect(page.locator('[data-testid="run-state"][data-run-state="running"]').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('region', { name: 'Now recording' })).toBeVisible();
  await stopAnyRun(request);
  await waitForRunState(request, 'idle');
  await expect(page.locator('[data-testid="run-state"][data-run-state="idle"]').first()).toBeVisible({ timeout: 30_000 });
});

test("the controller's noVNC bridge serves the fake screen", async ({ page }) => {
  await openPage(page, '/gallery#vnc-view');
  await page.getByRole('button', { name: 'Connect to /vnc' }).click();
  await expect(page.locator('[data-vnc-state]')).toHaveAttribute('data-vnc-state', 'connected', { timeout: 30_000 });
});
