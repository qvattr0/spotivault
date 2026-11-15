// The shell follows the run live over WS /api/events (plan S7: "The shell shows live run.state").

import { expect, test } from '@playwright/test';
import { expectRunState, recordEvents, runStates } from './live.ts';
import { useScenario } from './mock.ts';

test('the shell shows run.state changing live from the WS', async ({ page, request }) => {
  await useScenario(request, 'idle');
  const events = recordEvents(page);
  await page.goto('/dashboard');
  await expectRunState(page, 'idle');

  // From here on the page gets no REST answers, so whatever it shows came over the socket.
  // (page.route doesn't touch WebSockets.)
  await page.route('**/api/**', (route) => route.abort());

  // Start a run from outside the page, as the scheduler or another tab would.
  expect((await request.post('/api/runs', { data: {} })).status()).toBe(202);
  await expectRunState(page, 'running');
  expect(runStates(events)).toContain('running');

  await request.post('/api/runs/current/stop', { data: { mode: 'now' } });
  await expectRunState(page, 'idle');
  expect(runStates(events).at(-1)).toBe('idle');
});

test('a takeover pauses the run, and the shell says so', async ({ page, request }) => {
  await useScenario(request, 'running');
  await page.goto('/dashboard');
  await expectRunState(page, 'running');
  // The mock refuses a takeover (409) until the run has a current item.
  await expect.poll(async () => (await request.post('/__mock/takeover')).status(), { timeout: 10_000 }).toBe(204);
  // The mock pauses the run up to about 9 s after it accepts the takeover.
  await expectRunState(page, 'paused', 15_000);
});

test("the gallery's live shell runs and stops a backup", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await page.goto('/gallery?view=shell');
  const frame = page.frameLocator('iframe[title="Live shell"]');
  const ownState = page.getByTestId('gallery-run-state');
  await expectRunState(frame, 'idle');

  await page.getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByRole('status')).toHaveText('Run now: sent.');
  await expectRunState(frame, 'running');
  // The gallery page's own store follows the same run.
  await expect(ownState).toHaveAttribute('data-run-state', 'running');

  await page.getByRole('button', { name: 'Stop now' }).click();
  await expectRunState(frame, 'idle');
  await expect(ownState).toHaveAttribute('data-run-state', 'idle');
});

test("the gallery's live shell sets the mock up like a drawing", async ({ page, request }) => {
  await useScenario(request, 'idle');
  await page.goto('/gallery?view=shell');
  await page.getByRole('button', { name: /Dashboard · Paused/ }).click();
  await expect(page).toHaveURL(/screen=hJlHj/);
  const frame = page.frameLocator('iframe[title="Live shell"]');
  // The mock's "paused" scenario takes playback away 4 s into its run.
  await expectRunState(frame, 'paused', 15_000);
  await expect(page.getByRole('combobox', { name: 'Scenario' })).toHaveValue('paused');
});
