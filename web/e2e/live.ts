// Helpers for watching the live state in e2e tests: the run state the shell shows, and the events
// the page's WebSocket receives.

import { expect, type FrameLocator, type Page } from '@playwright/test';

/** An event as it comes over WS /api/events (contracts/events.md). */
export interface WireEvent {
  seq: number | null;
  type: string;
  at: string;
  data: Record<string, unknown>;
}

/**
 * The sidebar's status card when it shows this run state: SidebarStatus sets data-testid="run-state"
 * and data-run-state on it.
 */
export function runStateCard(scope: Page | FrameLocator, state: string) {
  return scope.locator(`[data-testid="run-state"][data-run-state="${state}"]`);
}

/** Waits until the shell shows this run state. */
export async function expectRunState(scope: Page | FrameLocator, state: string, timeout = 10_000) {
  await expect(runStateCard(scope, state).first()).toBeVisible({ timeout });
}

/** Collects every event the page's live socket receives, from now on. */
export function recordEvents(page: Page): WireEvent[] {
  const events: WireEvent[] = [];
  page.on('websocket', (socket) => {
    if (!new URL(socket.url()).pathname.endsWith('/api/events')) return;
    socket.on('framereceived', ({ payload }) => {
      try {
        events.push(JSON.parse(String(payload)) as WireEvent);
      } catch {
        // Not JSON: not an event.
      }
    });
  });
  return events;
}

/** The run states that run.state events brought, in order. */
export function runStates(events: WireEvent[]): string[] {
  return events.filter((e) => e.type === 'run.state').map((e) => String(e.data.state));
}
