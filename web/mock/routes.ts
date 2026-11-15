// The mock's REST API: every path in contracts/openapi.yaml, answered from the world's state
// (which starts from the contract's examples, in fixtures.ts). Status codes and error codes follow
// the contract. Paths it doesn't know answer 404 `not_found`.
//
// Plus /__mock/* controls, which the real controller doesn't have: switch scenario, take playback
// away mid-run, raise a Spytify error, skip a setup step, change the Spotify connection, and make
// the live socket misbehave (drop, restart, lose an event, 1013). See web/README.md § Mock backend.

import * as f from './fixtures.ts';
import type { World } from './world.ts';
import type { Connection, ErrorCode, LibraryItem, TrackList } from '../src/api/types.ts';

export interface Reply {
  status: number;
  body?: unknown;
  /** For cover images. */
  contentType?: string;
}

interface Request {
  params: Record<string, string>;
  query: URLSearchParams;
  body: Record<string, unknown>;
}

type Handler = (world: World, req: Request) => Reply;

const ok = (body: unknown, status = 200): Reply => ({ status, body });
const noContent: Reply = { status: 204 };

export function fail(status: number, code: ErrorCode, message: string, details: Record<string, unknown> | null = null): Reply {
  return { status, body: { error: { code, message, details } } };
}

const runActive = () => fail(409, 'run_active', 'Not available while a backup is recording.');
const noRun = () => fail(409, 'no_run', 'No backup is running.');
const notFound = () => fail(404, 'not_found', 'No such item.');

/** A placeholder cover: a 135° gradient, like the drawings' placeholder art. SVG, not the contract's JPEG/PNG. */
function cover(seed: string): Reply {
  const hue = [...seed].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 55% 45%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360} 45% 22%)"/></linearGradient></defs><rect width="300" height="300" fill="url(#g)"/></svg>`;
  return { status: 200, body: svg, contentType: 'image/svg+xml' };
}

function sortLibrary(items: LibraryItem[], sort: string | null): LibraryItem[] {
  const byName = (a: LibraryItem, b: LibraryItem) => a.name.localeCompare(b.name);
  const sorted = items.slice();
  if (sort === 'name') sorted.sort(byName);
  else if (sort === 'track_count') sorted.sort((a, b) => (b.total ?? b.recorded) - (a.total ?? a.recorded) || byName(a, b));
  else if (sort !== 'recently_added') {
    sorted.sort((a, b) => (b.last_backup_at ?? '').localeCompare(a.last_backup_at ?? '') || byName(a, b));
  }
  // Liked Songs is always first when it matches.
  return [...sorted.filter((i) => i.id === 'liked'), ...sorted.filter((i) => i.id !== 'liked')];
}

const CONNECTION_STATES: readonly Connection['state'][] = ['not_configured', 'disconnected', 'ok', 'expiring', 'expired'];

