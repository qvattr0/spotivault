// The Dashboard against the real controller in fake mode (demo, 10 times faster): the idle cards,
// then Run now, the running Dashboard live, Remove from this run, and Stop now.
// The demo controller is shared, in file order: each test stops any run it started.

import { expect, test, type Page } from '@playwright/test';
import type { LastRun, ScheduleNext } from '../../src/api/types.ts';
import { demoReady, getJson, openPage, stopAnyRun, waitForRunState } from '../helpers.ts';

test.beforeAll(async ({ request }) => {
  await demoReady(request);
});

test.afterEach(async ({ request }) => {
  await stopAnyRun(request);
});

const nextCard = (page: Page) => page.getByRole('region', { name: 'Next backup' });
const lastCard = (page: Page) => page.getByRole('region', { name: 'Last run' });

test('idle: the next backup as the controller reports it, and the last run', async ({ page, request }) => {
  const next = await getJson<ScheduleNext>(request, '/api/schedule/next');
  await openPage(page, '/dashboard');
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  // The demo has no schedule.
  if (next.at === null) await expect(nextCard(page).getByText('No backup scheduled')).toBeVisible();
  await expect(nextCard(page).getByText(`${next.playlists_to_check} playlists to check`, { exact: false })).toBeVisible();
  await expect(nextCard(page).getByRole('button', { name: 'Run now' })).toBeEnabled();
  // Earlier files may have run something: either way the card says so.
  await expect(lastCard(page).getByText(/^No backups yet$| · (Run now|Scheduled|Start-up)$/)).toBeVisible();
});

test('Run now: the running Dashboard follows the run live; Remove from this run; Stop now', async ({ page, request }) => {
  test.setTimeout(150_000);
  await openPage(page, '/dashboard');
  await nextCard(page).getByRole('button', { name: 'Run now' }).click();

  // The header, live.
  await expect(page.getByRole('heading', { level: 1, name: 'Backing up' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/^started \d\d:\d\d · \d+:\d\d elapsed · Run now/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop after this track' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Now recording' })).toHaveCount(1);

  // The current item expands and records; its track table ticks off.
  const queue = page.getByRole('region', { name: 'Queue' });
  const current = queue.getByRole('group');
  await expect(current.getByText('Recording', { exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(current.getByRole('list', { name: 'Tracks' }).locator('[data-state="recording"]')).toHaveCount(1);
  // The header ends with this run's own time left, from the controller (RunSummary.time_left).
  await expect(
    page.getByText(/ · Run now · (about \d+ (min|h) left in this run( \+ \d+ playlists? of unknown length)?|\d+ playlists? of unknown length left in this run)$/),
  ).toBeVisible();

  // Up next: take the last item out of this run.
  const upNext = page.getByRole('region', { name: 'Up next' });
  const rows = upNext.getByRole('listitem');
  const before = await rows.count();
  expect(before).toBeGreaterThan(1);
  const name = (await rows.last().getByRole('button', { name: /^Options for / }).getAttribute('aria-label'))?.replace('Options for ', '') ?? '';
  await rows.last().getByRole('button', { name: /^Options for / }).click();
  await page.getByRole('menuitem', { name: 'Remove from this run' }).click();
  await expect(rows).toHaveCount(before - 1);
  await expect(upNext.getByText(name, { exact: true })).toHaveCount(0);

  // Stop now asks first; the run ends Stopped, and the idle Dashboard shows it.
  await page.getByRole('button', { name: 'More ways to stop' }).click();
  await page.getByRole('menuitem', { name: 'Stop now' }).click();
  await page.getByRole('dialog', { name: 'Stop now?' }).getByRole('button', { name: 'Stop now' }).click();
  await waitForRunState(request, 'idle');
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible({ timeout: 30_000 });
  await expect(lastCard(page).getByText('Stopped', { exact: true })).toBeVisible();
  await expect(lastCard(page).getByText(/ · Run now$/)).toBeVisible();
  await expect(lastCard(page).getByRole('link', { name: 'View in History' })).toHaveAttribute('href', /^\/history\/runs\/\d+$/);
  // The take Stop now cut short isn't a failure: it's skipped (`discarded`), so the stopped run
  // has no failed track and no issue to list.
  const last = await getJson<LastRun>(request, '/api/runs/last');
  expect(last.run?.counters?.failed).toBe(0);
  expect(last.issues).toEqual([]);
});
