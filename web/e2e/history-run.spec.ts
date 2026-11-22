// A run's page against the mock (web-ui.md § Run page): the header, the items and their badges,
// the tracks of an item, Copy path, Retry failed and Retry all failed, and the states a run reaches
// when it's stopped, cut by a window's end, stalled twice or has an item removed.

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fakeId } from '../mock/fixtures.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

/** The run that ended last: the first row of GET /api/runs (History is newest first). */
async function newestRunId(request: APIRequestContext): Promise<number> {
  const body = (await (await request.get('/api/runs')).json()) as { runs: { id: number }[] };
  const id = body.runs[0]?.id;
  if (id === undefined) throw new Error('no runs');
  return id;
}

async function waitForIdle(request: APIRequestContext): Promise<void> {
  await expect
    .poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 90_000 })
    .toBe('idle');
}

async function stopNow(request: APIRequestContext): Promise<void> {
  expect((await request.post('/api/runs/current/stop', { data: { mode: 'now' } })).status()).toBe(202);
}

/** The run page's header: its title, outcome pill and totals. */
function headerOf(page: Page) {
  return page.locator('h1').locator('..');
}

/** The item's row in the run page: the toggle is labelled with the item's name. */
function itemToggle(page: Page, name: string) {
  return page.getByRole('button', { name, exact: true });
}

test.beforeAll(async ({ browser }, testInfo) => {
  // The dev server optimises a dependency the first time a page imports it, and reloads that page.
  // This visit takes that reload first, so the tests below see a settled page.
  const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  const page = await context.newPage();
  await useScenario(context.request, 'idle');
  await page.goto('/history/runs/41');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 60_000 });
  await context.close();
});

test("a run's page shows its header, its totals and its items in the order they ran", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');

  await expect(page.getByRole('heading', { level: 1 })).toContainText(' · Scheduled');
  await expect(headerOf(page).getByText('Completed with issues', { exact: true })).toBeVisible();
  await expect(page.getByText('84 recorded')).toBeVisible();
  await expect(page.getByText('1,204 skipped')).toBeVisible();
  await expect(page.getByText('3 failed')).toBeVisible();
  await expect(page.getByText(/window \d\d:\d\d–\d\d:\d\d/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'History · Runs' })).toHaveAttribute('href', '/history/runs');

  // The items, in the order they ran, with their badges.
  const items = page.locator('ol > li');
  await expect(items).toHaveCount(4);
  await expect(items.nth(0)).toContainText('Liked Songs');
  await expect(items.nth(1)).toContainText('Chill Mix');
  await expect(items.nth(1)).toContainText('Interrupted, retried');
  await expect(items.nth(2)).toContainText('Up to date: nothing new');
  await expect(items.nth(3)).toContainText('Removed from run');
});

test('an item opens to its tracks: recorded with size and path, skipped, and failed with the reason', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await itemToggle(page, 'Chill Mix').click();
  await expect(itemToggle(page, 'Chill Mix')).toHaveAttribute('aria-expanded', 'true');

  const tracks = page.getByRole('table', { name: 'Tracks of Chill Mix' });
  await expect(tracks.getByRole('row')).toHaveCount(9); // the header and 8 tracks
  await expect(tracks.getByText(/^Recorded · 6\.2 MB$/).first()).toBeVisible();
  await expect(tracks.getByText(/\.m4a$/).first()).toBeVisible();
  await expect(tracks.getByText('Skipped (duplicate)')).toBeVisible();
  await expect(tracks.getByText('Skipped (ad)')).toBeVisible();
  await expect(tracks.getByText('Failed · low volume')).toBeVisible();
  await expect(tracks.getByRole('button', { name: 'Copy path' }).first()).toBeVisible();

  // The toggle closes it again.
  await itemToggle(page, 'Chill Mix').click();
  await expect(page.getByRole('table', { name: 'Tracks of Chill Mix' })).toHaveCount(0);
});

