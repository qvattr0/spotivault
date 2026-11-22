// What the gallery's live shell view can do to the backend: the mock's own /__mock controls
// (README § Mock backend), and the run endpoints of the real API. Each action throws an Error
// with a short message when it's refused.

import { api, errorCode } from '@/api';
import type { Scenario } from '@mock/fixtures.ts';

/** The mock's current scenario, or null when no mock answers (a real controller, or nothing). */
export async function currentScenario(): Promise<Scenario | null> {
  try {
    const response = await fetch('/__mock/scenario');
    if (!response.ok) return null;
    const body = (await response.json()) as { scenario?: Scenario };
    return body.scenario ?? null;
  } catch {
    return null;
  }
}

/** Starts the mock over in a scenario. Open pages get a new hello. */
export function setScenario(scenario: Scenario): Promise<void> {
  return mockPost('/__mock/scenario', { scenario });
}

async function mockPost(path: string, body: unknown = {}): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} answered ${response.status}`);
}

/** Throws when an API call was refused, with the contract's error code. */
async function check(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  const { error, response } = await call;
  if (!response.ok) throw new Error(`refused: ${errorCode(error)} (${response.status})`);
}

export interface RunAction {
  label: string;
  run: () => Promise<void>;
}

/** The buttons under the frame, in the order a run goes. */
export const RUN_ACTIONS: RunAction[] = [
  { label: 'Run now', run: () => check(api.POST('/api/runs', { body: {} })) },
  { label: 'Take over playback', run: () => mockPost('/__mock/takeover') },
  { label: 'Spytify error', run: () => mockPost('/__mock/error') },
  { label: 'Resume', run: () => check(api.POST('/api/runs/current/resume')) },
  {
    label: 'Stop after this track',
    run: () => check(api.POST('/api/runs/current/stop', { body: { mode: 'after_track' } })),
  },
  { label: 'Stop now', run: () => check(api.POST('/api/runs/current/stop', { body: { mode: 'now' } })) },
];
