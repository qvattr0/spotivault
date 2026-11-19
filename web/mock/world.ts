// The mock controller's state, and the simulations that change it: the client install, the login
// and runs (item phases, tracks, the level meter, stop, takeover and resume). Every change goes out
// as the WS event events.md names, so the UI sees what it would see from the real controller.
//
// A run goes: run.state idle -> starting, the pre-run check, then (as in the controller) run.queue
// with the queue built only now, and run.state running. Then per item: item.state planning ->
// preflight -> preparing -> starting -> playing, session.state waiting -> recording, track.started
// and track.finished per track with `level` 10 times a second while recording, then
// session.state stopping, item.state and run.state finishing, a `backlog` event, and on to the next
// item. Liked Songs first skips a track it already has (track.skipped, duplicate); an album's
// second track comes out too quiet (a failed track, the album ends Partial). At the end:
// run.state idle and run.finished.
//
// Mock controls cut a run short the ways web-ui.md § Warnings describes: a takeover (the run
// pauses), a stall (Interrupted · will retry, at the end of the queue), a fatal error (Partial), the
// window ending (Carried over, Window ended), and the client not running (a restart, and the run
// goes on or fails).
//
// Times are shortened: a track lasts seconds, not minutes. `speed` shortens them further (tests).

import * as f from './fixtures.ts';
import type { Hub } from './hub.ts';
import type {
  Album,
  Backlog,
  Checklist,
  ClientInstall,
  ClientStatus,
  Connection,
  HistoryRow,
  ItemState,
  LastRun,
  LibraryItem,
  LibrarySummary,
  QueueItem,
  RunItem,
  RunState,
  RunSummary,
  RunTrack,
  SavedAlbum,
  Schedule,
  ScheduleNext,
  SessionState,
  Settings,
  Setup,
  SetupStepId,
  Status,
  Storage,
  TrackResult,
} from '../src/api/types.ts';
import type { ControllerErrorCode, Hello, SpytifyErrorCode } from '../src/state/events.ts';

/** How the mock's "Spotify" answers the Library's link and suggestion calls (POST /__mock/spotify). */
export type SpotifyHealth = 'ok' | 'unavailable' | 'rate_limited';

/**
 * A checklist row as POST /__mock/checklist sets it: an Auto row's state (`ok`, `needs_change`,
 * `unknown`), or a Confirm row's tick.
 */
export type ChecklistRowValue = 'ok' | 'needs_change' | 'unknown' | boolean;

export interface WorldData {
  scenario: f.Scenario;
  tosAt: string | null;
  /**
   * Steps marked done by an action, not by a live fact: step 5 by its device check (GET
   * /api/spotify/devices, or the one after auth/finish), as the controller's connection.py
   * _mark_step_five does; steps 7 to 9 by their writes (see README § Mock backend).
   */
  manualDone: Set<SetupStepId>;
  /**
   * Steps that were done once. As in the controller (setup.py, "Done is sticky"), a step stays done
   * when its fact changes later, until "Run setup again".
   */
  doneOnce: Set<SetupStepId>;
  /**
   * Setup was completed once. It stays complete when a fact behind a step changes later (the Web API
   * connection expires, the client logs out) until "Run setup again": otherwise an expired
   * connection would send every route back to the wizard, and the red banner could never show.
   */
  setupCompleted: boolean;
  /** POST /api/spotify/auth/start was called and its address not used yet ("A pasted address works once"). */
  pendingAuth: boolean;
  /** The container's client is in GET /api/spotify/devices (step 5's second check). */
  deviceListed: boolean;
  /**
   * While the client isn't running (POST /__mock/client): whether the restart a run makes brings its
   * device back. If not, the run fails `device_missing` (web-ui.md § Warnings, Client not running).
   */
  clientComesBack: boolean;
  /**
   * The items the last window's end cut off, still waiting for their turn. A run puts them first and
   * marks them Carried over (`carried_over_in`), as the controller does (engine/queue.py).
   */
  carriedOver: Set<string>;
  spotify: SpotifyHealth;
  /** The VNC screen is up. While it isn't, WS /vnc closes with 1013 (contract: x-websockets). */
  vncUp: boolean;
  /** Each Library item's resting status while a run has it Queued, to put back afterwards. */
  restingStatus: Map<string, LibraryItem['status']>;
  /** The items of the runs the mock has run, for their run pages. Older runs show a sample. */
  runItems: Map<number, RunItem[]>;
  /** Each item's track results in the runs the mock has run, by `<run id>/<item id>`. */
  runTracks: Map<string, TrackResult[]>;
  client: ClientStatus;
  checklist: Checklist;
  connection: Connection;
  settings: Settings;
  storage: Storage;
  library: LibraryItem[];
  albums: Album[];
  saved: SavedAlbum[];
  history: HistoryRow[];
  backlog: Backlog | null;
  schedule: Schedule;
  scheduleNext: ScheduleNext;
  status: Status;
  queue: QueueItem[];
  currentTracks: RunTrack[];
  nextRunId: number;
}

/** The wizard step the `setup` scenario starts at, unless POST /__mock/scenario names another. */
export const DEFAULT_SETUP_STEP: SetupStepId = 'client_settings';

function initialData(scenario: f.Scenario, step: SetupStepId = DEFAULT_SETUP_STEP): WorldData {
  const hello = f.helloFor(scenario);
  const data: WorldData = {
    scenario,
    tosAt: hello.setup.tos_acknowledged_at,
    manualDone: new Set(hello.setup.completed ? (['webapi', 'playlists', 'albums', 'done'] as const) : []),
    doneOnce: new Set(hello.setup.completed ? f.SETUP_STEP_IDS : []),
    setupCompleted: hello.setup.completed,
    pendingAuth: false,
    deviceListed: true,
    clientComesBack: true,
    carriedOver: new Set(),
    spotify: 'ok',
    vncUp: true,
    restingStatus: new Map(),
    runItems: new Map(),
    runTracks: new Map(),
    client: hello.client,
    checklist: hello.setup.completed ? readyChecklist() : f.checklistM1,
    connection: hello.connection,
    settings: f.settingsDefault,
    storage: f.storageOk,
    library: structuredClone(f.libraryItems),
    albums: structuredClone(f.albums),
    saved: structuredClone(f.savedAlbums),
    history: structuredClone(f.historyRows),
    backlog: hello.backlog,
    schedule: f.scheduleNightly,
    scheduleNext: f.scheduleNext,
    status: hello.status,
    queue: [],
    currentTracks: [],
    nextRunId: 42,
  };
  if (scenario === 'setup') atSetupStep(data, step);
  if (scenario === 'new') justSetUp(data);
  return data;
}

function readyChecklist(): Checklist {
  return { ...f.checklistM1, ready: true, rows: f.checklistM1.rows.map(fixRow) };
}

/**
 * The wizard midway: every step before `step` done, `step` and the ones after it not yet. As in the
 * controller, steps 2 to 4 and 6 follow facts (installed, logged in, checklist, storage); step 5
 * is marked by its device check, and 7 and 8 by their writes.
 */
function atSetupStep(data: WorldData, step: SetupStepId) {
  const index = f.SETUP_STEP_IDS.indexOf(step);
  const before = (id: SetupStepId) => f.SETUP_STEP_IDS.indexOf(id) < index;
  data.tosAt = before('tos') ? '2026-11-15T09:12:44Z' : null;
  data.client = before('client') ? (before('login') ? f.clientLoggedIn : f.clientLoggedOut) : f.clientNotInstalled;
  data.checklist = before('client_settings') ? readyChecklist() : f.checklistM1;
  data.connection = before('webapi') ? f.connectionOk : f.connectionNotConfigured;
  // Step 6 is done as soon as /music is mounted and writable (controller setup.py), so being at
  // step 6 means it isn't: the red alert shows until POST /__mock/storage {"mounted": true}.
  data.storage = step === 'output' ? f.storageNotMounted : f.storageOk;
  data.backlog = before('webapi') ? f.backlog : null;
  data.albums = [];
  data.saved = structuredClone([...f.savedAlbums, ...f.albums.map(savedFromAlbum)]);
  data.history = [];
  data.schedule = f.scheduleManual;
  for (const id of ['webapi', 'playlists', 'albums'] as const) if (before(id)) data.manualDone.add(id);
}

