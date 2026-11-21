// The setup wizard against the mock, steps 1 to 4: every state web-ui.md § Setup wizard describes
// for them. Steps 5 to 9 and /reconnect are in wizard-connect.spec.ts and wizard-finish.spec.ts;
// a walk through all nine in wizard-walk.spec.ts.

import { expect, test, type Page } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';

function heading(page: Page, name: string | RegExp) {
  return page.getByRole('heading', { level: 1, name });
}

test.describe('step 1: Welcome and Terms notice', () => {
  test('Continue waits for "I understand", then stores it and moves on to step 2', async ({ page, request }) => {
    await useScenario(request, 'fresh');
    await openPage(page, '/setup/welcome');
    await expect(heading(page, 'Back up your Spotify playlists as real files')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Before you start' })).toBeVisible();
    await expect(page.getByText("Recording breaks Spotify's terms of use.", { exact: false })).toBeVisible();
    const proceed = page.getByRole('button', { name: 'Continue' });
    await expect(proceed).toBeDisabled();

    await page.getByLabel('I understand').check();
    const posted = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/setup/tos'));
    await proceed.click();
    expect((await posted).status()).toBe(200);
    await expect(page).toHaveURL(/\/setup\/client$/);
  });

  test('once acknowledged, it shows read-only, without the checkbox', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client' });
    await openPage(page, '/setup/welcome');
    await expect(heading(page, 'Back up your Spotify playlists as real files')).toBeVisible();
    await expect(page.getByLabel('I understand')).toHaveCount(0);
    await expect(page.getByText(/^You acknowledged this notice on /)).toBeVisible();
    await page.getByRole('link', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/client$/);
  });

  test('after setup, About\'s "Read the Terms notice again" has a way back to Settings', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await openPage(page, '/setup/welcome');
    await expect(page.getByLabel('I understand')).toHaveCount(0);
    await page.getByRole('link', { name: 'Back to Settings' }).click();
    await expect(page).toHaveURL(/\/settings$/);
  });
});

test.describe('step 2: Spotify client', () => {
  test('Installing shows the phase, progress and log lines, then Installed shows the version', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client' });
    await openPage(page, '/setup/client');
    // The controller starts the install by itself on its first start; the mock waits for it.
    await expect(heading(page, 'Install the Spotify client')).toBeVisible();
    await page.getByRole('button', { name: 'Install' }).click();

    await expect(heading(page, 'Installing the Spotify client')).toBeVisible();
    await expect(page.getByRole('progressbar', { name: 'Install progress' })).toBeVisible();
    await expect(page.getByRole('log', { name: 'Install log' })).toContainText('InRelease signature OK');
    await expect(page.getByText(/^Downloading spotify-client 1\.3\.4…$/)).toBeVisible();
    await expect(page.getByText(/^\d+%$/)).toBeVisible();
    // Continue waits for the install (the drawing draws it enabled; web-ui.md wins).
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    await expect(heading(page, 'The Spotify client is installed')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Version 1.3.4.258, in /config.')).toBeVisible();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/login$/);
  });

  test('Failed shows why and the last log lines, and Retry starts the install again', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client' });
    await openPage(page, '/setup/client');
    await mockControls(request).installFails();
    await expect(heading(page, "The client couldn't be installed")).toBeVisible();
    const alert = page.getByRole('alert').filter({ hasText: "Spotify's repository couldn't be reached" });
    await expect(alert).toContainText('Check the NAS has internet access, then retry.');
    await expect(page.getByRole('log', { name: 'Install log' })).toContainText('Connection reset by peer');

    const retried = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/client/install'));
    await page.getByRole('button', { name: 'Retry' }).click();
    expect((await retried).status()).toBe(202);
    await expect(heading(page, 'Installing the Spotify client')).toBeVisible();
  });

  test('an installed client ticks the step off on its own', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'login' });
    await openPage(page, '/setup/client');
    await expect(heading(page, 'The Spotify client is installed')).toBeVisible();
    await expect(page.getByRole('list', { name: 'Setup steps' }).getByRole('link', { name: /Spotify client/ })).toHaveCount(0);
  });
});

