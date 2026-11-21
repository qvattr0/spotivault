// Sample data for the mock backend, the gallery and unit tests, typed against the contract
// (contracts/openapi.yaml through src/api/types.ts). If the contract changes shape, `npm run
// typecheck` fails here until the samples follow.
//
// Where the contract has a named example (components.examples), the sample copies it and says so.
// Names and numbers follow the drawings ("Lorne", "Late Night Drive", "Elsewhere").
//
// Browser-safe: no Node imports, so src/ can import it too (`@mock/fixtures.ts`).

import type {
  Album,
  Backlog,
  Checklist,
  ClientInstall,
  ClientStatus,
  Connection,
  Container,
  Devices,
  HistoryRow,
  ItemTrack,
  LastRun,
  LibraryItem,
  LibrarySummary,
  PlaylistPreview,
  QueueItem,
  RunSummary,
  SavedAlbum,
  Schedule,
  ScheduleNext,
  Settings,
  Setup,
  SetupStepId,
  Status,
  Storage,
  TrackState,
} from '../src/api/types.ts';
import type { Hello } from '../src/state/events.ts';

// --- Helpers -------------------------------------------------------------------------------------

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** An ISO time `ms` from now (negative for the past). */
export function fromNow(ms: number): string {
  return new Date(Date.now() + ms).toISOString();
}

/** A fake 22-character Spotify id made from a name: fakeId('chill mix') -> 'chillmix00000000000000'. */
export function fakeId(name: string): string {
  return (name.replace(/[^0-9A-Za-z]/g, '') + '0'.repeat(22)).slice(0, 22);
}

export const BOOT_ID = '7f3c9a10-5b2e-4c55-9d0e-2f1a6b7c8d90';
export const VERSION = '0.1.0';

// --- Setup ---------------------------------------------------------------------------------------

export const SETUP_STEP_IDS: SetupStepId[] = [
  'tos', 'client', 'login', 'client_settings', 'webapi', 'output', 'playlists', 'albums', 'done',
];

/** The setup state with every step before `active` done. `active: null` means setup is complete. */
export function setupAt(active: SetupStepId | null): Setup {
  const activeIndex = active === null ? SETUP_STEP_IDS.length : SETUP_STEP_IDS.indexOf(active);
  return {
    steps: SETUP_STEP_IDS.map((id, i) => ({
      id,
      state: i < activeIndex ? 'done' : i === activeIndex ? 'active' : 'todo',
    })),
    first_unfinished: active,
    completed: active === null,
    tos_acknowledged_at: activeIndex > 0 ? '2026-11-15T09:12:44Z' : null,
  };
}

/** contract: components.examples.SetupMidway */
export const setupMidway: Setup = setupAt('client_settings');
export const setupComplete: Setup = setupAt(null);

// --- The Spotify client --------------------------------------------------------------------------

export const installNotStarted: ClientInstall = {
  state: 'not_started',
  phase: null,
  progress: null,
  bytes_done: null,
  bytes_total: null,
  version: null,
  previous_version: null,
  error: null,
  log_tail: [],
  started_at: null,
  finished_at: null,
};

export const installInstalled: ClientInstall = {
  state: 'installed',
  phase: null,
  progress: null,
  bytes_done: null,
  bytes_total: null,
  version: '1.3.4.258',
  previous_version: null,
  error: null,
  log_tail: ['ldd check passed', 'switched current to 1.3.4.258'],
  started_at: '2026-11-15T09:13:02Z',
  finished_at: '2026-11-15T09:14:31Z',
};

export const installFailed: ClientInstall = {
  ...installInstalled,
  state: 'failed',
  phase: 'download',
  version: '1.3.4.258',
  error: { code: 'network', message: 'The download stopped: connection reset by peer.' },
  log_tail: ['InRelease signature OK', 'Packages sha256 OK', 'Downloading spotify-client_1.3.4.258.deb', 'curl: (56) Recv failure: Connection reset by peer'],
  finished_at: '2026-11-15T09:13:40Z',
};

/** contract: components.examples.ClientLoggedIn */
export const clientLoggedIn: ClientStatus = {
  installed: true,
  version: '1.3.4.258',
  running: true,
  logged_in: true,
  login_signals: { mpris: true, user_folder: true, window_title: 'Spotify Premium' },
  device_name: 'spotivault',
  restartable: true,
  install: installInstalled,
};

