// The drawn screens the live shell can be set up like: which mock scenario and route reproduce
// each one. The gallery's "Shell, live" view offers them, and the e2e tests screenshot them as
// e2e/screenshots/<node>.png, to set beside web/design-reference/<node>.png.
//
// Plain data with type-only imports: the e2e tests and the report script (Node) read it too.

import type { RunState } from '../../api/types.ts';
import type { Scenario } from '../../../mock/fixtures.ts';

export interface ShellScreen {
  /** The frame's node id in screens.md, which is also its reference PNG's name. */
  node: string;
  /** The frame's name in screens.md. */
  title: string;
  /** The mock scenario that sets it up (mock/fixtures.ts). */
  scenario: Scenario;
  /** The route it's drawn at. */
  path: string;
  /** The run state the shell shows once the scenario has played out. None for the wizard. */
  runState?: RunState;
  /** Wait for the bottom bar to show a track recording, as drawn, before the screenshot. */
  recording?: boolean;
}

export const SHELL_SCREENS: ShellScreen[] = [
  { node: 't4YEY', title: 'Dashboard · Running', scenario: 'running', path: '/dashboard', runState: 'running' },
  // The mock's "paused" scenario takes playback away 4 s into the run.
  { node: 'hJlHj', title: 'Dashboard · Paused (playback moved)', scenario: 'paused', path: '/dashboard', runState: 'paused' },
  { node: 'fzNDm', title: 'Dashboard · Idle (with expiry banner)', scenario: 'expiring', path: '/dashboard', runState: 'idle' },
  { node: 'jh5YJ', title: 'Player · View-only (during a run)', scenario: 'running', path: '/player', runState: 'running', recording: true },
  { node: 'ZQChN', title: 'Player · Interactive', scenario: 'idle', path: '/player', runState: 'idle' },
  { node: 'Oleh8', title: 'Setup 1 · Welcome and Terms', scenario: 'fresh', path: '/setup/welcome' },
];

/** The width of every drawn screen (screens.md § Frame size and layout). These are all 960 tall. */
export const SCREEN_SIZE = { width: 1440, height: 960 };
