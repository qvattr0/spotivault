// The S8 pages in the state of each drawn frame (src/design/screens.md), for the screenshot report:
// screenshots.spec.ts opens each one on the mock, runs its `prepare`, and saves it as
// e2e/screenshots/<node>.png, to set beside web/design-reference/<node>.png.
//
// Not here: the frames of things M1 leaves out (custom covers, Schedule, History's Tracks).
// The order is screens.md's.

import { expect, type APIRequestContext, type Page } from '@playwright/test';
import type { Scenario } from '../mock/fixtures.ts';
import { fakeId } from '../mock/fixtures.ts';
import type { SetupStepId } from '../src/api/types.ts';
import { expectRunState } from './live.ts';
import { mockControls } from './mock.ts';

export interface PageScreen {
  /** The frame's node id in screens.md, which is also its reference PNG's name. */
  node: string;
  /** The frame's name in screens.md. */
  title: string;
  scenario: Scenario;
  /** Where the `setup` scenario starts. */
  step?: SetupStepId;
  path: string;
  /** The frame's height when it isn't 960: the screenshot is then the whole page, at this height. */
  height?: number;
  /** Puts the page in the drawn state, once it's open. */
  prepare?: (page: Page, request: APIRequestContext) => Promise<void>;
}

const libraryRow = (page: Page, name: string) =>
  page.getByRole('table', { name: 'Library' }).getByRole('row').filter({ hasText: name });

async function waitForRun(page: Page, state: string) {
  await expectRunState(page, state, 15_000);
}

