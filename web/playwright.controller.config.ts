// Playwright against a real controller in fake mode, not the mock: the built UI (dist/) is served
// by `uv run python -m spotivault --fake`, as the image serves it. Run it after `npm run build`
// (npm run e2e:controller does both).
//
//   npm run e2e:controller                         both projects
//   npm run e2e:controller -- --project demo       one of them
//
// Two controllers, one per project, each on a free port with a new, empty data folder:
// - `wizard` (e2e-controller/wizard/): the `wizard` scenario, a fresh container, at real speed. For
//   the setup wizard. Its client logs itself in 20 s after it starts.
// - `demo` (e2e-controller/demo/): the `demo` scenario, set up at start-up with a library of 18
//   playlists and 124 saved albums, never run, no schedule. The fake world runs 10 times faster
//   (E2E_DEMO_SPEED), so a track records in 10–30 s. For every page after setup.
//
// The ports and folders are picked once, here, and passed on in the environment: Playwright loads
// this file again in each worker, and must find the same ones there.

import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

function freePort(): string {
  return execFileSync(
    process.execPath,
    ['-e', 'const s = require("node:net").createServer().listen(0, () => { process.stdout.write(String(s.address().port)); s.close(); });'],
    { encoding: 'utf8' },
  ).trim();
}

process.env.E2E_CONTROLLER_PORT ??= freePort();
process.env.E2E_DEMO_PORT ??= freePort();
process.env.E2E_CONTROLLER_DATA ??= mkdtempSync(join(tmpdir(), 'spotivault-e2e-'));

const WIZARD_PORT = Number(process.env.E2E_CONTROLLER_PORT);
const DEMO_PORT = Number(process.env.E2E_DEMO_PORT);
const DATA = process.env.E2E_CONTROLLER_DATA;
const DEMO_SPEED = process.env.E2E_DEMO_SPEED ?? '10';
const web = fileURLToPath(new URL('.', import.meta.url));

/** One controller in fake mode: the scenario, its port, its own data folder. */
function controller(scenario: 'wizard' | 'demo', port: number, speed: string) {
  return {
    // --directory runs the command in controller/, where the locked venv is.
    command: `uv run --directory ${JSON.stringify(join(web, '..', 'controller'))} python -m spotivault --fake --port ${port}`,
    url: `http://localhost:${port}/api/health`,
    env: {
      SPOTIVAULT_HOST: '127.0.0.1',
      SPOTIVAULT_WEB_ROOT: join(web, 'dist'),
      SPOTIVAULT_FAKE_SCENARIO: scenario,
      SPOTIVAULT_FAKE_SPEED: speed,
      SPOTIVAULT_CONFIG_DIR: join(DATA, scenario, 'config'),
      SPOTIVAULT_MUSIC_DIR: join(DATA, scenario, 'music'),
    },
    reuseExistingServer: false,
    timeout: 120_000,
  };
}

const browser = { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 960 } };

export default defineConfig({
  // E2E_OUTPUT gives a second run at once its own folder, as for npm run e2e.
  outputDir: process.env.E2E_OUTPUT ?? 'test-results-controller',
  // The tests of a project share one controller and its state, so they run in order, one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 960 },
  },
  projects: [
    { name: 'wizard', testDir: 'e2e-controller/wizard', use: { ...browser, baseURL: `http://localhost:${WIZARD_PORT}` } },
    { name: 'demo', testDir: 'e2e-controller/demo', use: { ...browser, baseURL: `http://localhost:${DEMO_PORT}` } },
  ],
  webServer: [controller('wizard', WIZARD_PORT, '1'), controller('demo', DEMO_PORT, DEMO_SPEED)],
});
