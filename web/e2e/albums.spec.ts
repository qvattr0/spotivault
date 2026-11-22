// The Albums pages against the mock (web-ui.md § Albums): the grid and the list, the filter and
// search, the row menus, the + modal and the detail view, and each state the page can show.

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fakeId } from '../mock/fixtures.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

/** The album's tile in the grid, by its name (a Card's title is a button that opens it). */
function card(page: Page, name: string) {
  return page.getByRole('button', { name, exact: true });
}

/** A list row by its album name. */
function row(page: Page, name: string) {
  return page.getByRole('table', { name: 'Albums' }).getByRole('row').filter({ hasText: name });
}

test('the grid shows every added album, with a pill for each state but Recorded', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await expect(page.getByRole('heading', { level: 1, name: 'Albums' })).toBeVisible();
  await expect(page.getByText('5 albums · 1 recorded · 2 queued')).toBeVisible();

  for (const name of ['OK Computer', 'In Rainbows', 'Melodrama', 'Elsewhere', 'Blonde']) {
    await expect(card(page, name)).toBeVisible();
  }
  // Queued links to the Dashboard (Album states); Partial and Unavailable are plain labels.
  await expect(page.getByRole('link', { name: 'Queued' })).toHaveCount(2);
  await expect(page.getByRole('link', { name: 'Queued' }).first()).toHaveAttribute('href', '/dashboard');
  // The pill comes after the filter chips in the page, so the last "Partial" is the pill.
  await expect(page.getByText('Partial', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('Unavailable', { exact: true })).toBeVisible();
  // A recorded album has no pill: the only "Recorded" on the page is the filter chip.
  await expect(page.getByText('Recorded', { exact: true })).toHaveCount(1);
});

test('the filter chips and the search narrow the grid, and Escape clears the search', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');

  await page.getByRole('radio', { name: 'Queued' }).click();
  await expect(card(page, 'In Rainbows')).toBeVisible();
  await expect(card(page, 'OK Computer')).toHaveCount(0);

  // Partial also lists unavailable albums that have recorded tracks (Blonde has three).
  await page.getByRole('radio', { name: 'Partial' }).click();
  await expect(card(page, 'Elsewhere')).toBeVisible();
  await expect(card(page, 'Blonde')).toBeVisible();
  await expect(card(page, 'Melodrama')).toHaveCount(0);

  await page.getByRole('radio', { name: 'All' }).click();
  const search = page.getByRole('searchbox', { name: 'Search albums' });
  await search.fill('lorde');
  await expect(card(page, 'Melodrama')).toBeVisible();
  await expect(card(page, 'OK Computer')).toHaveCount(0);

  await search.press('Escape');
  await expect(search).toHaveValue('');
  await expect(card(page, 'OK Computer')).toBeVisible();
});

test('the list view is remembered per browser, and sorts by album', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('radio', { name: 'List' }).click();
  await expect(page.getByRole('table', { name: 'Albums' })).toBeVisible();

  await openPage(page, '/albums');
  await expect(page.getByRole('table', { name: 'Albums' })).toBeVisible();

  await page.getByRole('combobox', { name: 'Sort' }).selectOption('album');
  await expect(page.getByRole('table', { name: 'Albums' }).getByRole('row').nth(1)).toContainText('Blonde');
  // Each row: album and artist, year, tracks, recorded date, status, and the ⋯ menu.
  await expect(row(page, 'OK Computer')).toContainText('1997');
  await expect(row(page, 'OK Computer')).toContainText('12 / 12');
  await expect(row(page, 'OK Computer')).toContainText('Recorded');
});

test('a row menu opens the album on Spotify, and shows where its files are', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('radio', { name: 'List' }).click();

  await row(page, 'OK Computer').getByRole('button', { name: 'Options for OK Computer' }).click();
  const popup = page.waitForEvent('popup');
  await page.getByRole('menuitem', { name: 'Open in Spotify' }).click();
  expect((await popup).url()).toContain('open.spotify.com/album/');

  await row(page, 'OK Computer').getByRole('button', { name: 'Options for OK Computer' }).click();
  await page.getByRole('menuitem', { name: 'Show files path' }).click();
  await expect(page.getByText('Recorded in Radiohead/OK Computer')).toBeVisible();
});

