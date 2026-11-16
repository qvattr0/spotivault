// The UI against the real controller in fake mode (playwright.controller.config.ts). The tests share
// one controller, so they run in order: the wizard starts fresh, and step 1 is the first to change it.

import type { APIRequestContext } from '@playwright/test';
import { expect, test } from '@playwright/test';
import { SETUP_STEPS } from '../src/shell/setup-steps.ts';

/** Where the setup gate should send you now: the first unfinished step, read from GET /api/setup. */
async function gatePath(request: APIRequestContext): Promise<string> {
  const setup = await (await request.get('/api/setup')).json();
  if (setup.completed || setup.first_unfinished === null) return '/dashboard';
  const step = SETUP_STEPS.find((s) => s.id === setup.first_unfinished);
  return `/setup/${step?.slug ?? 'welcome'}`;
}

function endsWith(path: string): RegExp {
  return new RegExp(`${path.replace(/[/-]/g, (c) => `\\${c}`)}$`);
}

test('the app loads from the controller, and the live socket gets its hello', async ({ page }) => {
  const frames: string[] = [];
  page.on('websocket', (ws) => {
    if (ws.url().endsWith('/api/events')) ws.on('framereceived', (data) => frames.push(String(data.payload)));
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to spotivault' })).toBeVisible();
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

  const setup = await (await request.get('/api/setup')).json();
  expect(setup.tos_acknowledged_at).not.toBeNull();
  await expect(page).toHaveURL(endsWith(await gatePath(request)));
});

test('an unbuilt route (501) leaves the page working', async ({ page, request }) => {
  // S6's status route isn't built: the controller says so in the error envelope.
  const status = await request.get('/api/status');
  expect(status.status()).toBe(501);
  expect((await status.json()).error.details.reason).toBe('not_built');

  // With the socket refused, the store reads the snapshot through REST (rest.ts), /api/status
  // among it. The page must still load the wizard from the rest of the snapshot.
  await page.routeWebSocket('**/api/events', (ws) => ws.close({ code: 1013, reason: 'test: socket refused' }));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const read = page.waitForResponse((r) => r.url().endsWith('/api/status'), { timeout: 30_000 });
  await page.goto('/setup/welcome');
  expect((await read).status()).toBe(501);
  await expect(page.getByRole('heading', { name: 'Welcome to spotivault' })).toBeVisible({ timeout: 30_000 });
  expect(errors).toEqual([]);
});
