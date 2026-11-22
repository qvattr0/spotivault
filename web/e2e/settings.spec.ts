// Settings against the mock: the page's sections, Recording, Files, Library and the Unsaved changes
// bar. The Spotify, Container and About sections are in settings-account.spec.ts.

import { expect, test, type APIRequestContext } from '@playwright/test';
import type { Settings } from '../src/api/types.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

async function savedSettings(request: APIRequestContext): Promise<Settings> {
  const response = await request.get('/api/settings');
  return (await response.json()) as Settings;
}

test('Settings has its sections, and none that M1 leaves out', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();
  for (const name of ['Recording', 'Files', 'Library', 'Spotify account (Web API)', 'Spotify client', 'Container', 'About']) {
    await expect(page.getByRole('heading', { level: 2, name })).toBeVisible();
  }
  // Notifications and the UI password aren't in M1, and no link goes to Schedule (web-ui.md § Settings).
  await expect(page.getByRole('heading', { name: 'Notifications' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Security' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Unsaved changes' })).toHaveCount(0);
});

test('the format chips save with the bitrate, and the page shows the saved choice after a reload', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const format = page.getByRole('radiogroup', { name: 'Format' });
  await expect(format.getByRole('radio', { name: 'AAC 256' })).toBeChecked();

  await format.getByRole('radio', { name: 'AAC 320' }).click();
  const bar = page.getByRole('region', { name: 'Unsaved changes' });
  await expect(bar).toBeVisible();
  await bar.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  await expect(bar).toHaveCount(0);
  expect(await savedSettings(request)).toMatchObject({ format: 'aac', bitrate: 320, extension: 'm4a' });

  await openPage(page, '/settings');
  await expect(page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'AAC 320' })).toBeChecked();
});

test('More formats opens by itself for FLAC, and the layout shows its extension', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const more = page.getByRole('button', { name: 'More formats' });
  await expect(more).toHaveAttribute('aria-expanded', 'false');
  await more.click();
  const flacs = page.getByRole('radiogroup', { name: 'More formats' });
  await flacs.getByRole('radio', { name: 'FLAC' }).click();
  await expect(page.getByText('FLAC. No benefit: the source is lossy (Ogg Vorbis 320). Bigger files, same quality.')).toBeVisible();
  await expect(page.getByText('Music/{album_artist}/{album}/{track} - {title}.flac')).toBeVisible();
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
  expect(await savedSettings(request)).toMatchObject({ format: 'flac', bitrate: null, extension: 'flac' });

  await openPage(page, '/settings');
  await expect(page.getByRole('button', { name: 'More formats' })).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('radiogroup', { name: 'More formats' }).getByRole('radio', { name: 'FLAC' })).toBeChecked();
});

test('Discard puts the saved values back; a toggle set back is no change', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const m3u = page.getByRole('switch', { name: 'Write .m3u playlists' });
  await expect(m3u).toHaveAttribute('aria-checked', 'true');
  await m3u.click();
  const bar = page.getByRole('region', { name: 'Unsaved changes' });
  await expect(bar).toBeVisible();
  await bar.getByRole('button', { name: 'Discard' }).click();
  await expect(bar).toHaveCount(0);
  await expect(m3u).toHaveAttribute('aria-checked', 'true');

  await m3u.click();
  await m3u.click();
  await expect(bar).toHaveCount(0);
});

test('the Unsaved changes bar never covers the control whose change brought it up', async ({ page, request }) => {
  await useScenario(request, 'idle');
  // Short enough that the Library section starts below the fold, so it can be scrolled to the foot.
  await page.setViewportSize({ width: 1440, height: 640 });
  await openPage(page, '/settings');
  const toggle = page.getByRole('switch', { name: 'Automatically track playlists I create' });
  // Scroll the panel so the switch sits just above its foot, fully in view, where the bar will
  // come up, and focus it there without scrolling (as Tab does with a control already in view).
  await toggle.evaluate((element) => {
    const panel = element.closest('main');
    if (!panel) throw new Error('no panel');
    panel.scrollTop += element.getBoundingClientRect().bottom - panel.getBoundingClientRect().bottom + 8;
    (element as HTMLElement).focus({ preventScroll: true });
  });
  // It's in view, in the band the bar will cover.
  const before = await toggle.evaluate((element) => {
    const panel = element.closest('main')?.getBoundingClientRect();
    return panel ? panel.bottom - element.getBoundingClientRect().bottom : -1;
  });
  expect(before).toBeGreaterThanOrEqual(0);
  expect(before).toBeLessThan(40);
  await page.keyboard.press('Space');
  const bar = page.getByRole('region', { name: 'Unsaved changes' });
  await expect(bar).toBeVisible();
  await expect
    .poll(async () => {
      const [control, foot] = await Promise.all([toggle.boundingBox(), bar.boundingBox()]);
      return control && foot ? control.y + control.height <= foot.y : false;
    })
    .toBe(true);
});

test('a playlist file toggle saves, and Library’s auto-track toggle saves with it', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await page.getByRole('switch', { name: 'Write .m3u playlists' }).click();
  await page.getByRole('switch', { name: 'Automatically track playlists I create' }).click();
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  expect(await savedSettings(request)).toMatchObject({ write_m3u: false, auto_track_owned: false });
});