export const clientNotInstalled: ClientStatus = {
  installed: false,
  version: null,
  running: false,
  logged_in: false,
  login_signals: { mpris: false, user_folder: false, window_title: null },
  device_name: 'spotivault',
  restartable: false,
  install: installNotStarted,
};

export const clientLoggedOut: ClientStatus = {
  ...clientLoggedIn,
  logged_in: false,
  // A logged-out client shows its plain login window, titled "Spotify" (contract: logged_in).
  login_signals: { mpris: true, user_folder: false, window_title: 'Spotify' },
};

/** contract: components.examples.ChecklistM1 */
export const checklistM1: Checklist = {
  checked_at: '2026-11-15T09:20:00Z',
  ready: false,
  rows: [
    { id: 'crossfade', section: 'playback', required: 'Off', check: 'confirm', state: null, confirmed: true, blocker: true },
    { id: 'gapless', section: 'playback', required: 'Off', check: 'confirm', state: null, confirmed: true, blocker: true },
    { id: 'automix', section: 'playback', required: 'Off', check: 'auto', state: 'ok', confirmed: null, blocker: true },
    { id: 'autoplay', section: 'playback', required: 'Off', check: 'confirm', state: null, confirmed: false, blocker: false },
    { id: 'normalization', section: 'playback', required: 'Off', check: 'auto', state: 'needs_change', confirmed: null, blocker: true },
    { id: 'equalizer', section: 'playback', required: 'Off', check: 'auto', state: 'ok', confirmed: null, blocker: true },
    { id: 'mono', section: 'playback', required: 'Off', check: 'auto', state: 'ok', confirmed: null, blocker: true },
    { id: 'streaming_quality', section: 'audio_quality', required: 'Very high', check: 'auto', state: 'ok', confirmed: null, blocker: true },
    { id: 'auto_adjust_quality', section: 'audio_quality', required: 'Off', check: 'auto', state: 'unknown', confirmed: null, blocker: true },
    { id: 'volume', section: 'player', required: '100%', check: 'set_for_you', state: null, confirmed: null, blocker: false },
  ],
};

// --- The Spotify Web API connection --------------------------------------------------------------

/** contract: components.examples.ConnectionOk */
export const connectionOk: Connection = {
  state: 'ok',
  display_name: 'Lorne',
  user_id: 'lorne',
  client_id_masked: '0123…cdef',
  authorized_at: '2026-11-12T20:00:00Z',
  expires_at: '2027-05-12T20:00:00Z',
  scopes: [
    'playlist-read-private',
    'playlist-read-collaborative',
    'user-library-read',
    'user-read-playback-state',
    'user-modify-playback-state',
  ],
};

/** The yellow banner: within 4 weeks of `expires_at`. */
export const connectionExpiring: Connection = {
  ...connectionOk,
  state: 'expiring',
  authorized_at: fromNow(-170 * DAY),
  expires_at: fromNow(12 * DAY),
};

/** The red banner: scheduled runs are held. */
export const connectionExpired: Connection = {
  ...connectionOk,
  state: 'expired',
  authorized_at: fromNow(-190 * DAY),
  expires_at: fromNow(-7 * DAY),
};

export const connectionNotConfigured: Connection = {
  state: 'not_configured',
  display_name: null,
  user_id: null,
  client_id_masked: null,
  authorized_at: null,
  expires_at: null,
  scopes: [],
};

export const devices: Devices = {
  devices: [
    { id: 'a1b2c3d4e5f6', name: 'spotivault', type: 'Computer', is_active: false },
    { id: 'f6e5d4c3b2a1', name: "Lorne's iPhone", type: 'Smartphone', is_active: false },
  ],
  ours: { id: 'a1b2c3d4e5f6', name: 'spotivault', type: 'Computer', is_active: false },
  device_name: 'spotivault',
};

// --- Settings, storage, container ----------------------------------------------------------------

/** contract: components.examples.SettingsDefault */
export const settingsDefault: Settings = {
  format: 'aac',
  bitrate: 256,
  extension: 'm4a',
  write_m3u: true,
  save_spotify_covers: true,
  auto_track_owned: true,
  layout: { pattern: '{album_artist}/{album}/{track} - {title}', prefix: 'none', underscores: false, strip_accents: false },
};