test('Copy path copies a recorded track\'s file path, and says so', async ({ page, request, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await itemToggle(page, 'Chill Mix').click();
  await page.getByRole('table', { name: 'Tracks of Chill Mix' }).getByRole('button', { name: 'Copy path' }).first().click();
  await expect(page.getByText('Path copied')).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/\.m4a$/);
});

test('Copy path works over plain http too, where the browser offers no clipboard API', async ({ page, request, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  // As at http://<nas>:8080: not a secure page, so no navigator.clipboard. The test keeps its own
  // handle on it, to read what was copied.
  await page.addInitScript(() => {
    (window as unknown as { testClipboard: Clipboard }).testClipboard = navigator.clipboard;
    Object.defineProperty(window, 'isSecureContext', { value: false });
    Object.defineProperty(navigator, 'clipboard', { value: undefined });
  });
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await itemToggle(page, 'Chill Mix').click();
  const copy = page.getByRole('table', { name: 'Tracks of Chill Mix' }).getByRole('button', { name: 'Copy path' }).first();
  await copy.click();
  await expect(page.getByText('Path copied')).toBeVisible();
  await expect(copy).toBeFocused();
  expect(await page.evaluate(() => (window as unknown as { testClipboard: Clipboard }).testClipboard.readText())).toMatch(/\.m4a$/);
});

test('Retry failed starts a backup of that item, and the toast says so', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await itemToggle(page, 'Chill Mix').click();
  await page.getByRole('button', { name: 'Retry failed', exact: true }).click();
  await expect(page.getByText('Backup started')).toBeVisible();
  await expect
    .poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 15_000 })
    .toBe('running');
  await stopNow(request);
  await waitForIdle(request);
});

test('Retry all failed sends every item with failed tracks', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await page.getByRole('button', { name: 'Retry all failed' }).click();
  await expect(page.getByText('Backup started')).toBeVisible();
  await expect
    .poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 15_000 })
    .toBe('running');
  // Chill Mix is the only item of this run with failed tracks: it's the one queued.
  const queue = (await (await request.get('/api/runs/current')).json()) as { queue: { item_id: string }[] };
  expect(queue.queue.map((item) => item.item_id)).toContain(fakeId('chillmix'));
  await stopNow(request);
  await waitForIdle(request);
});

test('during a backup, Retry failed adds the item to the current run', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/history/runs/41');
  await itemToggle(page, 'Chill Mix').click();
  await page.getByRole('button', { name: 'Retry failed', exact: true }).click();
  await expect(page.getByText('Added to the current run')).toBeVisible();
});

test('a stopped run shows Stopped, and the items it never reached', async ({ page, request }) => {
  await useScenario(request, 'running');
  await expect.poll(async () => (await (await request.get('/api/status')).json()).session_state, { timeout: 15_000 }).toBe('recording');
  await stopNow(request);
  await waitForIdle(request);

  await openPage(page, `/history/runs/${await newestRunId(request)}`);
  await expect(headerOf(page).getByText('Stopped', { exact: true })).toBeVisible();
  // Liked Songs was carried over into this run, and then stopped in it.
  await expect(page.locator('ol > li').first()).toContainText('Carried over from the previous run');
  await expect(page.locator('ol > li').first()).toContainText('Stopped');
  // Its tracks: the duplicate it skipped, and the take Stop now cut short: skipped, not failed.
  await itemToggle(page, 'Liked Songs').click();
  const tracks = page.getByRole('table', { name: 'Tracks of Liked Songs' });
  await expect(tracks.getByText('Skipped (duplicate)')).toBeVisible();
  await expect(tracks.getByText('Skipped (backup stopped mid-track)')).toBeVisible();
  const run = (await (await request.get(`/api/runs/${await newestRunId(request)}`)).json()) as { run: { counters: object } };
  expect(run.run.counters).toMatchObject({ skipped_other: 1, failed: 0 });
});

