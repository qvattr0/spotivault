// The setup wizard against the mock, steps 6 to 9: Output, What to back up, Albums and Done.

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';
import type { LibrarySummary, Settings, Setup } from '../src/api/types.ts';

function heading(page: Page, name: string | RegExp) {
  return page.getByRole('heading', { level: 1, name });
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  return (await (await request.get(path)).json()) as T;
}

test.describe('step 6: Output', () => {
  test('/music not mounted: the red alert says how to map it, and Re-check finds it mounted', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'output' });
    await openPage(page, '/setup/output');
    await expect(heading(page, 'Where and how to save')).toBeVisible();
    const alert = page.getByRole('alert').filter({ hasText: "/music isn't mounted" });
    await expect(alert).toContainText('In the UGOS Docker app');
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    await mockControls(request).storage(true);
    await alert.getByRole('button', { name: 'Re-check' }).click();
    await expect(page.getByText('/music is mounted and writable')).toBeVisible();
    // The shared folder's own path (GET /api/container's music_source).
    await expect(page.getByText('1.84 TB free on /Music')).toBeVisible();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/playlists$/);
  });

  test('the format is saved as you choose it; More formats holds FLAC and WAV, with no benefit', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'playlists' });
    await openPage(page, '/setup/output');
    const formats = page.getByRole('radiogroup', { name: 'Format' });
    await expect(formats.getByRole('radio', { name: 'AAC 256' })).toBeChecked();
    await expect(formats).toContainText('Default · .m4a');
    await expect(page.getByText('Music/Radiohead/OK Computer/01 - Airbag.m4a')).toBeVisible();
    await expect(page.getByText('Music/Playlists/Late Night Drive.m3u')).toBeVisible();
    // M1 writes no cover files (open questions 14 and 15), so the text promises none.
    await expect(page.getByText(/Each playlist gets an \.m3u file in Music\/Playlists\//)).toBeVisible();
    await expect(page.getByText(/and its cover/)).toHaveCount(0);
    await expect(page.getByText(/with tags and a 640 px cover/)).toBeVisible();

    const saved = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/api/settings'));
    await formats.getByText('MP3 320', { exact: true }).click();
    expect((await saved).request().postDataJSON()).toEqual({ format: 'mp3', bitrate: 320 });
    await expect(formats.getByRole('radio', { name: 'MP3 320' })).toBeChecked();
    await expect(page.getByText('Music/Radiohead/OK Computer/01 - Airbag.mp3')).toBeVisible();

    await page.getByRole('button', { name: /More formats/ }).click();
    const more = page.getByRole('radiogroup', { name: 'More formats' });
    await expect(more).toContainText('No benefit: the source is lossy. Bigger files, same quality.');
    await more.getByText('FLAC', { exact: true }).click();
    await expect(more.getByRole('radio', { name: 'FLAC' })).toBeChecked();
    expect((await getJson<Settings>(request, '/api/settings')).format).toBe('flac');
  });

  test('the arrow keys move through the formats; focus stays, and the last one is saved', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'playlists' });
    await openPage(page, '/setup/output');
    const formats = page.getByRole('radiogroup', { name: 'Format' });
    await formats.getByRole('radio', { name: 'AAC 256' }).focus();
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    const mp3 = formats.getByRole('radio', { name: 'MP3 320' });
    await expect(mp3).toBeFocused();
    await expect(mp3).toBeChecked();
    await expect.poll(async () => (await getJson<Settings>(request, '/api/settings')).format).toBe('mp3');
    await expect(mp3).toBeChecked();
    await expect(mp3).toBeFocused();
  });
});