export const PAGE_SCREENS: PageScreen[] = [
  // --- Setup wizard ---
  {
    node: 'Oleh8', title: 'Setup 1 · Welcome and Terms', scenario: 'fresh', path: '/setup/welcome',
    prepare: async (page) => {
      await page.getByRole('checkbox', { name: 'I understand' }).check();
    },
  },
  {
    node: 'h2Qgw', title: 'Setup 2 · Spotify client · Installing', scenario: 'setup', step: 'client', path: '/setup/client',
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Install' }).click();
      // The mock's download goes 6 → 80 % in tenths, 0.5 s each: 65 % is the nearest to the drawn 62 %.
      await expect(page.getByText(/^65%$/)).toBeVisible({ timeout: 15_000 });
    },
  },
  {
    node: 'dxPUp', title: 'Setup 2 · Spotify client · Failed', scenario: 'setup', step: 'client', path: '/setup/client',
    prepare: async (page, request) => {
      await mockControls(request).installFails();
      await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible({ timeout: 15_000 });
    },
  },
  {
    node: 'UzVcR', title: 'Setup 3 · Log in to Spotify', scenario: 'setup', step: 'login', path: '/setup/login',
    prepare: async (page) => {
      await expect(page.getByRole('region', { name: 'Spotify Client' }).getByText('Connected')).toBeVisible({ timeout: 15_000 });
    },
  },
  {
    node: 'wNpTP', title: 'Setup 4 · Spotify client settings', scenario: 'setup', step: 'client_settings',
    path: '/setup/client-settings', height: 1240,
    prepare: async (page, request) => {
      // Drawn: one Auto row needs a change (Gapless) and two Confirm rows unticked. Gapless and
      // Crossfade are Confirm rows in web-ui.md § 4, so Volume normalization needs the change here.
      // (Not `ready: true` first: the step would turn done, and stay done.)
      await mockControls(request).checklist({ rows: { normalization: 'needs_change', auto_adjust_quality: 'ok', gapless: false, autoplay: false } });
      await page.getByRole('button', { name: 'Re-check' }).click();
      await expect(page.getByText('Needs change', { exact: true })).toBeVisible();
    },
  },
  {
    node: 'j8m6AR', title: 'Setup 5 · Connect the Spotify Web API', scenario: 'setup', step: 'webapi', path: '/setup/web-api',
    height: 1260,
    prepare: async (page, request) => {
      await mockControls(request).deviceListed(false);
      await mockControls(request).connection('ok');
      await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible({ timeout: 15_000 });
    },
  },
  {
    node: 'Mj5zE', title: 'Setup 6 · Output', scenario: 'setup', step: 'output', path: '/setup/output',
    prepare: async (page, request) => {
      await mockControls(request).storage(true);
      await page.getByRole('button', { name: 'Re-check' }).click();
      await expect(page.getByText('/music is mounted and writable')).toBeVisible();
    },
  },
  {
    node: 'ZJSG0', title: 'Setup 7 · Playlists', scenario: 'setup', step: 'playlists', path: '/setup/playlists',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'Back up all my playlists' }).check();
    },
  },
  {
    node: 'sUXcW', title: 'Setup 8 · Albums', scenario: 'setup', step: 'albums', path: '/setup/albums',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'Back up all my saved albums' }).check();
    },
  },
  {
    node: 'BAzX6', title: 'Setup 9 · Done', scenario: 'setup', step: 'done', path: '/setup/done',
    prepare: async (page) => {
      // The summary's rows show "…" until their reads are back.
      await expect(page.getByText('…', { exact: true })).toHaveCount(0);
    },
  },

  // --- Library ---
  {
    node: 'ZGPGu', title: 'Library · List', scenario: 'idle', path: '/library',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'List' }).click();
      await libraryRow(page, 'Late Night Drive').getByRole('button', { name: 'Options for Late Night Drive' }).click();
      await expect(page.getByRole('menu')).toBeVisible();
      await libraryRow(page, 'Indie Finds').hover({ position: { x: 600, y: 20 } });
    },
  },
  {
    node: 'GH52o', title: 'Library · Grid', scenario: 'running', path: '/library',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'Grid' }).click();
      // A card shows the recording ring once a track records.
      await expect(page.getByRole('list', { name: 'Library' }).getByText('Recording').first()).toBeVisible({ timeout: 15_000 });
      await page.getByRole('list', { name: 'Library' }).getByRole('listitem').filter({ hasText: 'Late Night Drive' }).hover();
    },
  },
  {
    // Drawn with "Late Night Drive", your own playlist with every track state. The mock's Late Night
    // Drive is followed (no track list), so Chill Mix stands in: yours, with every state.
    node: 'l9Wn7L', title: 'Library · Detail', scenario: 'idle', path: `/library/${fakeId('chillmix')}`,
    prepare: async (page) => {
      await page.getByRole('table', { name: /^Tracks/ }).getByRole('row').nth(2).hover();
    },
  },
  {
    node: 'w06M4n', title: 'Library · Add playlists modal', scenario: 'idle', path: '/library',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'List' }).click();
      await page.getByRole('button', { name: 'Add playlists' }).click();
      const dialog = page.getByRole('dialog', { name: 'Add playlists' });
      await dialog.getByRole('searchbox').fill(`https://open.spotify.com/playlist/${fakeId('fridayfinds')}`);
      await expect(dialog.getByRole('button', { name: 'Add Friday Finds' })).toBeVisible({ timeout: 10_000 });
    },
  },

  // --- Albums ---
  {
    node: 'MX2OU', title: 'Albums · Grid', scenario: 'running', path: '/albums',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'Grid' }).click();
      // The run reaches the albums after Liked Songs and a playlist with nothing new.
      await expect(page.getByRole('link', { name: 'Recording' })).toBeVisible({ timeout: 60_000 });
    },
  },
  {
    node: 'wwJXz', title: 'Albums · List', scenario: 'idle', path: '/albums',
    prepare: async (page) => {
      await page.getByRole('radio', { name: 'List' }).click();
      const row = page.getByRole('table', { name: 'Albums' }).getByRole('row').filter({ hasText: 'OK Computer' });
      await row.getByRole('button', { name: 'Options for OK Computer' }).click();
      await expect(page.getByRole('menu')).toBeVisible();
    },
  },
  {
    // "new": no album added yet, so every saved album is in the modal, as drawn (the page behind
    // is then empty).
    node: 'L3CNc7', title: 'Albums · Add albums modal', scenario: 'new', path: '/albums',
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Add albums' }).click();
      await expect(page.getByRole('dialog', { name: 'Add albums' }).getByRole('button', { name: /^Add / }).first()).toBeVisible();
    },
  },

  // --- Dashboard ---
  {
    node: 'fzNDm', title: 'Dashboard · Idle (with expiry banner)', scenario: 'expiring', path: '/dashboard',
    prepare: (page) => waitForRun(page, 'idle'),
  },
  {
    // Drawn mid-run: done and up-to-date items above the current one. The mock's run records Liked
    // Songs, passes a playlist with nothing new, then records the albums: wait for the first album.
    node: 't4YEY', title: 'Dashboard · Running', scenario: 'running', path: '/dashboard',
    prepare: async (page) => {
      await waitForRun(page, 'running');
      await expect(page.getByText('Item 3 of 5').first()).toBeVisible({ timeout: 45_000 });
      await expect(page.getByText('Recording', { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    },
  },
  {
    // The mock's "paused" scenario takes playback away 4 s into the run.
    node: 'hJlHj', title: 'Dashboard · Paused (playback moved)', scenario: 'paused', path: '/dashboard',
    prepare: (page) => waitForRun(page, 'paused'),
  },

  // --- History ---
  {
    node: 'o5vCh7', title: 'History · Runs', scenario: 'idle', path: '/history/runs',
    prepare: async (page) => {
      // Drawn with the first row hovered.
      await page.getByRole('table', { name: 'Runs' }).getByRole('row').nth(1).hover();
    },
  },
  {
    node: 'bWcg0', title: 'History · Run page', scenario: 'idle', path: '/history/runs/41',
    prepare: async (page) => {
      await page.getByRole('button', { name: /Chill Mix/ }).first().click();
      await expect(page.getByRole('table', { name: 'Tracks of Chill Mix' })).toBeVisible();
    },
  },
  {
    // Drawn following a run's lines, all sources, Run: All, scrolled up a little ("Jump to latest").
    node: 'xRi3r', title: 'History · Logs', scenario: 'running', path: '/history/logs',
    prepare: async (page) => {
      const log = page.getByRole('log', { name: 'Log lines' });
      await expect(log.locator('[data-source="spytify"]').first()).toBeVisible({ timeout: 15_000 });
      await log.hover();
      await page.mouse.wheel(0, -120);
      await expect(page.getByRole('button', { name: /Jump to latest/ })).toBeVisible();
    },
  },

  // --- Settings ---
  {
    node: 't6RqK', title: 'Settings', scenario: 'idle', path: '/settings', height: 2926,
    prepare: async (page) => {
      await page.getByRole('radiogroup', { name: 'Format' }).getByRole('radio', { name: 'AAC 320' }).click();
      await expect(page.getByRole('region', { name: 'Unsaved changes' })).toBeVisible();
    },
  },
  {
    node: 'w1uXEY', title: 'Settings · Edit layout modal', scenario: 'idle', path: '/settings',
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Edit layout' }).click();
      await expect(page.getByRole('dialog', { name: 'Edit layout' })).toBeVisible();
      // Drawn with the field focused (its white stroke).
      await page.getByRole('textbox', { name: 'Layout' }).focus();
    },
  },

  // --- Player ---
  {
    node: 'ZQChN', title: 'Player · Interactive', scenario: 'idle', path: '/player',
    prepare: (page) => waitForRun(page, 'idle'),
  },
  {
    node: 'jh5YJ', title: 'Player · View-only (during a run)', scenario: 'running', path: '/player',
    prepare: async (page) => {
      await waitForRun(page, 'running');
      const bar = page.getByRole('region', { name: 'Now recording' });
      await expect(bar.getByText('Recording', { exact: true })).toBeVisible({ timeout: 15_000 });
      // Drawn with Restart's tooltip showing.
      await page.getByRole('button', { name: 'Restart client' }).hover();
      await expect(page.getByText('Not available while a backup is recording')).toBeVisible();
    },
  },
];
