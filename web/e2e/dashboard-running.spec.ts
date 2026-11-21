// The Dashboard while a run is going (web-ui.md § Running: queue-first), against the mock: the run
// header, the docked strip, the queue's rows, the live track table, Up next, and both ways to stop.
// Mock times: a run starts in 1.2 s; an item gets ready in about 2 s; tracks last 6, 7.5 and 9 s;
// Finishing lasts 1.5 s. Liked Songs (2 new) takes about 19 s. After the last item, the run ends
// 1.5 s later (the controller's wrap-up), so the queue's last rows stay that long.

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { Album } from '../src/api/types.ts';
import { expectRunState } from './live.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

const queue = (page: Page) => page.getByRole('region', { name: 'Queue' });
const upNext = (page: Page) => page.getByRole('region', { name: 'Up next' });
const tracks = (page: Page) => page.getByRole('list', { name: 'Tracks' });

test('the run header: title, line, live counters and Stop; the strip docked under it', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await expect(page.getByRole('heading', { level: 1, name: 'Backing up' })).toBeVisible();
  await expect(page.getByText('Running', { exact: true })).toBeVisible({ timeout: 10_000 });
  // "started 01:00 · 0:42 elapsed · Scheduled · stops by 07:00", then the backlog's time left.
  await expect(page.getByText(/^started \d\d:\d\d · 0:0\d elapsed · Scheduled · stops by \d\d:\d\d · about 27 h left$/)).toBeVisible();
  const counters = page.getByLabel('Counters');
  await expect(counters).toContainText('Recorded 0');
  await expect(counters).toContainText('Failed 0');
  // Liked Songs first skips a track it already has. Skipped doesn't count that (only tracks the run
  // skipped without recording them), so it stays at 0 once the skip shows in the track table.
  await expect(queue(page).getByText('Skipped (duplicate)').first()).toBeVisible({ timeout: 10_000 });
  await expect(counters).toContainText('Skipped 0');
  await expect(page.getByRole('button', { name: 'Stop after this track' })).toBeEnabled();

  // The strip sits at the top, docked; the global bottom bar is hidden on the Dashboard.
  const strips = page.getByRole('region', { name: 'Now recording' });
  await expect(strips).toHaveCount(1);
  await expect(strips.getByRole('button', { name: 'Stop after this track' })).toHaveCount(0);
  await expect(strips.getByText(/^Item 1 of \d$/)).toBeVisible();
});

test('the current item expands: progress, Recording, and the track table ticking off live', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  const current = queue(page).getByRole('group', { name: 'Liked Songs' });
  await expect(current.getByText('Recording', { exact: true }).first()).toBeVisible({ timeout: 10_000 });

  // Liked Songs first skips a track it already has: a row of its own, done at once.
  const rows = tracks(page).getByRole('listitem');
  await expect(rows).toHaveCount(3, { timeout: 10_000 });
  await expect(rows.nth(0)).toHaveAttribute('data-state', 'skipped_duplicate');
  await expect(rows.nth(0)).toContainText('Old Favourite');
  await expect(rows.nth(0)).toContainText('Skipped (duplicate)');
  await expect(current.getByText('1 / 3')).toBeVisible();
  const first = rows.nth(1);
  await expect(first).toHaveAttribute('data-state', 'recording');
  await expect(first).toContainText('Last Hours');
  await expect(first).toContainText(/Recording · 0:0\d \/ 0:06/);
  await expect(rows.nth(2)).toHaveAttribute('data-state', 'pending');
  await expect(rows.nth(2)).toContainText('Pending');

  // The first track ends: Recorded with its size; the second records.
  await expect(first).toHaveAttribute('data-state', 'recorded', { timeout: 10_000 });
  await expect(first).toContainText(/Recorded · \d\.\d MB/);
  await expect(rows.nth(2)).toHaveAttribute('data-state', 'recording');
  await expect(current.getByText('2 / 3')).toBeVisible();
});

