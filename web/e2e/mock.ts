// Controls for the mock backend that Playwright's dev server starts (web/README.md § Mock backend).
// Each test starts by choosing a scenario, then puts the world in the state it needs:
//
//   await useScenario(request, 'running');
//   const mock = mockControls(request);
//   await mock.takeover();                     // playback moves to a phone: the run pauses
//   await useScenario(request, 'setup', { step: 'webapi' });   // the wizard at step 5
//
// The tests share one mock and run one at a time (playwright.config.ts), so a test never has to
// undo what it did: the next one starts from its own scenario.

import { expect, type APIRequestContext, type Page } from '@playwright/test';
import type { Scenario } from '../mock/fixtures.ts';
import type { Backlog, Connection, SetupStepId } from '../src/api/types.ts';

/** Starts the mock over in a scenario (`step`: where the `setup` scenario starts). Pages reconnect and get the new hello. */
export async function useScenario(request: APIRequestContext, scenario: Scenario, options: { step?: SetupStepId } = {}): Promise<void> {
  const response = await request.post('/__mock/scenario', { data: { scenario, ...options } });
  if (!response.ok()) throw new Error(`mock scenario ${scenario}: ${response.status()} ${await response.text()}`);
}

/** The mock's controls, beyond the scenario. Each throws if the mock refused (409: nothing to act on). */
export function mockControls(request: APIRequestContext) {
  async function post(path: string, data: Record<string, unknown> = {}): Promise<void> {
    const response = await request.post(`/__mock/${path}`, { data });
    if (!response.ok()) throw new Error(`mock ${path}: ${response.status()} ${await response.text()}`);
  }
  /** Waits until a track is recording (GET /api/status). */
  async function untilRecording(): Promise<void> {
    await expect
      .poll(async () => ((await (await request.get('/api/status')).json()) as { session_state: string | null }).session_state, {
        timeout: 15_000,
        message: 'a track recording',
      })
      .toBe('recording');
  }
  /** Retries a control the mock refuses until the run has reached a state where it applies. */
  async function whenRecording(path: string, data: Record<string, unknown> = {}): Promise<void> {
    await expect
      .poll(async () => (await request.post(`/__mock/${path}`, { data })).status(), { timeout: 15_000, message: `mock ${path}` })
      .toBeLessThan(300);
  }
  return {
    /**
     * Playback moves to "Lorne's iPhone" mid-track: the item is Interrupted, the run pauses, then
     * device.moved (the controller's order). Waits for a track: the mock refuses it before one records.
     */
    takeover: () => whenRecording('takeover'),
    /** Playback stalls: at the end of the track the item is "Interrupted · will retry", moved to the end. */
    stall: () => whenRecording('stall'),
    /**
     * The schedule window ends: stop after this track, Carried over, the run ends Window ended. Waits
     * for a track first: the mock takes a window end at any time, and before a track plays the item
     * would just end Stopped.
     */
    windowEnd: async () => {
      await untilRecording();
      await post('window-end');
    },
    /**
     * An `error` alert. Default: Spytify's capture_silent. `{source: 'controller', code: 'webapi'}`
     * is the Web API warning; `fatal: true` ends the item Partial; `withdrawn: true` takes it back.
     */
    error: (options: { source?: 'spytify' | 'controller'; code?: string; message?: string; fatal?: boolean; withdrawn?: boolean } = {}) =>
      post('error', options),
    /** The client install fails (step 2, Failed). */
    installFails: () => post('install-fails'),
    /**
     * The client's settings change (step 4; Settings › Spotify client): Auto rows by state
     * (`'ok'`, `'needs_change'`, `'unknown'`), Confirm rows by tick. `{ ready: true }` fixes them all.
     */
    checklist: (change: { rows?: Record<string, 'ok' | 'needs_change' | 'unknown' | boolean>; ready?: boolean }) =>
      post('checklist', change),
    /** The client logs in or out (step 3; the Player; the Dashboard's Held card). */
    login: (loggedIn: boolean) => post('login', { logged_in: loggedIn }),
    /**
     * The client stops, or starts again. The next run restarts it (a red alert) and goes on, or, with
     * `comesBack: false`, fails once the wait for its device is over (web-ui.md § Warnings).
     */
    client: (running: boolean, options: { comesBack?: boolean } = {}) =>
      post('client', { running, comes_back: options.comesBack !== false }),
    /** Whether the container's client is a playback device (step 5's second check). */
    deviceListed: (listed: boolean) => post('devices', { listed }),
    /** How "Spotify" answers link previews and adds: 503 spotify_unavailable or rate_limited. */
    spotify: (state: 'ok' | 'unavailable' | 'rate_limited') => post('spotify', { state }),
    /** The Web API connection changes live; the banner follows. */
    connection: (state: Connection['state']) => post('connection', { state }),
    /** /music mounted or not (step 6's red alert; step 6 is done once it is). */
    storage: (mounted: boolean) => post('storage', { mounted }),
    /** The VNC screen up, or closing WS /vnc with 1013 ("not up yet"). */
    vnc: (up: boolean) => post('vnc', { up }),
    /** History: empty ("No backups yet"), or the samples plus `older` older runs (paging). */
    history: (options: { empty: true } | { older: number }) => post('history', options),
    /** Marks the active wizard step done, whatever it is: a shortcut past a step's own write. */
    nextStep: () => post('setup/next'),
    /**
     * The backlog estimate changes (a `backlog` event): `measuring` (no track list read yet),
     * `fresh` (nothing recorded), `in_progress` (27 h left) or `complete`. `patch` sets fields on top.
     */
    backlog: (state: 'measuring' | 'fresh' | 'in_progress' | 'complete', patch: Partial<Backlog> = {}) =>
      post('backlog', { state, patch }),
    /**
     * A playlist made in Spotify (or, with `followed: true`, followed there): the Library's next
     * Refresh finds it, as a new item or a new suggestion in the + modal.
     */
    newPlaylist: (name: string, options: { followed?: boolean } = {}) =>
      post('new-playlist', { name, followed: options.followed === true }),
    /**
     * History › Logs: lines now, for the live tail (`add`); `burst` lines at once, more than one
     * `log.lines` holds (the live cap); `empty`: no lines at all; or `read_budget`: a page looks at
     * that many lines at most, as the controller's reads about 8 MB (until the next scenario).
     */
    logs: (
      change:
        | { add: { source: 'controller' | 'spytify' | 'client' | 'system'; level: 'debug' | 'info' | 'warning' | 'error'; message: string }[] }
        | { burst: number }
        | { empty: true }
        | { read_budget: number },
    ) => post('logs', change),
  };
}

/** Opens a page once the live store has its first snapshot (no "Connecting to spotivault…"). */
export async function openPage(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page.getByText(/^(Connecting to spotivault…|Can't reach spotivault\. Trying again…)$/)).toHaveCount(0, { timeout: 15_000 });
}
