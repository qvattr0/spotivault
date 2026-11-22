// History › Logs against the mock (web-ui.md § Logs tab): the live tail following the bottom, the
// Source and Level chips, the search (a sparse one across pages too), "Jump to latest" and "Load
// older lines" by keyboard, the lines the live tail leaves out, the run page's "Logs for this
// run", a run that doesn't exist, a phone-wide window, and the .zip.

import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';
import { screenshotPath } from './report.ts';

function logBox(page: Page) {
  return page.getByRole('log', { name: 'Log lines' });
}

function rows(page: Page) {
  return logBox(page).locator('[data-line-id]');
}

/** "Load older lines" by keyboard (Shift+Tab from the lines): it shows at the top of the box only when the lines are, or with the keyboard's focus. */
async function loadOlderByKeyboard(page: Page) {
  const older = page.getByRole('button', { name: 'Load older lines' });
  await logBox(page).focus();
  await page.keyboard.press('Shift+Tab');
  await expect(older).toBeFocused();
  await expect(older).toHaveCSS('opacity', '1');
  await page.keyboard.press('Enter');
}

test('the live tail follows the bottom: new lines show as they come', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(page.getByRole('heading', { level: 1, name: 'History' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'History' }).getByRole('link', { name: 'Logs' })).toHaveAttribute('aria-current', 'page');
  await expect(rows(page).first()).toBeVisible();
  // Every source is there, with its badge.
  // (A System or Spytify badge also says, to screen readers only, which service or item log.)
  for (const badge of ['Controller', 'Spytify', 'Client', 'System']) {
    await expect(logBox(page).getByText(new RegExp(`^${badge}(, .+)?$`)).first()).toBeAttached();
  }
  await expect(page.getByText('Logs rotate after 14 days or 50 MB, whichever comes first.')).toBeVisible();

  await mockControls(request).logs({ add: [{ source: 'spytify', level: 'error', message: 'capture: the stream stalled' }] });
  const newest = rows(page).last();
  await expect(newest).toContainText('capture: the stream stalled');
  await expect(newest).toHaveAttribute('data-level', 'error');
  await expect(newest).toBeInViewport();
  await expect(page.getByRole('button', { name: /Jump to latest/ })).toHaveCount(0);
});

test('the Source and Level chips narrow the lines, live ones too', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();

  const level = page.getByRole('group', { name: 'Level' });
  await level.getByRole('button', { name: 'Error' }).click();
  await expect(level.getByRole('button', { name: 'Error' })).toHaveAttribute('aria-pressed', 'true');
  await expect(rows(page).first()).toBeVisible();
  await expect(logBox(page).locator('[data-line-id]:not([data-level="error"])')).toHaveCount(0);

  await page.getByRole('group', { name: 'Source' }).getByRole('button', { name: 'Spotify client' }).click();
  await expect(logBox(page).locator('[data-line-id]:not([data-source="client"])')).toHaveCount(0);
  await expect(rows(page)).not.toHaveCount(0);

  // A live line the filters don't take stays out; one they take comes in.
  await mockControls(request).logs({
    add: [
      { source: 'controller', level: 'error', message: 'not the client' },
      { source: 'client', level: 'error', message: '[1121/1:ERROR:x.cc(1)] client crashed' },
    ],
  });
  await expect(logBox(page).getByText('client crashed', { exact: false })).toBeVisible();
  await expect(logBox(page).getByText('not the client')).toHaveCount(0);

  // Both chips off: every source and level but debug again.
  await level.getByRole('button', { name: 'Error' }).click();
  await page.getByRole('group', { name: 'Source' }).getByRole('button', { name: 'Spotify client' }).click();
  await expect(logBox(page).getByText('not the client')).toBeVisible();
});

test('the search finds lines, and says when none match', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  const search = page.getByRole('searchbox', { name: 'Search logs' });
  await search.fill('HOLOCENE');
  await expect(rows(page).first()).toContainText(/holocene/i);
  const texts = await rows(page).allTextContents();
  expect(texts.every((text) => /holocene/i.test(text))).toBe(true);

  await search.fill('no such line anywhere');
  await expect(logBox(page).getByText('No lines match “no such line anywhere”.')).toBeVisible();
  await search.press('Escape');
  await expect(rows(page).first()).toBeVisible();
});