test.describe('step 7: What to back up', () => {
  test('"Back up all my playlists" is the default, with the count and Include Liked Songs', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'playlists' });
    await openPage(page, '/setup/playlists');
    await expect(heading(page, 'What should spotivault back up?')).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Back up all my playlists' })).toBeChecked();
    await expect(page.getByText(/^You have \d+ playlists?$/)).toBeVisible();
    const liked = page.getByLabel('Include Liked Songs');
    await expect(liked).toBeChecked();
    await liked.uncheck();

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/albums$/);
    expect((await getJson<Settings>(request, '/api/settings')).auto_track_owned).toBe(true);
    expect((await getJson<LibrarySummary>(request, '/api/library/summary')).liked_tracked).toBe(false);
    expect((await getJson<Setup>(request, '/api/setup')).steps.find((s) => s.id === 'playlists')?.state).toBe('done');
  });

  test('"I\'ll choose in the Library" tracks nothing yet', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'playlists' });
    await openPage(page, '/setup/playlists');
    await page.getByText("I'll choose in the Library").click();
    await expect(page.getByRole('radio', { name: "I'll choose in the Library" })).toBeChecked();
    await expect(page.getByText('Track playlists anytime with the + button in the Library.')).toBeVisible();
    await expect(page.getByLabel('Include Liked Songs')).toBeDisabled();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/albums$/);
    expect((await getJson<Settings>(request, '/api/settings')).auto_track_owned).toBe(false);
    const summary = await getJson<LibrarySummary>(request, '/api/library/summary');
    expect(summary.liked_tracked).toBe(false);
    expect(summary.owned_tracked).toBe(0);

    // Coming back shows what was chosen.
    await page.getByRole('link', { name: 'Back' }).click();
    await expect(page.getByRole('radio', { name: "I'll choose in the Library" })).toBeChecked();
  });
});

test.describe('step 8: Albums', () => {
  test('"Back up all my saved albums" adds every saved album as Queued', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'albums' });
    await openPage(page, '/setup/albums');
    await expect(heading(page, 'Which albums should spotivault back up?')).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Back up all my saved albums' })).toBeChecked();
    const count = page.getByText(/^You have \d+ saved albums?$/);
    await expect(count).toBeVisible();
    const saved = Number((await count.textContent())?.match(/\d+/)?.[0]);
    await expect(page.getByText(/^Albums you downloaded in a Spotify app count as saved albums\./)).toBeVisible();

    const added = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/albums'));
    await page.getByRole('button', { name: 'Continue' }).click();
    expect((await added).request().postDataJSON()).toEqual({ all: true });
    await expect(page).toHaveURL(/\/setup\/done$/);
    await expect(page.getByText(new RegExp(` · ${saved} albums$`))).toBeVisible();

    // Coming back from the stepper shows what was chosen.
    await page.getByRole('list', { name: 'Setup steps' }).getByRole('link', { name: /^Albums\b.*done$/ }).click();
    await expect(page).toHaveURL(/\/setup\/albums$/);
    await expect(page.getByText(/^You have \d+ saved albums?$/)).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Back up all my saved albums' })).toBeChecked();
  });

  test('"I\'ll choose in Albums" adds nothing, but answers the step: step 9 shows Albums done', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'albums' });
    await openPage(page, '/setup/albums');
    let posted = false;
    page.on('request', (r) => {
      if (r.method() === 'POST' && r.url().endsWith('/api/albums')) posted = true;
    });
    await page.getByText("I'll choose in Albums").click();
    await expect(page.getByText('Add albums anytime with the + button on the Albums page.')).toBeVisible();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/done$/);
    await expect(page.getByText(/ · 0 albums$/)).toBeVisible();
    expect(posted).toBe(false);

    // The stepper ticks Albums, and GET /api/setup agrees: step 9 is next, so a new visit resumes there.
    const steps = page.getByRole('list', { name: 'Setup steps' });
    await expect(steps.getByRole('link', { name: /^Albums\b.*done$/ })).toBeVisible();
    const setup = await getJson<Setup>(request, '/api/setup');
    expect(setup.first_unfinished).toBe('done');
    expect(setup.steps.find((s) => s.id === 'albums')?.state).toBe('done');
    await openPage(page, '/');
    await expect(page).toHaveURL(/\/setup\/done$/);

    // Coming back from the stepper shows what was chosen, so Continue keeps it: still nothing added.
    await steps.getByRole('link', { name: /^Albums\b.*done$/ }).click();
    await expect(page).toHaveURL(/\/setup\/albums$/);
    await expect(page.getByText(/^You have \d+ saved albums?$/)).toBeVisible();
    await expect(page.getByRole('radio', { name: "I'll choose in Albums" })).toBeChecked();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/done$/);
    await expect(page.getByText(/ · 0 albums$/)).toBeVisible();
    expect(posted).toBe(false);
  });
});

