// The setup wizard against the real controller in fake mode, `wizard` project: a fresh container at
// real speed (playwright.controller.config.ts). foundation.spec.ts runs first and passes step 1, so
// this walks steps 2 to 9 with the UI, as a user would, then reconnects once setup is complete,
// and runs the wizard again from Settings.
//
// The fake world (controller ARCHITECTURE.md § Fake mode): fake mode doesn't install the client by
// itself (controller client/manager.py), so step 2 shows Install; the install takes about 18 s.
// The client logs in at a click on the VNC screen (or 20 s after it starts), with Spotify's default
// prefs, which turn tidy 30 s later. Any authorization code works but one starting "bad".

import { expect, test, type Page } from '@playwright/test';
import { endsWith, getJson, openPage } from '../helpers.ts';
import type { Setup } from '../../src/api/types.ts';

/** Spotify's consent page isn't reached: the new tab gets a stand-in, and we read its `state`. */
async function authorize(page: Page): Promise<string> {
  await page.context().route('https://accounts.spotify.com/**', (route) => route.fulfill({ contentType: 'text/html', body: '<p>Consent</p>' }));
  const popup = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Open Spotify consent page' }).click();
  const tab = await popup;
  await tab.waitForURL(/accounts\.spotify\.com\/authorize/);
  const state = new URL(tab.url()).searchParams.get('state') ?? '';
  await tab.close();
  return state;
}

async function connect(page: Page) {
  const state = await authorize(page);
  await page.getByLabel('Address of the error page').fill(`http://127.0.0.1:8888/callback?code=e2e-code&state=${state}`);
  const finished = page.waitForResponse((r) => r.url().endsWith('/api/spotify/auth/finish'));
  await page.getByRole('button', { name: 'Connect' }).click();
  expect((await finished).status()).toBe(200);
  await expect(page.getByLabel('Address of the error page')).toHaveCount(0);
  await expect(page.getByText(/^Connected as .+ · expires /)).toBeVisible({ timeout: 20_000 });
}

test('steps 2 to 9 with the controller, from the install to the Library', async ({ page, request }) => {
  test.setTimeout(240_000);
  const proceed = page.getByRole('button', { name: 'Continue' });

  // 2. Install the client, unless it's under way or done already.
  await openPage(page, '/setup/client');
  const notStarted = page.getByRole('heading', { level: 1, name: 'Install the Spotify client' });
  const installed = page.getByRole('heading', { level: 1, name: 'The Spotify client is installed' });
  await expect(notStarted.or(installed).or(page.getByRole('heading', { level: 1, name: 'Installing the Spotify client' }))).toBeVisible();
  if (await notStarted.isVisible()) {
    const started = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/client/install'));
    await page.getByRole('button', { name: 'Install' }).click();
    expect((await started).status()).toBe(202);
    await expect(page.getByRole('progressbar', { name: 'Install progress' })).toBeVisible();
  }
  await expect(installed).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/^Version .+, in \/config\.$/)).toBeVisible();
  await proceed.click();

  // 3. A click on the fake VNC screen stands in for the phone's scan.
  await expect(page).toHaveURL(endsWith('/setup/login'));
  const screen = page.getByRole('region', { name: 'Spotify Client' });
  await expect(screen.getByText('Connected', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(async () => {
    await screen.locator('canvas').click();
    await expect(page.getByText('Logged in. This step is done.')).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 40_000 });
  await expect(proceed).toBeEnabled();
  await proceed.click();

  // 4. Tick the Confirm rows; the Auto rows turn OK 30 s after the login: Re-check until then.
  await expect(page).toHaveURL(endsWith('/setup/client-settings'));
  for (const row of ['Crossfade', 'Gapless playback']) {
    const box = page.getByRole('checkbox', { name: new RegExp(`^${row}: confirm`) });
    if (!(await box.isChecked())) {
      const saved = page.waitForResponse((r) => r.url().endsWith('/api/setup/checklist/confirm'));
      await box.check();
      expect((await saved).status()).toBe(200);
    }
  }
  await expect(async () => {
    const recheck = page.waitForResponse((r) => r.url().endsWith('/api/client/checklist'));
    await page.getByRole('button', { name: 'Re-check' }).click();
    await recheck;
    await expect(proceed).toBeEnabled({ timeout: 3_000 });
  }).toPass({ timeout: 90_000, intervals: [2_000] });
  await proceed.click();

  // 5. A Client ID, Authorize, the pasted address, and both checks.
  await expect(page).toHaveURL(endsWith('/setup/web-api'));
  await page.getByLabel('Client ID').fill('0123456789abcdef0123456789abcdef');
  await connect(page);
  await expect(page.getByLabel('Client ID')).toHaveValue(/^0123.+cdef$/);
  await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible({ timeout: 30_000 });
  await expect(proceed).toBeEnabled({ timeout: 20_000 });
  await proceed.click();

  // 6. The fake /music is mounted and writable.
  await expect(page).toHaveURL(endsWith('/setup/output'));
  await expect(page.getByText('/music is mounted and writable')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'AAC 256' })).toBeChecked();
  await expect(proceed).toBeEnabled();
  await proceed.click();

  // 7. Back up all my playlists, with Liked Songs (the defaults).
  await expect(page).toHaveURL(endsWith('/setup/playlists'));
  await expect(page.getByText(/^You have \d+ playlists?$/)).toBeVisible({ timeout: 30_000 });
  await proceed.click();

  // 8. Back up all my saved albums (the default).
  await expect(page).toHaveURL(endsWith('/setup/albums'));
  await expect(page.getByText(/^You have \d+ saved albums?$/)).toBeVisible({ timeout: 30_000 });
  const added = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/albums'));
  await proceed.click();
  expect((await added).status()).toBe(200);

  // 9. The summary, then Open Library finishes setup.
  await expect(page).toHaveURL(endsWith('/setup/done'));
  const summary = page.locator('dl');
  await expect(summary).toContainText(/Account\s*.+ · expires /);
  await expect(summary).toContainText('FormatAAC 256 · .m4a');
  await expect(summary).toContainText(/Folder\s*\/music/);
  await expect(summary).toContainText(/Tracking\s*.*Liked Songs · \d+ albums?/, { timeout: 15_000 });
  await expect(summary).toContainText('ScheduleNone yet');
  await page.getByRole('button', { name: 'Open Library' }).click();
  await expect(page).toHaveURL(endsWith('/library'));
  expect((await getJson<Setup>(request, '/api/setup')).completed).toBe(true);
});

