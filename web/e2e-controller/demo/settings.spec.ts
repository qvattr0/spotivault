// Settings against the real controller in fake mode (demo project): the page reads what the
// controller reports, and saves go through PUT /api/settings. Each test puts back what it changed.
// Not covered here, on purpose: Disconnect (it would take the demo's Web API connection away for
// every later test) and Run setup again (it reopens the wizard for the whole demo).

import { expect, test } from '@playwright/test';
import type { Container, Health, Settings, Status } from '../../src/api/types.ts';
import { demoReady, endsWith, getJson, openPage, stopAnyRun } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

test('Settings shows the container, the connection and the music folder the controller reports', async ({ page, request }) => {
  const container = await getJson<Container>(request, '/api/container');
  const health = await getJson<Health>(request, '/api/health');
  await openPage(page, '/settings');
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();

  const containerRegion = page.getByRole('region', { name: 'Container' });
  await expect(containerRegion.getByText(container.device_name, { exact: true })).toBeVisible();
  await expect(containerRegion.getByText(`Spytify ${container.versions.spytify}`, { exact: false })).toBeVisible();

  await expect(page.getByRole('group', { name: 'Connection' }).getByText(/^Connected as /)).toBeVisible();
  await expect(page.getByRole('region', { name: 'About' }).getByText(`spotivault ${health.version}`, { exact: true })).toBeVisible();

  // The folder check: the demo's /music is mounted and writable, so the row shows its free space.
  await expect(page.getByRole('group', { name: 'Music folder' }).getByText(/ free$/)).toBeVisible();
});

test('a format saved on the controller is read back after a reload, and is put back', async ({ page, request }) => {
  const before = await getJson<Settings>(request, '/api/settings');
  try {
    await openPage(page, '/settings');
    await page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'AAC 320' }).click();
    await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    expect(await getJson<Settings>(request, '/api/settings')).toMatchObject({ format: 'aac', bitrate: 320 });

    await openPage(page, '/settings');
    await expect(page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'AAC 320' })).toBeChecked();
  } finally {
    await request.put('/api/settings', { data: { format: before.format, bitrate: before.bitrate } });
  }
});

test('the playlist-file toggle saves through the controller, and is put back; no covers toggle in M1', async ({ page, request }) => {
  const before = await getJson<Settings>(request, '/api/settings');
  try {
    await openPage(page, '/settings');
    // M1 writes no cover files, so "Save Spotify's covers" isn't shown; the setting is left alone.
    await expect(page.getByRole('switch', { name: "Save Spotify's covers" })).toHaveCount(0);
    await page.getByRole('switch', { name: 'Write .m3u playlists' }).click();
    await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    expect(await getJson<Settings>(request, '/api/settings')).toMatchObject({
      write_m3u: !before.write_m3u,
      save_spotify_covers: before.save_spotify_covers,
    });
  } finally {
    await request.put('/api/settings', { data: { write_m3u: before.write_m3u } });
  }
});

test('Check access re-runs the music folder check on the controller', async ({ page, request }) => {
  await openPage(page, '/settings');
  await page.getByRole('button', { name: 'Check access' }).click();
  await expect(page.getByRole('group', { name: 'Music folder' }).getByText(/ free$/)).toBeVisible();
  const storage = await getJson<{ ok: boolean }>(request, '/api/storage');
  expect(storage.ok).toBe(true);
});

test('Re-check reads the settings checklist: its ten rows stay on screen', async ({ page }) => {
  await openPage(page, '/settings');
  const list = page.getByRole('list', { name: 'Settings checklist' });
  await expect(list.getByRole('listitem')).toHaveCount(10);
  await page.getByRole('button', { name: 'Re-check' }).click();
  await expect(list.getByRole('listitem')).toHaveCount(10);
});

test('Open Player goes to the Player, and the Terms notice link points at the wizard', async ({ page, request }) => {
  await openPage(page, '/settings');
  await expect(page.getByRole('region', { name: 'About' }).getByRole('link', { name: 'Read the Terms notice again' })).toHaveAttribute(
    'href',
    '/setup/welcome',
  );
  await page.getByRole('link', { name: 'Open Player' }).click();
  await expect(page).toHaveURL(endsWith('/player'));
  await expect(page.getByRole('heading', { level: 1, name: 'Player' })).toBeVisible();
  // The Status payload is read only to make sure nothing is running for the next test.
  expect((await getJson<Status>(request, '/api/status')).state).toBe('idle');
});
