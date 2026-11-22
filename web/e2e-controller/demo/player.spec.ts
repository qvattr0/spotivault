// The Player against the real controller in fake mode (demo): the fake client's screen through the
// controller's /vnc bridge, the status strip, and view-only during a run with Take control.

import { expect, test, type Page } from '@playwright/test';
import type { ClientStatus } from '../../src/api/types.ts';
import { demoReady, getJson, openPage, startRun, stopAnyRun } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

const strip = (page: Page) => page.getByRole('group', { name: 'Client status' });
const banner = (page: Page) => page.getByRole('status').filter({ hasText: 'A backup is recording.' });

test('interactive: the version, Logged in, and the screen connected', async ({ page, request }) => {
  const client = await getJson<ClientStatus>(request, '/api/client/status');
  await openPage(page, '/player');
  await expect(page.getByRole('heading', { level: 1, name: 'Player' })).toBeVisible();
  await expect(strip(page).getByText(`Spotify ${client.version}`)).toBeVisible();
  await expect(strip(page).getByText('Logged in')).toBeVisible();
  await expect(page.locator('[data-vnc-state]')).toHaveAttribute('data-vnc-state', 'connected', { timeout: 30_000 });
  await expect(strip(page).getByText('VNC connected')).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restart client' })).not.toHaveAttribute('aria-disabled');
});

test('during a run: view-only, Restart disabled; Take control unlocks it; the run ends', async ({ page, request }) => {
  test.setTimeout(120_000);
  await startRun(request, ['liked']);
  await openPage(page, '/player');
  await expect(banner(page)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Restart client' })).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('region', { name: 'Now recording' })).toBeVisible();

  await banner(page).getByRole('button', { name: 'Take control' }).click();
  await page.getByRole('dialog', { name: 'Take control anyway?' }).getByRole('button', { name: 'Take control' }).click();
  await expect(banner(page)).toHaveCount(0);
  await expect(page.locator('[data-vnc-state]')).toHaveAttribute('data-vnc-state', 'connected', { timeout: 30_000 });

  await stopAnyRun(request);
  await expect(page.getByRole('button', { name: 'Restart client' })).not.toHaveAttribute('aria-disabled', { timeout: 15_000 });
  await expect(banner(page)).toHaveCount(0);
});