test('the session pill says Waiting until a track records, then Recording', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/dashboard');
  await backUpNow(request, ['liked']);
  // web-ui.md § Now-playing strip: Waiting while the run starts and the item gets ready.
  const strip = page.getByRole('region', { name: 'Now recording' });
  await expect(strip.getByText('Waiting', { exact: true })).toBeVisible();
  const current = queue(page).getByRole('group', { name: 'Liked Songs' });
  await expect(current.getByText('Waiting', { exact: true })).toBeVisible();
  await expect(strip.getByText('Recording', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(current.getByText('Recording', { exact: true }).first()).toBeVisible();
  await expect(strip.getByText('Waiting', { exact: true })).toHaveCount(0);
});

test('rows as items end: Finishing, then Done and Up to date', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  // The ~25–30 s between items (1.5 s in the mock).
  await expect(queue(page).getByText('Finishing Liked Songs… saving the last track')).toBeVisible({ timeout: 25_000 });
  await expect(queue(page).getByRole('progressbar', { name: 'Finishing Liked Songs' })).toBeVisible();
  await expect(queue(page).getByText('Liked Songs · 2 recorded · 0 failed')).toBeVisible({ timeout: 5_000 });
  // The playlist after it has nothing new.
  await expect(queue(page).getByText(/^Indie Finds · nothing new$/)).toBeVisible({ timeout: 10_000 });
});

test('Up next: what to expect, and Remove from this run', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  const list = upNext(page);
  await expect(list.getByText('Indie Finds')).toBeVisible({ timeout: 10_000 });
  await expect(list.getByText('nothing new')).toBeVisible();
  await expect(list.getByText('3 tracks')).toHaveCount(3);

  await list.getByRole('button', { name: 'Options for In Rainbows' }).click();
  await page.getByRole('menuitem', { name: 'Remove from this run' }).click();
  await expect(list.getByText('In Rainbows')).toHaveCount(0);
  await expect(list.getByText('3 tracks')).toHaveCount(2);
  // The item count leaves it out too.
  await expect(page.getByRole('region', { name: 'Now recording' }).getByText('Item 1 of 4')).toBeVisible();
});

test('a run starting: "Building the queue…" until its pre-run check passes, then the queue', async ({ page, request }) => {
  // As in the controller (engine/run.py _drive), the queue is built after the pre-run check, so a
  // run in Starting has no items yet. A client that isn't running holds it there while the check
  // restarts it (3 s in the mock). (A carried-over item runs first once the queue is built, so it's
  // never in Up next then; the next test shows its pill in Up next, after Back up now.)
  await useScenario(request, 'idle');
  await mockControls(request).client(false);
  await openPage(page, '/dashboard');
  expect((await request.post('/api/runs', { data: {} })).status()).toBe(202);
  await expect(queue(page).getByText('Building the queue…')).toBeVisible();
  await expect(upNext(page)).toHaveCount(0);

  await expect(queue(page).getByRole('group', { name: 'Liked Songs' })).toBeVisible({ timeout: 15_000 });
  await expect(upNext(page).getByText('Indie Finds')).toBeVisible();
  await expect(queue(page).getByText('Building the queue…')).toHaveCount(0);
});

test('an item the last window cut off waits in Up next as Carried over', async ({ page, request }) => {
  test.setTimeout(60_000);
  // The window ends while Liked Songs records: it's carried over to the next run.
  await useScenario(request, 'running');
  await mockControls(request).windowEnd();
  await expect.poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 30_000 }).toBe('idle');

  // A run of one album; then Back up now on Liked Songs puts it in Up next, marked Carried over.
  const albums = (await (await request.get('/api/albums')).json()) as { items: Album[] };
  const album = albums.items.find((a) => a.status === 'queued');
  await backUpNow(request, [album?.id ?? '']);
  await openPage(page, '/dashboard');
  await expect(queue(page).getByRole('group', { name: album?.name })).toBeVisible({ timeout: 10_000 });
  await backUpNow(request, ['liked']);
  const liked = upNext(page).getByRole('listitem').filter({ hasText: 'Liked Songs' });
  await expect(liked.getByText('Carried over', { exact: true })).toBeVisible();
  await expect(liked.getByText('2 new')).toBeVisible();
});

test('a stall: the item moves to the end of Up next, "Interrupted · will retry"', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await mockControls(request).stall();
  const list = upNext(page);
  await expect(list.getByText('Interrupted · will retry')).toBeVisible({ timeout: 15_000 });
  await expect(list.getByRole('listitem').last()).toContainText('Liked Songs');
});

