// The S8 foundation's shared parts in a real browser, against the mock: the noVNC view on the
// mock's VNC server, and menus drawn on top of the page.

import { expect, test } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';

test("the noVNC view connects to the mock's screen, and a click on the login screen logs in", async ({ page, request }) => {
  await useScenario(request, 'setup', { step: 'login' });
  await page.goto('/gallery#vnc-view');
  await page.getByRole('button', { name: 'Connect to /vnc' }).click();
  const view = page.locator('[data-vnc-state]');
  await expect(view).toHaveAttribute('data-vnc-state', 'connected', { timeout: 15_000 });
  await expect(page.getByText('State: connected')).toBeVisible();

  // The QR code stands in the middle of the screen: a click there is the phone's scan.
  await view.locator('canvas').click();
  await expect
    .poll(async () => (await (await request.get('/api/client/status')).json()).logged_in, { timeout: 10_000 })
    .toBe(true);
});

test('the noVNC view says when the screen is not up, and reconnects', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await mock.vnc(false);
  await page.goto('/gallery#vnc-view');
  await page.getByRole('button', { name: 'Connect to /vnc' }).click();
  const view = page.locator('[data-vnc-state]');
  await expect(view).toHaveAttribute('data-vnc-state', 'reconnecting', { timeout: 15_000 });
  await mock.vnc(true);
  await expect(view).toHaveAttribute('data-vnc-state', 'connected', { timeout: 20_000 });
});

test('a menu opens on top of the page, outside any clipping parent', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/library');
  // The now-playing bar's Stop menu opens upwards from the foot of the screen.
  const bar = page.getByRole('region', { name: 'Now recording' });
  await bar.getByRole('button', { name: /More ways to stop/ }).click();
  const menu = page.getByRole('menu');
  await expect(menu).toBeVisible();
  await expect(menu).toHaveAttribute('data-placement', 'above');
  expect(await menu.evaluate((node) => node.parentElement === document.body)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
});