test('a sparse search reads on past the first page, then offers older lines', async ({ page, request }) => {
  // A page looks at 20 lines at most (the controller's 8 MB): the start-up line is further back.
  await useScenario(request, 'idle');
  await mockControls(request).logs({ read_budget: 20 });
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();
  const search = page.getByRole('searchbox', { name: 'Search logs' });
  await search.fill('DEVICE_NAME');
  await expect(logBox(page).getByText('DEVICE_NAME=spotivault TZ=Europe/Berlin UMASK=000')).toBeVisible();
  await expect(logBox(page).getByText(/No lines match/)).toHaveCount(0);

  // 3 lines a page: four pages don't reach it. The tab says so, and Load older lines reads on.
  await mockControls(request).logs({ read_budget: 3 });
  await search.fill('UMASK=000');
  await expect(logBox(page).getByText('No lines match “UMASK=000” in the newest logs.')).toBeVisible();
  const older = page.getByRole('button', { name: /older lines/ });
  await expect(older).toHaveCSS('opacity', '1');
  for (let n = 0; n < 10 && (await rows(page).count()) === 0; n += 1) {
    await expect(older).toHaveText('Load older lines');
    await older.click();
    await expect(older.or(rows(page).first())).toBeVisible();
    await expect(older.filter({ hasText: 'Loading' })).toHaveCount(0);
  }
  await expect(logBox(page).getByText('DEVICE_NAME=spotivault TZ=Europe/Berlin UMASK=000')).toBeVisible();
});

test('"Load older lines" by keyboard: the lines keep their place and the tail goes on', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();
  await logBox(page).focus();
  const atBottom = () => logBox(page).evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  expect(await atBottom()).toBe(true);
  // It's just before the lines: Shift+Tab from the log reaches it, and the lines don't move.
  await page.keyboard.press('Shift+Tab');
  const older = page.getByRole('button', { name: 'Load older lines' });
  await expect(older).toBeFocused();
  await expect(older).toHaveCSS('opacity', '1');
  expect(await atBottom()).toBe(true);
  await expect(page.getByRole('button', { name: /Jump to latest/ })).toHaveCount(0);

  const before = await rows(page).count();
  await page.keyboard.press('Enter');
  await expect.poll(() => rows(page).count()).toBeGreaterThan(before);
  await expect(page.locator(':focus')).toHaveText(/older lines/);
  await expect(page.getByRole('button', { name: /Jump to latest/ })).toHaveCount(0);
  await mockControls(request).logs({ add: [{ source: 'controller', level: 'info', message: 'still following' }] });
  await expect(logBox(page).getByText('still following')).toBeInViewport();
});

test('scrolling up pauses the tail; "Jump to latest" brings the waiting lines', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();
  await logBox(page).hover();
  await page.mouse.wheel(0, -800);
  const jump = page.getByRole('button', { name: /Jump to latest/ });
  await expect(jump).toBeVisible();

  await mockControls(request).logs({ add: [{ source: 'controller', level: 'warning', message: 'came while paused' }] });
  await expect(jump).toContainText('1 new line');
  await expect(logBox(page).getByText('came while paused')).toHaveCount(0);

  await jump.click();
  await expect(logBox(page).getByText('came while paused')).toBeInViewport();
  await expect(jump).toHaveCount(0);

  // By keyboard: the pill goes once the view follows, and the focus stays in the log.
  await logBox(page).hover();
  await page.mouse.wheel(0, -800);
  await jump.focus();
  await page.keyboard.press('Enter');
  await expect(jump).toHaveCount(0);
  await expect(logBox(page)).toBeFocused();
});