test('/reconnect authorizes again, skipping the stored Client ID', async ({ page }) => {
  await openPage(page, '/reconnect');
  await expect(page.getByRole('heading', { level: 1, name: 'Connect the Spotify Web API' })).toBeVisible();
  await expect(page.getByLabel('Client ID')).toHaveCount(0);
  await connect(page);
  await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Done' }).click();
  await expect(page).toHaveURL(endsWith('/dashboard'));
});

test('Run setup again reopens step 2, and the wizard walks on to the Library', async ({ page, request }) => {
  test.setTimeout(120_000);
  const proceed = page.getByRole('button', { name: 'Continue' });
  await openPage(page, '/settings');
  await page.getByRole('button', { name: 'Run setup again' }).click();
  await expect(page).toHaveURL(endsWith('/setup/client'));
  expect((await getJson<Setup>(request, '/api/setup')).completed).toBe(false);

  // The controller runs the live checks with the reset: steps 2 to 4 and 6 are done again at once,
  // so Continue goes on (the setup gate would send it back to a step that isn't done).
  await expect(page.getByRole('heading', { level: 1, name: 'The Spotify client is installed' })).toBeVisible();
  await proceed.click();
  await expect(page).toHaveURL(endsWith('/setup/login'));
  await expect(page.getByText('Logged in. This step is done.')).toBeVisible();
  await proceed.click();
  await expect(page).toHaveURL(endsWith('/setup/client-settings'));
  await proceed.click();
  // Step 5: still connected; the device check marks it done again.
  await expect(page).toHaveURL(endsWith('/setup/web-api'));
  await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible({ timeout: 30_000 });
  await proceed.click();
  await expect(page).toHaveURL(endsWith('/setup/output'));
  await proceed.click();
  await expect(page).toHaveURL(endsWith('/setup/playlists'));
  await expect(page.getByText(/^You have \d+ playlists?$/)).toBeVisible({ timeout: 30_000 });
  await proceed.click();
  // Step 8, the other answer this time: "I'll choose in Albums" queues nothing, but answers the
  // step, so step 9's stepper ticks Albums and the controller has step 9 next.
  await expect(page).toHaveURL(endsWith('/setup/albums'));
  await expect(page.getByText(/^You have \d+ saved albums?$/)).toBeVisible({ timeout: 30_000 });
  await page.getByText("I'll choose in Albums").click();
  await proceed.click();
  await expect(page).toHaveURL(endsWith('/setup/done'));
  const steps = page.getByRole('list', { name: 'Setup steps' });
  await expect(steps.getByRole('link', { name: /^Albums\b.*done$/ })).toBeVisible();
  const setup = await getJson<Setup>(request, '/api/setup');
  expect(setup.first_unfinished).toBe('done');
  expect(setup.steps.find((s) => s.id === 'albums')?.state).toBe('done');
  await page.getByRole('button', { name: 'Open Library' }).click();
  await expect(page).toHaveURL(endsWith('/library'));
  expect((await getJson<Setup>(request, '/api/setup')).completed).toBe(true);
});