export const storageOk: Storage = {
  music: { path: '/music', mounted: true, writable: true, free_bytes: 1_843_000_000_000, total_bytes: 3_998_000_000_000, error: null },
  config: { path: '/config', mounted: true, writable: true, free_bytes: 92_000_000_000, total_bytes: 250_000_000_000, error: null },
  min_free_bytes: 2_000_000_000,
  ok: true,
};

export const storageNotMounted: Storage = {
  ...storageOk,
  music: { path: '/music', mounted: false, writable: true, free_bytes: 41_000_000_000, total_bytes: 64_000_000_000, error: 'not_mounted' },
  ok: false,
};

export const container: Container = {
  device_name: 'spotivault',
  tz: 'Europe/Berlin',
  music_source: '/Music',
  umask: '022',
  ui_password_env_set: false,
  versions: { image: '0.1.0', controller: '0.1.0', spytify: '2.0.2', client: '1.3.4.258' },
};

// --- Library -------------------------------------------------------------------------------------

export const LATE_NIGHT_DRIVE = '3cEYpjA9oz9GiPac4AsH4n';

function playlist(item: Partial<LibraryItem> & Pick<LibraryItem, 'id' | 'name'>): LibraryItem {
  return {
    kind: 'owned',
    uri: `spotify:playlist:${item.id}`,
    owner: 'you',
    cover: `/api/library/${item.id}/cover?size=thumb`,
    cover_source: 'spotify',
    tracked: true,
    item_access: true,
    total: 40,
    recorded: 40,
    new: 0,
    last_backup_at: fromNow(-20 * HOUR),
    status: 'up_to_date',
    removable: false,
    progress: null,
    ...item,
  };
}

/** The Library, Liked Songs first. Covers every status pill and every kind. */
export const libraryItems: LibraryItem[] = [
  // contract: components.examples.LibraryList (Liked Songs)
  playlist({
    id: 'liked', kind: 'liked', uri: 'spotify:user:lorne:collection', name: 'Liked Songs', cover: null,
    cover_source: 'none', total: 2004, recorded: 1990, new: 14, last_backup_at: fromNow(-9 * HOUR), status: 'new',
  }),
  playlist({
    // A followed playlist: its total is /me/playlists' items.total, with no track list (contract:
    // LibraryItem.total), so it shows "32 / 35 recorded".
    id: LATE_NIGHT_DRIVE, kind: 'followed', name: 'Late Night Drive', owner: 'Lorde', item_access: false,
    total: 35, recorded: 32, new: null, removable: true, status: 'up_to_date',
  }),
  playlist({ id: fakeId('chillmix'), name: 'Chill Mix', total: 120, recorded: 84, new: 0, status: 'partial' }),
  playlist({ id: fakeId('indiefinds'), name: 'Indie Finds', total: 64, recorded: 64 }),
  playlist({ id: fakeId('sundayvinyl'), name: 'Sunday Vinyl', total: 31, recorded: 31, status: 'unavailable' }),
  playlist({ id: fakeId('roadtrip2026'), name: 'Road Trip 2026', total: 52, recorded: 0, new: 52, last_backup_at: null, status: 'never_backed_up' }),
  playlist({ id: fakeId('focus'), name: 'Focus', tracked: false, total: 88, recorded: 0, new: null, last_backup_at: null, status: 'not_tracked' }),
  // A linked playlist: no total and no track list (S0, Q10).
  playlist({
    id: fakeId('kexpliveset'), kind: 'linked', name: 'KEXP Live Sets', owner: 'KEXP', item_access: false,
    total: null, recorded: 12, new: null, removable: true, status: 'up_to_date',
  }),
];

export const librarySummary: LibrarySummary = {
  owned_count: 23,
  owned_tracked: 18,
  liked_tracked: true,
  added_count: 2,
  tracked_count: 21,
  auto_track_owned: true,
};

