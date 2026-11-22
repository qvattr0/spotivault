// History · Runs against the mock (web-ui.md § Runs tab): every outcome and the no-run rows, the
// filter chips, paging as you scroll, the empty list, and a run that finishes while the list is open.

import { expect, test, type APIRequestContext } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';

/** The list's rows, header included: "Runs", the table. */
function runsTable(page: import('@playwright/test').Page) {
  return page.getByRole('table', { name: 'Runs' });
}

async function startRunNow(request: APIRequestContext, items: string[]): Promise<void> {
  expect((await request.post('/api/runs', { data: { items } })).status()).toBe(202);
  await expect
    .poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 15_000 })
    .toBe('running');
}

test('History lists every outcome, and the rows for the runs that did not happen', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  await expect(page.getByRole('heading', { level: 1, name: 'History' })).toBeVisible();

  const table = runsTable(page);
  for (const outcome of ['Completed with issues', 'Completed', 'Window ended', 'Stopped', 'Failed']) {
    await expect(table.getByText(outcome, { exact: true }).first()).toBeVisible();
  }
  for (const text of [
    'Missed: spotivault was not running',
    'Skipped: the previous run was paused',
    'Held: Spotify connection expired',
  ]) {
    await expect(table.getByText(text)).toBeVisible();
  }
  // A row for a run that didn't happen has nothing to open.
  await expect(table.getByRole('row', { name: /Missed: spotivault was not running/ }).getByRole('link')).toHaveCount(0);
  // The note under the list says what a large ↷ count means.
  await expect(page.getByText('duplicates are skipped in under a second.')).toBeVisible();
});

test('the filter chips narrow the list: With issues, Scheduled and Run now', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  const table = runsTable(page);

  await page.getByRole('radio', { name: 'With issues' }).click();
  await expect(table.getByText('Completed with issues', { exact: true })).toBeVisible();
  await expect(table.getByText('Failed', { exact: true }).first()).toBeVisible();
  await expect(table.getByText('Completed', { exact: true })).toHaveCount(0);
  await expect(table.getByText('Window ended', { exact: true })).toHaveCount(0);

  await page.getByRole('radio', { name: 'Run now' }).click();
  await expect(table.getByRole('cell', { name: 'Run now', exact: true }).first()).toBeVisible();
  await expect(table.getByRole('cell', { name: 'Scheduled', exact: true })).toHaveCount(0);

  // Scheduled includes the start-up runs.
  await page.getByRole('radio', { name: 'Scheduled' }).click();
  await expect(table.getByRole('cell', { name: 'Start-up', exact: true }).first()).toBeVisible();
  await expect(table.getByRole('cell', { name: 'Run now', exact: true })).toHaveCount(0);
});

test('older runs load as you scroll', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).history({ older: 60 });
  await openPage(page, '/history/runs');
  const table = runsTable(page);

  // The first page: 50 runs and the header row.
  await expect(table.getByRole('row')).toHaveCount(51);
  const more = page.getByRole('button', { name: 'Load older runs' });
  await more.scrollIntoViewIfNeeded();
  // The rest: the 9 sample rows and 60 older runs, all of them, and no more to load.
  await expect(table.getByRole('row')).toHaveCount(70, { timeout: 15_000 });
  await expect(more).toHaveCount(0);
});

test('a run opens its page from the list', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  await runsTable(page).getByRole('row').filter({ hasText: 'Completed with issues' }).getByRole('link').click();
  await expect(page).toHaveURL(/\/history\/runs\/41$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(' · Scheduled');
});

test('with no runs yet, History says No backups yet', async ({ page, request }) => {
  await useScenario(request, 'new');
  await mockControls(request).history({ empty: true });
  await openPage(page, '/history/runs');
  await expect(page.getByText('No backups yet', { exact: true })).toBeVisible();
  await expect(runsTable(page)).toHaveCount(0);

  // A filter with nothing to show gets its own line.
  await page.getByRole('radio', { name: 'With issues' }).click();
  await expect(page.getByText('No runs match this filter.')).toBeVisible();
});

test('a run joins the list as Running when it starts, and shows its outcome when it ends, live', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  await startRunNow(request, ['liked']);

  // Listed as the controller lists it: no outcome or counts yet, and Running links to the Dashboard.
  const top = runsTable(page).getByRole('row').nth(1);
  await expect(top.getByRole('link', { name: 'Running' })).toHaveAttribute('href', '/dashboard');
  await expect(top.getByRole('cell', { name: 'Run now', exact: true })).toBeVisible();
  await expect(top).not.toContainText('—');

  await expect.poll(async () => (await request.post('/api/runs/current/stop', { data: { mode: 'now' } })).status()).toBeLessThan(300);
  await expect(top).toContainText('Stopped', { timeout: 20_000 });
  await expect(top.getByRole('link', { name: 'Running' })).toHaveCount(0);
  await expect(top.getByRole('cell', { name: 'Run now', exact: true })).toBeVisible();
});

test("the page of a run still going says so, and points to the Dashboard", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  await startRunNow(request, ['liked']);
  await runsTable(page).getByRole('row').nth(1).getByRole('link').first().click();
  await expect(page).toHaveURL(/\/history\/runs\/\d+$/);
  await expect(page.getByRole('link', { name: 'Running' })).toHaveAttribute('href', '/dashboard');
  await expect(page.getByText('This backup is still going.', { exact: false })).toBeVisible();
  await expect(page.getByText(/ recorded$/)).toHaveCount(0);
  await expect(page.locator('ol > li').first()).toContainText('Liked Songs');

  await expect.poll(async () => (await request.post('/api/runs/current/stop', { data: { mode: 'now' } })).status()).toBeLessThan(300);
  // When it ends, the page shows its outcome and totals.
  await expect(page.getByText('Stopped', { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('This backup is still going.', { exact: false })).toHaveCount(0);
});

test('the page of a run opened while it starts says the queue is being built, then lists its items', async ({ page, request }) => {
  // As in the controller, the queue is built after the pre-run check. A client that isn't running
  // holds the run in Starting while the check restarts it (3 s in the mock).
  await useScenario(request, 'idle');
  await openPage(page, '/history/runs');
  await mockControls(request).client(false);
  expect((await request.post('/api/runs', { data: { items: ['liked'] } })).status()).toBe(202);
  const top = runsTable(page).getByRole('row').nth(1);
  await expect(top.getByRole('link', { name: 'Running' })).toBeVisible();
  await top.getByRole('link').first().click();
  await expect(page).toHaveURL(/\/history\/runs\/\d+$/);
  await expect(page.getByText('Building the queue…')).toBeVisible();

  // The queue is built: the page reads the run again (run.queue) and lists the item.
  await expect(page.locator('ol > li').first()).toContainText('Liked Songs', { timeout: 15_000 });
  await expect(page.getByText('Building the queue…')).toHaveCount(0);
  await expect(page.getByText('This backup is still going.', { exact: false })).toBeVisible();
});

test("a list that can't load says what went wrong", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await page.route('**/api/runs*', (route) => route.fulfill({ status: 500, contentType: 'text/plain', body: 'boom' }));
  await openPage(page, '/history/runs');
  await expect(page.getByText('Something went wrong in spotivault. Try again; the log has the details.')).toBeVisible();
  await expect(runsTable(page)).toHaveCount(0);
});