test('Record again starts a run for the album, and Remove keeps its files', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('radio', { name: 'List' }).click();

  await row(page, 'Melodrama').getByRole('button', { name: 'Options for Melodrama' }).click();
  await page.getByRole('menuitem', { name: 'Record again' }).click();
  await expect(page.getByText('Backup started')).toBeVisible();

  await row(page, 'Melodrama').getByRole('button', { name: 'Options for Melodrama' }).click();
  await page.getByRole('menuitem', { name: 'Remove from Albums' }).click();
  await expect(page.getByText('Removed from Albums. Its files are kept.')).toBeVisible();
  await expect(row(page, 'Melodrama')).toHaveCount(0);
});

test('the + modal adds a saved album, which joins the page as Queued', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  await expect(modal.getByText('Your saved albums · most recently saved first')).toBeVisible();
  // Each Add says which album it adds.
  await expect(modal.getByRole('button', { name: /^Add / })).toHaveCount(2);

  await modal.getByRole('button', { name: 'Add Currents', exact: true }).click();
  // The added album leaves the list; the modal stays open for more.
  await expect(modal.getByRole('button', { name: /^Add / })).toHaveCount(1);
  await modal.getByRole('button', { name: 'Done' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(card(page, 'Currents')).toBeVisible();
  await expect(page.getByText('6 albums · 1 recorded · 3 queued')).toBeVisible();
});

test('the + modal from the keyboard: after an Add, focus moves to the next Add, and Escape still closes it', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  const first = modal.getByRole('button', { name: 'Add Currents', exact: true });
  await first.focus();
  await page.keyboard.press('Enter');
  await expect(first).toHaveCount(0);
  await expect(modal.getByRole('button', { name: 'Add Punisher', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  // The last one gone: focus goes to the filter.
  await expect(modal.getByRole('searchbox', { name: 'Filter by album name' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('an album added meanwhile elsewhere: Add says so, and the album is on the page', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  await expect(modal.getByRole('button', { name: 'Add Currents', exact: true })).toBeVisible();
  // Another tab adds it first: the answer skips it, `already_added`.
  const elsewhere = await request.post('/api/albums', { data: { ids: [fakeId('currents')] } });
  expect(elsewhere.ok()).toBe(true);

  await modal.getByRole('button', { name: 'Add Currents', exact: true }).click();
  const toast = page.getByText('Currents was already added.');
  await expect(toast).toBeVisible();
  // Drawn above the modal's scrim, where it can be read: the toast is the top element at its own
  // centre. (toBeVisible doesn't check whether something covers it.)
  await expect
    .poll(() =>
      toast.evaluate((text) => {
        const box = text.parentElement ?? text;
        const rect = box.getBoundingClientRect();
        const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        return top !== null && box.contains(top);
      }),
    )
    .toBe(true);
  await expect(modal.getByRole('button', { name: 'Add Currents', exact: true })).toHaveCount(0);
  await modal.getByRole('button', { name: 'Done' }).click();
  await expect(card(page, 'Currents')).toBeVisible();
});

test('the + modal filters by name, and says when nothing matches', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  const filter = modal.getByRole('searchbox', { name: 'Filter by album name' });

  await filter.fill('pun');
  await expect(modal.getByText('Punisher', { exact: true })).toBeVisible();
  await expect(modal.getByText('Currents', { exact: true })).toHaveCount(0);

  await filter.fill('zzz');
  await expect(modal.getByText('No saved album matches “zzz”')).toBeVisible();

  await filter.press('Escape');
  await expect(modal).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('with no album added, the grid says so, and the + modal offers every saved album', async ({ page, request }) => {
  await useScenario(request, 'new');
  await openPage(page, '/albums');
  await expect(page.getByText('No albums yet')).toBeVisible();
  await expect(page.getByText('0 albums · 0 recorded · 0 queued')).toBeVisible();

  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  await expect(modal.getByRole('button', { name: /^Add / })).toHaveCount(7);
});

test('when every saved album is added, the + modal says so', async ({ page, request }) => {
  await useScenario(request, 'new');
  const added = await request.post('/api/albums', { data: { all: true } });
  expect(added.ok()).toBe(true);
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  const modal = page.getByRole('dialog', { name: 'Add albums' });
  await expect(modal.getByText('All your saved albums are already added')).toBeVisible();
  await expect(modal.getByText('Save albums in Spotify first, then they show up here.')).toBeVisible();
});

test('without a Web API connection, the + modal says what to do', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).connection('disconnected');
  await openPage(page, '/albums');
  await page.getByRole('button', { name: 'Add albums' }).click();
  await expect(page.getByText('Connect spotivault to Spotify first (Settings › Spotify account).')).toBeVisible();
});

test('the detail view lists the tracks with their states, and Record now starts a run', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await card(page, 'Elsewhere').click();
  await expect(page).toHaveURL(/\/albums\/[0-9A-Za-z]{22}$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Elsewhere' })).toBeVisible();
  await expect(page.locator('a[href="/albums"]').first()).toBeVisible();
  await expect(page.getByText('fakename · 11 tracks', { exact: false })).toBeVisible();

  const tracks = page.getByRole('table', { name: 'Tracks' });
  await expect(tracks.getByRole('row')).toHaveCount(12);
  await expect(tracks.getByText('Failed · low volume')).toBeVisible();
  // Elsewhere: 9 of 11 on disk (rows 4 and 8 were duplicates), then the failed track and a missing one.
  await expect(tracks.getByText('Skipped (duplicate)')).toHaveCount(2);
  await expect(tracks.getByText('Missing', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Record now' }).click();
  await expect(page.getByText('Backup started')).toBeVisible();
});

test('the detail view removes the album and goes back to the list', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums');
  await card(page, 'Melodrama').click();
  await page.getByRole('button', { name: 'Remove from Albums' }).click();
  await expect(page).toHaveURL(/\/albums$/);
  await expect(card(page, 'Melodrama')).toHaveCount(0);
});

test('an album that is not on the page says so', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/albums/unknownalbumid0000000');
  await expect(page.getByText("It isn't there any more. The page may be out of date.")).toBeVisible();
  await expect(page.getByRole('link', { name: 'Back to Albums' })).toBeVisible();
});

test('during a run, the queued albums show Queued, linking to the Dashboard', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/albums');
  await expect(page.getByRole('link', { name: 'Queued' }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'Queued' }).first()).toHaveAttribute('href', '/dashboard');
});

test('a recording album shows Recording, linking to the Dashboard, and the grid follows it live', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, `/albums/${await albumId(request, 'Melodrama')}`);
  await page.getByRole('button', { name: 'Record now' }).click();
  await expect(page.getByText('Backup started')).toBeVisible();

  // The album's own pill turns to Recording while its tracks are taken (album.item), then back.
  await openPage(page, '/albums');
  await expect(page.getByRole('link', { name: 'Recording' })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('link', { name: 'Recording' })).toHaveAttribute('href', '/dashboard');
});

test('the summary and the detail view follow the albums live, while the run goes on', async ({ page, request }) => {
  test.setTimeout(120_000);
  await useScenario(request, 'idle');
  const runState = async () => ((await (await request.get('/api/status')).json()) as { state: string }).state;
  await openPage(page, '/albums');
  await expect(page.getByText('5 albums · 1 recorded · 2 queued')).toBeVisible();

  // In Rainbows, then Melodrama. In Rainbows ends Partial: its second track comes out too quiet.
  const inRainbows = await albumId(request, 'In Rainbows');
  const started = await request.post('/api/runs', { data: { items: [inRainbows, await albumId(request, 'Melodrama')] } });
  expect(started.ok()).toBe(true);
  // In Rainbows records: no longer queued. The summary follows its status, not only the run's end.
  await expect(page.getByText('5 albums · 1 recorded · 1 queued')).toBeVisible({ timeout: 15_000 });
  expect(await runState()).not.toBe('idle');

  // Its detail view: the track table follows the album's own event when its turn ends.
  await card(page, 'In Rainbows').click();
  const tracks = page.getByRole('table', { name: 'Tracks' });
  await expect(tracks.getByText('Missing', { exact: true })).toHaveCount(10);
  await expect(tracks.getByText('Failed · low volume')).toBeVisible({ timeout: 60_000 });
  await expect(tracks.getByText('Missing', { exact: true })).toHaveCount(0);
  expect(await runState()).not.toBe('idle'); // Melodrama's turn
});

/** The id of an album by its name, from the mock's list (GET /api/albums). */
async function albumId(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.get('/api/albums');
  const { items } = (await response.json()) as { items: { id: string; name: string }[] };
  const album = items.find((item) => item.name === name);
  if (!album) throw new Error(`no album ${name}`);
  return album.id;
}