/** Followed playlists not in the Library yet: the + modal's suggestions. */
export const suggestions: PlaylistPreview[] = [
  { id: fakeId('pitchforkbest'), uri: `spotify:playlist:${fakeId('pitchforkbest')}`, name: 'Best New Tracks', owner: 'Pitchfork', cover: null, kind: 'followed', item_access: false, total: 50, already_added: false },
  { id: fakeId('jazzbrunch'), uri: `spotify:playlist:${fakeId('jazzbrunch')}`, name: 'Jazz Brunch', owner: 'Mara', cover: null, kind: 'followed', item_access: false, total: 77, already_added: false },
];

/**
 * Playlists you don't follow that a pasted link resolves to (S0, Q10): a name, owner and cover,
 * but no total and no track list. Any other id in a link is `not_found`; see mock/links.ts.
 */
export const linkedPreviews: PlaylistPreview[] = [
  { id: fakeId('fridayfinds'), uri: `spotify:playlist:${fakeId('fridayfinds')}`, name: 'Friday Finds', owner: 'Ana', cover: null, kind: 'linked', item_access: false, total: null, already_added: false },
  { id: fakeId('morningcommute'), uri: `spotify:playlist:${fakeId('morningcommute')}`, name: 'Morning Commute', owner: 'radio_eins', cover: null, kind: 'linked', item_access: false, total: null, already_added: false },
];

// --- Albums --------------------------------------------------------------------------------------

export const ELSEWHERE = '4glBZ0bZMgkmFyi6TD4h69';

function album(a: Partial<Album> & Pick<Album, 'id' | 'name' | 'artist'>): Album {
  return {
    uri: `spotify:album:${a.id}`,
    year: null,
    cover: `/api/albums/${a.id}/cover?size=thumb`,
    total: 12,
    recorded: 12,
    status: 'recorded',
    added_at: fromNow(-30 * DAY),
    completed_at: fromNow(-12 * DAY),
    progress: null,
    ...a,
  };
}

export const albums: Album[] = [
  album({ id: ELSEWHERE, name: 'Elsewhere', artist: 'fakename', total: 11, recorded: 9, status: 'partial', completed_at: null }),
  album({ id: fakeId('okcomputer'), name: 'OK Computer', artist: 'Radiohead', year: 1997 }),
  album({ id: fakeId('inrainbows'), name: 'In Rainbows', artist: 'Radiohead', year: 2007, total: 10, recorded: 0, status: 'queued', completed_at: null }),
  album({ id: fakeId('melodrama'), name: 'Melodrama', artist: 'Lorde', year: 2017, total: 11, recorded: 0, status: 'queued', completed_at: null }),
  album({ id: fakeId('blonde'), name: 'Blonde', artist: 'Frank Ocean', year: 2016, total: 17, recorded: 3, status: 'unavailable', completed_at: null }),
];

export const savedAlbums: SavedAlbum[] = [
  { id: fakeId('currents'), uri: `spotify:album:${fakeId('currents')}`, name: 'Currents', artist: 'Tame Impala', year: 2015, cover: null, total: 13, saved_at: fromNow(-3 * DAY) },
  { id: fakeId('punisher'), uri: `spotify:album:${fakeId('punisher')}`, name: 'Punisher', artist: 'Phoebe Bridgers', year: 2020, cover: null, total: 11, saved_at: fromNow(-40 * DAY) },
];

// --- Track lists ---------------------------------------------------------------------------------

const TITLES = [
  'Airbag', 'Paranoid Android', 'Subterranean Homesick Alien', 'Exit Music', 'Let Down', 'Karma Police',
  'Fitter Happier', 'Electioneering', 'Climbing Up the Walls', 'No Surprises', 'Lucky', 'The Tourist',
];

/** A track list with a mix of states, for detail views. */
export function trackList(count: number, opts: { album?: string; artist?: string; access?: boolean } = {}): ItemTrack[] {
  const states: TrackState[] = ['recorded', 'recorded', 'recorded', 'skipped_duplicate', 'failed', 'missing', 'new'];
  return Array.from({ length: count }, (_, i) => {
    const state = states[i % states.length] ?? 'recorded';
    const title = TITLES[i % TITLES.length] ?? `Track ${i + 1}`;
    const artist = opts.artist ?? 'Radiohead';
    const albumName = opts.album ?? 'OK Computer';
    const recorded = state === 'recorded' || state === 'skipped_duplicate';
    return {
      position: opts.access === false ? null : i + 1,
      // The index first, so ids stay unique per list (fakeId cuts at 22 characters).
      track_id: fakeId(`t${i}x${albumName}`),
      title,
      artists: [artist],
      album: albumName,
      duration_ms: 180_000 + ((i * 37_000) % 160_000),
      state,
      size_bytes: recorded ? 6_000_000 + i * 120_000 : null,
      path: recorded ? `${artist}/${albumName}/${String(i + 1).padStart(2, '0')} - ${title}.m4a` : null,
      reason: state === 'failed' ? 'low_volume' : null,
      recorded_at: recorded ? fromNow(-2 * DAY) : null,
    };
  });
}

