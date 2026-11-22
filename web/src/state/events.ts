// The live events of WS /api/events, typed from contracts/events.md.
// Schema names (RunSummary, QueueItem, ...) come from contracts/openapi.yaml through ../api.
// When events.md changes, change this file to match.

import type {
  Album,
  Backlog,
  ClientInstall,
  ClientStatus,
  Connection,
  ErrorCode,
  HistoryRow,
  ItemState,
  LibraryItem,
  LogLine,
  QueueItem,
  RunState,
  RunSummary,
  SessionState,
  Setup,
  Status,
} from '../api/types.ts';

/** The first event on every connection: everything the shell needs to draw. */
export interface Hello {
  /** Changes on every controller start. A new one means: drop cached state. */
  boot_id: string;
  version: string;
  setup: Setup;
  status: Status;
  connection: Connection;
  client: ClientStatus;
  /** The last estimate, or null before the first one. */
  backlog: Backlog | null;
}

export type RunStateEvent = RunSummary & { previous_state: RunState };

export interface RunQueueEvent {
  run_id: number;
  queue: QueueItem[];
}

export interface ItemStateEvent {
  run_id: number;
  item: QueueItem;
  previous_state: ItemState;
}

export interface RunFinishedEvent {
  run: HistoryRow;
}

export interface TrackStartedEvent {
  run_id: number;
  item_id: string;
  take_id: string;
  /** The first artist, as MPRIS gives it. */
  artist: string;
  title: string;
  album: string | null;
  length_ms: number;
  cover_url: string | null;
  /** Null when the take didn't match the item's track list. */
  track_id: string | null;
  position: number | null;
  /** False for a track the controller is about to jump over. */
  planned: boolean;
}

export interface TrackFinishedEvent {
  run_id: number;
  item_id: string;
  take_id: string;
  track_id: string | null;
  /** Relative to the music folder. */
  path: string;
  duration_ms: number;
  bytes: number;
  /** False for a take that doesn't count (low volume, pause fade, partial): the track stays missing. */
  counted: boolean;
  low_volume: boolean;
  pause_fade: boolean;
  partial: boolean;
}

export type SkipReason = 'duplicate' | 'too_short' | 'ad' | 'incomplete' | 'seeked' | 'low_quality' | 'silent';

export interface TrackSkippedEvent {
  run_id: number;
  item_id: string;
  take_id: string;
  reason: SkipReason;
  /** Set for `duplicate`, relative to the music folder. */
  path: string | null;
  track_id: string | null;
}

export interface ChannelLevel {
  peak_dbfs: number;
  rms_dbfs: number;
}

/** The level meter. At most 10 a second, only while recording. Volatile: `seq` is null. */
export interface LevelEvent {
  peak_dbfs: number;
  rms_dbfs: number;
  /** Left, then right. */
  channels: ChannelLevel[];
}

export interface SessionStateEvent {
  run_id: number;
  item_id: string;
  state: SessionState;
}

export interface DeviceMovedEvent {
  run_id: number;
  /** Null when the run started while another device was playing (paused_reason device_busy). */
  item_id: string | null;
  device: { id: string | null; name: string; type: string };
  discarded_take_id: string | null;
}

export type SpytifyErrorCode =
  | 'output_dir'
  | 'disk_full'
  | 'temp_file'
  | 'write'
  | 'ring_overflow'
  | 'capture_stalled'
  | 'capture_silent'
  | 'capture_low_quality'
  | 'player_volume_low'
  | 'read'
  | 'encode'
  | 'rename'
  | 'counter_full';

export type ControllerErrorCode =
  | 'recorder_exit'
  | 'recorder_timeout'
  | 'steering_guard'
  | 'loop_guard'
  | 'context_changed'
  | 'webapi'
  | 'storage'
  | 'client_restarted';

/** A red alert. `withdrawn: true` means: remove the alert with this code. */
export interface ErrorEvent {
  source: 'spytify' | 'controller';
  code: SpytifyErrorCode | ControllerErrorCode;
  message: string;
  /** The current item can't continue: it ends partial and the run moves on. */
  fatal: boolean;
  withdrawn: boolean;
  run_id: number | null;
  item_id: string | null;
  facts: Record<string, unknown> | null;
}

/** Why a catalog refresh ran: a run's start, a page open, setup, an item tracked or added, or the Refresh button. */
export type CatalogRefreshTrigger = 'run' | 'page_open' | 'setup' | 'item_added' | 'manual';