test('a run whose window ends carries the cut item over, and ends Window ended', async ({ page, request }) => {
  test.setTimeout(120_000);
  await useScenario(request, 'running');
  // The window ends during a track: the cut item is carried over. Before a track, it would just stop.
  await expect.poll(async () => (await (await request.get('/api/status')).json()).session_state, { timeout: 30_000 }).toBe('recording');
  await mockControls(request).windowEnd();
  await waitForIdle(request);

  await openPage(page, `/history/runs/${await newestRunId(request)}`);
  await expect(headerOf(page).getByText('Window ended', { exact: true })).toBeVisible();
  await expect(page.locator('ol > li').first()).toContainText('Carried over to the next run');
  await expect(page.locator('ol > li').first()).toContainText('Carried over from the previous run');
});

test('an item stalled twice ends Partial, and the run is Completed with issues', async ({ page, request }) => {
  test.setTimeout(120_000);
  await useScenario(request, 'idle');
  const id = fakeId('chillmix');
  expect((await request.post('/api/runs', { data: { items: [id] } })).status()).toBe(202);
  const mock = mockControls(request);
  // The first stall moves the item to the end of the queue, which here is its only place: it
  // plays again at once as its second attempt. The second stall on that attempt ends it Partial.
  await mock.stall();
  await expect
    .poll(
      async () => {
        const queue = (await (await request.get('/api/runs/current')).json()) as { queue: { item_id: string; attempt: number; state: string }[] };
        return queue.queue.find((item) => item.item_id === id)?.attempt ?? 0;
      },
      { timeout: 60_000 },
    )
    .toBe(2);
  await mock.stall();
  await waitForIdle(request);

  await openPage(page, `/history/runs/${await newestRunId(request)}`);
  await expect(headerOf(page).getByText('Completed with issues', { exact: true })).toBeVisible();
  await expect(page.locator('ol > li').first()).toContainText('Interrupted twice: Partial');
  await itemToggle(page, 'Chill Mix').click();
  await expect(page.getByRole('table', { name: 'Tracks of Chill Mix' }).getByText('Failed · interrupted')).toBeVisible();
});

test('an item removed from the queue shows Removed from run', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const chill = fakeId('chillmix');
  expect((await request.post('/api/runs', { data: { items: ['liked', chill] } })).status()).toBe(202);
  await expect.poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 15_000 }).toBe('running');
  expect((await request.delete(`/api/runs/current/items/${chill}`)).status()).toBe(204);
  await stopNow(request);
  await waitForIdle(request);

  await openPage(page, `/history/runs/${await newestRunId(request)}`);
  await expect(page.locator('ol > li').filter({ hasText: 'Chill Mix' })).toContainText('Removed from run');
  await expect(page.locator('ol > li').first()).toContainText('Stopped');
});

test('a run with a failed setting shows its reason', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/35');
  await expect(headerOf(page).getByText('Failed', { exact: true })).toBeVisible();
  await expect(page.getByText('a client setting changed')).toBeVisible();
});

test('a run cut short by a container restart says so', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/33');
  await expect(headerOf(page).getByText('Failed', { exact: true })).toBeVisible();
  await expect(page.getByText('container restarted')).toBeVisible();
});

test('a run that did not happen has its page, with no items', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/36');
  await expect(page.getByText('Missed: spotivault was not running')).toBeVisible();
  await expect(page.locator('ol')).toHaveCount(0);
});

test('a run that is not in History says so', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/999999');
  await expect(page.getByText("There's no run with that number.")).toBeVisible();
  await expect(page.getByRole('link', { name: 'History · Runs' })).toBeVisible();
});

test("a run page that can't load says what went wrong", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await page.route('**/api/runs/41', (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'boom' }));
  await openPage(page, '/history/runs/41');
  await expect(page.getByText('Something went wrong in spotivault. Try again; the log has the details.')).toBeVisible();
});
