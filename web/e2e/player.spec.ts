// The Player (web-ui.md § Player), against the mock and its VNC screen (mock/vnc.ts): the toolbar,
// the status strip, the VNC states, and view-only during a run with Take control.

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { expectRunState } from './live.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

const strip = (page: Page) => page.getByRole('group', { name: 'Client status' });
const view = (page: Page) => page.locator('[data-vnc-state]');
const canvas = (page: Page) => view(page).locator('canvas');
const banner = (page: Page) => page.getByRole('status').filter({ hasText: 'A backup is recording.' });

async function loggedIn(request: APIRequestContext): Promise<boolean> {
  return ((await (await request.get('/api/client/status')).json()) as { logged_in: boolean }).logged_in;
}

test('interactive: the toolbar, the status strip and the screen', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/player');
  await expect(page.getByRole('heading', { level: 1, name: 'Player' })).toBeVisible();
  await expect(page).toHaveTitle('Player · spotivault');
  await expect(strip(page).getByText('Spotify 1.3.4.258')).toBeVisible();
  await expect(strip(page).getByText('Logged in')).toBeVisible();
  await expect(view(page)).toHaveAttribute('data-vnc-state', 'connected', { timeout: 15_000 });
  await expect(strip(page).getByText('VNC connected')).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restart client' })).not.toHaveAttribute('aria-disabled');

  // Fit (the default) scales the 1280 × 800 screen to the view; 100% shows it pixel for pixel.
  const scale = page.getByRole('radiogroup', { name: 'Scale' });
  await expect(scale.getByRole('radio', { name: 'Fit' })).toBeChecked();
  const fitted = await canvas(page).boundingBox();
  expect(fitted?.width).toBeLessThan(1280);
  await scale.getByRole('radio', { name: '100%' }).click();
  await expect(scale.getByRole('radio', { name: '100%' })).toBeChecked();
  await expect.poll(async () => Math.round((await canvas(page).boundingBox())?.width ?? 0)).toBe(1280);
});

test('Fullscreen shows the view on its own, and leaves again', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/player');
  const button = page.getByRole('button', { name: 'Fullscreen' });
  await button.click();
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => document.fullscreenElement?.contains(document.querySelector('[data-vnc-state]')))).toBe(true);
  // The view covers the toolbar now: Esc (the browser's own) leaves. Headless Chromium has no Esc
  // for it, so the test leaves the way the browser does.
  await page.evaluate(() => document.exitFullscreen());
  await expect(button).toHaveAttribute('aria-pressed', 'false');
});

test('Restart client asks first, then restarts', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/player');
  await page.getByRole('button', { name: 'Restart client' }).click();
  const dialog = page.getByRole('dialog', { name: 'Restart the Spotify client?' });
  await expect(dialog.getByText('It comes back logged in.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toHaveCount(0);

  await page.getByRole('button', { name: 'Restart client' }).click();
  await page.getByRole('dialog', { name: 'Restart the Spotify client?' }).getByRole('button', { name: 'Restart' }).click();
  await expect(page.getByText('Restarting the Spotify client')).toBeVisible();
});

test('not logged in: a link to wizard step 3, and a click on the login screen logs in', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).login(false);
  await openPage(page, '/player');
  await expect(strip(page).getByRole('link', { name: 'Not logged in' })).toHaveAttribute('href', '/setup/login');
  await expect(view(page)).toHaveAttribute('data-vnc-state', 'connected', { timeout: 15_000 });
  // The mock's login screen: a click stands in for scanning the QR code with the phone.
  await canvas(page).click();
  await expect(strip(page).getByText('Logged in')).toBeVisible({ timeout: 10_000 });
});

test('the screen not up: Reconnecting…, then Disconnected with Retry', async ({ page, request }) => {
  // VncView tries 5 times, 1 + 2 + 4 + 8 s apart, before it gives up.
  test.setTimeout(60_000);
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await mock.vnc(false);
  await openPage(page, '/player');
  await expect(strip(page).getByText('VNC reconnecting…')).toBeVisible({ timeout: 10_000 });
  await expect(strip(page).getByText('VNC disconnected')).toBeVisible({ timeout: 40_000 });
  await mock.vnc(true);
  await strip(page).getByRole('button', { name: 'Retry' }).click();
  await expect(strip(page).getByText('VNC connected')).toBeVisible({ timeout: 15_000 });
});

test('during a run: view-only with a banner and a lock; Restart disabled with its reason', async ({ page, request }) => {
  await useScenario(request, 'running');
  const mock = mockControls(request);
  await openPage(page, '/player');
  await expect(banner(page)).toHaveText("A backup is recording. The view is read-only so a click doesn't spoil it.Take control");
  await expect(page.getByTitle('View-only while a backup is recording')).toBeVisible();
  const restart = page.getByRole('button', { name: 'Restart client' });
  await expect(restart).toHaveAttribute('aria-disabled', 'true');
  await restart.hover();
  await expect(page.getByRole('tooltip', { name: 'Not available while a backup is recording' })).toBeVisible();
  // aria-disabled keeps it focusable for the tooltip; a click does nothing.
  await restart.click({ force: true });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  // The global now-playing bar is at the foot of the page.
  await expect(page.getByRole('region', { name: 'Now recording' })).toBeVisible();

  // A click on the screen goes nowhere: the login screen stays logged out.
  await mock.login(false);
  await expect(view(page)).toHaveAttribute('data-vnc-state', 'connected', { timeout: 15_000 });
  await canvas(page).click();
  await page.waitForTimeout(1500);
  expect(await loggedIn(request)).toBe(false);
});

test('Take control asks first, unlocks the view for this run, and locks again for the next', async ({ page, request }) => {
  await useScenario(request, 'running');
  const mock = mockControls(request);
  await mock.login(false);
  await openPage(page, '/player');
  await expect(view(page)).toHaveAttribute('data-vnc-state', 'connected', { timeout: 15_000 });

  await banner(page).getByRole('button', { name: 'Take control' }).click();
  const dialog = page.getByRole('dialog', { name: 'Take control anyway?' });
  await expect(dialog.getByText('Clicks in the client can pause or skip the track being recorded.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Take control' }).click();
  await expect(banner(page)).toHaveCount(0);
  await expect(page.getByTitle('View-only while a backup is recording')).toHaveCount(0);
  // The run carries on, and clicks reach the client now.
  await expectRunState(page, 'running');
  await canvas(page).click();
  await expect.poll(() => loggedIn(request), { timeout: 10_000 }).toBe(true);

  // The run ends: still interactive. Another run starts: locked again.
  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  await expectRunState(page, 'idle', 15_000);
  await expect(banner(page)).toHaveCount(0);
  expect((await request.post('/api/runs', { data: {} })).status()).toBe(202);
  await expect(banner(page)).toBeVisible({ timeout: 10_000 });
});

test('the banner goes when the run ends', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/player');
  await expect(banner(page)).toBeVisible();
  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  await expect(banner(page)).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole('button', { name: 'Restart client' })).not.toHaveAttribute('aria-disabled');
});