test.describe('step 9: Done', () => {
  test('the summary, then Open Library finishes setup', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'done' });
    await openPage(page, '/setup/done');
    await expect(heading(page, "You're all set")).toBeVisible();
    const summary = page.locator('dl');
    await expect(summary).toContainText(/Account\s*Lorne · expires \d+ \w+ \d{4}/);
    await expect(summary).toContainText('FormatAAC 256 · .m4a');
    await expect(summary).toContainText('Folder/music → /Music');
    await expect(summary).toContainText(/Tracking\s*\d+ playlists \+ Liked Songs · \d+ albums?/);
    // No Schedule page in M1, so no "set it in Schedule".
    await expect(summary).toContainText('ScheduleNone yet');
    // The backup length, last: nothing recorded yet, and the followed playlists of unknown length.
    await expect(summary).toContainText('Backup lengthAbout 298 h of music to record+ 2 followed playlists (unknown length)');
    await expect(page.getByRole('term').last()).toHaveText('Backup length');

    await page.getByRole('button', { name: 'Open Library' }).click();
    await expect(page).toHaveURL(/\/library$/);
    expect((await getJson<Setup>(request, '/api/setup')).completed).toBe(true);
  });

  test('the backup length says Measuring… while the track lists load, then the figure', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'done' });
    const mock = mockControls(request);
    await openPage(page, '/setup/done');
    const summary = page.locator('dl');
    await expect(summary).toContainText('Backup lengthAbout 298 h of music to record');
    await mock.backlog('measuring');
    await expect(summary).toContainText('Backup lengthMeasuring…');
    await expect(page.getByText(/unknown length/)).toHaveCount(0);
    await mock.backlog('fresh', { unknown_items: 1 });
    await expect(summary).toContainText('Backup lengthAbout 298 h of music to record+ 1 followed playlist (unknown length)');
  });

  test('Back up now finishes setup, starts a first run and opens the Dashboard', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'done' });
    await openPage(page, '/setup/done');
    const run = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/runs'));
    await page.getByRole('button', { name: 'Back up now' }).click();
    expect((await run).status()).toBe(202);
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText('Backup started')).toBeVisible();
  });

  test("Back up now says why the run couldn't start, and still opens the Dashboard", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'done' });
    await mockControls(request).login(false);
    await openPage(page, '/setup/done');
    await page.getByRole('button', { name: 'Back up now' }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText('The backup couldn’t start: the Spotify client is logged out. Log in again in the Player.')).toBeVisible();
  });

  test('a step from 1 to 6 not done: the steps are named, with links', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'done' });
    // Not reachable through the gate (steps 7 to 9 open only once 1 to 6 are done), so the
    // controller's answer is played here: 409 setup_incomplete with the steps.
    await page.route('**/api/setup/complete', (route) =>
      route.fulfill({
        status: 409,
        json: { error: { code: 'setup_incomplete', message: 'Finish the setup steps first: webapi, output.', details: { steps: ['webapi', 'output'] } } },
      }),
    );
    await openPage(page, '/setup/done');
    await page.getByRole('button', { name: 'Open Library' }).click();
    const alert = page.getByRole('alert').filter({ hasText: 'Finish setup first' });
    await expect(alert).toContainText("These steps aren't done yet: Web API, Output.");
    await expect(alert.getByRole('link', { name: 'Web API' })).toHaveAttribute('href', '/setup/web-api');
    await expect(page).toHaveURL(/\/setup\/done$/);
  });
});