test('older lines load as you scroll to the top', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();
  const first = await rows(page).first().getAttribute('data-line-id');
  const before = await rows(page).count();
  await logBox(page).hover();
  await logBox(page).evaluate((el) => el.scrollBy(0, -el.scrollHeight));
  await expect.poll(() => rows(page).count()).toBeGreaterThan(before);
  // The line that was first is still there, now with older ones above it.
  await expect(logBox(page).locator(`[data-line-id="${first}"]`)).toHaveCount(1);
  expect(await rows(page).first().getAttribute('data-line-id')).not.toBe(first);
});

test('a burst too big for the live tail is counted, and "Show them" reads it', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  await expect(rows(page).first()).toBeVisible();
  await mockControls(request).logs({ burst: 450 });
  await expect(page.getByText(/250 lines came too fast to show live/)).toBeVisible();
  await expect(rows(page).last()).toContainText('burst line 450 of 450');
  await expect(logBox(page).getByText('burst line 1 of 450', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Show them' }).click();
  await expect(page.getByText(/came too fast/)).toHaveCount(0);
  await expect(rows(page).last()).toContainText('burst line 450 of 450');
});

test('"Logs for this run" opens the tab on that run', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs/41');
  await page.getByRole('link', { name: 'Logs for this run' }).click();
  await expect(page).toHaveURL(/\/history\/logs\?run=41$/);
  await expect(page.getByRole('combobox', { name: 'Run' })).toHaveValue('41');
  await expect(logBox(page).getByText('runs: run 41 ended: completed_with_issues')).toBeVisible();
  await loadOlderByKeyboard(page);
  await expect(logBox(page).getByText('runs: run 41 started (Scheduled), 3 items')).toBeAttached();
  // Only run 41's Spytify logs; nothing from before or after the run.
  await expect(logBox(page).getByText(/^runs: run 40 /)).toHaveCount(0);
  await expect(logBox(page).getByText('DEVICE_NAME=spotivault TZ=Europe/Berlin UMASK=000')).toHaveCount(0);

  // Back to All.
  await page.getByRole('combobox', { name: 'Run' }).selectOption('all');
  await expect(page).toHaveURL(/\/history\/logs$/);
  await expect(logBox(page).getByText('DEVICE_NAME=spotivault TZ=Europe/Berlin UMASK=000')).toBeAttached();
});

test('a run going on shows its lines live, filtered to it', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  const runId = ((await (await request.get('/api/status')).json()) as { run: { id: number } }).run.id;
  await openPage(page, `/history/logs?run=${runId}`);
  await expect(logBox(page).locator('[data-source="spytify"]').filter({ hasText: 'track.' }).first()).toBeVisible({ timeout: 15_000 });
});

test('a run that doesn\'t exist offers all runs', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs?run=999');
  await expect(page.getByText("There's no run with that number.")).toBeVisible();
  await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Show all runs' }).click();
  await expect(page).toHaveURL(/\/history\/logs$/);
  await expect(rows(page).first()).toBeVisible();
});

test('at phone width, a line keeps its time and badge above the message', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  const row = rows(page).last();
  await expect(row).toBeVisible();
  const [rowBox, messageBox, timeBox] = await Promise.all([
    row.boundingBox(),
    row.locator(':scope > span').last().boundingBox(),
    row.locator('time').boundingBox(),
  ]);
  expect(rowBox && messageBox && timeBox).toBeTruthy();
  if (!rowBox || !messageBox || !timeBox) return;
  expect(messageBox.width).toBeGreaterThan(rowBox.width * 0.8);
  expect(messageBox.y).toBeGreaterThanOrEqual(timeBox.y + timeBox.height - 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: screenshotPath('logs-390.png'), animations: 'disabled' });
});

test('Download saves the last 7 days as a .zip', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/logs');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download last 7 days (.zip)' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^spotivault-logs-\d{8}-\d{4}\.zip$/);
  const bytes = await readFile(await file.path());
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
});

test('with no lines at all, the tab says so', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).logs({ empty: true });
  await openPage(page, '/history/logs');
  await expect(logBox(page).getByText('No log lines yet.')).toBeVisible();
});
