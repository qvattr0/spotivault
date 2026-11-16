// The mock controller's state, and the simulations that change it: the client install, the login
// and runs (item phases, tracks, the level meter, stop, takeover and resume). Every change goes out
// as the WS event events.md names, so the UI sees what it would see from the real controller.
//
// A run goes: run.state idle -> starting -> running, then per item: item.state planning ->
// preflight -> preparing -> starting -> playing, session.state waiting -> recording, track.started
// and track.finished per track with `level` 10 times a second while recording, then
// session.state stopping, item.state and run.state finishing, a `backlog` event, and on to the next
// item. Liked Songs first skips a track it already has (track.skipped, duplicate). At the end:
// run.state idle and run.finished.
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
  LibraryItem,
  QueueItem,
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
} from '../src/api/types.ts';
import type { Hello } from '../src/state/events.ts';

export interface WorldData {
  scenario: f.Scenario;
  tosAt: string | null;
  /** Steps that turn done on a write the contract doesn't name (see README § Mock backend). */
  manualDone: Set<SetupStepId>;
  /**
   * Setup was completed once. It stays complete when a fact behind a step changes later (the Web API
   * connection expires, the client logs out) until "Run setup again": otherwise an expired
   * connection would send every route back to the wizard, and the red banner could never show.
   */
  setupCompleted: boolean;
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

function initialData(scenario: f.Scenario): WorldData {
  const hello = f.helloFor(scenario);
  const doneBefore = (id: SetupStepId) =>
    hello.setup.steps.find((s) => s.id === id)?.state === 'done';
  return {
    scenario,
    tosAt: hello.setup.tos_acknowledged_at,
    manualDone: new Set((['output', 'playlists', 'albums', 'done'] as const).filter(doneBefore)),
    setupCompleted: hello.setup.completed,
    client: hello.client,
    checklist: hello.setup.completed ? { ...f.checklistM1, ready: true, rows: f.checklistM1.rows.map(fixRow) } : f.checklistM1,
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
}

/** A checklist row as it is once you've changed the setting in the client. */
function fixRow(row: Checklist['rows'][number]): Checklist['rows'][number] {
  if (row.check === 'auto') return { ...row, state: 'ok' };
  if (row.check === 'confirm') return { ...row, confirmed: true };
  return row;
}

const CURRENT_STATES: ItemState[] = ['planning', 'preflight', 'preparing', 'starting', 'playing', 'finishing'];

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
  let takeover = false;
  let wakeUp: (() => void) | null = null;
  let resumeRun: (() => void) | null = null;
  /** Which item data.currentTracks belongs to, so a retried item keeps what it recorded. */
  let tracksFor: string | null = null;

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
    const facts: Record<SetupStepId, boolean> = {
      tos: data.tosAt !== null,
      client: data.client.installed,
      login: data.client.logged_in,
      client_settings: data.checklist.ready,
      webapi: data.connection.state === 'ok' || data.connection.state === 'expiring',
      output: data.manualDone.has('output'),
      playlists: data.manualDone.has('playlists'),
      albums: data.manualDone.has('albums'),
      done: data.manualDone.has('done'),
    };
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
    setClient({ ...data.client, logged_in: true, login_signals: { mpris: true, user_folder: true, window_title: 'Spotify Premium' } });
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
    hub.publish('track.skipped', {
      run_id: runId, item_id: item.item_id, take_id: take, reason: 'duplicate',
      path: 'fakename/Elsewhere/01 - Old Favourite.m4a', track_id: trackId,
    });
    const counts = countsOf(item.item_id);
    setItem(item.item_id, { counts: { ...counts, skipped: counts.skipped + 1 } });
    bumpCounters({ skipped_duplicate: 1 });
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
  function setItemProgress(itemId: string, progress: LibraryItem['progress']) {
    const libraryItem = data.library.find((i) => i.id === itemId);
    if (libraryItem) {
      Object.assign(libraryItem, { progress, status: progress ? 'recording' : 'up_to_date', last_backup_at: progress ? libraryItem.last_backup_at : new Date().toISOString() });
      hub.publish('library.item', libraryItem);
    }
    const albumItem = data.albums.find((a) => a.id === itemId);
    if (albumItem) {
      Object.assign(albumItem, progress ? { progress, status: 'recording' } : { progress: null, status: 'recorded', recorded: albumItem.total, completed_at: new Date().toISOString() });
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
    return items;
  }

  function queueItemFor(id: string): QueueItem | null {
    const lib = data.library.find((i) => i.id === id);
    if (lib) return f.queueItem({ item_id: id, kind: lib.kind, name: lib.name, cover: lib.cover, expect: { kind: 'new_tracks', count: 2 } });
    const alb = data.albums.find((a) => a.id === id);
    if (alb) return f.queueItem({ item_id: id, kind: 'album', name: alb.name, cover: alb.cover, expect: { kind: 'tracks', count: 3 } });
    return null;
  }

  function startRun(items: QueueItem[], trigger: RunSummary['trigger']) {
    const run: RunSummary = {
      id: data.nextRunId++,
      trigger,
      state: 'starting',
      started_at: new Date().toISOString(),
      window_end: null,
      paused_reason: null,
      stop_mode: null,
      counters: { recorded: 0, skipped_duplicate: 0, skipped_other: 0, failed: 0, bytes_added: 0 },
    };
    data.queue = items;
    data.currentTracks = [];
    tracksFor = null;
    stopMode = null;
    takeover = false;
    setStatus({ state: 'starting', run, item: null, track: null, session_state: null, view_only: true });
    hub.publish('run.state', { ...run, previous_state: 'idle' });
    publishQueue();
    guard(simulateRun());
    return run;
  }

  function bumpCounters(patch: Partial<RunSummary['counters']>) {
    const run = data.status.run;
    if (!run) return;
    const counters = { ...run.counters };
    for (const [key, value] of Object.entries(patch) as [keyof typeof counters, number][]) counters[key] += value;
    publishRun(run.state, run.state, { counters });
  }

  async function simulateRun() {
    await wait(1200);
    publishRun('running', 'starting');

    for (;;) {
      if (stopMode) break;
      const next = data.queue.find((q) => q.state === 'up_next' || q.state === 'interrupted');
      if (!next) break;
      const outcome = await simulateItem(next);
      if (outcome === 'paused') {
        // Wait for Resume (or Stop), then retry the same item.
        await new Promise<void>((resolve) => (resumeRun = resolve));
        resumeRun = null;
        if (stopMode) break;
        publishRun('running', 'paused', { paused_reason: null });
      }
    }

    // Anything not run this time.
    for (const q of data.queue) {
      if (q.state === 'up_next' || q.state === 'interrupted') setItem(q.item_id, { state: 'stopped' });
    }
    await endRun(stopMode ? 'stopped' : 'completed');
  }

  /** Plays one item. Returns 'paused' after a takeover. */
  async function simulateItem(item: QueueItem): Promise<'done' | 'paused'> {
    const id = item.item_id;
    const run = data.status.run;
    if (!run) return 'done';
    const attempt = item.state === 'interrupted' ? 2 : 1;
    for (const phase of ['planning', 'preflight', 'preparing'] as const) {
      setItem(id, { state: phase, attempt });
      await wait(350);
      // A stop before any track plays ends the item at once.
      if (stopping()) {
        setItem(id, { state: 'stopped' });
        return 'done';
      }
    }

    const planned = item.expect.kind === 'new_tracks' ? (item.expect.count ?? 2) : (item.expect.count ?? 3);
    if (planned === 0) {
      setItem(id, { state: 'up_to_date', planned: 0, badges: ['up_to_date'] });
      return 'done';
    }

    setItem(id, { state: 'starting', planned });
    setItemProgress(id, { run_id: run.id, state: 'starting', recorded: 0, planned });
    if (tracksFor !== id) data.currentTracks = Array.from({ length: planned }, (_, i) => ({
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
    tracksFor = id;
    await wait(400);
    setItem(id, { state: 'playing' });
    setSession('waiting');
    await wait(600);
    if (item.kind === 'liked' && attempt === 1) await simulateDuplicate(run.id, item);

    let recorded = countsOf(id).recorded;
    let recordedNow = 0;
    let recordedMs = 0;
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

      if (takeover) {
        takeover = false;
        track.state = 'pending';
        setItem(id, { state: 'interrupted', reason: "Playback moved to Lorne's iPhone." });
        setSession('paused');
        publishRun('paused', 'running', { paused_reason: 'device_moved' });
        return 'paused';
      }
      if (stopping() === 'now') {
        track.state = 'failed';
        track.reason = 'discarded';
        break;
      }

      const bytes = 2_855_116 + Math.round(Math.random() * 1_000_000);
      track.state = 'recorded';
      track.size_bytes = bytes;
      recorded += 1;
      recordedNow += 1;
      recordedMs += length;
      hub.publish('track.finished', {
        run_id: run.id, item_id: id, take_id: take, track_id: track.track_id,
        path: `fakename/${item.name}/${String(track.position).padStart(2, '0')} - ${track.title}.m4a`,
        duration_ms: length, bytes, counted: true, low_volume: false, pause_fade: false, partial: false,
      });
      setItem(id, { counts: { ...countsOf(id), recorded } });
      setItemProgress(id, { run_id: run.id, state: 'playing', recorded, planned });
      bumpCounters({ recorded: 1, bytes_added: bytes });
      if (stopping() === 'after_track') break;
    }

    setSession('stopping');
    setItem(id, { state: 'finishing' });
    // While a stop is going, the run stays `stopping` (the header says "Stopping after this track…").
    if (!stopMode) publishRun('finishing', 'running');
    await wait(1500);
    setSession('idle');
    setStatus({ track: null });
    setItem(id, { state: stopMode ? 'stopped' : 'done' });
    setItemProgress(id, null);
    bumpBacklog(recordedNow, recordedMs);
    if (!stopMode) publishRun('running', 'finishing');
    return 'done';
  }

  async function endRun(outcome: 'completed' | 'stopped') {
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
      outcome,
      counters: run.counters,
      reason: null,
      window: null,
    };
    data.history.unshift(row);
    hub.publish('run.state', { ...run, state: 'idle', previous_state: previous });
    data.status = f.statusIdle;
    data.queue = [];
    data.currentTracks = [];
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
    reset(next: f.Scenario) {
      generation += 1;
      wakeUp?.();
      resumeRun?.();
      for (const timer of timers) clearTimeout(timer);
      timers.clear();
      setLevel(false);
      data = initialData(next);
      hub.restart();
      if (next === 'running' || next === 'paused') {
        startRun(defaultQueue(), 'scheduled');
        // Paused: the run starts, then playback "moves to a phone" once a track is recording.
        if (next === 'paused') later(4000, () => world.takeover());
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
      setClient({ ...data.client, running: true });
      return data.client;
    },
    recheck() {
      // Each Re-check finds one more setting fixed, as if you were changing them in the client.
      const index = data.checklist.rows.findIndex(
        (r) => r.check === 'auto' && r.state !== 'ok',
      );
      const rows = data.checklist.rows.map((r, i) => (i === index ? fixRow(r) : r));
      data.checklist = withReady({ ...data.checklist, rows, checked_at: new Date().toISOString() });
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
    restartSetup() {
      data.manualDone.clear();
      data.setupCompleted = false;
      // The live facts (client, login, connection) stay; steps 6–9 are asked again.
      publishSetup();
      return setup();
    },

    runActive: () => data.status.state !== 'idle',
    startRunNow(ids?: string[]) {
      if (!ids) return startRun(defaultQueue(), 'run_now');
      const items = ids.map(queueItemFor).filter((q): q is QueueItem => q !== null);
      return startRun(items, 'run_now');
    },
    /** Back up now during a run: the items go right after the current one. */
    addToRun(ids: string[]) {
      const items = ids.map(queueItemFor).filter((q): q is QueueItem => q !== null);
      const rest = data.queue.filter((q) => !ids.includes(q.item_id));
      const currentIndex = rest.findIndex((q) => CURRENT_STATES.includes(q.state));
      rest.splice(currentIndex + 1, 0, ...items);
      data.queue = rest;
      publishQueue();
      return items.map((q) => q.item_id);
    },
    removeFromRun(id: string): 'ok' | 'not_found' | 'item_is_current' {
      const item = data.queue.find((q) => q.item_id === id);
      if (!item) return 'not_found';
      if (CURRENT_STATES.includes(item.state)) return 'item_is_current';
      if (item.state !== 'up_next' && item.state !== 'interrupted') return 'not_found';
      data.queue = data.queue.filter((q) => q.item_id !== id);
      publishQueue();
      return 'ok';
    },
    stop(mode: 'after_track' | 'now') {
      const run = data.status.run;
      if (!run) return null;
      stopMode = mode === 'now' || stopMode === 'now' ? 'now' : 'after_track';
      publishRun('stopping', run.state, { stop_mode: stopMode });
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
    /** Playback moves to another device mid-track (mock control). */
    takeover() {
      const run = data.status.run;
      const item = data.status.item;
      if (!run || run.state !== 'running' || !item) return false;
      takeover = true;
      hub.publish('device.moved', {
        run_id: run.id,
        item_id: item.item_id,
        device: { id: 'f6e5d4c3b2a1', name: "Lorne's iPhone", type: 'Smartphone' },
        discarded_take_id: data.status.track?.take_id ?? null,
      });
      wakeUp?.();
      return true;
    },
    /** Spytify raises an error alert (mock control). */
    raiseError(withdrawn = false) {
      const run = data.status.run;
      hub.publish('error', {
        source: 'spytify',
        code: 'capture_silent',
        message: withdrawn ? '' : 'No audio for 10 s: the capture is silent.',
        fatal: false,
        withdrawn,
        run_id: run?.id ?? null,
        item_id: data.status.item?.item_id ?? null,
        facts: null,
      });
    },
    setTracked(id: string, tracked: boolean) {
      const item = data.library.find((i) => i.id === id);
      if (!item) return null;
      Object.assign(item, { tracked, status: tracked ? (item.last_backup_at ? 'up_to_date' : 'never_backed_up') : 'not_tracked' });
      hub.publish('library.item', item);
      return item;
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