const ROUTES: Record<string, Handler> = {
  'GET /api/health': (w) =>
    ok({
      status: 'ok', version: f.VERSION, boot_id: w.bootId(), uptime_s: Math.round(process.uptime()),
      checks: { db: 'ok', display: 'ok', pulseaudio: 'ok', client: w.data.client.running ? 'running' : 'not_installed' },
    }),

  // Setup
  'GET /api/setup': (w) => ok(w.setup()),
  'POST /api/setup/tos': (w, req) =>
    req.body.understood === true ? ok(w.acknowledgeTos()) : fail(422, 'validation_failed', 'understood must be true.', { field: 'understood' }),
  'POST /api/setup/restart': (w) => (w.runActive() ? runActive() : ok(w.restartSetup())),
  'POST /api/setup/checklist/confirm': (w, req) => ok(w.confirm((req.body.rows ?? {}) as Record<string, boolean>)),

  // The client
  'GET /api/client/status': (w) => ok(w.data.client),
  'POST /api/client/install': (w) => {
    if (w.runActive()) return runActive();
    if (w.data.client.install.state === 'installing') {
      return fail(409, 'install_in_progress', 'The client install is already running.');
    }
    return ok(w.startInstall(), 202);
  },
  'GET /api/client/checklist': (w) => ok(w.recheck()),
  'POST /api/client/restart': (w) => (w.runActive() ? runActive() : ok(w.restartClient(), 202)),

  // Spotify Web API
  'POST /api/spotify/app': (w, req) => {
    const id = String(req.body.client_id ?? '');
    if (!/^[0-9a-f]{32}$/.test(id)) return fail(422, 'validation_failed', 'A Client ID is 32 hex characters.', { field: 'client_id' });
    return ok(w.setClientId(`${id.slice(0, 4)}…${id.slice(-4)}`));
  },
  'POST /api/spotify/auth/start': (w) => {
    if (w.data.connection.state === 'not_configured') return fail(409, 'no_client_id', 'Store a Client ID first.');
    return ok({
      authorize_url: 'https://accounts.spotify.com/authorize?client_id=mock&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&code_challenge_method=S256&code_challenge=mock&state=k7Qm2c',
      redirect_uri: 'http://127.0.0.1:8888/callback',
      expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    });
  },
  'POST /api/spotify/auth/finish': (w, req) => {
    const url = String(req.body.redirect_url ?? '');
    if (!url.startsWith('http://127.0.0.1:8888/callback')) return fail(422, 'invalid_redirect', 'That is not the callback address.');
    if (url.includes('error=access_denied')) return fail(422, 'access_denied', 'You declined.');
    if (!url.includes('code=')) return fail(422, 'invalid_redirect', 'The address has no code.');
    return ok(w.connect());
  },
  'GET /api/spotify/devices': (w) =>
    w.data.connection.state === 'ok' || w.data.connection.state === 'expiring'
      ? ok(f.devices)
      : fail(409, 'not_connected', 'Connect the Spotify Web API first.'),
  'GET /api/spotify/connection': (w) => ok(w.data.connection),
  'DELETE /api/spotify/connection': (w) => (w.runActive() ? runActive() : ok(w.disconnect())),

  // Settings
  'GET /api/storage': (w) => ok(w.data.storage),
  'GET /api/settings': (w) => ok(w.data.settings),
  'PUT /api/settings': (w, req) => {
    const extension = { aac: 'm4a', mp3: 'mp3', flac: 'flac', wav: 'wav' } as const;
    const body = req.body as Partial<typeof w.data.settings>;
    const next = { ...w.data.settings, ...body };
    next.extension = extension[next.format];
    w.data.settings = next;
    // Mock rule: wizard step 6 saves the format, step 7 saves auto_track_owned.
    if ('format' in body) w.markDone('output');
    if ('auto_track_owned' in body) w.markDone('playlists');
    return ok(next);
  },
  'GET /api/container': () => ok(f.container),

  // Library
  'GET /api/library/summary': () => ok(f.librarySummary),
  'GET /api/library': (w, req) => {
    const filter = req.query.get('filter') ?? 'all';
    const q = (req.query.get('q') ?? '').toLowerCase();
    const items = w.data.library.filter((i) => {
      if (q && !i.name.toLowerCase().includes(q)) return false;
      if (filter === 'tracked') return i.tracked;
      if (filter === 'not_tracked') return !i.tracked;
      if (filter === 'owned') return i.kind === 'owned' || i.kind === 'liked';
      if (filter === 'added') return i.kind === 'followed' || i.kind === 'linked';
      return true;
    });
    return ok({ items: sortLibrary(items, req.query.get('sort')) });
  },
  'POST /api/library': (w, req) => {
    const url = String(req.body.url ?? '');
    if (url.includes('37i9dQZF1')) return fail(422, 'spotify_owned', "Playlists made by Spotify aren't available through the API.");
    const preview = f.suggestions.find((s) => url.includes(s.id));
    if (!preview) return fail(422, 'not_found', 'Spotify has no such playlist.');
    if (w.data.library.some((i) => i.id === preview.id)) return fail(409, 'already_added', 'Already in the Library.');
    const item: LibraryItem = {
      id: preview.id, kind: preview.kind, uri: preview.uri, name: preview.name ?? preview.id, owner: preview.owner ?? '',
      cover: `/api/library/${preview.id}/cover?size=thumb`, cover_source: 'spotify', tracked: true, item_access: false,
      total: null, recorded: 0, new: null, last_backup_at: null, status: 'never_backed_up', removable: true,
      playback_note: null, progress: null,
    };
    w.data.library.push(item);
    return ok(item, 201);
  },
  'GET /api/library/suggestions': (w, req) => {
    const q = (req.query.get('q') ?? '').toLowerCase();
    const items = f.suggestions.filter(
      (s) => !w.data.library.some((i) => i.id === s.id) && `${s.name} ${s.owner}`.toLowerCase().includes(q),
    );
    return ok({ items });
  },
  'POST /api/library/resolve': (_w, req) => {
    const url = String(req.body.url ?? '');
    if (!/spotify[:.]/.test(url)) return fail(422, 'invalid_url', 'Not a Spotify playlist link.');
    if (url.includes('37i9dQZF1')) return fail(422, 'spotify_owned', "Playlists made by Spotify aren't available through the API.");
    if (url.includes('private')) return fail(422, 'private', 'This playlist is private.');
    const preview = f.suggestions.find((s) => url.includes(s.id)) ?? f.suggestions[0];
    return ok({ ...preview, kind: 'linked' });
  },
  'PATCH /api/library/:id': (w, req) => {
    const item = w.setTracked(req.params.id ?? '', Boolean(req.body.tracked));
    return item ? ok(item) : notFound();
  },
  'DELETE /api/library/:id': (w, req) => {
    const item = w.data.library.find((i) => i.id === req.params.id);
    if (!item) return notFound();
    if (!item.removable) return fail(409, 'not_removable', "Owned playlists and Liked Songs can't be removed, only untracked.");
    w.data.library = w.data.library.filter((i) => i !== item);
    return noContent;
  },
  'GET /api/library/:id/tracks': (w, req) => {
    const item = w.data.library.find((i) => i.id === req.params.id);
    if (!item) return notFound();
    const tracks = f.trackList(item.item_access ? 12 : 6, { access: item.item_access });
    const list: TrackList = {
      item_id: item.id,
      item_access: item.item_access,
      total: item.item_access ? tracks.length : null,
      duration_ms: item.item_access ? tracks.reduce((sum, t) => sum + (t.duration_ms ?? 0), 0) : null,
      tracks,
    };
    return ok(list);
  },
  'GET /api/library/:id/cover': (w, req) =>
    req.params.id === 'liked' || !w.data.library.some((i) => i.id === req.params.id) ? notFound() : cover(req.params.id ?? ''),

  // Albums
  'GET /api/albums': (w, req) => {
    const filter = req.query.get('filter') ?? 'all';
    const q = (req.query.get('q') ?? '').toLowerCase();
    const items = w.data.albums.filter((a) => {
      if (q && !`${a.name} ${a.artist}`.toLowerCase().includes(q)) return false;
      if (filter === 'recorded') return a.status === 'recorded';
      if (filter === 'queued') return a.status === 'queued';
      if (filter === 'partial') return a.status === 'partial' || (a.status === 'unavailable' && a.recorded > 0);
      return true;
    });
    const count = (s: string) => w.data.albums.filter((a) => a.status === s).length;
    return ok({
      items,
      summary: { total: w.data.albums.length, recorded: count('recorded'), queued: count('queued'), partial: count('partial') },
    });
  },
  'POST /api/albums': (w, req) => {
    if (w.data.connection.state === 'not_configured' || w.data.connection.state === 'disconnected') {
      return fail(409, 'not_connected', 'Connect the Spotify Web API first.');
    }
    const ids = req.body.all === true ? w.data.saved.map((s) => s.id) : ((req.body.ids ?? []) as string[]);
    const added = [];
    const skipped = [];
    for (const id of ids) {
      const saved = w.data.saved.find((s) => s.id === id);
      if (w.data.albums.some((a) => a.id === id)) skipped.push({ id, reason: 'already_added' });
      else if (!saved) skipped.push({ id, reason: 'not_saved' });
      else {
        const album = {
          id: saved.id, uri: saved.uri, name: saved.name, artist: saved.artist, year: saved.year,
          cover: `/api/albums/${saved.id}/cover?size=thumb`, total: saved.total, recorded: 0, status: 'queued' as const,
          added_at: new Date().toISOString(), completed_at: null, progress: null,
        };
        w.data.albums.push(album);
        w.data.saved = w.data.saved.filter((s) => s !== saved);
        added.push(album);
      }
    }
    w.markDone('albums');
    return ok({ added, skipped });
  },
  'GET /api/albums/saved': (w) => ok({ saved_total: w.data.saved.length + w.data.albums.length, items: w.data.saved }),
  'DELETE /api/albums/:id': (w, req) => {
    if (!w.data.albums.some((a) => a.id === req.params.id)) return notFound();
    w.data.albums = w.data.albums.filter((a) => a.id !== req.params.id);
    return noContent;
  },
  'GET /api/albums/:id/tracks': (w, req) => {
    const a = w.data.albums.find((x) => x.id === req.params.id);
    if (!a) return notFound();
    const tracks = f.trackList(a.total, { album: a.name, artist: a.artist });
    return ok({ item_id: a.id, item_access: true, total: a.total, duration_ms: tracks.reduce((s, t) => s + (t.duration_ms ?? 0), 0), tracks });
  },
  'GET /api/albums/:id/cover': (w, req) =>
    w.data.albums.some((a) => a.id === req.params.id) ? cover(req.params.id ?? '') : notFound(),

  // Runs
  'GET /api/backlog': (w) => ok(w.data.backlog ?? f.backlog),
  'GET /api/status': (w) => ok(w.data.status),
  'GET /api/runs': (w, req) => {
    const filter = req.query.get('filter') ?? 'all';
    const runs = w.data.history.filter((r) => {
      if (filter === 'with_issues') return r.kind !== 'run' || r.outcome === 'completed_with_issues' || r.outcome === 'failed';
      if (filter === 'scheduled') return r.trigger === 'scheduled';
      if (filter === 'run_now') return r.trigger === 'run_now';
      return true;
    });
    return ok({ runs, next_cursor: null });
  },
  'POST /api/runs': (w, req) => {
    const items = req.body.items as string[] | undefined;
    if (!w.setup().completed) return fail(409, 'setup_incomplete', 'Finish setup first.');
    if (w.data.connection.state === 'expired') return fail(409, 'connection_expired', 'The Spotify connection expired. Reconnect to run.');
    if (items) {
      const unknown = items.filter((id) => !w.data.library.some((i) => i.id === id) && !w.data.albums.some((a) => a.id === id));
      if (unknown.length) return fail(404, 'not_found', 'Not in the Library or Albums.', { ids: unknown });
    }
    if (w.runActive()) {
      if (!items) return runActive();
      const added = w.addToRun(items);
      return ok({ run_id: w.data.status.run?.id ?? 0, started: false, added }, 202);
    }
    const run = w.startRunNow(items);
    return ok({ run_id: run.id, started: true, added: [] }, 202);
  },
  'GET /api/runs/last': (w) => {
    const run = w.data.history.find((r) => r.kind === 'run') ?? null;
    return ok({ run, issues: run?.id === f.lastRun.run?.id ? f.lastRun.issues : [] });
  },
  'GET /api/runs/current': (w) =>
    ok({ run: w.data.status.run, queue: w.data.queue, current_tracks: w.data.currentTracks }),
  'POST /api/runs/current/stop': (w, req) => {
    const mode = req.body.mode;
    if (mode !== 'after_track' && mode !== 'now') return fail(422, 'validation_failed', 'mode is after_track or now.', { field: 'mode' });
    const run = w.stop(mode);
    return run ? ok(run, 202) : noRun();
  },
  'POST /api/runs/current/resume': (w) => {
    if (!w.runActive()) return noRun();
    const run = w.resume();
    return run ? ok(run, 202) : fail(409, 'not_paused', 'The backup is not paused.');
  },
  'DELETE /api/runs/current/items/:id': (w, req) => {
    if (!w.runActive()) return noRun();
    const result = w.removeFromRun(req.params.id ?? '');
    if (result === 'not_found') return fail(404, 'not_found', 'The item is not waiting in the queue.');
    if (result === 'item_is_current') return fail(409, 'item_is_current', 'Stop the run instead.');
    return noContent;
  },
  'GET /api/runs/:id': (w, req) => {
    const row = w.data.history.find((r) => String(r.id) === req.params.id);
    if (!row) return notFound();
    const items = row.kind !== 'run' ? [] : [
      { item_id: 'liked', kind: 'liked', name: 'Liked Songs', cover: null, order: 1, state: 'done', badges: [], counts: { recorded: 12, skipped: 1990, failed: 0 }, bytes: 98_000_000, started_at: row.started_at, ended_at: row.started_at, reason: null, can_retry: false },
      { item_id: f.fakeId('chillmix'), kind: 'owned', name: 'Chill Mix', cover: `/api/library/${f.fakeId('chillmix')}/cover?size=thumb`, order: 2, state: 'partial', badges: [], counts: { recorded: 40, skipped: 80, failed: 2 }, bytes: 320_000_000, started_at: row.started_at, ended_at: row.ended_at, reason: '2 tracks failed: low volume', can_retry: true },
      { item_id: f.ELSEWHERE, kind: 'album', name: 'Elsewhere', cover: `/api/albums/${f.ELSEWHERE}/cover?size=thumb`, order: 3, state: 'up_to_date', badges: ['up_to_date'], counts: { recorded: 0, skipped: 11, failed: 0 }, bytes: 0, started_at: row.ended_at, ended_at: row.ended_at, reason: null, can_retry: false },
    ];
    return ok({ run: row, items });
  },
  'GET /api/runs/:id/items/:item/tracks': (w, req) => {
    if (!w.data.history.some((r) => String(r.id) === req.params.id)) return notFound();
    const tracks = f.trackList(8).map((t, i) => ({
      position: t.position, track_id: t.track_id, title: t.title, artists: t.artists,
      result: i % 4 === 3 ? 'failed' : i % 4 === 2 ? 'skipped' : 'recorded',
      reason: i % 4 === 3 ? 'low_volume' : i % 4 === 2 ? 'duplicate' : null,
      size_bytes: i % 4 < 2 ? 6_200_000 : null, path: t.path, take_id: `20261113-0600${i}`, at: new Date().toISOString(),
    }));
    return ok({ tracks });
  },

  // Schedule
  'GET /api/schedule': (w) => ok(w.data.schedule),
  'PUT /api/schedule': (w, req) => {
    const hours = req.body.hours as typeof w.data.schedule.hours | undefined;
    if (!hours) return fail(422, 'validation_failed', 'hours is required.', { field: 'hours' });
    const total = Object.values(hours).reduce((n, day) => n + day.length, 0);
    w.data.schedule = { ...w.data.schedule, hours, hours_per_week: total };
    return ok(w.data.schedule);
  },
  'GET /api/schedule/next': (w) => {
    const held = w.data.connection.state === 'expired' ? 'connection_expired' : w.data.status.state === 'paused' ? 'run_paused' : null;
    return ok({ ...w.data.scheduleNext, held_reason: held });
  },

  'GET /api/webapi/usage': () =>
    ok({
      days: 7, from: '2026-11-09', to: '2026-11-15',
      totals: { requests: 812, retried: 3, rate_limited: 0, errors_4xx: 6, errors_5xx: 2 },
      by_day: [{ day: '2026-11-15', method: 'GET', endpoint: '/playlists/{id}/items', lane: 'catalog', requests: 41, retried: 0, rate_limited: 0, status_2xx: 38, status_4xx: 3, status_5xx: 0, p50_ms: 182, p95_ms: 410 }],
      rate_limits: [], warnings: [],
    }),

  // --- Mock controls (not in the contract) --------------------------------------------------------
  'GET /__mock/scenario': (w) => ok({ scenario: w.data.scenario, scenarios: f.SCENARIOS }),
  'POST /__mock/scenario': (w, req) => {
    const name = req.body.scenario as f.Scenario;
    if (!f.SCENARIOS.includes(name)) return fail(422, 'validation_failed', `scenario is one of ${f.SCENARIOS.join(', ')}.`);
    w.reset(name);
    return ok({ scenario: name });
  },
  'POST /__mock/takeover': (w) => (w.takeover() ? noContent : fail(409, 'no_run', 'Nothing is recording.')),
  'POST /__mock/error': (w, req) => {
    w.raiseError(req.body.withdrawn === true);
    return noContent;
  },
  'POST /__mock/install-fails': (w) => {
    w.failInstall();
    return noContent;
  },
  'POST /__mock/setup/next': (w) => ok(w.nextStep()),
  'POST /__mock/storage': (w, req) => {
    w.data.storage = req.body.mounted === false ? f.storageNotMounted : f.storageOk;
    return ok(w.data.storage);
  },
  'POST /__mock/connection': (w, req) => {
    const state = req.body.state as Connection['state'];
    if (!CONNECTION_STATES.includes(state)) return fail(422, 'validation_failed', `state is one of ${CONNECTION_STATES.join(', ')}.`);
    return ok(w.setConnectionState(state));
  },

  // The live socket misbehaving, for the UI's reconnect and resync code.
  'POST /__mock/drop': (w, req) => {
    // {"every_s": 30} keeps dropping every 30 s; {"every_s": 0} stops.
    if (typeof req.body.every_s === 'number') w.hub.dropEvery(req.body.every_s);
    else w.hub.drop();
    return noContent;
  },
  'POST /__mock/restart': (w) => {
    w.hub.restart();
    return ok({ boot_id: w.bootId() });
  },
  'POST /__mock/gap': (w) => {
    // Lose one event, then send a harmless one, so clients see the gap at once.
    w.hub.loseNext();
    w.hub.publish('setup.state', w.setup());
    return noContent;
  },
  'POST /__mock/slow': (w) => {
    w.hub.closeSlow();
    return noContent;
  },
};

/** Finds the handler for a method and path, with its `:params`. */
export function route(method: string, path: string): { handler: Handler; params: Record<string, string> } | null {
  const parts = path.split('/');
  for (const [key, handler] of Object.entries(ROUTES)) {
    const [m, pattern] = key.split(' ') as [string, string];
    if (m !== method) continue;
    const want = pattern.split('/');
    if (want.length !== parts.length) continue;
    const params: Record<string, string> = {};
    const match = want.every((segment, i) => {
      const part = parts[i] ?? '';
      if (segment.startsWith(':')) {
        params[segment.slice(1)] = decodeURIComponent(part);
        return part !== '';
      }
      return segment === part;
    });
    if (match) return { handler, params };
  }
  return null;
}

export function handle(world: World, method: string, url: URL, body: Record<string, unknown>): Reply {
  const found = route(method, url.pathname);
  if (!found) return fail(404, 'not_found', `The mock has no ${method} ${url.pathname}.`);
  return found.handler(world, { params: found.params, query: url.searchParams, body });
}