test("Save Spotify's covers saves, and is on by default", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const covers = page.getByRole('switch', { name: "Save Spotify's covers" });
  await expect(covers).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByText(/^Each playlist's cover is saved next to its \.m3u as Music\/Playlists\/<name>\.jpg/)).toBeVisible();
  await covers.click();
  const bar = page.getByRole('region', { name: 'Unsaved changes' });
  await expect(bar).toBeVisible();
  await bar.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  expect(await savedSettings(request)).toMatchObject({ save_spotify_covers: false });
  await openPage(page, '/settings');
  await expect(page.getByRole('switch', { name: "Save Spotify's covers" })).toHaveAttribute('aria-checked', 'false');
});

test("Save Spotify's covers: Discard from the unsaved changes puts it back, and nothing is saved", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const covers = page.getByRole('switch', { name: "Save Spotify's covers" });
  await covers.click();
  const bar = page.getByRole('region', { name: 'Unsaved changes' });
  await expect(bar).toBeVisible();
  await bar.getByRole('button', { name: 'Discard' }).click();
  await expect(bar).toHaveCount(0);
  await expect(covers).toHaveAttribute('aria-checked', 'true');
  expect(await savedSettings(request)).toMatchObject({ save_spotify_covers: true });
});

test('Edit layout opens the wizard\'s modal, and Cancel leaves the layout as it was', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await page.getByRole('button', { name: 'Edit layout' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit layout' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Unsaved changes' })).toHaveCount(0);
});

test('a layout changed in Edit layout is saved from the unsaved changes', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await page.getByRole('button', { name: 'Edit layout' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit layout' });
  await dialog.getByRole('switch', { name: 'Underscores instead of spaces' }).click();
  await dialog.getByRole('button', { name: 'Apply' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  expect((await savedSettings(request)).layout).toMatchObject({ underscores: true });
});

test('Edit layout checks as you type: an error replaces the hint, and Apply waits until it is valid', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await page.getByRole('button', { name: 'Edit layout' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit layout' });
  const field = dialog.getByRole('textbox', { name: 'Layout' });
  const apply = dialog.getByRole('button', { name: 'Apply' });
  const hint = dialog.getByText(/^Folders can be none, \{album_artist\}, or \{album_artist\}\/\{album\}\. The file name/);
  await expect(dialog.getByText('Valid', { exact: true })).toBeVisible();
  await expect(hint).toBeVisible();

  // Each rule of web-ui.md § Files has its own red line, in place of the hint (layout-example.ts).
  const invalid: [string, string][] = [
    ['{album}/{title}', 'Folders can be none, {album_artist}, or {album_artist}/{album}.'],
    ['{album_artist}/{genre}', "{genre} isn't a placeholder. Use one of the six below."],
    ['{album_artist}/{title', 'A { or } is on its own. Placeholders look like {title}.'],
    ['{album_artist}\\{title}', 'A \\ can’t be used. Use / between folders.'],
    ['{album_artist}/', 'The file name, after the last /, can’t be empty.'],
    ['{album_artist}/{year}', 'The file name needs a placeholder other than {year}, which is always empty.'],
  ];
  for (const [pattern, error] of invalid) {
    await field.fill(pattern);
    await expect(field).toHaveAttribute('aria-invalid', 'true');
    await expect(dialog.getByText(error, { exact: true })).toBeVisible();
    await expect(hint).toHaveCount(0);
    await expect(dialog.getByText('Valid', { exact: true })).toHaveCount(0);
    await expect(dialog.getByText('Fix the layout to see an example.')).toBeVisible();
    await expect(apply).toBeDisabled();
  }

  // The Insert chips type a placeholder at the cursor; the layout turns valid, and the example follows.
  await field.fill('{album_artist}/');
  await field.press('End');
  await dialog.getByRole('button', { name: 'Insert {title}' }).click();
  await expect(field).toHaveValue('{album_artist}/{title}');
  await expect(dialog.getByText('Valid', { exact: true })).toBeVisible();
  await expect(hint).toBeVisible();
  await expect(dialog.getByText('Music/fakename/Last Hours.m4a', { exact: true })).toBeVisible();

  // Prefix: Counter, then Album track number, each added before the file name with " - ".
  const prefix = dialog.getByRole('radiogroup', { name: 'Prefix' });
  await prefix.getByRole('radio', { name: 'Counter (001)' }).click();
  await expect(dialog.getByText('Music/fakename/001 - Last Hours.m4a', { exact: true })).toBeVisible();
  await prefix.getByRole('radio', { name: 'Album track number' }).click();
  await expect(dialog.getByText('Music/fakename/05 - Last Hours.m4a', { exact: true })).toBeVisible();

  await apply.click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Music/{album_artist}/{title}.m4a', { exact: true })).toBeVisible();
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();
  expect((await savedSettings(request)).layout).toMatchObject({ pattern: '{album_artist}/{title}', prefix: 'track_number' });
});

test('the music folder shows its free space, and Check access checks it again', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await mock.storage(false);
  await openPage(page, '/settings');
  await expect(page.getByText("/music isn't mounted.")).toBeVisible();
  await mock.storage(true);
  await page.getByRole('button', { name: 'Check access' }).click();
  await expect(page.getByText('/music → /Music · 1.84 TB free')).toBeVisible();
});

test('Re-check on the checklist asks for it again and keeps every row', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const list = page.getByRole('list', { name: 'Settings checklist' });
  await expect(list.getByRole('listitem')).toHaveCount(10);
  const answer = page.waitForResponse((r) => r.url().endsWith('/api/client/checklist') && r.request().method() === 'GET');
  await page.getByRole('button', { name: 'Re-check' }).click();
  expect((await answer).ok()).toBe(true);
  await expect(list.getByRole('listitem').filter({ hasText: 'Volume normalization' })).toContainText('OK');
});