/**
 * An album's tracks as its state says: the recorded ones first (every fourth a duplicate of a file
 * already there), then the rest `missing`, with the low-volume failure first when it ended Partial.
 * An album's tracks are never `new` (web-ui.md § Albums › Detail view: Recorded, Skipped
 * (duplicate), Missing or Failed), as in the controller.
 */
export function albumTrackList(album: Album): ItemTrack[] {
  return trackList(album.total, { album: album.name, artist: album.artist }).map((t, i) => {
    const recordedAt = fromNow(-2 * DAY);
    if (i < album.recorded) {
      return { ...t, state: i % 4 === 3 ? 'skipped_duplicate' : 'recorded', size_bytes: 6_000_000 + i * 120_000, path: t.path ?? `${album.artist}/${album.name}/${String(i + 1).padStart(2, '0')} - ${t.title}.m4a`, reason: null, recorded_at: recordedAt };
    }
    const rest: TrackState = album.status === 'partial' && i === album.recorded ? 'failed' : 'missing';
    return { ...t, state: rest, size_bytes: null, path: null, reason: rest === 'failed' ? 'low_volume' : null, recorded_at: null };
  });
}

// --- Runs and History ----------------------------------------------------------------------------

const zeroCounters = { recorded: 0, skipped_duplicate: 0, skipped_other: 0, failed: 0, bytes_added: 0 };

/** The running run in contract: components.examples.StatusRunning. */
export const runRunning: RunSummary = {
  id: 42,
  trigger: 'scheduled',
  state: 'running',
  started_at: '2026-11-15T00:00:00Z',
  window_end: '2026-11-15T07:00:00+01:00',
  paused_reason: null,
  stop_mode: null,
  counters: { recorded: 12, skipped_duplicate: 230, skipped_other: 0, failed: 1, bytes_added: 41_943_040 },
  time_left: { seconds: 1946, unknown_items: 1, as_of: '2026-11-15T00:42:10Z' },
};

export function queueItem(q: Partial<QueueItem> & Pick<QueueItem, 'item_id' | 'name'>): QueueItem {
  return {
    kind: 'owned',
    cover: null,
    state: 'up_next',
    attempt: 1,
    planned: null,
    expect: { kind: 'checking', count: null },
    counts: { recorded: 0, skipped: 0, failed: 0 },
    badges: [],
    reason: null,
    ...q,
  };
}

/** contract: components.examples.StatusRunning */
export const statusRunning: Status = {
  state: 'running',
  run: runRunning,
  item: queueItem({
    item_id: ELSEWHERE, kind: 'album', name: 'Elsewhere', cover: `/api/albums/${ELSEWHERE}/cover?size=thumb`,
    state: 'playing', planned: 2, expect: { kind: 'tracks', count: 2 }, counts: { recorded: 1, skipped: 0, failed: 0 },
  }),
  track: {
    take_id: '20261113-060012-002',
    track_id: '0bYg9bo50gSsH3LtXe2SQn',
    title: 'Last Hours',
    artist: 'fakename',
    album: 'Elsewhere',
    cover_url: 'https://i.scdn.co/image/ab67616d0000b273a5a8fb8d51934d96766181d9',
    length_ms: 88_421,
    started_at: '2026-11-15T00:42:10Z',
    position: 5,
  },
  session_state: 'recording',
  view_only: true,
};

export const statusIdle: Status = {
  state: 'idle',
  run: null,
  item: null,
  track: null,
  session_state: null,
  view_only: false,
};

