// Playwright: end-to-end tests in e2e/, in Chromium only, against the Vite dev server and the mock
// backend it starts. Ports differ from `npm run dev`'s, so both can run at once.
//
//   npm run e2e                    all tests
//   npx playwright test --ui       pick and watch tests
//
// Each test can switch the mock's scenario: see e2e/mock.ts.
//
// Two runs at once (two worktrees, two agents) would share the mock and test-results/. Give the
// second its own: E2E_PORT=5299 E2E_MOCK_PORT=8299 E2E_OUTPUT=test-results-2 npm run e2e

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 5199);
const MOCK_PORT = Number(process.env.E2E_MOCK_PORT ?? 8199);

export default defineConfig({
  testDir: 'e2e',
  outputDir: process.env.E2E_OUTPUT ?? 'test-results',
  fullyParallel: false,
  // Tests share one mock backend, so they run one at a time.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 960 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 960 } } }],
  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    env: { MOCK_PORT: String(MOCK_PORT), SPOTIVAULT_BACKEND: '' },
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
