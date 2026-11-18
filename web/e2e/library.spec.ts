// The Library against the mock (web-ui.md § Library): the list and the grid, filters, search,
// sort, the tracking switch, Back up now, the row and header menus, the detail view, and the
// + modal with its suggestions, pasted links and their errors. Every state the page has is
// reached here through the mock's scenarios and controls.

import { expect, test, type Locator, type Page } from '@playwright/test';
import { fakeId, LATE_NIGHT_DRIVE } from '../mock/fixtures.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

/** The row of the List view that holds this name. */
function row(page: Page, name: string): Locator {
  return page.getByRole('table', { name: 'Library' }).getByRole('row').filter({ hasText: name });
}

/** The card of the Grid view that holds this name. */
function card(page: Page, name: string): Locator {
  return page.getByRole('list', { name: 'Library' }).getByRole('listitem').filter({ hasText: name });
}

/** Opens the + modal from the header. */
async function openAdd(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Add playlists' }).click();
  await expect(page.getByRole('dialog', { name: 'Add playlists' })).toBeVisible();
}

test.describe('the List view', () => {
  test('shows every item with its status, under the summary line', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await expect(page.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible();
    await expect(page.getByText(/^7 of 8 tracked · last backup /)).toBeVisible();

    // Each pill of the Library's set (web-ui.md § Item states), from the idle scenario.
    await expect(row(page, 'Liked Songs').getByText('14 new')).toBeVisible();
    await expect(row(page, 'Late Night Drive').getByText('Up to date')).toBeVisible();
    await expect(row(page, 'Chill Mix').getByText('Partial')).toBeVisible();
    await expect(row(page, 'Road Trip 2026').getByText('Never backed up')).toBeVisible();
    await expect(row(page, 'Sunday Vinyl').getByText('Unavailable')).toBeVisible();
    await expect(row(page, 'Focus').getByText('Not tracked')).toBeVisible();
    // Liked Songs comes first, whatever the sort.
    await expect(page.getByRole('table', { name: 'Library' }).getByRole('row').nth(1)).toContainText('Liked Songs');
  });

  test('a followed playlist shows its listed total with a tooltip; a linked one has no total', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await expect(row(page, 'Late Night Drive').getByText(/recorded/)).toContainText('32 / 35 recorded');
    await expect(row(page, 'KEXP Live Sets').getByText('12 recorded', { exact: true })).toBeVisible();
  });

  test('the new scenario has every tracked playlist never backed up', async ({ page, request }) => {
    await useScenario(request, 'new');
    await openPage(page, '/library');
    await expect(row(page, 'Chill Mix').getByText('Never backed up')).toBeVisible();
    await expect(row(page, 'Indie Finds').getByText('Never backed up')).toBeVisible();
  });

  test('a running item shows Recording and Queued, both linking to the Dashboard', async ({ page, request }) => {
    await useScenario(request, 'running');
    await openPage(page, '/library');
    await expect(page.getByRole('link', { name: 'Recording' }).first()).toHaveAttribute('href', '/dashboard');
    await expect(page.getByRole('link', { name: 'Queued' }).first()).toHaveAttribute('href', '/dashboard');
  });

  test('the list is kept when you come back from a detail view', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await row(page, 'Chill Mix').getByRole('button', { name: 'Chill Mix', exact: true }).click();
    await expect(page).toHaveURL(/\/library\/[0-9A-Za-z]+$/);
    await page.getByRole('link', { name: 'Library' }).first().click();
    await expect(page.getByRole('heading', { level: 1, name: 'Library' })).toBeVisible();
    await expect(row(page, 'Chill Mix')).toBeVisible();
  });
});

