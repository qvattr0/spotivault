// The UI against the real controller in fake mode, `wizard` project (playwright.controller.config.ts):
// a fresh container. The tests share one controller, so they run in order: the wizard starts fresh,
// and step 1 is the first to change it. The wizard builder's tests (wizard.spec.ts) run after these.

import { expect, test } from '@playwright/test';
import { endsWith, gatePath, getJson } from '../helpers.ts';
import type { Setup } from '../../src/api/types.ts';

test('the app loads from the controller, and the live socket gets its hello', async ({ page }) => {
  const frames: string[] = [];
  page.on('websocket', (ws) => {
    if (ws.url().endsWith('/api/events')) ws.on('framereceived', (data) => frames.push(String(data.payload)));
  });
  await page.goto('/');
  await expect(page).toHaveURL(endsWith('/setup/welcome'));
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect.poll(() => frames.some((f) => f.includes('"type":"hello"'))).toBe(true);
});

test('the setup gate sends you to the first unfinished step', async ({ page, request }) => {
  const target = await gatePath(request);
  await page.goto('/library');
  await expect(page).toHaveURL(endsWith(target));
});

test('step 1: I understand and Continue post to the controller, then move on', async ({ page, request }) => {
  await page.goto('/setup/welcome');
  await page.getByLabel('I understand').check();
  const posted = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/setup/tos'));
  await page.getByRole('button', { name: 'Continue' }).click();
  expect((await posted).status()).toBe(200);

  const setup = await getJson<Setup>(request, '/api/setup');
  expect(setup.tos_acknowledged_at).not.toBeNull();
  await expect(page).not.toHaveURL(endsWith('/setup/welcome'));
});

test('a REST error and a refused socket leave the page working', async ({ page }) => {
  // The controller answers every route now (S6). Make one fail as an unbuilt route did (501, in the
  // contract's error envelope), and refuse the socket, so the store reads its snapshot through
  // REST (state/rest.ts), /api/status among it. The page must still load the wizard.
  await page.route('**/api/status', (route) =>
    route.fulfill({ status: 501, json: { error: { code: 'internal', message: 'test: not built', details: { reason: 'not_built' } } } }),
  );
  await page.routeWebSocket('**/api/events', (ws) => ws.close({ code: 1013, reason: 'test: socket refused' }));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const read = page.waitForResponse((r) => r.url().endsWith('/api/status'), { timeout: 30_000 });
  await page.goto('/setup/welcome');
  expect((await read).status()).toBe(501);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 30_000 });
  expect(errors).toEqual([]);
});
