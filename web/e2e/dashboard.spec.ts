// The Dashboard when no run is going (web-ui.md § Idle), against the mock: Next backup and its
// variants (scheduled, no schedule, Held), Last run and "No backups yet", and Run now.
// Not yet (plan D8): the Full backup card.

import { expect, test, type Page } from '@playwright/test';
import { expectRunState } from './live.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

const nextCard = (page: Page) => page.getByRole('region', { name: 'Next backup' });
const lastCard = (page: Page) => page.getByRole('region', { name: 'Last run' });

test('idle with a schedule: the next window, what it covers, the week strip and the last run', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/dashboard');
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();

  const next = nextCard(page);
  // The mock's next window starts 9 h from now and lasts 6 h.
  await expect(next.getByText(/^(Tonight|Today|Tomorrow) \d\d:\d\d–\d\d:\d\d · in 9 h$/)).toBeVisible();
  await expect(next.getByText(/^\d+ playlists to check · 3 albums queued$/)).toBeVisible();
  await expect(next.getByRole('img', { name: 'Backup hours: 48 h a week' })).toBeVisible();
  await expect(next.getByRole('button', { name: 'Run now' })).toBeEnabled();
  // Not in M1: the Schedule page, so no "Change schedule".
  await expect(page.getByText('Change schedule')).toHaveCount(0);

  const last = lastCard(page);
  await expect(last.getByText(/^\w{3} \d+ \w{3} · \d\d:\d\d · 5 h 12 m · Scheduled$/)).toBeVisible();
  await expect(last.getByText('Completed with issues')).toBeVisible();
  for (const [label, value] of [
    ['recorded', '84'],
    ['skipped (duplicate)', '1,204'],
    ['failed', '3'],
    ['added', '+642 MB'],
  ]) {
    await expect(last.getByRole('term').filter({ hasText: label }).first()).toBeVisible();
    await expect(last.getByRole('definition').filter({ hasText: value })).toBeVisible();
  }
  await expect(last.getByRole('listitem')).toHaveText([
    'Chill Mix: 2 tracks failed: low volume',
    'Late Night Drive: Strobe: failed: recorder error',
    'Sunday Vinyl: playlist unavailable, files kept',
  ]);
  await expect(last.getByRole('link', { name: 'View in History' })).toHaveAttribute('href', '/history/runs/41');
  // Not yet (plan D8).
  await expect(page.getByText('Full backup')).toHaveCount(0);
});

test('set up a moment ago: no backup scheduled, and no backups yet', async ({ page, request }) => {
  await useScenario(request, 'new');
  await openPage(page, '/dashboard');
  const next = nextCard(page);
  await expect(next.getByText('No backup scheduled')).toBeVisible();
  await expect(next.getByText(/^\d+ playlists to check$/)).toBeVisible();
  await expect(next.getByRole('img')).toHaveCount(0);
  await expect(next.getByRole('button', { name: 'Run now' })).toBeVisible();

  const last = lastCard(page);
  await expect(last.getByText('No backups yet')).toBeVisible();
  await expect(last.getByRole('link', { name: 'View in History' })).toHaveCount(0);
});

test('held, connection expired or disconnected: the card turns red and offers Reconnect', async ({ page, request }) => {
  await useScenario(request, 'expired');
  await openPage(page, '/dashboard');
  const next = nextCard(page);
  await expect(next.getByText('Backups held')).toBeVisible();
  await expect(next.getByText('The Spotify connection has expired. Backups wait until you reconnect.')).toBeVisible();
  await expect(next.getByRole('button', { name: 'Run now' })).toHaveCount(0);
  await expect(next.getByRole('link', { name: 'Reconnect' })).toHaveAttribute('href', '/reconnect');

  // Disconnected (Settings › Disconnect): held too, with the same way out.
  await mockControls(request).connection('disconnected');
  await expect(next.getByText("spotivault isn't connected to Spotify. Backups wait until you connect it.")).toBeVisible();
  await expect(next.getByRole('link', { name: 'Reconnect' })).toHaveAttribute('href', '/reconnect');
});

test('held, client logged out: "Log in again" opens wizard step 3, and it clears live', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await openPage(page, '/dashboard');
  const next = nextCard(page);
  await expect(next.getByRole('button', { name: 'Run now' })).toBeVisible();

  await mock.login(false);
  await expect(next.getByText('The Spotify client is logged out. Backups wait until you log in again.')).toBeVisible();
  const logIn = next.getByRole('link', { name: 'Log in again' });
  await expect(logIn).toHaveAttribute('href', '/setup/login');

  await mock.login(true);
  await expect(next.getByRole('button', { name: 'Run now' })).toBeVisible();
  await expect(next.getByText('Backups held')).toHaveCount(0);

  await mock.login(false);
  await next.getByRole('link', { name: 'Log in again' }).click();
  await expect(page).toHaveURL(/\/setup\/login$/);
});

test('Run now starts a run, and the Dashboard switches to it live', async ({ page, request }) => {
  await useScenario(request, 'new');
  await openPage(page, '/dashboard');
  await nextCard(page).getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Backing up' })).toBeVisible();
  await expect(page).toHaveTitle('Dashboard · spotivault');
  await expectRunState(page, 'running', 15_000);
  await expect(page.getByRole('region', { name: 'Queue' })).toBeVisible();

  // Stop now, then the idle Dashboard shows the run that just ended.
  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible({ timeout: 15_000 });
  const last = lastCard(page);
  await expect(last.getByText(/ · Run now$/)).toBeVisible();
  await expect(last.getByText('Stopped', { exact: true })).toBeVisible();
  await expect(last.getByRole('link', { name: 'View in History' })).toHaveAttribute('href', '/history/runs/42');
});

test('Run now refused: the error shows as a toast', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/dashboard');
  // The client logs out between the card's last read and the click (the card would turn red).
  await page.route('**/api/runs', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ error: { code: 'client_logged_out', message: 'The Spotify client is logged out.', details: null } }),
        })
      : route.fallback(),
  );
  await nextCard(page).getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByText('The Spotify client is logged out. Log in again in the Player.')).toBeVisible();
});