test.describe('the Grid view', () => {
  test('the choice is remembered per browser, and cards carry the badge and the status', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('radio', { name: 'Grid' }).click();
    await expect(page.getByRole('list', { name: 'Library' })).toBeVisible();
    await expect(card(page, 'Chill Mix').getByRole('switch', { name: 'Track Chill Mix' })).toHaveAttribute('aria-checked', 'true');
    await expect(card(page, 'Focus').getByRole('switch', { name: 'Track Focus' })).toHaveAttribute('aria-checked', 'false');
    await expect(card(page, 'Chill Mix').getByText('Partial')).toBeVisible();

    // A new visit opens the grid again: the choice is per browser, not per visit.
    await openPage(page, '/library');
    await expect(page.getByRole('list', { name: 'Library' })).toBeVisible();
  });

  test('during a run: Recording and Queued link to the Dashboard, and a ring shows the progress', async ({ page, request }) => {
    await useScenario(request, 'running');
    await openPage(page, '/library');
    await page.getByRole('radio', { name: 'Grid' }).click();
    const liked = card(page, 'Liked Songs');
    await expect(liked.getByRole('link', { name: 'Recording' })).toHaveAttribute('href', '/dashboard', { timeout: 10_000 });
    await expect(card(page, 'Indie Finds').getByRole('link', { name: 'Queued' })).toHaveAttribute('href', '/dashboard');

    // web-ui.md § Grid view: a thin ring around the badge while the item records. Its fill is the
    // share recorded: Liked Songs has 2 new tracks, so half once the first is recorded.
    const ring = liked.getByRole('switch', { name: 'Track Liked Songs' }).locator('svg circle').nth(1);
    await expect(ring).toHaveAttribute('stroke-dasharray', '0 100');
    await expect(ring).toHaveAttribute('stroke-dasharray', '50 100', { timeout: 15_000 });
    // A queued item has no ring (its badge holds only the check).
    await expect(card(page, 'Indie Finds').getByRole('switch', { name: 'Track Indie Finds' }).locator('svg circle')).toHaveCount(0);
  });

  test('the badge toggles tracking', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('radio', { name: 'Grid' }).click();
    await card(page, 'Focus').getByRole('switch', { name: 'Track Focus' }).click();
    await expect(card(page, 'Focus').getByRole('switch', { name: 'Track Focus' })).toHaveAttribute('aria-checked', 'true');
    await expect(card(page, 'Focus').getByText('Never backed up')).toBeVisible();
  });
});

test.describe('filter, search and sort', () => {
  test('each filter chip shows its items', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('radio', { name: 'Not tracked' }).click();
    await expect(row(page, 'Focus')).toBeVisible();
    await expect(page.getByRole('table', { name: 'Library' }).getByRole('row').filter({ hasNotText: 'Focus' })).toHaveCount(1); // header only

    await page.getByRole('radio', { name: 'Created by you' }).click();
    await expect(row(page, 'Chill Mix')).toBeVisible();
    await expect(row(page, 'Late Night Drive')).toHaveCount(0);

    await page.getByRole('radio', { name: 'Added' }).click();
    await expect(row(page, 'Late Night Drive')).toBeVisible();
    await expect(row(page, 'KEXP Live Sets')).toBeVisible();
    await expect(row(page, 'Chill Mix')).toHaveCount(0);

    await page.getByRole('radio', { name: 'Tracked', exact: true }).click();
    await expect(row(page, 'Focus')).toHaveCount(0);
    await expect(row(page, 'Chill Mix')).toBeVisible();
  });

  test('search narrows the list after a pause, and Escape clears it', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    const search = page.getByRole('searchbox', { name: 'Search in Library' });
    await search.fill('chill');
    await expect(row(page, 'Chill Mix')).toBeVisible();
    await expect(row(page, 'Indie Finds')).toHaveCount(0);
    await search.press('Escape');
    await expect(search).toHaveValue('');
    await expect(row(page, 'Indie Finds')).toBeVisible();
  });

  test('a search with no match says so', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('searchbox', { name: 'Search in Library' }).fill('no such playlist');
    await expect(page.getByText('Nothing matches')).toBeVisible();
  });

  test('sort by name puts the items in name order, Liked Songs still first', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('combobox', { name: 'Sort' }).selectOption('name');
    const order = ['Chill Mix', 'Focus', 'Indie Finds', 'KEXP Live Sets', 'Late Night Drive', 'Road Trip 2026', 'Sunday Vinyl'];
    // The list is re-sorted by the controller's answer, so poll until the new order has arrived.
    await expect
      .poll(async () => {
        const names = await page.getByRole('table', { name: 'Library' }).getByRole('row').allInnerTexts();
        return names.map((text) => order.find((name) => text.startsWith(name))).filter(Boolean);
      })
      .toEqual(order);
  });
});

