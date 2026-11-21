// The Library against the real controller in fake mode, `demo` project: the main path of the page
// (web-ui.md § Library). Shares the controller with the other demo specs, in file order: each test
// leaves the controller as it found it (the tracking check and the auto-track setting are put back,
// and afterEach stops any run).

import { expect, test, type Page } from '@playwright/test';
import type { LibraryItem } from '../../src/api/types.ts';
import { demoReady, getJson, openPage, startRun, stopAnyRun } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

/** The row of the List view that holds this name. */
function row(page: Page, name: string) {
  return page.getByRole('table', { name: 'Library' }).getByRole('row').filter({ hasText: name });
}

test('the Library lists the account, Liked Songs first, with its summary', async ({ page, request }) => {
  const { items } = await getJson<{ items: LibraryItem[] }>(request, '/api/library');
  await openPage(page, '/library');
  await expect(page.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible();
  await expect(page.getByText(new RegExp(`^\\d+ of ${items.length} tracked( · last backup .*)?$`))).toBeVisible();
  const rows = page.getByRole('table', { name: 'Library' }).getByRole('row');
  await expect(rows.nth(1)).toContainText('Liked Songs');
  await expect(rows).toHaveCount(items.length + 1); // and the header row
});

test('the tracking check turns a playlist off and on, and the controller keeps it', async ({ page, request }) => {
  const { items } = await getJson<{ items: LibraryItem[] }>(request, '/api/library');
  const playlist = items.find((item) => item.kind === 'owned' && item.tracked);
  expect(playlist, 'a tracked playlist of your own').toBeTruthy();
  const name = playlist?.name ?? '';

  await openPage(page, '/library');
  const toggle = row(page, name).getByRole('checkbox', { name: `Track ${name}` });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect
    .poll(async () => (await getJson<{ items: LibraryItem[] }>(request, '/api/library')).items.find((i) => i.id === playlist?.id)?.tracked)
    .toBe(false);

  // Put it back, as it was.
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await expect
    .poll(async () => (await getJson<{ items: LibraryItem[] }>(request, '/api/library')).items.find((i) => i.id === playlist?.id)?.tracked)
    .toBe(true);
});

test('Refresh reads the Library from Spotify now, and says when it is done', async ({ page, request }) => {
  await openPage(page, '/library');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  // The demo account has nothing new since its last refresh.
  await expect(page.getByText(/^Library refreshed/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeVisible();
  const { items } = await getJson<{ items: LibraryItem[] }>(request, '/api/library');
  await expect(page.getByRole('table', { name: 'Library' }).getByRole('row')).toHaveCount(items.length + 1);
});

test('Refresh is greyed out during a backup, and says why', async ({ page, request }) => {
  await startRun(request, ['liked']);
  await openPage(page, '/library');
  const refresh = page.getByRole('button', { name: 'Refresh', exact: true });
  await expect(refresh).toHaveAttribute('aria-disabled', 'true');
  await refresh.hover();
  await expect(
    page.getByRole('tooltip', { name: 'Not available while a backup is recording. Each backup refreshes the Library first.' }),
  ).toBeVisible();
});

test('Back up now on Liked Songs starts a run, and its row shows Recording or Queued', async ({ page }) => {
  await openPage(page, '/library');
  const liked = row(page, 'Liked Songs');
  await liked.hover();
  await liked.getByRole('button', { name: 'Back up now' }).click();
  await expect(page.getByText(/^(Backup started|Added to the current run|Already in the current run: nothing added)$/)).toBeVisible();
  await expect(liked.getByRole('link', { name: /^(Recording|Queued)$/ })).toBeVisible({ timeout: 30_000 });
});

test('the detail view of Liked Songs lists its tracks', async ({ page }) => {
  await openPage(page, '/library/liked');
  await expect(page.getByRole('heading', { level: 1, name: 'Liked Songs' })).toBeVisible();
  const tracks = page.getByRole('table', { name: 'Tracks' }).getByRole('row');
  await expect(tracks.nth(1)).toBeVisible({ timeout: 15_000 });
  expect(await tracks.count()).toBeGreaterThan(2);
  await expect(page.getByRole('button', { name: 'Stop tracking' })).toBeVisible();
  await expect(page.getByText('Files are never deleted.')).toBeVisible();
});

test('the + modal: a search with no followed playlist says so; a link to one of yours shows Added', async ({ page, request }) => {
  const { items } = await getJson<{ items: LibraryItem[] }>(request, '/api/library');
  const own = items.find((item) => item.kind === 'owned');
  expect(own, 'a playlist of your own').toBeTruthy();

  await openPage(page, '/library');
  await page.getByRole('button', { name: 'Add playlists' }).click();
  const modal = page.getByRole('dialog', { name: 'Add playlists' });
  // The demo account may follow a playlist that isn't in the Library yet, so ask for one that can't exist.
  await modal.getByRole('searchbox').fill('no such playlist anywhere');
  await expect(modal.getByText('Nothing to suggest')).toBeVisible();

  await modal.getByRole('searchbox').fill(`https://open.spotify.com/playlist/${own?.id}`);
  await expect(modal.getByText('from link')).toBeVisible({ timeout: 15_000 });
  await expect(modal.getByText('Added', { exact: true })).toBeVisible();

  await modal.getByRole('searchbox').fill('https://example.com/not-spotify');
  await expect(modal.getByText("That isn't a Spotify playlist link.", { exact: true })).toBeVisible();

  await modal.getByRole('searchbox').fill('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M');
  await expect(modal.getByText("Playlists made by Spotify aren't available through the API, so they can't be added.", { exact: true })).toBeVisible({ timeout: 15_000 });

  await modal.getByRole('button', { name: 'Done' }).click();
  await expect(modal).toHaveCount(0);
});

test('the Library options: the auto-track switch flips, and goes back as it was', async ({ page, request }) => {
  await openPage(page, '/library');
  const option = 'Automatically track playlists I create';
  await page.getByRole('button', { name: 'Library options' }).click();
  const before = await page.getByRole('menuitemcheckbox', { name: option }).getAttribute('aria-checked');
  await page.getByRole('menuitemcheckbox', { name: option }).click();
  await expect
    .poll(async () => (await getJson<{ auto_track_owned: boolean }>(request, '/api/library/summary')).auto_track_owned)
    .toBe(before !== 'true');

  // Put it back.
  await page.getByRole('button', { name: 'Library options' }).click();
  await page.getByRole('menuitemcheckbox', { name: option }).click();
  await expect
    .poll(async () => (await getJson<{ auto_track_owned: boolean }>(request, '/api/library/summary')).auto_track_owned)
    .toBe(before === 'true');
});
