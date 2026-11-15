// Playwright against a real controller in fake mode, not the mock: the built UI (dist/) is served
// by `uv run python -m spotivault --fake`, as the image serves it. Run it after `npm run build`
// (npm run e2e:controller does both).
//
//   npm run e2e:controller
//
// The controller starts on a free port with a new, empty data folder (so the wizard scenario
// starts fresh every run). Both are picked once, here, and passed on in the environment: Playwright
// loads this file again in each worker, and must find the same port and folder there.

import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

process.env.E2E_CONTROLLER_PORT ??= execFileSync(
  process.execPath,
  ['-e', 'const s = require("node:net").createServer().listen(0, () => { process.stdout.write(String(s.address().port)); s.close(); });'],
  { encoding: 'utf8' },
).trim();
process.env.E2E_CONTROLLER_DATA ??= mkdtempSync(join(tmpdir(), 'spotivault-e2e-'));

const PORT = Number(process.env.E2E_CONTROLLER_PORT);
const DATA = process.env.E2E_CONTROLLER_DATA;
const web = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  testDir: 'e2e-controller',
  outputDir: 'test-results-controller',
  // The tests share one controller and its state, so they run in order, one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 960 },
  },
  projects: [{ name: 'controller', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 960 } } }],
  webServer: {
    // --directory runs the command in controller/, where the locked venv is.
    command: `uv run --directory ${JSON.stringify(join(web, '..', 'controller'))} python -m spotivault --fake --port ${PORT}`,
    url: `http://localhost:${PORT}/api/health`,
    env: {
      SPOTIVAULT_HOST: '127.0.0.1',
      SPOTIVAULT_WEB_ROOT: join(web, 'dist'),
      SPOTIVAULT_FAKE_SCENARIO: 'wizard',
      SPOTIVAULT_CONFIG_DIR: join(DATA, 'config'),
      SPOTIVAULT_MUSIC_DIR: join(DATA, 'music'),
    },
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