test.describe('actions on an item', () => {
  test('the tracking switch flips, and the status follows', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await row(page, 'Focus').getByRole('switch', { name: 'Track Focus' }).click();
    await expect(row(page, 'Focus').getByRole('switch', { name: 'Track Focus' })).toHaveAttribute('aria-checked', 'true');
    await expect(row(page, 'Focus').getByText('Never backed up')).toBeVisible();
  });

  test('Back up now on a row starts a run, and the toast says so', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    const target = row(page, 'Indie Finds');
    await target.hover();
    await target.getByRole('button', { name: 'Back up now' }).click();
    await expect(page.getByText('Backup started')).toBeVisible();
  });

  test('the row menu offers Back up now, Open in Spotify, Show files path, and Remove for added items', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('button', { name: 'Options for Chill Mix' }).click();
    const menu = page.getByRole('menu');
    await expect(menu.getByRole('menuitem', { name: 'Back up now' })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: 'Open in Spotify' })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: 'Show files path' })).toBeVisible();
    // Your own playlists are only untracked, never removed.
    await expect(menu.getByRole('menuitem', { name: 'Remove from Library' })).toHaveCount(0);
    await menu.getByRole('menuitem', { name: 'Show files path' }).click();
    await expect(page.getByText('Music/Playlists/Chill Mix.m3u')).toBeVisible();
  });

  test('Remove from Library takes an added item out, and keeps its files', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('button', { name: 'Options for KEXP Live Sets' }).click();
    await page.getByRole('menuitem', { name: 'Remove from Library' }).click();
    await expect(page.getByText('Removed from Library')).toBeVisible();
    await expect(row(page, 'KEXP Live Sets')).toHaveCount(0);
  });

  test('the header menu tracks playlists you create automatically, and backs up all tracked now', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await page.getByRole('button', { name: 'Library options' }).click();
    const auto = page.getByRole('menuitemcheckbox', { name: 'Automatically track playlists I create' });
    await expect(auto).toHaveAttribute('aria-checked', 'true');
    await auto.click();
    await page.getByRole('button', { name: 'Library options' }).click();
    await expect(page.getByRole('menuitemcheckbox', { name: 'Automatically track playlists I create' })).toHaveAttribute('aria-checked', 'false');
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Library options' }).click();
    await page.getByRole('menuitem', { name: 'Back up all tracked now' }).click();
    await expect(page.getByText('Backup started')).toBeVisible();
  });
});

test.describe('the detail view', () => {
  test('lists the tracks with their states, and the header has the actions', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await row(page, 'Chill Mix').getByRole('button', { name: 'Chill Mix', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Chill Mix' })).toBeVisible();
    await expect(page.getByText('Playlist', { exact: true })).toBeVisible();
    await expect(page.getByText(/^by you · 120 tracks · .* · 84 recorded$/)).toBeVisible();

    const tracks = page.getByRole('table', { name: 'Tracks' });
    await expect(tracks.getByText(/^Recorded · /).first()).toBeVisible();
    await expect(tracks.getByText('Skipped (duplicate)').first()).toBeVisible();
    await expect(tracks.getByText('Failed · low volume').first()).toBeVisible();
    await expect(tracks.getByText('Missing').first()).toBeVisible();
    await expect(tracks.getByText('New', { exact: true }).first()).toBeVisible();

    await expect(page.getByRole('button', { name: 'Back up now' })).toBeVisible();
    await expect(page.getByRole('switch', { name: 'Track Chill Mix' })).toHaveAttribute('aria-checked', 'true');
    await expect(page.getByText('Files are never deleted.')).toBeVisible();
  });

  test('a playlist without item access says so, and shows only what was recorded', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, `/library/${LATE_NIGHT_DRIVE}`);
    await expect(page.getByRole('heading', { level: 1, name: 'Late Night Drive' })).toBeVisible();
    await expect(
      page.getByText("Spotify doesn't share this playlist's track list with the app; tracks appear here as they're recorded."),
    ).toBeVisible();
    // The header and the four recorded or skipped tracks; the others were never seen by the app.
    await expect(page.getByRole('table', { name: 'Tracks' }).getByRole('row')).toHaveCount(5);
    await expect(page.getByText('Missing')).toHaveCount(0);
  });

  test('Stop tracking your own playlist keeps its files', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, `/library/${fakeId('chillmix')}`);
    await page.getByRole('button', { name: 'Stop tracking' }).click();
    await expect(page.getByRole('switch', { name: 'Track Chill Mix' })).toHaveAttribute('aria-checked', 'false');
    // The header's word and the status pill both say it.
    await expect(page.getByText('Not tracked', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop tracking' })).toBeDisabled();
  });

  test('Remove from Library on an added playlist goes back to the list', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, `/library/${fakeId('kexpliveset')}`);
    await page.getByRole('button', { name: 'Remove from Library' }).click();
    await expect(page).toHaveURL(/\/library$/);
    await expect(row(page, 'KEXP Live Sets')).toHaveCount(0);
  });

  test('a playlist that is gone says so, and links back to the Library', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library/3cEYpjA9oz9GiPac4AsH4z');
    await expect(page.getByText("This playlist isn't in the Library")).toBeVisible();
    await expect(page.getByRole('link', { name: 'Back to Library' })).toHaveAttribute('href', '/library');
  });
});