/** History: every outcome, plus the no-run rows (missed, skipped, held). Newest first. */
export const historyRows: HistoryRow[] = [
  {
    id: 41, kind: 'run', trigger: 'scheduled', started_at: fromNow(-21 * HOUR), ended_at: fromNow(-16 * HOUR),
    duration_s: 18_720, outcome: 'completed_with_issues',
    counters: { recorded: 84, skipped_duplicate: 1204, skipped_other: 2, failed: 3, bytes_added: 641_728_512 },
    reason: null, window: { start: fromNow(-21 * HOUR), end: fromNow(-15 * HOUR) },
  },
  {
    id: 40, kind: 'run', trigger: 'run_now', started_at: fromNow(-2 * DAY), ended_at: fromNow(-2 * DAY + HOUR),
    duration_s: 3_600, outcome: 'completed',
    counters: { recorded: 11, skipped_duplicate: 0, skipped_other: 0, failed: 0, bytes_added: 98_566_144 },
    reason: null, window: null,
  },
  {
    id: 39, kind: 'held', trigger: 'scheduled', started_at: fromNow(-3 * DAY), ended_at: null, duration_s: null,
    outcome: null, counters: null, reason: 'connection_expired', window: null,
  },
  {
    id: 38, kind: 'run', trigger: 'scheduled', started_at: fromNow(-4 * DAY), ended_at: fromNow(-4 * DAY + 6 * HOUR),
    duration_s: 21_600, outcome: 'window_ended',
    counters: { recorded: 61, skipped_duplicate: 412, skipped_other: 0, failed: 0, bytes_added: 512_000_000 },
    reason: null, window: { start: fromNow(-4 * DAY), end: fromNow(-4 * DAY + 6 * HOUR) },
  },
  {
    id: 37, kind: 'run', trigger: 'run_now', started_at: fromNow(-5 * DAY), ended_at: fromNow(-5 * DAY + 600_000),
    duration_s: 600, outcome: 'stopped', counters: { ...zeroCounters, recorded: 2, bytes_added: 14_000_000 },
    reason: null, window: null,
  },
  {
    id: 36, kind: 'missed', trigger: 'scheduled', started_at: fromNow(-6 * DAY), ended_at: null, duration_s: null,
    outcome: null, counters: null, reason: 'not_running', window: null,
  },
  {
    id: 35, kind: 'run', trigger: 'startup', started_at: fromNow(-7 * DAY), ended_at: fromNow(-7 * DAY + 60_000),
    duration_s: 60, outcome: 'failed', counters: zeroCounters, reason: 'setting_drifted', window: null,
  },
  {
    id: 34, kind: 'skipped', trigger: 'scheduled', started_at: fromNow(-8 * DAY), ended_at: null, duration_s: null,
    outcome: null, counters: null, reason: 'previous_paused', window: null,
  },
  {
    id: 33, kind: 'run', trigger: 'scheduled', started_at: fromNow(-9 * DAY), ended_at: fromNow(-9 * DAY + 2 * HOUR),
    duration_s: 7_200, outcome: 'failed',
    counters: { ...zeroCounters, recorded: 14, skipped_duplicate: 120, bytes_added: 98_000_000 },
    reason: 'container_restarted', window: { start: fromNow(-9 * DAY), end: fromNow(-9 * DAY + 6 * HOUR) },
  },
];

/**
 * Older nightly runs to put after `historyRows` (POST /__mock/history {"older": n}), so History has
 * more than one page and "loading more as you scroll" can be seen. Their ids start at 1000.
 */
export function olderHistory(count: number): HistoryRow[] {
  return Array.from({ length: count }, (_, i) => {
    const start = -(9 + i) * DAY - 23 * HOUR;
    const recorded = (i * 7) % 23;
    return {
      id: 1000 + i, kind: 'run', trigger: 'scheduled', started_at: fromNow(start), ended_at: fromNow(start + 2 * HOUR),
      duration_s: 7_200, outcome: 'completed',
      counters: { recorded, skipped_duplicate: 400 + i, skipped_other: 0, failed: 0, bytes_added: recorded * 7_500_000 },
      reason: null, window: { start: fromNow(start), end: fromNow(start + 6 * HOUR) },
    };
  });
}

