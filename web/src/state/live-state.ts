// What the live store holds. Pages and the shell read it through the hooks in hooks.ts.

import type {
  Backlog,
  ClientInstall,
  ClientStatus,
  Connection,
  QueueItem,
  Setup,
  Status,
} from '../api/types.ts';
import type { DeviceMovedEvent, ErrorEvent, LevelEvent } from './events.ts';

/**
 * The WebSocket itself (not the Spotify connection, which is `spotify`).
 * - idle: never connected (tests, the gallery);
 * - connecting: the first attempt;
 * - open: connected; `ready` says whether a snapshot has arrived;
 * - reconnecting: lost, trying again with backoff (1 s doubling to 15 s). The last known state
 *   stays on screen, and after 5 s the store reads it through REST every 10 s until the socket is back.
 */
export type SocketState = 'idle' | 'connecting' | 'open' | 'reconnecting';

/** A warning shown between the now-playing strip and the queue on the Dashboard. */
export type Alert =
  | { kind: 'device_moved'; at: string; event: DeviceMovedEvent }
  | { kind: 'error'; at: string; event: ErrorEvent };

export interface LiveState {
  socket: SocketState;
  /**
   * True once a snapshot has arrived: a `hello`, or the REST read the store falls back to when the
   * socket can't connect. Until then the fields below are null.
   */
  ready: boolean;
  /** `hello.boot_id`: changes when the controller restarts. */
  bootId: string | null;
  /** The controller's version, from `hello`. */
  version: string | null;
  /** The `seq` of the last event applied. */
  lastSeq: number | null;
  /**
   * Counts the times the store reloaded its state after events may have been missed: a reconnect
   * (every hello but the first), a `seq` gap, a REST read while the socket is down. Data a page
   * loaded through REST before then may be stale: useApi() loads it again when this changes.
   */
  resyncs: number;

  /** The wizard's steps. `setup.completed` false sends every route to /setup. */
  setup: Setup | null;
  /** What's happening now: kept current by run.state, item.state, track.started and session.state. */
  status: Status | null;
  /** The Spotify Web API connection: the expiry banner, Settings, wizard step 5. */
  spotify: Connection | null;
  /** The Spotify client in the container: installed, running, logged in. */
  client: ClientStatus | null;
  /** The latest client install progress (wizard step 2). Also inside `client.install`. */
  install: ClientInstall | null;
  /** The backlog estimate, or null before the first one. */
  backlog: Backlog | null;
  /**
   * The current run's queue, from `run.queue` and `item.state`; [] when no run is going. Null while
   * unknown: `hello` doesn't carry it, so the store loads it with GET /api/runs/current after a
   * hello that has a run, and when a new run starts.
   */
  queue: QueueItem[] | null;
  /**
   * Open warnings of the current run: playback moved, Spytify or controller errors. Cleared when the
   * run ends or another starts. A reconnect keeps them while the same run goes on: no REST read
   * gives them back.
   */
  alerts: Alert[];
}

/** The latest `level` event, kept apart from LiveState because it changes 10 times a second. */
export interface LevelReading {
  level: LevelEvent;
  /** `Date.now()` when it arrived, so the meter can fall to silence when they stop. */
  receivedAt: number;
}

export const initialLiveState: LiveState = {
  socket: 'idle',
  ready: false,
  bootId: null,
  version: null,
  lastSeq: null,
  resyncs: 0,
  setup: null,
  status: null,
  spotify: null,
  client: null,
  install: null,
  backlog: null,
  queue: null,
  alerts: [],
};

export const idleStatus: Status = {
  state: 'idle',
  run: null,
  item: null,
  track: null,
  session_state: null,
  view_only: false,
};