test.describe('the + modal', () => {
  test('suggests the playlists you follow; typing filters them; Add tracks one and stays open', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    const modal = page.getByRole('dialog', { name: 'Add playlists' });
    await expect(modal.getByText('Playlists you follow')).toBeVisible();
    await expect(modal.getByText('Best New Tracks')).toBeVisible();
    await expect(modal.getByText('Jazz Brunch')).toBeVisible();

    await modal.getByRole('searchbox').fill('jazz');
    await expect(modal.getByText('Best New Tracks')).toHaveCount(0);
    await modal.getByRole('button', { name: 'Add Jazz Brunch' }).click();
    await expect(modal.getByText('Added', { exact: true })).toBeVisible();
    await expect(modal).toBeVisible();

    await modal.getByRole('button', { name: 'Done' }).click();
    await expect(modal).toHaveCount(0);
    await expect(row(page, 'Jazz Brunch')).toBeVisible();
    await expect(row(page, 'Jazz Brunch').getByRole('switch', { name: 'Track Jazz Brunch' })).toHaveAttribute('aria-checked', 'true');
  });

  test('a search with no followed playlist says Nothing to suggest', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    await page.getByRole('dialog', { name: 'Add playlists' }).getByRole('searchbox').fill('zzzz');
    await expect(page.getByText('Nothing to suggest')).toBeVisible();
  });

  test('a pasted link previews the playlist, and Add tracks it', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    const modal = page.getByRole('dialog', { name: 'Add playlists' });
    await modal.getByRole('searchbox').fill(`https://open.spotify.com/playlist/${fakeId('fridayfinds')}?si=abc`);
    await expect(modal.getByText('Friday Finds')).toBeVisible();
    await expect(modal.getByText('by Ana · from link')).toBeVisible();
    await modal.getByRole('button', { name: 'Add Friday Finds' }).click();
    await expect(modal.getByText('Added', { exact: true })).toBeVisible();
  });

  test('a spotify: URI previews too', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    await page.getByRole('dialog', { name: 'Add playlists' }).getByRole('searchbox').fill(`spotify:playlist:${fakeId('morningcommute')}`);
    await expect(page.getByRole('dialog', { name: 'Add playlists' }).getByText('Morning Commute')).toBeVisible();
  });

  test('a link that cannot be used says why, in the modal', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    const modal = page.getByRole('dialog', { name: 'Add playlists' });
    const search = modal.getByRole('searchbox');

    await search.fill('https://example.com/playlist/nope');
    await expect(modal.getByText("That isn't a Spotify playlist link.", { exact: true })).toBeVisible();

    await search.fill('spotify:playlist:ZZZZZZZZZZZZZZZZZZZZZZ');
    await expect(modal.getByText('Spotify has no playlist at that link.')).toBeVisible();

    await search.fill('spotify:playlist:privateprivate12345678');
    await expect(modal.getByText("That playlist is private, so it can't be added.")).toBeVisible();

    await search.fill('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M');
    await expect(modal.getByText("Playlists made by Spotify aren't available through the API, so they can't be added.", { exact: true })).toBeVisible();
  });

  test('without a connection, or with Spotify down, a link says so', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await mockControls(request).connection('disconnected');
    await openPage(page, '/library');
    await openAdd(page);
    const modal = page.getByRole('dialog', { name: 'Add playlists' });
    await modal.getByRole('searchbox').fill(`spotify:playlist:${fakeId('fridayfinds')}`);
    await expect(modal.getByText('Connect spotivault to Spotify first (Settings › Spotify account).')).toBeVisible();

    await mockControls(request).connection('ok');
    await mockControls(request).spotify('unavailable');
    await modal.getByRole('searchbox').fill(`spotify:playlist:${fakeId('morningcommute')}`);
    await expect(modal.getByText("Spotify isn't answering. Try again later.")).toBeVisible();
  });

  test('an expired connection refuses the link with its own words', async ({ page, request }) => {
    await useScenario(request, 'expired');
    await openPage(page, '/library');
    await openAdd(page);
    await page.getByRole('dialog', { name: 'Add playlists' }).getByRole('searchbox').fill(`spotify:playlist:${fakeId('fridayfinds')}`);
    await expect(page.getByText('The Spotify connection has expired. Reconnect to go on.')).toBeVisible();
  });

  test('Escape closes it, and focus goes back to the + button', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Add playlists' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Add playlists' })).toBeFocused();
  });

  test('from the keyboard, Add leaves focus on "Added", and Escape still closes it', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/library');
    await openAdd(page);
    const modal = page.getByRole('dialog', { name: 'Add playlists' });
    await modal.getByRole('button', { name: 'Add Jazz Brunch' }).focus();
    await page.keyboard.press('Enter');
    await expect(modal.getByText('Added', { exact: true })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(modal).toHaveCount(0);
  });
});