/** Set up a moment ago (the `new` scenario): no run yet, no schedule, no album added. */
function justSetUp(data: WorldData) {
  data.history = [];
  data.schedule = f.scheduleManual;
  data.albums = [];
  data.saved = structuredClone([...f.savedAlbums, ...f.albums.map(savedFromAlbum)]);
  data.library = data.library.map((item) => ({
    ...item,
    recorded: 0,
    new: item.item_access ? item.total : null,
    last_backup_at: null,
    status: item.tracked ? 'never_backed_up' : 'not_tracked',
  }));
}

/**
 * A queue entry as the run page lists it. `endedAt` is null while the run goes on: then an item
 * still waiting hasn't started, and none has an end time.
 */
function runItemOf(q: QueueItem, order: number, startedAt: string, endedAt: string | null): RunItem {
  const ran = !(q.state === 'stopped' || q.state === 'removed' || (endedAt === null && WAITING_STATES.includes(q.state)));
  return {
    item_id: q.item_id, kind: q.kind, name: q.name, cover: q.cover, order, state: q.state, badges: q.badges,
    counts: q.counts, bytes: q.counts.recorded * 3_400_000, started_at: ran ? startedAt : null,
    ended_at: ran ? endedAt : null, reason: q.reason, can_retry: q.counts.failed > 0,
  };
}

function savedFromAlbum(album: Album): SavedAlbum {
  return {
    id: album.id, uri: album.uri, name: album.name, artist: album.artist, year: album.year,
    cover: null, total: album.total, saved_at: album.added_at,
  };
}

/** A checklist row as it is once you've changed the setting in the client. */
function fixRow(row: Checklist['rows'][number]): Checklist['rows'][number] {
  if (row.check === 'auto') return { ...row, state: 'ok' };
  if (row.check === 'confirm') return { ...row, confirmed: true };
  return row;
}

const CURRENT_STATES: ItemState[] = ['planning', 'preflight', 'preparing', 'starting', 'playing', 'finishing'];
/** Waiting in the queue: Up next, or re-queued after an interruption. */
const WAITING_STATES: ItemState[] = ['up_next', 'interrupted'];

/**
 * After the last item, before run.state idle: the controller updates the backlog and writes the
 * History row. Meanwhile the queue's last rows (Done, Carried over, Stopped) stay on the Dashboard.
 */
const WRAP_UP_MS = 1500;
/** Client not running: how long the restarted client takes to show up again. */
const CLIENT_RESTART_MS = 3000;
/** Client not running: how long a run waits for the device after the restart (60 s in the controller). */
const DEVICE_WAIT_MS = 6000;

/** Thrown inside a simulation when the world is reset under it. */
class Cancelled extends Error {}

export type World = ReturnType<typeof createWorld>;

export interface WorldOptions {
  /** Runs the simulations this many times faster: 10 makes a 6 s track last 0.6 s. Default 1. */
  speed?: number;
}