export const lastRun: LastRun = {
  run: historyRows[0] ?? null,
  issues: [
    { item_id: fakeId('chillmix'), name: 'Chill Mix', message: '2 tracks failed: low volume' },
    { item_id: LATE_NIGHT_DRIVE, name: 'Late Night Drive', message: 'Strobe: failed: recorder error' },
    { item_id: fakeId('sundayvinyl'), name: 'Sunday Vinyl', message: 'playlist unavailable, files kept' },
  ],
};

// --- Backlog and schedule ------------------------------------------------------------------------

/** contract: components.examples.BacklogScheduled (finish_at and as_of moved relative to now) */
export const backlog: Backlog = {
  tracks_total: 5120,
  tracks_recorded: 4708,
  seconds_total: 1_072_800,
  seconds_recorded: 975_600,
  seconds_left: 97_305,
  items_to_record: 9,
  unknown_items: 2,
  finish_at: fromNow(3 * DAY),
  as_of: fromNow(-HOUR),
};

/** contract: components.examples.ScheduleNightly */
export const scheduleNightly: Schedule = {
  hours: {
    mon: [1, 2, 3, 4, 5, 6], tue: [1, 2, 3, 4, 5, 6], wed: [1, 2, 3, 4, 5, 6], thu: [1, 2, 3, 4, 5, 6],
    fri: [1, 2, 3, 4, 5, 6], sat: [0, 1, 2, 3, 4, 5, 6, 7, 8], sun: [0, 1, 2, 3, 4, 5, 6, 7, 8],
  },
  tz: 'Europe/Berlin',
  run_order: ['carried_over', 'liked', 'playlists', 'albums'],
  windows_per_week: 7,
  hours_per_week: 48,
};

/** Manual only: every day empty (web-ui.md § Schedule, "No backups scheduled · Run now only"). */
export const scheduleManual: Schedule = {
  hours: { mon: [], tue: [], wed: [], thu: [], fri: [], sat: [], sun: [] },
  tz: 'Europe/Berlin',
  run_order: ['carried_over', 'liked', 'playlists', 'albums'],
  windows_per_week: 0,
  hours_per_week: 0,
};

export const scheduleNext: ScheduleNext = {
  at: fromNow(9 * HOUR),
  window_end: fromNow(15 * HOUR),
  in_progress: false,
  playlists_to_check: 18,
  albums_queued: 3,
  held_reason: null,
};

// --- The hello snapshot --------------------------------------------------------------------------

/**
 * The mock's starting points (web/README.md § Mock backend):
 * - `fresh`: a new container, at step 1. `setup`: midway through the wizard, at step 4 by default
 *   (POST /__mock/scenario takes `step` for any other).
 * - `new`: set up a moment ago: never run, no schedule, no albums added, nothing backed up yet.
 * - `idle` (the default), `expiring`, `expired`: set up, with History, albums and a schedule.
 * - `running`, `paused`: a scheduled run going; `paused` loses playback to a phone 4 s in.
 */
export type Scenario = 'fresh' | 'setup' | 'new' | 'idle' | 'expiring' | 'expired' | 'running' | 'paused';

export const SCENARIOS: readonly Scenario[] = ['fresh', 'setup', 'new', 'idle', 'expiring', 'expired', 'running', 'paused'];

/** The `hello` data a scenario starts with. The mock's world starts from the same values. */
export function helloFor(scenario: Scenario): Hello {
  const base: Hello = {
    boot_id: BOOT_ID,
    version: VERSION,
    setup: setupComplete,
    status: statusIdle,
    connection: connectionOk,
    client: clientLoggedIn,
    backlog,
  };
  switch (scenario) {
    case 'fresh':
      return { ...base, setup: setupAt('tos'), connection: connectionNotConfigured, client: clientNotInstalled, backlog: null };
    case 'setup':
      return { ...base, setup: setupMidway, connection: connectionNotConfigured, backlog: null };
    case 'new':
    case 'idle':
      return base;
    case 'expiring':
      return { ...base, connection: connectionExpiring };
    case 'expired':
      return { ...base, connection: connectionExpired };
    case 'running':
      return { ...base, status: statusRunning };
    case 'paused':
      return {
        ...base,
        status: {
          ...statusRunning,
          state: 'paused',
          run: { ...runRunning, state: 'paused', paused_reason: 'device_moved' },
          session_state: 'paused',
        },
      };
  }
}