test('a track that comes out too quiet shows Failed · low volume, and the album ends Partial', async ({ page, request }) => {
  // The second of three tracks fails at about 17 s; the album ends about 11 s later.
  test.setTimeout(60_000);
  await useScenario(request, 'idle');
  const albums = (await (await request.get('/api/albums')).json()) as { items: Album[] };
  const album = albums.items.find((a) => a.status === 'queued');
  expect(album).toBeDefined();
  // Liked Songs after it, so the run is still going when the album ends.
  await backUpNow(request, [album?.id ?? '', 'liked']);
  await openPage(page, '/dashboard');
  const failed = tracks(page).locator('[data-state="failed"]');
  await expect(failed).toContainText('Failed · low volume', { timeout: 25_000 });
  await expect(page.getByLabel('Counters')).toContainText('Failed 1');
  // No alert for a failed track (web-ui.md § Warnings).
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(queue(page).getByText(`${album?.name} · 1 track failed: low volume`)).toBeVisible({ timeout: 20_000 });
  await expect(queue(page).getByText('Partial', { exact: true })).toBeVisible();

  // Once the run ends, the Last run card lists it as an issue.
  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  const last = page.getByRole('region', { name: 'Last run' });
  await expect(last.getByRole('listitem')).toHaveText([`${album?.name}: 1 track failed: low volume`], { timeout: 15_000 });
});

test('Stop after this track: the header says so, Stop now stays, and the run ends Stopped', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await expect(queue(page).getByText('Recording', { exact: true }).first()).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: 'Stop after this track' }).click();
  await expect(page.getByRole('button', { name: 'Stopping after this track…' })).toBeDisabled();
  await expect(page.getByText('Stopping', { exact: true }).first()).toBeVisible();
  // Stop now is still in the arrow: it upgrades the stop.
  await page.getByRole('button', { name: 'More ways to stop' }).click();
  await expect(page.getByRole('menuitem', { name: 'Stop now' })).toBeEnabled();
  await page.keyboard.press('Escape');

  await expectRunState(page, 'idle', 20_000);
  await expect(page.getByRole('region', { name: 'Last run' }).getByText('Stopped', { exact: true })).toBeVisible();
});

test('Stop now asks first, then the run ends Stopped', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await expectRunState(page, 'running', 10_000);
  await page.getByRole('button', { name: 'More ways to stop' }).click();
  await page.getByRole('menuitem', { name: 'Stop now' }).click();
  const dialog = page.getByRole('dialog', { name: 'Stop now?' });
  await expect(dialog.getByText('The current track will be discarded and recorded next time.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toHaveCount(0);
  await expectRunState(page, 'running');

  await page.getByRole('button', { name: 'More ways to stop' }).click();
  await page.getByRole('menuitem', { name: 'Stop now' }).click();
  await page.getByRole('dialog', { name: 'Stop now?' }).getByRole('button', { name: 'Stop now' }).click();
  await expectRunState(page, 'idle', 15_000);
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Last run' }).getByText('Stopped', { exact: true })).toBeVisible();
});

test('the window ends: stop after this track, Carried over, and the run ends Window ended', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await mockControls(request).windowEnd();
  await expect(page.getByRole('button', { name: 'Stopping after this track…' })).toBeDisabled();
  // The track records to its end. Then the cut item is Carried over, and the items it never reached
  // end Stopped (web-ui.md § Queue; Q18). The rows show until the run ends, so they're read together.
  const ended = queue(page).locator('[data-state="carried_over"], [data-state="stopped"]');
  await expect(ended).toHaveText(
    [
      /^Liked Songs · \d recorded\s*Carried over$/,
      /^Indie Finds · 0 recorded\s*Stopped$/,
      /^Elsewhere · 0 recorded\s*Stopped$/,
      /^In Rainbows · 0 recorded\s*Stopped$/,
      /^Melodrama · 0 recorded\s*Stopped$/,
    ],
    { timeout: 20_000 },
  );
  await expectRunState(page, 'idle', 20_000);
  await expect(page.getByRole('region', { name: 'Last run' }).getByText('Window ended')).toBeVisible();
});

test('Back up now during a run puts the item right after the current one', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await expect(upNext(page).getByRole('listitem').first()).toContainText('Indie Finds', { timeout: 10_000 });
  const albums = (await (await request.get('/api/albums')).json()) as { items: Album[] };
  const melodrama = albums.items.find((a) => a.name === 'Melodrama');
  await backUpNow(request, [melodrama?.id ?? '']);
  await expect(upNext(page).getByRole('listitem').first()).toContainText('Melodrama');
});

async function backUpNow(request: APIRequestContext, items: string[]) {
  const response = await request.post('/api/runs', { data: { items } });
  expect(response.status()).toBe(202);
}
