// The warnings between the strip and the queue (web-ui.md § Warnings during a run), against the
// mock: playback moved (the run pauses; Resume and Stop), Spytify errors, the Web API warning,
// autoplay moving on, and a fatal error ending the item Partial.

import { expect, test, type Page } from '@playwright/test';
import { expectRunState } from './live.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

const queue = (page: Page) => page.getByRole('region', { name: 'Queue' });

test('playback moved: the run pauses, the alert names the device, and the take is discarded', async ({ page, request }) => {
  // The takeover comes once the page shows the run, so its live socket sees device.moved and the
  // alert can name the device. (The "paused" scenario takes playback away 4 s into its run, which a
  // slow page load can miss: the page then says "another device", as the next tests check.)
  await useScenario(request, 'running');
  await openPage(page, '/dashboard');
  await expectRunState(page, 'running', 10_000);
  await mockControls(request).takeover();
  await expectRunState(page, 'paused', 20_000);
  await expect(page.getByRole('heading', { level: 1, name: 'Paused' })).toBeVisible();

  const alert = page.getByRole('status').filter({ hasText: "Playback moved to Lorne's iPhone." });
  await expect(alert).toContainText("The backup is paused so it won't interrupt you.");
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();

  // The current item stays expanded, interrupted, with the discarded take marked. Mock only: the
  // controller sends no track table while paused, and the contract doesn't say which is right
  // (web-ui.md § What the drawings leave out, "Paused after a takeover"; waits on the user).
  const current = queue(page).getByRole('group', { name: 'Liked Songs' });
  await expect(current.getByText('Interrupted', { exact: true })).toBeVisible();
  await expect(current.locator('[data-state="discarded"]')).toContainText('Discarded · will redo');

  // Resume takes playback back: the alert goes, and the item records again.
  await page.getByRole('button', { name: 'Resume' }).click();
  await expectRunState(page, 'running', 10_000);
  await expect(page.getByRole('heading', { level: 1, name: 'Backing up' })).toBeVisible();
  await expect(alert).toHaveCount(0);
  await expect(current.getByText('Recording', { exact: true }).first()).toBeVisible({ timeout: 10_000 });
});

test("playback moved, then Stop: the run ends Stopped", async ({ page, request }) => {
  await useScenario(request, 'paused');
  await openPage(page, '/dashboard');
  await expectRunState(page, 'paused', 20_000);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expectRunState(page, 'idle', 15_000);
  await expect(page.getByRole('region', { name: 'Last run' }).getByText('Stopped', { exact: true })).toBeVisible();
});

test('a page opened while paused, with no device.moved seen, still says why', async ({ page, request }) => {
  await useScenario(request, 'paused');
  await expect.poll(async () => (await (await request.get('/api/status')).json()).state, { timeout: 20_000 }).toBe('paused');
  await openPage(page, '/dashboard');
  await expect(page.getByRole('status').filter({ hasText: 'Playback moved to another device.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible();
});

test('a Spytify error shows as a red alert with its message, until Spytify withdraws it', async ({ page, request }) => {
  await useScenario(request, 'running');
  const mock = mockControls(request);
  await openPage(page, '/dashboard');
  await expectRunState(page, 'running', 10_000);
  await mock.error();
  const alert = page.getByRole('alert').filter({ hasText: 'No audio for 10 s: the capture is silent.' });
  await expect(alert).toBeVisible();
  await mock.error({ withdrawn: true });
  await expect(alert).toHaveCount(0);
});

test('a fatal Spytify error: the item ends Partial and the run moves on', async ({ page, request }) => {
  await useScenario(request, 'running');
  const mock = mockControls(request);
  await openPage(page, '/dashboard');
  // A track is recording (its row in the current item's track list), so the error fails it. The
  // row says "Recording · 0:02 / 0:06" once its clock runs, so the text is matched at its start.
  await expect(queue(page).getByRole('list', { name: 'Tracks' }).getByText(/^Recording\b/).first()).toBeVisible({ timeout: 15_000 });
  await mock.error({ fatal: true, code: 'write', message: 'Spytify could not write the file.' });
  const alert = page.getByRole('alert').filter({ hasText: 'Spytify could not write the file.' });
  await expect(alert).toContainText('This item ends Partial, and the backup goes on with the next one.');
  await expect(queue(page).getByText('Liked Songs · Spytify error: the capture failed.')).toBeVisible({ timeout: 20_000 });
  await expect(queue(page).getByText('Partial', { exact: true })).toBeVisible();
  // The track it was recording failed.
  await expect(page.getByLabel('Counters')).toContainText('Failed 1');
});

test('the Web API warning is yellow; autoplay moving on is red', async ({ page, request }) => {
  await useScenario(request, 'running');
  const mock = mockControls(request);
  await openPage(page, '/dashboard');
  await expectRunState(page, 'running', 10_000);
  await mock.error({ source: 'controller', code: 'webapi', message: "The jump to the next track failed: Spotify answered 502." });
  await expect(page.getByRole('status').filter({ hasText: 'The jump to the next track failed: Spotify answered 502.' })).toBeVisible();
  await mock.error({ source: 'controller', code: 'context_changed', message: 'Spotify started another playlist, so the recorder stopped.' });
  await expect(page.getByRole('alert').filter({ hasText: 'Spotify started another playlist, so the recorder stopped.' })).toBeVisible();
  // Both stay until the run ends.
  await expect(page.getByRole('status').filter({ hasText: 'The jump to the next track failed' })).toBeVisible();
});

// web-ui.md § Warnings, Client not running: the run restarts the client once (a red alert, the
// controller's `client_restarted` error), then waits for its device. The mock shortens the wait.
const RESTARTED = "The device spotivault wasn't listed, so the Spotify client was restarted.";

test('the client not running: the run restarts it, says so, and goes on', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).client(false);
  await openPage(page, '/dashboard');
  // Not held: the card still offers Run now.
  await page.getByRole('region', { name: 'Next backup' }).getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByRole('alert').filter({ hasText: RESTARTED })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('heading', { level: 1, name: 'Backing up' })).toBeVisible();
  await expect(page.getByText('Starting', { exact: true }).first()).toBeVisible();
  // The client is back: the first item records.
  await expect(queue(page).getByText('Recording', { exact: true }).first()).toBeVisible({ timeout: 20_000 });
});

test("the client not running, and its device doesn't show up: the run fails", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).client(false, { comesBack: false });
  await openPage(page, '/dashboard');
  await page.getByRole('region', { name: 'Next backup' }).getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByRole('alert').filter({ hasText: RESTARTED })).toBeVisible({ timeout: 10_000 });
  await expectRunState(page, 'idle', 20_000);
  const last = page.getByRole('region', { name: 'Last run' });
  await expect(last.getByText('Failed', { exact: true })).toBeVisible();
  await expect(last.getByText("Failed: the container's client isn't listed as a playback device")).toBeVisible();
});