/** Why a catalog refresh failed or was skipped (events.md § Catalog refresh): an ErrorCode. */
export type CatalogRefreshReason = Extract<
  ErrorCode,
  'run_active' | 'not_connected' | 'connection_expired' | 'rate_limited' | 'spotify_unavailable' | 'internal'
>;

/**
 * A catalog refresh started or ended (events.md § Catalog refresh). One that was asked for and
 * didn't run sends only `ended`, with `refresh_id` null and outcome `skipped`.
 */
export interface CatalogRefreshEvent {
  refresh_id: number | null;
  trigger: CatalogRefreshTrigger;
  state: 'started' | 'ended';
  /** Null while started. */
  outcome: 'ok' | 'partial' | 'failed' | 'skipped' | null;
  /** The counts are null while started. */
  items_changed: number | null;
  /** New Library items: playlists you created since the last refresh. */
  items_added: number | null;
  /** New suggestions in the + modal: playlists you follow that aren't in the Library. */
  suggestions_added: number | null;
  /** Why it was `failed` or `skipped`; null otherwise. */
  reason: CatalogRefreshReason | null;
}

/**
 * New log lines for the Logs tab's live tail (events.md § Logs). Only to a connection that sent
 * `logs.follow`; at most twice a second, 200 lines at most. Volatile: `seq` is null.
 */
export interface LogLinesEvent {
  /** Oldest first. The same line can also come from GET /api/logs: drop it by `id`. */
  lines: LogLine[];
  /** Matching lines left out of this batch (the cap, or a slow socket). */
  dropped: number;
  /** The `follow_id` of the `logs.follow` this batch answers. */
  follow_id: number | string | null;
}

export type ClientInstallEvent = ClientInstall & {
  /** The new log line, or null. */
  log_line: string | null;
};

/** Every event type and its `data`. */
export interface EventMap {
  hello: Hello;
  // Run and queue
  'run.state': RunStateEvent;
  'run.queue': RunQueueEvent;
  'item.state': ItemStateEvent;
  'run.finished': RunFinishedEvent;
  // Backlog
  backlog: Backlog;
  // Spytify, relayed
  'track.started': TrackStartedEvent;
  'track.finished': TrackFinishedEvent;
  'track.skipped': TrackSkippedEvent;
  level: LevelEvent;
  'session.state': SessionStateEvent;
  // Warnings
  'device.moved': DeviceMovedEvent;
  error: ErrorEvent;
  // Library and Albums
  'library.item': LibraryItem;
  'album.item': Album;
  'catalog.refresh': CatalogRefreshEvent;
  // Setup, client and connection
  'setup.state': Setup;
  'client.install': ClientInstallEvent;
  'client.status': ClientStatus;
  connection: Connection;
  // History › Logs (only after logs.follow)
  'log.lines': LogLinesEvent;
}

/** The events with `seq: null`: not counted, never held back. */
export type VolatileEventType = 'level' | 'log.lines';

export type EventType = keyof EventMap;

/** One WebSocket message: `{seq, type, at, data}`. */
export interface Envelope<K extends EventType = EventType> {
  /** Counts up by 1 per event, per controller process. Null only for `level` and `log.lines`. */
  seq: K extends VolatileEventType ? null : number;
  type: K;
  /** RFC 3339, UTC, with milliseconds. */
  at: string;
  data: EventMap[K];
}

/** Any event, as a union you can `switch` on by `type`. */
export type LiveEvent = { [K in EventType]: Envelope<K> }[EventType];

export const EVENT_TYPES: readonly EventType[] = [
  'hello',
  'run.state',
  'run.queue',
  'item.state',
  'run.finished',
  'backlog',
  'track.started',
  'track.finished',
  'track.skipped',
  'level',
  'session.state',
  'device.moved',
  'error',
  'library.item',
  'album.item',
  'catalog.refresh',
  'setup.state',
  'client.install',
  'client.status',
  'connection',
  'log.lines',
];

/** True for the volatile types (`seq: null`). */
export function isVolatile(type: EventType): type is VolatileEventType {
  return type === 'level' || type === 'log.lines';
}

/** True for a message whose type this UI knows. Unknown types are ignored (events.md). */
export function isKnownEvent(message: { type?: unknown }): message is LiveEvent {
  return typeof message.type === 'string' && (EVENT_TYPES as readonly string[]).includes(message.type);
}