test.describe('step 3: Log in to Spotify', () => {
  test("the client's login screen shows, and the step turns green by itself on login", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'login' });
    await openPage(page, '/setup/login');
    await expect(heading(page, 'Log in to Spotify')).toBeVisible();
    for (const line of ['Open Spotify on your phone.', 'Scan the code.', 'Approve the login. Use the account whose playlists you want to back up.']) {
      await expect(page.getByText(line, { exact: true })).toBeVisible();
    }
    const panel = page.getByRole('region', { name: 'Spotify Client' });
    await expect(panel.getByText('Connected')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Waiting for login… this step turns green on its own.')).toBeVisible();
    // No "I'm logged in" button: Continue waits.
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    // A click on the QR code stands in for the phone's scan (mock/vnc.ts).
    await panel.locator('canvas').click();
    await expect(page.getByText('Logged in. This step is done.')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/client-settings$/);
  });

  test('Reset login screen restarts the client for a fresh code', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'login' });
    await openPage(page, '/setup/login');
    await expect(page.getByText('Code expired, or the client shows something else?')).toBeVisible();
    const restarted = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/client/restart'));
    await page.getByRole('button', { name: 'Reset login screen' }).click();
    expect((await restarted).status()).toBe(202);
    await expect(page.getByText('Restarting the client. A new code shows in a few seconds.')).toBeVisible();
  });

  test('the screen says when it is not up yet', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'login' });
    await mockControls(request).vnc(false);
    await openPage(page, '/setup/login');
    await expect(page.getByRole('region', { name: 'Spotify Client' }).getByText('Reconnecting…').first()).toBeVisible({ timeout: 15_000 });
  });

  test("after setup, the Held card's \"Log in again\" lands here, with a way back", async ({ page, request }) => {
    await useScenario(request, 'idle');
    await mockControls(request).login(false);
    await openPage(page, '/setup/login');
    await expect(page.getByText('Waiting for login… this step turns green on its own.')).toBeVisible();
    await mockControls(request).login(true);
    await expect(page.getByText('Logged in. This step is done.')).toBeVisible();
    await page.getByRole('link', { name: 'Back to Dashboard' }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});

test.describe('step 4: Spotify client settings', () => {
  test('Needs change and Unknown hold Continue, with the reason beside it; Re-check reads again', async ({ page, request }) => {
    // The contract's example: Volume normalization needs a change, Auto adjust is unknown.
    await useScenario(request, 'setup', { step: 'client_settings' });
    await openPage(page, '/setup/client-settings');
    await expect(heading(page, 'Spotify client settings')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Spotify client · Settings' })).toBeVisible();

    const normalization = page.locator('[data-row="normalization"]');
    await expect(normalization).toContainText('Volume normalization');
    await expect(normalization).toContainText('Off');
    await expect(normalization).toContainText('Needs change');
    await expect(page.locator('[data-row="auto_adjust_quality"]')).toContainText('Unknown');
    await expect(page.locator('[data-row="volume"]')).toContainText('Set for you');
    await expect(page.locator('[data-row="automix"]')).toContainText('OK');
    await expect(page.getByText(/Not a blocker: the run also stops when the context changes\./)).toBeVisible();
    for (const section of ['Playback', 'Audio quality', 'Player']) {
      await expect(page.getByRole('heading', { level: 2, name: section })).toBeVisible();
    }
    // The rows follow the client's Settings order: Playback starts with Autoplay.
    const order = await page.locator('li[data-row]').evaluateAll((items) => items.map((item) => item.getAttribute('data-row')));
    expect(order).toEqual([
      'autoplay',
      'crossfade',
      'gapless',
      'automix',
      'normalization',
      'mono',
      'equalizer',
      'streaming_quality',
      'auto_adjust_quality',
      'volume',
    ]);
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
    await expect(page.getByText('Volume normalization needs to be off')).toBeVisible();

    // You change the setting in the client, then Re-check.
    await mockControls(request).checklist({ rows: { normalization: 'ok' } });
    await page.getByRole('button', { name: 'Re-check' }).click();
    await expect(normalization).not.toContainText('Needs change');
    await expect(page.getByText("Auto adjust quality can't be read yet. Re-check once the client is logged in")).toBeVisible();
  });

  test('Confirm rows tick and untick through the API; Autoplay can stay unticked', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client_settings' });
    await openPage(page, '/setup/client-settings');
    const crossfade = page.getByRole('checkbox', { name: /^Crossfade: confirmed/ });
    await expect(crossfade).toBeChecked();
    const posted = page.waitForResponse((r) => r.url().endsWith('/api/setup/checklist/confirm'));
    await crossfade.uncheck();
    expect((await posted).request().postDataJSON()).toEqual({ rows: { crossfade: false } });
    await expect(page.getByRole('checkbox', { name: /^Crossfade: confirm it/ })).not.toBeChecked();
    await expect(page.getByRole('checkbox', { name: /^Autoplay: confirm it/ })).not.toBeChecked();
  });

  test('once every blocker is satisfied, Continue goes on to step 5', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'client_settings' });
    await openPage(page, '/setup/client-settings');
    const proceed = page.getByRole('button', { name: 'Continue' });
    await expect(proceed).toBeDisabled();
    // You change both settings in the client, then Re-check.
    await mockControls(request).checklist({ rows: { normalization: 'ok', auto_adjust_quality: 'ok' } });
    await page.getByRole('button', { name: 'Re-check' }).click();
    await expect(page.locator('[data-row="normalization"]')).toContainText('OK');
    await expect(proceed).toBeEnabled();
    await proceed.click();
    await expect(page).toHaveURL(/\/setup\/web-api$/);
  });
});
