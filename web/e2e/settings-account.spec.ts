// Settings against the mock: Spotify account (Web API), Spotify client, Container and About, and the
// Run setup again action. Recording, Files and the Unsaved changes bar are in settings.spec.ts.

import { expect, test } from '@playwright/test';
import type { Setup } from '../src/api/types.ts';
import { mockControls, openPage, useScenario } from './mock.ts';

test('Spotify account: connected, with the account, the dates, the masked Client ID and Reconnect', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const section = page.getByRole('group', { name: 'Connection' });
  // The dates follow the browser's time zone, so only their months and years are checked.
  await expect(section.getByText(/^Connected as Lorne · authorized \d{1,2} Nov 2026 · expires \d{1,2} May 2027$/)).toBeVisible();
  await expect(section.getByText('OK', { exact: true })).toBeVisible();
  await expect(section.getByRole('link', { name: 'Reconnect' })).toHaveAttribute('href', '/reconnect');
  await expect(page.getByRole('group', { name: 'Client ID' }).getByText('0123…cdef')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Change' })).toHaveAttribute('href', '/reconnect?change=client_id');
});

test('Spotify account follows the connection live: expiring, expired, then disconnected', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await openPage(page, '/settings');
  await mock.connection('expiring');
  await expect(page.getByText('Expiring', { exact: true })).toBeVisible();
  await mock.connection('expired');
  await expect(page.getByText('Expired', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Disconnect' }).click();
  await expect(page.getByText('Not connected to Spotify.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Disconnect' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/reconnect');
});

test('Spotify account before any Client ID: Not set up, and Connect goes to the wizard', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).connection('not_configured');
  await openPage(page, '/settings');
  const connection = page.getByRole('group', { name: 'Connection' });
  await expect(connection.getByText('No Client ID yet.')).toBeVisible();
  await expect(connection.getByText('Not set up', { exact: true })).toBeVisible();
  await expect(connection.getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/reconnect');
  await expect(page.getByRole('group', { name: 'Client ID' }).getByText('Not set', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Disconnect' })).toHaveCount(0);
});

test('Spotify client: logged in, then logged out live, with a link to the Player', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const mock = mockControls(request);
  await openPage(page, '/settings');
  await expect(page.getByText('Logged in', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open Player' })).toHaveAttribute('href', '/player');
  await mock.login(false);
  await expect(page.getByText('Not logged in', { exact: true })).toBeVisible();
});

test('Spotify client not installed yet: the client line says so, and there is no login pill', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await mockControls(request).installFails();
  await openPage(page, '/settings');
  await expect(page.getByRole('group', { name: 'Client' }).getByText('Not installed yet')).toBeVisible();
  await expect(page.getByText('Not logged in', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Logged in', { exact: true })).toHaveCount(0);
});

test('Container: the environment and versions, read-only', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  const container = page.getByRole('region', { name: 'Container' });
  await expect(container.getByText('Change these in the UGOS Docker app')).toBeVisible();
  await expect(container.getByRole('group', { name: 'Device name (DEVICE_NAME)' }).getByText('spotivault', { exact: true })).toBeVisible();
  await expect(container.getByText('Europe/Berlin', { exact: true })).toBeVisible();
  await expect(container.getByText('/music → /Music', { exact: true })).toBeVisible();
  await expect(container.getByText('022', { exact: true })).toBeVisible();
  await expect(container.getByText('image 0.1.0 · Spytify 2.0.2 · Spotify 1.3.4.258', { exact: true })).toBeVisible();
});

test('About: the version, the Terms notice again, and the project page', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  await expect(page.getByText('spotivault 0.1.0', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Read the Terms notice again' })).toHaveAttribute('href', '/setup/welcome');
  await expect(page.getByRole('link', { name: 'GitHub' })).toHaveAttribute('href', /^https:\/\/github\.com\//);
});

test('Run setup again reopens the wizard at step 2, and deletes nothing', async ({ page, request }) => {
  await useScenario(request, 'idle');
  await openPage(page, '/settings');
  // The page goes straight to step 2: it doesn't pass by step 5, whose page would run its device check.
  const deviceChecks: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/spotify/devices')) deviceChecks.push(r.url());
  });
  await page.getByRole('button', { name: 'Run setup again' }).click();
  await expect(page).toHaveURL(/\/setup\/client$/);
  // Nothing is deleted, and setup is no longer complete (the gate sends you through the wizard).
  const setup = (await (await request.get('/api/setup')).json()) as Setup;
  expect(setup.completed).toBe(false);
  // The live checks ran with the reset, so the wizard walks on from step 2: the client is still
  // installed, and Continue opens step 3.
  await expect(page.getByRole('heading', { level: 1, name: 'The Spotify client is installed' })).toBeVisible();
  expect(deviceChecks).toEqual([]);
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(/\/setup\/login$/);
  await expect(page.getByText('Logged in. This step is done.')).toBeVisible();
});

test('after Run setup again, step 5 waits for its own device check, which its page runs', async ({ page, request }) => {
  await useScenario(request, 'idle');
  // Through the API, with no page open, so nothing runs the check before the setup is read.
  expect((await request.post('/api/setup/restart')).ok()).toBe(true);
  // As in the controller: steps 2 to 4 and 6 are live checks and are done again at once. Step 5
  // isn't: it's marked by its device check (GET /api/spotify/devices).
  expect(((await (await request.get('/api/setup')).json()) as Setup).first_unfinished).toBe('webapi');
  // So a later step sends you back to it, and its page runs the check, which lets you on.
  await openPage(page, '/setup/output');
  await expect(page).toHaveURL(/\/setup\/web-api$/);
  await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(/\/setup\/output$/);
});

test('during a run, Save works and Run setup again says why it is refused', async ({ page, request }) => {
  await useScenario(request, 'running');
  await openPage(page, '/settings');
  await page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'MP3 320' }).click();
  await page.getByRole('region', { name: 'Unsaved changes' }).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved')).toBeVisible();

  await page.getByRole('button', { name: 'Run setup again' }).click();
  await expect(page.getByText('Not available while a backup is recording.')).toBeVisible();
  await expect(page).toHaveURL(/\/settings$/);
});
