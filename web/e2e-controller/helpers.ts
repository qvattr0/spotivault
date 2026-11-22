// Helpers for the tests against the real controller in fake mode (playwright.controller.config.ts).
// The controller has no /__mock controls: tests reach states through the real API, as a user
// would, and wait for the fake world to get there.
//
// Two controllers, one per project, each shared by every test of its project, in file order:
// - wizard (e2e-controller/wizard/): a fresh container. Tests walk the wizard forward.
// - demo (e2e-controller/demo/): set up at start-up, with a library. Leave it as you found it:
//   stop any run you started (test.afterEach(({ request }) => stopAnyRun(request))), and put back
//   settings you changed.

import { expect, type APIRequestContext, type Page } from '@playwright/test';
import type { RunState, Setup, Status } from '../src/api/types.ts';
import { SETUP_STEPS } from '../src/shell/setup-steps.ts';

/** GET a JSON answer, failing the test on an error status. */
export async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `GET ${path}: ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

/** Where the setup gate sends you now: the first unfinished step, read from GET /api/setup. */
export async function gatePath(request: APIRequestContext): Promise<string> {
  const setup = await getJson<Setup>(request, '/api/setup');
  if (setup.completed || setup.first_unfinished === null) return '/dashboard';
  const step = SETUP_STEPS.find((s) => s.id === setup.first_unfinished);
  return `/setup/${step?.slug ?? 'welcome'}`;
}

/** A URL pattern for `expect(page).toHaveURL()`: the path at the end of the URL. */
export function endsWith(path: string): RegExp {
  return new RegExp(`${path.replace(/[/\-?]/g, (c) => `\\${c}`)}$`);
}

/**
 * The demo controller completes its wizard in the background at start-up, then refreshes the
 * catalog. Waits for both: setup complete, and the Library listing more than Liked Songs.
 */
export async function demoReady(request: APIRequestContext): Promise<void> {
  await expect
    .poll(async () => (await getJson<Setup>(request, '/api/setup')).completed, { timeout: 30_000, message: 'demo setup complete' })
    .toBe(true);
  await expect
    .poll(async () => (await getJson<{ items: unknown[] }>(request, '/api/library')).items.length, { timeout: 60_000, message: 'demo Library loaded' })
    .toBeGreaterThan(1);
}

/** Waits until the run is in this state (GET /api/status). */
export async function waitForRunState(request: APIRequestContext, state: RunState, timeout = 60_000): Promise<void> {
  await expect
    .poll(async () => (await getJson<Status>(request, '/api/status')).state, { timeout, message: `run state ${state}` })
    .toBe(state);
}

/** Stops whatever run is going (Stop now) and waits until the controller is idle again. */
export async function stopAnyRun(request: APIRequestContext): Promise<void> {
  const status = await getJson<Status>(request, '/api/status');
  if (status.state === 'idle') return;
  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  await waitForRunState(request, 'idle');
}

/** Starts a forced run of these items (Back up now) and waits until a track records. */
export async function startRun(request: APIRequestContext, items: string[]): Promise<number> {
  const response = await request.post('/api/runs', { data: { items } });
  expect(response.status(), 'POST /api/runs').toBe(202);
  const { run_id: runId } = (await response.json()) as { run_id: number };
  await expect
    .poll(async () => (await getJson<Status>(request, '/api/status')).session_state, { timeout: 60_000, message: 'a track recording' })
    .toBe('recording');
  return runId;
}

/** Opens an app page once the live store has its first snapshot (no "Connecting to spotivault…"). */
export async function openPage(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page.getByText(/^(Connecting to spotivault…|Can't reach spotivault\. Trying again…)$/)).toHaveCount(0, { timeout: 15_000 });
}