export function createWorld(hub: Hub, scenario: f.Scenario = 'idle', options: WorldOptions = {}) {
  const speed = options.speed && options.speed > 0 ? options.speed : 1;
  let data = initialData(scenario);
  /** Bumped on reset: simulations started before it stop at their next wait. */
  let generation = 0;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  let levelTimer: ReturnType<typeof setInterval> | null = null;

  // Run control, read by the run simulation.
  let stopMode: 'after_track' | 'now' | null = null;
  /** Reads stopMode fresh. (Inside an async function TypeScript keeps a narrowed value across an
      `await`, though a REST call can change it meanwhile.) */
  const stopping = () => stopMode;
  /**
   * What cuts the playing track short, set by a mock control: playback moves to a phone
   * (`takeover`), playback stalls for more than 20 s (`stall`), or a fatal Spytify error (`fatal`).
   */
  let interrupt: 'takeover' | 'stall' | 'fatal' | null = null;
  /** The schedule window is ending (POST /__mock/window-end): stop after this track, Carried over. */
  let windowEnding = false;
  let wakeUp: (() => void) | null = null;
  let resumeRun: (() => void) | null = null;
  /** Which item data.currentTracks belongs to, so a retried item keeps what it recorded. */
  let tracksFor: string | null = null;
  /**
   * While a run starts: the items it will queue once its pre-run check passes. As in the controller
   * (engine/run.py _drive), the queue is built only then, so until then the run has no items.
   */
  let planned: QueueItem[] = [];
  /** Back up now while the run starts: these go first once the queue is built (controller: pending_forced). */
  let pendingForced: string[] = [];

  /** Runs `fn` after `ms`, unless the world is reset first. */
  function later(ms: number, fn: () => void) {
    const timer = setTimeout(() => {
      timers.delete(timer);
      fn();
    }, ms / speed);
    timers.add(timer);
  }

  /** Waits `ms`, or less if stop now or a takeover wakes it. Throws Cancelled after a reset. */
  function wait(ms: number): Promise<void> {
    const gen = generation;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(done, ms / speed);
      timers.add(timer);
      wakeUp = done;
      function done() {
        clearTimeout(timer);
        timers.delete(timer);
        wakeUp = null;
        if (gen !== generation) reject(new Cancelled());
        else resolve();
      }
    });
  }

  function guard(promise: Promise<void>) {
    promise.catch((error: unknown) => {
      if (!(error instanceof Cancelled)) console.error('mock: simulation failed', error);
    });
  }

  // --- Setup -------------------------------------------------------------------------------------

  /** Works out each step's state from the facts, as the controller does. */
  function setup(): Setup {
    const live: Record<SetupStepId, boolean> = {
      tos: data.tosAt !== null,
      client: data.client.installed,
      login: data.client.logged_in,
      client_settings: data.checklist.ready,
      // Step 5 isn't a live fact: its device check marks it (checkDevices), as in the controller.
      // So after "Run setup again" it stays todo until step 5 reads the devices again.
      webapi: data.manualDone.has('webapi'),
      // As in the controller (setup.py): done once /music is mounted and writable.
      output: data.storage.ok,
      playlists: data.manualDone.has('playlists'),
      albums: data.manualDone.has('albums'),
      done: data.manualDone.has('done'),
    };
    // Done is sticky (controller setup.py): a step stays done until "Run setup again".
    for (const id of f.SETUP_STEP_IDS) if (live[id]) data.doneOnce.add(id);
    const facts = Object.fromEntries(f.SETUP_STEP_IDS.map((id) => [id, data.doneOnce.has(id)])) as Record<SetupStepId, boolean>;
    const first = f.SETUP_STEP_IDS.find((id) => !facts[id]) ?? null;
    if (first === null) data.setupCompleted = true;
    return {
      steps: f.SETUP_STEP_IDS.map((id) => ({
        id,
        state: facts[id]
          ? 'done'
          : id === 'client' && data.client.install.state === 'failed'
            ? 'failed'
            : id === first
              ? 'active'
              : 'todo',
      })),
      first_unfinished: first,
      completed: data.setupCompleted,
      tos_acknowledged_at: data.tosAt,
    };
  }

  function publishSetup() {
    hub.publish('setup.state', setup());
  }

  function setClient(client: ClientStatus) {
    data.client = client;
    hub.publish('client.status', client);
    publishSetup();
  }

  function setConnection(connection: Connection) {
    data.connection = connection;
    hub.publish('connection', connection);
    publishSetup();
  }

  // --- The client install and login ---------------------------------------------------------------

  async function simulateInstall() {
    const started = new Date().toISOString();
    const total = 179_306_496;
    let install: ClientInstall = {
      ...f.installNotStarted,
      state: 'installing',
      version: '1.3.4.258',
      started_at: started,
    };
    const step = async (patch: Partial<ClientInstall>, line: string | null, ms: number) => {
      install = { ...install, ...patch, log_tail: line ? [...install.log_tail, line].slice(-50) : install.log_tail };
      data.client = { ...data.client, install };
      hub.publish('client.install', { ...install, log_line: line });
      await wait(ms);
    };
    await step({ phase: 'release', progress: 0.02 }, 'Checking InRelease with gpgv', 600);
    await step({ progress: 0.04 }, 'InRelease signature OK', 400);
    await step({ phase: 'packages', progress: 0.06 }, 'Packages sha256 OK', 400);
    for (let i = 1; i <= 10; i++) {
      const done = Math.round((total * i) / 10);
      await step(
        { phase: 'download', progress: 0.06 + 0.74 * (i / 10), bytes_done: done, bytes_total: total },
        i === 1 ? 'Downloading spotify-client_1.3.4.258_amd64.deb' : null,
        500,
      );
    }
    await step({ phase: 'unpack', progress: 0.85 }, '.deb sha256 OK; unpacking', 900);
    await step({ phase: 'libraries', progress: 0.95 }, 'ldd check passed', 500);
    await step({ phase: 'switch', progress: 1 }, 'switched current to 1.3.4.258', 300);
    install = { ...install, state: 'installed', phase: null, progress: null, finished_at: new Date().toISOString() };
    hub.publish('client.install', { ...install, log_line: null });
    setClient({ ...data.client, installed: true, running: true, version: '1.3.4.258', restartable: true, install });

    // The QR scan: the mock logs in by itself a few seconds later.
    await wait(4000);
    world.setLoggedIn(true);
  }

  /**
   * After a login during setup, the client's settings "get changed" a few seconds later, as you
   * would change them (fake mode's prefs turn tidy 30 s after its login). Until then step 4 shows
   * Needs change and Unknown; Re-check reads them again.
   */
  function tidyPrefsLater() {
    if (data.checklist.ready) return;
    later(5000, () => {
      data.checklist = withReady({ ...data.checklist, rows: data.checklist.rows.map((r) => (r.check === 'auto' ? fixRow(r) : r)) });
      publishSetup();
    });
  }

  // --- Runs ---------------------------------------------------------------------------------------

  function setStatus(patch: Partial<Status>) {
    data.status = { ...data.status, ...patch };
  }

  function publishRun(state: RunState, previous: RunState, patch: Partial<RunSummary> = {}) {
    const run = data.status.run;
    if (!run) return;
    const next: RunSummary = { ...run, ...patch, state };
    setStatus({ state, run: next, view_only: true });
    hub.publish('run.state', { ...next, previous_state: previous });
  }

  function publishQueue() {
    const run = data.status.run;
    if (run) hub.publish('run.queue', { run_id: run.id, queue: data.queue });
    syncQueued();
  }

  /**
   * Library items waiting in the run show the Queued pill (LibraryStatus `queued`); once they're no
   * longer waiting they go back to the status they had. The current one shows Recording
   * (setItemProgress).
   */
  function syncQueued() {
    const waiting = new Set(data.queue.filter((q) => WAITING_STATES.includes(q.state)).map((q) => q.item_id));
    for (const item of data.library) {
      if (waiting.has(item.id) && item.status !== 'queued' && item.status !== 'recording') {
        data.restingStatus.set(item.id, item.status);
        item.status = 'queued';
        hub.publish('library.item', item);
      } else if (!waiting.has(item.id) && item.status === 'queued') {
        item.status = data.restingStatus.get(item.id) ?? 'up_to_date';
        data.restingStatus.delete(item.id);
        hub.publish('library.item', item);
      }
    }
  }

  function setItem(itemId: string, patch: Partial<QueueItem>) {
    const index = data.queue.findIndex((q) => q.item_id === itemId);
    const old = data.queue[index];
    const run = data.status.run;
    if (!old || !run) return;
    const item = { ...old, ...patch };
    data.queue[index] = item;
    if (CURRENT_STATES.includes(item.state) || data.status.item?.item_id === itemId) setStatus({ item });
    hub.publish('item.state', { run_id: run.id, item, previous_state: old.state });
    syncQueued();
  }

  /** The item's counts as they are now (the queue entry, not a copy taken earlier). */
  function countsOf(itemId: string): QueueItem['counts'] {
    return data.queue.find((q) => q.item_id === itemId)?.counts ?? { recorded: 0, skipped: 0, failed: 0 };
  }

  /** events.md § Backlog: a `backlog` event after each item. */
  function bumpBacklog(tracks: number, ms: number) {
    if (!data.backlog) return;
    const b = data.backlog;
    const seconds = Math.round(ms / 1000);
    data.backlog = {
      ...b,
      tracks_recorded: Math.min(b.tracks_total, b.tracks_recorded + tracks),
      seconds_recorded: Math.min(b.seconds_total, b.seconds_recorded + seconds),
      seconds_left: Math.max(0, b.seconds_left - seconds),
      as_of: new Date().toISOString(),
    };
    hub.publish('backlog', data.backlog);
  }

  /** A track that's already on disk: the controller jumps over it, and Spytify skips the take. */
  async function simulateDuplicate(runId: number, item: QueueItem) {
    const take = `${Date.now()}-dup`;
    const trackId = f.fakeId('oldfavourite');
    // A row of its own in the live track table, before the planned ones (it has no position).
    const row: RunTrack = {
      position: null, track_id: trackId, title: 'Old Favourite', artists: ['fakename'], duration_ms: 5000,
      state: 'recording', size_bytes: null, reason: null, take_id: take,
    };
    data.currentTracks = [row, ...data.currentTracks];
    hub.publish('track.started', {
      run_id: runId, item_id: item.item_id, take_id: take, artist: 'fakename', title: 'Old Favourite',
      album: 'Elsewhere', length_ms: 5000, cover_url: null, track_id: trackId, position: null, planned: false,
    });
    setStatus({
      track: {
        take_id: take, track_id: trackId, title: 'Old Favourite', artist: 'fakename', album: 'Elsewhere',
        cover_url: null, length_ms: 5000, started_at: new Date().toISOString(), position: null,
      },
    });
    await wait(700);
    row.state = 'skipped_duplicate';
    const path = 'fakename/Elsewhere/01 - Old Favourite.m4a';
    hub.publish('track.skipped', {
      run_id: runId, item_id: item.item_id, take_id: take, reason: 'duplicate', path, track_id: trackId,
    });
    addTrackResult(runId, item.item_id, {
      position: null, track_id: trackId, title: 'Old Favourite', artists: ['fakename'], result: 'skipped',
      reason: 'duplicate', size_bytes: null, path, take_id: take, at: new Date().toISOString(),
    });
    const counts = countsOf(item.item_id);
    setItem(item.item_id, { counts: { ...counts, skipped: counts.skipped + 1 } });
    bumpCounters({ skipped_duplicate: 1 });
  }

  /** A track's result in the run, for its run page (GET /api/runs/{id}/items/{item}/tracks). */
  function addTrackResult(runId: number, itemId: string, result: TrackResult) {
    const key = `${runId}/${itemId}`;
    data.runTracks.set(key, [...(data.runTracks.get(key) ?? []), result]);
  }

  /** The result of a played track, from its row in the live track table. */
  function resultOf(track: RunTrack, result: TrackResult['result'], path: string | null): TrackResult {
    return {
      position: track.position, track_id: track.track_id, title: track.title, artists: track.artists, result,
      reason: track.reason, size_bytes: track.size_bytes, path, take_id: track.take_id, at: new Date().toISOString(),
    };
  }

  function setSession(state: SessionState) {
    const run = data.status.run;
    const item = data.status.item;
    setStatus({ session_state: state });
    if (run && item) hub.publish('session.state', { run_id: run.id, item_id: item.item_id, state });
  }

  function setLevel(on: boolean) {
    if (levelTimer) clearInterval(levelTimer);
    levelTimer = null;
    if (!on) return;
    let t = 0;
    levelTimer = setInterval(() => {
      t += 1;
      const peak = Math.min(-0.5, -4 + 3 * Math.sin(t / 3) - Math.random() * 3);
      const channel = (offset: number) => ({ peak_dbfs: peak - offset, rms_dbfs: peak - 14 - offset });
      hub.publish('level', { peak_dbfs: peak, rms_dbfs: peak - 14, channels: [channel(0), channel(0.4)] });
    }, 100);
  }

  /** Marks a Library item or album as recording, or back to a resting state. */
  /**
   * Marks a Library item or album as recording (with its progress), or, with `progress` null, puts
   * it back to rest once its turn ended: up to date or recorded, or Partial when tracks failed.
   */
  function setItemProgress(itemId: string, progress: LibraryItem['progress'], outcome?: 'partial') {
    const libraryItem = data.library.find((i) => i.id === itemId);
    if (libraryItem) {
      if (progress) Object.assign(libraryItem, { progress, status: 'recording' });
      else {
        Object.assign(libraryItem, {
          progress: null, status: outcome ?? 'up_to_date', last_backup_at: new Date().toISOString(),
          new: libraryItem.new === null ? null : 0,
          recorded: libraryItem.total !== null && !outcome ? libraryItem.total : libraryItem.recorded,
        });
      }
      hub.publish('library.item', libraryItem);
    }
    const albumItem = data.albums.find((a) => a.id === itemId);
    if (albumItem) {
      if (progress) Object.assign(albumItem, { progress, status: 'recording' });
      else if (outcome) Object.assign(albumItem, { progress: null, status: 'partial', recorded: Math.max(0, albumItem.total - 1), completed_at: null });
      else Object.assign(albumItem, { progress: null, status: 'recorded', recorded: albumItem.total, completed_at: new Date().toISOString() });
      hub.publish('album.item', albumItem);
    }
  }

  /** The default run: Liked Songs, a playlist that's up to date, and the queued albums. */
  function defaultQueue(): QueueItem[] {
    const liked = data.library.find((i) => i.id === 'liked');
    const upToDate = data.library.find((i) => i.status === 'up_to_date' && i.item_access);
    const queued = data.albums.filter((a) => a.status === 'queued' || a.status === 'partial');
    const items: QueueItem[] = [];
    if (liked) items.push(f.queueItem({ item_id: 'liked', kind: 'liked', name: liked.name, expect: { kind: 'new_tracks', count: 2 } }));
    if (upToDate) items.push(f.queueItem({ item_id: upToDate.id, name: upToDate.name, cover: upToDate.cover, expect: { kind: 'new_tracks', count: 0 } }));
    for (const a of queued) {
      items.push(f.queueItem({ item_id: a.id, kind: 'album', name: a.name, cover: a.cover, expect: { kind: 'tracks', count: 3 } }));
    }
    return carriedFirst(items);
  }

  function queueItemFor(id: string): QueueItem | null {
    const lib = data.library.find((i) => i.id === id);
    if (lib) return markCarried(f.queueItem({ item_id: id, kind: lib.kind, name: lib.name, cover: lib.cover, expect: { kind: 'new_tracks', count: 2 } }));
    const alb = data.albums.find((a) => a.id === id);
    if (alb) return markCarried(f.queueItem({ item_id: id, kind: 'album', name: alb.name, cover: alb.cover, expect: { kind: 'tracks', count: 3 } }));
    return null;
  }

  /** An item the last window cut off joins a run marked Carried over (the Up next row's pill). */
  function markCarried(q: QueueItem): QueueItem {
    if (!data.carriedOver.has(q.item_id) || q.badges.includes('carried_over_in')) return q;
    return { ...q, badges: [...q.badges, 'carried_over_in'] };
  }

  /** web-ui.md § Run order: carried-over items run first (the only order in M1). */
  function carriedFirst(items: QueueItem[]): QueueItem[] {
    const marked = items.map(markCarried);
    return [...marked.filter((q) => data.carriedOver.has(q.item_id)), ...marked.filter((q) => !data.carriedOver.has(q.item_id))];
  }

  function startRun(items: QueueItem[], trigger: RunSummary['trigger'], windowEnd: string | null = null) {
    const run: RunSummary = {
      id: data.nextRunId++,
      trigger,
      state: 'starting',
      started_at: new Date().toISOString(),
      window_end: windowEnd,
      paused_reason: null,
      stop_mode: null,
      counters: { recorded: 0, skipped_duplicate: 0, skipped_other: 0, failed: 0, bytes_added: 0 },
    };
    // The queue is built after the pre-run check (buildQueue), as in the controller: no items yet.
    data.queue = [];
    planned = items;
    pendingForced = [];
    data.currentTracks = [];
    tracksFor = null;
    stopMode = null;
    interrupt = null;
    windowEnding = false;
    setStatus({ state: 'starting', run, item: null, track: null, session_state: null, view_only: true });
    hub.publish('run.state', { ...run, previous_state: 'idle' });
    guard(simulateRun());
    return run;
  }

  /**
   * The run's queue, once the pre-run check passed (controller: engine/run.py _build_queue): the
   * items Back up now added while it started go first, then the planned ones. Goes out as run.queue.
   */
  function buildQueue() {
    const forced = pendingForced
      .map((id) => planned.find((q) => q.item_id === id) ?? queueItemFor(id))
      .filter((q): q is QueueItem => q !== null);
    data.queue = [...forced, ...planned.filter((q) => !pendingForced.includes(q.item_id))];
    planned = [];
    pendingForced = [];
    publishQueue();
  }

  function bumpCounters(patch: Partial<RunSummary['counters']>) {
    const run = data.status.run;
    if (!run) return;
    const counters = { ...run.counters };
    for (const [key, value] of Object.entries(patch) as [keyof typeof counters, number][]) counters[key] += value;
    publishRun(run.state, run.state, { counters });
  }

  async function simulateRun() {
    const gen = generation;
    await wait(1200);
    // The pre-run check: a client that isn't running is restarted once, and the run waits for its
    // device. If it doesn't show up, the run fails (web-ui.md § Warnings, Client not running).
    if (!data.client.running && !(await restartClientForRun()) && !stopping()) {
      await endRun('failed', 'device_missing');
      return;
    }
    // A stop while starting ends the run before its queue is built, so it has no items (controller:
    // engine/run.py _drive).
    if (stopping()) {
      await endRun(windowEnding ? 'window_ended' : 'stopped');
      return;
    }
    buildQueue();
    publishRun('running', 'starting');

    for (;;) {
      if (stopMode) break;
      const next = data.queue.find((q) => WAITING_STATES.includes(q.state));
      if (!next) break;
      const outcome = await simulateItem(next);
      if (outcome === 'paused') {
        // Wait for Resume (or Stop), then retry the same item.
        await new Promise<void>((resolve) => (resumeRun = resolve));
        resumeRun = null;
        // A reset wakes a paused run only to end it: its world is gone. Going on, its next wait
        // (taken after the reset) wouldn't throw, and it would end the new world's run.
        if (gen !== generation) throw new Cancelled();
        if (stopMode) break;
        publishRun('running', 'paused', { paused_reason: null });
      }
    }

    // Anything not run this time ends Stopped (web-ui.md § Running, Q18).
    for (const q of data.queue) {
      if (WAITING_STATES.includes(q.state)) setItem(q.item_id, { state: 'stopped', badges: [...q.badges, 'stopped'] });
    }
    await wait(WRAP_UP_MS);
    await endRun(windowEnding ? 'window_ended' : stopMode ? 'stopped' : 'completed');
  }

  /**
   * The client isn't running when a run starts (controller: engine/precheck.py): an `error` event
   * (client_restarted), one restart, then a wait for its device. True once it's back.
   */
  async function restartClientForRun(): Promise<boolean> {
    const run = data.status.run;
    const name = data.client.device_name;
    hub.publish('error', {
      source: 'controller', code: 'client_restarted', message: `The device ${name} wasn't listed, so the Spotify client was restarted.`,
      fatal: false, withdrawn: false, run_id: run?.id ?? null, item_id: null, facts: null,
    });
    if (!data.clientComesBack) {
      await wait(DEVICE_WAIT_MS);
      return false;
    }
    await wait(CLIENT_RESTART_MS);
    setClient(clientStarted());
    return true;
  }

  /** The client running again: logged in, if its login was kept (the user folder is there). */
  function clientStarted(): ClientStatus {
    const kept = data.client.login_signals.user_folder;
    return {
      ...data.client,
      running: true,
      logged_in: kept,
      login_signals: kept ? f.clientLoggedIn.login_signals : f.clientLoggedOut.login_signals,
    };
  }

  /** The tracks the current item plans to record, for GET /api/runs/current's track table. */
  function planTracks(id: string, planned: number): RunTrack[] {
    return Array.from({ length: planned }, (_, i) => ({
      position: i + 1,
      track_id: f.fakeId(`${id}t${i}`),
      title: ['Last Hours', 'Weightless', 'Paper Planes', 'Hollow', 'Glass Rivers'][i % 5] ?? `Track ${i + 1}`,
      artists: ['fakename'],
      duration_ms: 6000 + i * 1500,
      state: 'pending',
      size_bytes: null,
      reason: null,
      take_id: null,
    }));
  }

  /** Plays one item. Returns 'paused' after a takeover. */
  async function simulateItem(item: QueueItem): Promise<'done' | 'paused'> {
    const id = item.item_id;
    const run = data.status.run;
    if (!run) return 'done';
    const attempt = item.state === 'interrupted' ? 2 : 1;
    // Its turn came: it isn't waiting from the last window any more (controller: engine/queue.py).
    data.carriedOver.delete(id);
    for (const phase of ['planning', 'preflight', 'preparing'] as const) {
      setItem(id, { state: phase, attempt });
      await wait(350);
      // A stop before any track plays ends the item at once.
      if (stopping()) {
        setItem(id, { state: 'stopped', badges: [...item.badges, 'stopped'] });
        return 'done';
      }
    }

    const planned = item.expect.kind === 'new_tracks' ? (item.expect.count ?? 2) : (item.expect.count ?? 3);
    if (planned === 0) {
      setItem(id, { state: 'up_to_date', planned: 0, badges: [...item.badges, 'up_to_date'] });
      return 'done';
    }

    setItem(id, { state: 'starting', planned });
    setItemProgress(id, { run_id: run.id, state: 'starting', recorded: 0, planned });
    if (tracksFor !== id) data.currentTracks = planTracks(id, planned);
    tracksFor = id;
    await wait(400);
    setItem(id, { state: 'playing' });
    setSession('waiting');
    await wait(600);
    if (item.kind === 'liked' && attempt === 1) await simulateDuplicate(run.id, item);

    let recorded = countsOf(id).recorded;
    let recordedNow = 0;
    let recordedMs = 0;
    let fatal = false;
    for (const track of data.currentTracks) {
      if (track.state !== 'pending') continue;
      if (stopMode === 'now') break;
      const take = `${Date.now()}`;
      track.state = 'recording';
      track.take_id = take;
      const length = track.duration_ms ?? 6000;
      hub.publish('track.started', {
        run_id: run.id, item_id: id, take_id: take, artist: track.artists[0] ?? '', title: track.title,
        album: item.kind === 'album' ? item.name : 'Elsewhere', length_ms: length, cover_url: null,
        track_id: track.track_id, position: track.position, planned: true,
      });
      setStatus({
        track: {
          take_id: take, track_id: track.track_id, title: track.title, artist: track.artists[0] ?? '',
          album: item.name, cover_url: null, length_ms: length, started_at: new Date().toISOString(), position: track.position,
        },
      });
      setSession('recording');
      setLevel(true);
      await wait(length);
      setLevel(false);

      const cut = interrupt;
      interrupt = null;
      if (cut === 'takeover') {
        // In the controller's order (engine/run.py _apply_report): Spytify's session.state first
        // (relayed while the item runs), then item.state interrupted, run.state paused, and only
        // then device.moved. The UI drops a playback-moved alert while the run says running, so
        // device.moved must come once the run is paused.
        track.state = 'pending';
        setSession('paused');
        setItem(id, { state: 'interrupted', reason: "Playback moved to Lorne's iPhone." });
        publishRun('paused', 'running', { paused_reason: 'device_moved' });
        hub.publish('device.moved', {
          run_id: run.id,
          item_id: id,
          device: { id: 'f6e5d4c3b2a1', name: "Lorne's iPhone", type: 'Smartphone' },
          discarded_take_id: take,
        });
        return 'paused';
      }
      if (cut === 'stall' && attempt === 1) {
        // web-ui.md § Queue: "Interrupted · will retry", re-queued at the end of the queue.
        track.state = 'pending';
        setSession('idle');
        setStatus({ track: null });
        setItemProgress(id, null);
        setItem(id, { state: 'interrupted', reason: 'Playback paused for more than 20 s.' });
        const moved = data.queue.find((q) => q.item_id === id);
        if (moved) data.queue = [...data.queue.filter((q) => q !== moved), moved];
        publishQueue();
        return 'done';
      }
      if (cut === 'stall' || cut === 'fatal' || stopping() === 'now') {
        // A second stall, a fatal error, or Stop now: the take is lost and the item ends.
        track.state = 'failed';
        track.reason = cut === 'stall' ? 'interrupted' : cut === 'fatal' ? 'recorder_error' : 'discarded';
        addTrackResult(run.id, id, resultOf(track, 'failed', null));
        fatal = cut !== null;
        if (fatal) bumpItemFailed(id);
        break;
      }

      const bytes = 2_855_116 + Math.round(Math.random() * 1_000_000);
      // An album's second track comes out too quiet: no alert, a failed track (web-ui.md § Warnings).
      const lowVolume = item.kind === 'album' && planned >= 3 && track.position === 2 && attempt === 1;
      const path = `fakename/${item.name}/${String(track.position).padStart(2, '0')} - ${track.title}.m4a`;
      hub.publish('track.finished', {
        run_id: run.id, item_id: id, take_id: take, track_id: track.track_id,
        path, duration_ms: length, bytes, counted: !lowVolume, low_volume: lowVolume, pause_fade: false, partial: false,
      });
      if (lowVolume) {
        track.state = 'failed';
        track.reason = 'low_volume';
        addTrackResult(run.id, id, resultOf(track, 'failed', null));
        bumpItemFailed(id);
      } else {
        track.state = 'recorded';
        track.size_bytes = bytes;
        addTrackResult(run.id, id, resultOf(track, 'recorded', path));
        recorded += 1;
        recordedNow += 1;
        recordedMs += length;
        setItem(id, { counts: { ...countsOf(id), recorded } });
        setItemProgress(id, { run_id: run.id, state: 'playing', recorded, planned });
        bumpCounters({ recorded: 1, bytes_added: bytes });
      }
      if (stopping() === 'after_track') break;
    }

    setSession('stopping');
    setItem(id, { state: 'finishing' });
    // While a stop is going, the run stays `stopping` (the header says "Stopping after this track…").
    if (!stopMode) publishRun('finishing', 'running');
    await wait(1500);
    setSession('idle');
    setStatus({ track: null });
    const failed = countsOf(id).failed;
    const badges = data.queue.find((q) => q.item_id === id)?.badges ?? [];
    if (windowEnding) {
      setItem(id, { state: 'carried_over', badges: [...badges, 'carried_over_out'] });
    } else if (stopMode) {
      setItem(id, { state: 'stopped', badges: [...badges, 'stopped'] });
    } else if (fatal || failed > 0) {
      const reason = fatal ? 'Spytify error: the capture failed.' : `${failed} track${failed === 1 ? '' : 's'} failed: low volume`;
      setItem(id, { state: 'partial', reason, badges: attempt === 2 ? [...badges, 'interrupted_twice'] : badges });
    } else {
      setItem(id, { state: 'done', badges: attempt === 2 ? [...badges, 'interrupted_retried'] : badges });
    }
    setItemProgress(id, null, failed > 0 || fatal ? 'partial' : undefined);
    bumpBacklog(recordedNow, recordedMs);
    if (!stopMode) publishRun('running', 'finishing');
    return 'done';
  }

  /** One more failed track on the current item and the run. */
  function bumpItemFailed(id: string) {
    const counts = countsOf(id);
    setItem(id, { counts: { ...counts, failed: counts.failed + 1 } });
    bumpCounters({ failed: 1 });
  }

  /** The run ends. `failed` comes only from the pre-run check here, so no item ran. */
  async function endRun(outcome: 'completed' | 'stopped' | 'window_ended' | 'failed', reason: string | null = null) {
    const run = data.status.run;
    if (!run) return;
    const previous = run.state;
    setLevel(false);
    const ended = new Date().toISOString();
    const row: HistoryRow = {
      id: run.id,
      kind: 'run',
      trigger: run.trigger,
      started_at: run.started_at,
      ended_at: ended,
      duration_s: Math.round((Date.parse(ended) - Date.parse(run.started_at)) / 1000),
      outcome: outcome === 'completed' && run.counters.failed > 0 ? 'completed_with_issues' : outcome,
      counters: run.counters,
      reason,
      window: run.window_end ? { start: run.started_at, end: run.window_end } : null,
    };
    data.history.unshift(row);
    // The run page (GET /api/runs/{id}) shows this run's own items. A run that ended in its pre-run
    // check (failed, or stopped while starting) has none: the queue is built after the check.
    data.runItems.set(run.id, data.queue.map((q, i) => runItemOf(q, i + 1, run.started_at, ended)));
    // The items this window's end cut off wait for the next run (only the last such window counts).
    if (outcome === 'window_ended') data.carriedOver = new Set(data.queue.filter((q) => q.state === 'carried_over').map((q) => q.item_id));
    hub.publish('run.state', { ...run, state: 'idle', previous_state: previous });
    data.status = f.statusIdle;
    data.queue = [];
    planned = [];
    pendingForced = [];
    data.currentTracks = [];
    syncQueued();
    hub.publish('run.finished', { run: row });
  }

  // --- The public face, used by the REST routes and the /__mock controls --------------------------

  const world = {
    get data() {
      return data;
    },
    setup,
    /** The live socket's side, for the /__mock socket controls (drop, restart, gap, slow). */
    hub,
    /** The "controller process": changes when the mock restarts (hub.restart). */
    bootId: () => hub.bootId(),
    hello(): Hello {
      return {
        boot_id: hub.bootId(),
        version: f.VERSION,
        setup: setup(),
        status: data.status,
        connection: data.connection,
        client: data.client,
        backlog: data.backlog,
      };
    },

    /**
     * Starts over in another scenario, as a restarted controller: a new boot_id, and open sockets are
     * closed (1012), so they reconnect and get a new hello.
     */
    reset(next: f.Scenario, step?: SetupStepId) {
      generation += 1;
      wakeUp?.();
      resumeRun?.();
      for (const timer of timers) clearTimeout(timer);
      timers.clear();
      setLevel(false);
      data = initialData(next, step);
      planned = [];
      pendingForced = [];
      hub.restart();
      if (next === 'running' || next === 'paused') {
        // A scheduled run in a window that ends in 6 h ("stops by 07:00"). Liked Songs was cut off
        // by the previous window, so it comes first, carried over (web-ui.md § Run order).
        data.carriedOver.add('liked');
        startRun(defaultQueue(), 'scheduled', new Date(Date.now() + 6 * 3_600_000).toISOString());
        // Paused: the run starts, then playback "moves to a phone" once a track is recording (about
        // 4 s in; tried again until one is).
        if (next === 'paused') {
          const takeOver = () => {
            if (!world.takeover()) later(250, takeOver);
          };
          later(4000, takeOver);
        }
      }
    },

    acknowledgeTos() {
      data.tosAt ??= new Date().toISOString();
      publishSetup();
      return setup();
    },
    startInstall() {
      guard(simulateInstall());
      return data.client.install;
    },
    failInstall() {
      const install = { ...f.installFailed, started_at: new Date().toISOString() };
      setClient({ ...data.client, installed: false, install });
    },
    restartClient() {
      setClient(clientStarted());
      return data.client;
    },
    /**
     * The client stops, or starts again (mock control). Stopped, it has no window, so it doesn't
     * count as logged in, but its login is kept (as in the controller). The next run restarts it;
     * `comesBack: false` keeps its device away, so that run fails (web-ui.md § Warnings).
     */
    setClientRunning(running: boolean, comesBack = true) {
      data.clientComesBack = comesBack;
      if (running) setClient(clientStarted());
      else setClient({ ...data.client, running: false, logged_in: false, login_signals: { mpris: false, user_folder: data.client.login_signals.user_folder, window_title: null } });
      return data.client;
    },
    /**
     * GET /api/client/checklist: reads the client's settings again. It only reads, as the
     * controller does: the settings change by themselves after a login in the wizard
     * (tidyPrefsLater), or through POST /__mock/checklist.
     */
    readChecklist() {
      data.checklist = { ...data.checklist, checked_at: new Date().toISOString() };
      publishSetup();
      return data.checklist;
    },
    /**
     * The client's settings change (mock control): `rows` sets Auto rows' states and Confirm rows'
     * ticks by row id; `ready` fixes every Auto row and ticks every blocking Confirm row.
     */
    setChecklist(change: { rows?: Record<string, ChecklistRowValue>; ready?: boolean }) {
      const rows = data.checklist.rows.map((r) => {
        if (change.ready) return r.blocker ? fixRow(r) : r.check === 'auto' ? fixRow(r) : r;
        const value = change.rows?.[r.id];
        if (value === undefined) return r;
        if (r.check === 'auto' && typeof value === 'string') return { ...r, state: value };
        if (r.check === 'confirm' && typeof value === 'boolean') return { ...r, confirmed: value };
        return r;
      });
      data.checklist = withReady({ ...data.checklist, rows });
      publishSetup();
      return data.checklist;
    },
    confirm(ticks: Record<string, boolean>) {
      const rows = data.checklist.rows.map((r) =>
        r.check === 'confirm' && r.id in ticks ? { ...r, confirmed: Boolean(ticks[r.id]) } : r,
      );
      data.checklist = withReady({ ...data.checklist, rows });
      publishSetup();
      return data.checklist;
    },
    setClientId(masked: string) {
      setConnection({ ...f.connectionNotConfigured, state: 'disconnected', client_id_masked: masked });
      return data.connection;
    },
    connect() {
      setConnection({ ...f.connectionOk, authorized_at: new Date().toISOString(), expires_at: new Date(Date.now() + 182 * 86_400_000).toISOString() });
      return data.connection;
    },
    disconnect() {
      setConnection({ ...data.connection, state: 'disconnected', display_name: null, user_id: null, authorized_at: null, expires_at: null, scopes: [] });
      return data.connection;
    },
    /** The Web API connection changes while the app is open (mock control): the banner follows. */
    setConnectionState(state: Connection['state']) {
      if (state === 'disconnected') return world.disconnect();
      const connection = {
        ok: f.connectionOk,
        expiring: f.connectionExpiring,
        expired: f.connectionExpired,
        not_configured: f.connectionNotConfigured,
      }[state];
      setConnection(connection);
      return data.connection;
    },
    markDone(step: SetupStepId) {
      data.manualDone.add(step);
      publishSetup();
    },
    /** For steps with no endpoint of their own: marks the active step done. */
    nextStep() {
      const first = setup().first_unfinished;
      if (first) world.markDone(first);
      return setup();
    },
    /** POST /api/setup/complete: steps 7 to 9 done, once steps 1 to 6 are (contract § completeSetup). */
    completeSetup(): Setup | { error: true; steps: SetupStepId[] } {
      const unfinished = setup().steps.slice(0, 6).filter((s) => s.state !== 'done').map((s) => s.id);
      if (unfinished.length > 0) return { error: true, steps: unfinished };
      for (const step of ['playlists', 'albums', 'done'] as const) data.manualDone.add(step);
      publishSetup();
      return setup();
    },
    restartSetup(): Setup {
      data.manualDone.clear();
      // Steps 2 to 9 go back to todo. The Terms notice stays acknowledged.
      data.doneOnce = new Set(data.tosAt ? ['tos'] : []);
      data.setupCompleted = false;
      // As in the controller (setup.py restart): the answer shows the steps just reset, so the wizard
      // reopens at step 2. The live checks follow at once, with their own setup.state: the facts
      // (client, login, checklist, storage) turn steps 2 to 4 and 6 done again. Step 5 waits for its
      // device check (GET /api/spotify/devices, which step 5's page reads); 7 to 9 are asked again.
      const reset: Setup = {
        steps: f.SETUP_STEP_IDS.map((id) => ({
          id,
          state: id === 'tos' && data.tosAt ? 'done' : id === 'client' ? 'active' : 'todo',
        })),
        first_unfinished: 'client',
        completed: false,
        tos_acknowledged_at: data.tosAt,
      };
      hub.publish('setup.state', reset);
      publishSetup();
      return reset;
    },

    runActive: () => data.status.state !== 'idle',
    startRunNow(ids?: string[]) {
      if (!ids) return startRun(defaultQueue(), 'run_now');
      const items = ids.map(queueItemFor).filter((q): q is QueueItem => q !== null);
      return startRun(carriedFirst(items), 'run_now');
    },
    /**
     * Back up now during a run (contract: RunCreated.added): the items go right after the current
     * one, in the given order; ones already waiting move there. The current item, and items that
     * already ended or were removed in this run, are left out (a run has one row per item).
     * Returns the ids now waiting there: empty when nothing was added.
     */
    addToRun(ids: string[]) {
      if (data.status.state === 'starting') {
        // The queue isn't built yet: they go first once it is (controller: _force_items).
        const added = ids.filter((id, i) => ids.indexOf(id) === i && !pendingForced.includes(id));
        pendingForced = [...pendingForced, ...added];
        return added;
      }
      const inRun = (id: string) => data.queue.find((q) => q.item_id === id);
      const wanted = ids.filter((id, i) => {
        const queued = inRun(id);
        return ids.indexOf(id) === i && (!queued || WAITING_STATES.includes(queued.state));
      });
      const moving = wanted.map((id) => inRun(id) ?? queueItemFor(id)).filter((q): q is QueueItem => !!q);
      const rest = data.queue.filter((q) => !wanted.includes(q.item_id));
      const currentIndex = rest.findIndex((q) => CURRENT_STATES.includes(q.state));
      rest.splice(currentIndex + 1, 0, ...moving);
      data.queue = rest;
      publishQueue();
      return moving.map((q) => q.item_id);
    },
    /** An Up next item leaves the run: it stays in the queue as `removed`, as in the controller. */
    removeFromRun(id: string): 'ok' | 'not_found' | 'item_is_current' {
      if (pendingForced.includes(id)) {
        pendingForced = pendingForced.filter((other) => other !== id);
        return 'ok';
      }
      const item = data.queue.find((q) => q.item_id === id);
      if (!item) return 'not_found';
      if (CURRENT_STATES.includes(item.state)) return 'item_is_current';
      if (!WAITING_STATES.includes(item.state)) return 'not_found';
      setItem(id, { state: 'removed', badges: [...item.badges, 'removed'] });
      publishQueue();
      return 'ok';
    },
    stop(mode: 'after_track' | 'now') {
      const run = data.status.run;
      if (!run) return null;
      stopMode = mode === 'now' || stopMode === 'now' ? 'now' : 'after_track';
      publishRun('stopping', run.state, { stop_mode: stopMode });
      // As in the controller: the session says `stopping` while the last track records to its end.
      if (data.status.session_state === 'recording') setSession('stopping');
      if (mode === 'now') wakeUp?.();
      resumeRun?.();
      return data.status.run;
    },
    resume() {
      const run = data.status.run;
      if (!run || run.state !== 'paused') return null;
      resumeRun?.();
      return data.status.run;
    },
    /**
     * Playback moves to another device mid-track (mock control): the take recording now is cut
     * short, and the run pauses at once (simulateItem sends the events, in the controller's order).
     * False unless a track is recording, as the controller sees a takeover only then.
     */
    takeover() {
      if (data.status.run?.state !== 'running' || data.status.session_state !== 'recording' || !data.status.track) return false;
      interrupt = 'takeover';
      wakeUp?.();
      return true;
    },
    /**
     * An `error` alert (mock control): Spytify's capture_silent by default, or any source and code
     * (events.md § Warnings): `controller`/`webapi` is the Web API warning, `controller`/
     * `context_changed` the autoplay one. `fatal` ends the current item Partial at the end of the
     * playing track, and the run moves on.
     */
    raiseError(options: { withdrawn?: boolean; fatal?: boolean; source?: 'spytify' | 'controller'; code?: SpytifyErrorCode | ControllerErrorCode; message?: string } = {}) {
      const run = data.status.run;
      const withdrawn = options.withdrawn === true;
      const fatal = options.fatal === true && !withdrawn;
      hub.publish('error', {
        source: options.source ?? 'spytify',
        code: options.code ?? 'capture_silent',
        message: withdrawn ? '' : (options.message ?? 'No audio for 10 s: the capture is silent.'),
        fatal,
        withdrawn,
        run_id: run?.id ?? null,
        item_id: data.status.item?.item_id ?? null,
        facts: null,
      });
      if (fatal && data.status.track) interrupt = 'fatal';
    },
    /**
     * Playback stalls for more than 20 s mid-item (mock control): at the end of the playing track
     * the item is Interrupted · will retry and moves to the end of the queue. A second stall of the
     * same item ends it Partial. False when nothing is recording.
     */
    stall() {
      if (!data.status.track || data.status.run?.state !== 'running') return false;
      interrupt = 'stall';
      return true;
    },
    /**
     * The schedule window ends (mock control): stop after this track; the cut item is Carried
     * over, the rest Stopped, and the run ends Window ended. False when no run is going.
     */
    windowEnd() {
      const run = data.status.run;
      if (!run || run.state === 'idle') return false;
      windowEnding = true;
      stopMode ??= 'after_track';
      publishRun('stopping', run.state, { stop_mode: stopMode });
      if (data.status.session_state === 'recording') setSession('stopping');
      resumeRun?.();
      return true;
    },
    /** The client logs in or out (mock control): wizard step 3, the Player, Held on the Dashboard. */
    setLoggedIn(loggedIn: boolean) {
      setClient({
        ...data.client,
        logged_in: loggedIn,
        login_signals: loggedIn
          ? { mpris: true, user_folder: true, window_title: 'Spotify Premium' }
          : { mpris: true, user_folder: false, window_title: 'Spotify' },
      });
      if (loggedIn) tidyPrefsLater();
      return data.client;
    },
    /**
     * Whether the container's client is a Connect device (mock control): step 5's second check. It
     * doesn't mark step 5 by itself: the next device check does (Retry on step 5's page).
     */
    setDeviceListed(listed: boolean) {
      data.deviceListed = listed;
    },
    /**
     * Step 5's device check, as the controller's connection.py _mark_step_five: once the devices are
     * read (GET /api/spotify/devices, or right after auth/finish), step 5 is done if ours is listed.
     */
    checkDevices(): boolean {
      if (data.deviceListed) world.markDone('webapi');
      return data.deviceListed;
    },
    /** How "Spotify" answers link previews and adds (mock control): 503 when not `ok`. */
    setSpotify(health: SpotifyHealth) {
      data.spotify = health;
    },
    /** The VNC screen is up or not (mock control); the server side is mock/vnc.ts. */
    setVncUp(up: boolean) {
      data.vncUp = up;
    },
    /** A click on the VNC login screen: stands in for scanning the QR code, as in fake mode. */
    vncClick() {
      if (data.client.installed && data.client.running && !data.client.logged_in) world.setLoggedIn(true);
    },
    setTracked(id: string, tracked: boolean) {
      const item = data.library.find((i) => i.id === id);
      if (!item) return null;
      if (item.status !== 'recording' && item.status !== 'queued') {
        Object.assign(item, { tracked, status: tracked ? (item.last_backup_at ? 'up_to_date' : 'never_backed_up') : 'not_tracked' });
      } else {
        item.tracked = tracked;
      }
      hub.publish('library.item', item);
      return item;
    },
    /** POST /api/library: a followed or linked playlist joins the Library, tracked. */
    addLibraryItem(item: LibraryItem) {
      data.library.push(item);
      hub.publish('library.item', item);
    },
    /** GET /api/library/summary, counted from the Library as it is now. */
    librarySummary(): LibrarySummary {
      const owned = data.library.filter((i) => i.kind === 'owned');
      return {
        owned_count: owned.length,
        owned_tracked: owned.filter((i) => i.tracked).length,
        liked_tracked: data.library.some((i) => i.kind === 'liked' && i.tracked),
        added_count: data.library.filter((i) => i.kind === 'followed' || i.kind === 'linked').length,
        tracked_count: data.library.filter((i) => i.tracked).length,
        auto_track_owned: data.settings.auto_track_owned,
      };
    },
    /**
     * PUT /api/settings. As in the controller: `auto_track_owned` marks step 7 done, and when it
     * changes, turning it on tracks every owned playlist; turning it off before setup is complete
     * (step 7's "I'll choose in the Library") untracks them and Liked Songs.
     */
    saveSettings(body: Partial<Settings>): Settings {
      const extension = { aac: 'm4a', mp3: 'mp3', flac: 'flac', wav: 'wav' } as const;
      const before = data.settings.auto_track_owned;
      const next = { ...data.settings, ...body };
      next.extension = extension[next.format];
      if (next.format === 'flac' || next.format === 'wav') next.bitrate = null;
      data.settings = next;
      if ('auto_track_owned' in body) {
        if (next.auto_track_owned !== before) {
          for (const item of data.library) {
            const owned = item.kind === 'owned' || (item.kind === 'liked' && !next.auto_track_owned);
            if (owned && (next.auto_track_owned || !data.setupCompleted)) world.setTracked(item.id, next.auto_track_owned);
          }
        }
        world.markDone('playlists');
      }
      return next;
    },
    /** GET /api/storage: the check runs, and step 6 turns done once it passes (controller setup.py). */
    storageChecked(): Storage {
      publishSetup();
      return data.storage;
    },
    /** GET /api/schedule/next, worked out from the schedule, the Library and why runs are held. */
    scheduleNext(): ScheduleNext {
      const manual = Object.values(data.schedule.hours).every((day) => day.length === 0);
      const state = data.connection.state;
      const held: ScheduleNext['held_reason'] = !data.setupCompleted
        ? 'setup_incomplete'
        : state === 'expired'
          ? 'connection_expired'
          : state === 'not_configured' || state === 'disconnected'
            ? 'not_connected'
            : // As in the controller: a client that isn't running isn't held (a run restarts it).
              !data.client.installed || (data.client.running && !data.client.logged_in)
              ? 'client_logged_out'
              : data.status.state === 'paused'
                ? 'run_paused'
                : null;
      return {
        ...data.scheduleNext,
        at: manual ? null : data.scheduleNext.at,
        window_end: manual ? null : data.scheduleNext.window_end,
        in_progress: manual ? false : data.scheduleNext.in_progress,
        playlists_to_check: data.library.filter((i) => i.tracked && i.status !== 'unavailable').length,
        albums_queued: data.albums.filter((a) => a.status === 'queued' || a.status === 'partial').length,
        held_reason: held,
      };
    },
    /**
     * The run going on as History lists it, as the controller does (history.py: "a run still going
     * included"): no end, no duration and no outcome yet; the counters so far. Null with no run.
     */
    liveHistoryRow(): HistoryRow | null {
      const run = data.status.run;
      if (!run) return null;
      return {
        id: run.id, kind: 'run', trigger: run.trigger, started_at: run.started_at, ended_at: null, duration_s: null,
        outcome: null, counters: run.counters, reason: null,
        window: run.window_end ? { start: run.started_at, end: run.window_end } : null,
      };
    },
    /** The run going on's items, for its run page (GET /api/runs/{id}). */
    liveRunItems(): RunItem[] {
      const run = data.status.run;
      return run ? data.queue.map((q, i) => runItemOf(q, i + 1, run.started_at, null)) : [];
    },
    /** The Last run card's issues for a run the mock ran: its items that didn't end cleanly. */
    issuesOf(runId: number): LastRun['issues'] {
      return (data.runItems.get(runId) ?? [])
        .filter((item) => item.reason && (item.state === 'partial' || item.state === 'failed'))
        .slice(0, 3)
        .map((item) => ({ item_id: item.item_id, name: item.name, message: item.reason ?? '' }));
    },
    /** History (mock control): empty ("No backups yet"), or the samples plus `older` older runs. */
    setHistory(rows: 'empty' | number) {
      data.history = rows === 'empty' ? [] : [...structuredClone(f.historyRows), ...f.olderHistory(rows)];
    },

    close() {
      generation += 1;
      for (const timer of timers) clearTimeout(timer);
      timers.clear();
      setLevel(false);
    },
  };

  if (scenario === 'running' || scenario === 'paused') world.reset(scenario);
  return world;
}

function withReady(checklist: Checklist): Checklist {
  const ready = checklist.rows.every(
    (r) => !r.blocker || (r.check === 'auto' ? r.state === 'ok' : r.check === 'confirm' ? r.confirmed === true : true),
  );
  return { ...checklist, ready };
}
