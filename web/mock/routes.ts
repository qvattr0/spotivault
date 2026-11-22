// The mock's REST API: every path in contracts/openapi.yaml, answered from the world's state
// (which starts from the contract's examples, in fixtures.ts). Status codes and error codes follow
// the contract. Paths it doesn't know answer 404 `not_found`. Every JSON answer is typed against
// the contract with `satisfies Answer<path, method>`, so `npm run typecheck` fails when the mock
// drifts from it.
//
// Plus /__mock/* controls, which the real controller doesn't have: they put the world in the
// states web-ui.md describes (a takeover, a stall, an error, a window ending, the client logged
// out, Spotify down, ...) and make the live socket misbehave. See web/README.md § Mock backend.

import * as f from './fixtures.ts';
import { LOG_LEVELS, LOG_SOURCES, sampleZip } from './logs.ts';
import type { ChecklistRowValue, SpotifyHealth, World } from './world.ts';
import type { paths } from '../src/api/schema.ts';
import type {
  Album,
  Connection,
  ErrorCode,
  LibraryItem,
  PlaylistPreview,
  RunItem,
  SetupStepId,
  TrackList,
  TrackResult,
} from '../src/api/types.ts';
import { checkLayout } from '../src/lib/layout.ts';

export interface Reply {
  status: number;
  body?: unknown;
  /** For cover images and the logs zip. */
  contentType?: string;
  /** More headers: the zip's Content-Disposition. */
  headers?: Record<string, string>;
}

interface Request {
  params: Record<string, string>;
  query: URLSearchParams;
  body: Record<string, unknown>;
}

type Handler = (world: World, req: Request) => Reply;

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete';

/** The JSON an operation answers with `status`, from the contract: Answer<'/api/library', 'get'>. */
type Answer<P extends keyof paths, M extends Method, S extends number = 200> = paths[P][M] extends {
  responses: infer R;
}
  ? R extends { [K in S]: { content: { 'application/json': infer B } } }
    ? B
    : never
  : never;

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

/** Albums' sort menu; ties sort by artist, then album (contract: listAlbums). */
function sortAlbums(items: Album[], sort: string | null): Album[] {
  const byArtist = (a: Album, b: Album) => a.artist.localeCompare(b.artist) || a.name.localeCompare(b.name);
  const sorted = items.slice();
  if (sort === 'album') sorted.sort((a, b) => a.name.localeCompare(b.name) || byArtist(a, b));
  else if (sort === 'artist') sorted.sort(byArtist);
  else if (sort === 'year') sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0) || byArtist(a, b));
  else sorted.sort((a, b) => b.added_at.localeCompare(a.added_at) || byArtist(a, b));
  return sorted;
}

const CONNECTION_STATES: readonly Connection['state'][] = ['not_configured', 'disconnected', 'ok', 'expiring', 'expired'];
const SPOTIFY_HEALTH: readonly SpotifyHealth[] = ['ok', 'unavailable', 'rate_limited'];

/** 409 when the Web API can't be asked: not connected, or the connection expired. */
function needsConnection(w: World): Reply | null {
  const state = w.data.connection.state;
  if (state === 'not_configured' || state === 'disconnected') return fail(409, 'not_connected', 'Connect the Spotify Web API first.');
  if (state === 'expired') return fail(409, 'connection_expired', 'The Spotify connection expired. Reconnect first.');
  return null;
}

/** 503 while the mock's "Spotify" is down or rate-limiting (POST /__mock/spotify). */
function spotifyDown(w: World): Reply | null {
  if (w.data.spotify === 'unavailable') return fail(503, 'spotify_unavailable', 'Spotify is not answering. Try again later.');
  if (w.data.spotify === 'rate_limited') return fail(503, 'rate_limited', 'Spotify asked to wait.', { retry_after_s: 120 });
  return null;
}

/**
 * A pasted link, as the controller reads it: `https://open.spotify.com/playlist/<id>` or
 * `spotify:playlist:<id>`. Followed playlists (the suggestions) and two linked ones resolve; a
 * Spotify-made id is refused; an id with "private" in it is private; any other id isn't found.
 */
function resolveLink(w: World, url: string): PlaylistPreview | Reply {
  const match = /^(?:https?:\/\/open\.spotify\.com\/(?:intl-[a-z]{2}\/)?playlist\/|spotify:playlist:)([0-9A-Za-z]{22})(?:[/?#].*)?$/.exec(url.trim());
  if (!match?.[1]) return fail(422, 'invalid_url', 'Not a Spotify playlist link.');
  const id = match[1];
  if (id.startsWith('37i9dQZF1')) return fail(422, 'spotify_owned', "Playlists made by Spotify aren't available through the API.");
  if (/private/i.test(id)) return fail(422, 'private', 'This playlist is private.');
  const preview = [...f.suggestions, ...w.data.foundSuggestions, ...f.linkedPreviews].find((p) => p.id === id);
  if (!preview) return fail(422, 'not_found', 'Spotify has no such playlist.');
  return { ...preview, already_added: w.data.library.some((i) => i.id === id) };
}

function isReply(value: PlaylistPreview | Reply): value is Reply {
  return 'status' in value;
}

/** A page of History: `cursor` is the offset as a string (opaque to the UI). */
function historyPage(w: World, filter: string, cursor: string | null, limit: number) {
  // The run going on comes first, as in the controller; 'with_issues' leaves it out (no outcome yet).
  const live = w.liveHistoryRow();
  const runs = [...(live ? [live] : []), ...w.data.history].filter((r) => {
    if (filter === 'with_issues') return r.kind !== 'run' || r.outcome === 'completed_with_issues' || r.outcome === 'failed';
    if (filter === 'scheduled') return r.trigger === 'scheduled' || r.trigger === 'startup';
    if (filter === 'run_now') return r.trigger === 'run_now';
    return true;
  });
  const start = Number(cursor ?? 0) || 0;
  const end = start + limit;
  return { runs: runs.slice(start, end), next_cursor: end < runs.length ? String(end) : null } satisfies Answer<'/api/runs', 'get'>;
}

/** The sample items of a run the mock didn't run itself (the fixtures' History). */
function sampleRunItems(row: { started_at: string; ended_at: string | null }): RunItem[] {
  return [
    { item_id: 'liked', kind: 'liked', name: 'Liked Songs', cover: null, order: 1, state: 'done', badges: [], counts: { recorded: 12, skipped: 1990, failed: 0 }, bytes: 98_000_000, started_at: row.started_at, ended_at: row.started_at, reason: null, can_retry: false },
    { item_id: f.fakeId('chillmix'), kind: 'owned', name: 'Chill Mix', cover: `/api/library/${f.fakeId('chillmix')}/cover?size=thumb`, order: 2, state: 'partial', badges: ['interrupted_retried'], counts: { recorded: 40, skipped: 80, failed: 2 }, bytes: 320_000_000, started_at: row.started_at, ended_at: row.ended_at, reason: '2 tracks failed: low volume', can_retry: true },
    { item_id: f.ELSEWHERE, kind: 'album', name: 'Elsewhere', cover: `/api/albums/${f.ELSEWHERE}/cover?size=thumb`, order: 3, state: 'up_to_date', badges: ['up_to_date'], counts: { recorded: 0, skipped: 11, failed: 0 }, bytes: 0, started_at: row.ended_at, ended_at: row.ended_at, reason: null, can_retry: false },
    { item_id: f.fakeId('focus'), kind: 'owned', name: 'Focus', cover: `/api/library/${f.fakeId('focus')}/cover?size=thumb`, order: 4, state: 'removed', badges: ['removed'], counts: { recorded: 0, skipped: 0, failed: 0 }, bytes: 0, started_at: null, ended_at: null, reason: null, can_retry: false },
  ];
}

/** An item's tracks in a run: recorded, skipped (duplicate, ad) and failed, in turn. */
function sampleRunTracks(): TrackResult[] {
  const results: [TrackResult['result'], string | null][] = [
    ['recorded', null], ['recorded', null], ['skipped', 'duplicate'], ['failed', 'low_volume'], ['skipped', 'ad'], ['recorded', null],
  ];
  return f.trackList(8).map((t, i) => {
    const [result, reason] = results[i % results.length] ?? ['recorded', null];
    return {
      position: t.position, track_id: t.track_id, title: t.title, artists: t.artists, result, reason,
      size_bytes: result === 'recorded' ? 6_200_000 + i * 10_000 : null, path: result === 'failed' ? null : t.path,
      take_id: `20261113-0600${i}`, at: new Date().toISOString(),
    };
  });
}

const ROUTES: Record<string, Handler> = {
  'GET /api/health': (w) =>
    ok({
      status: 'ok', version: f.VERSION, boot_id: w.bootId(), uptime_s: Math.round(process.uptime()),
      checks: { db: 'ok', display: 'ok', pulseaudio: 'ok', client: w.data.client.running ? 'running' : 'not_installed' },
    } satisfies Answer<'/api/health', 'get'>),

  // Setup
  'GET /api/setup': (w) => ok(w.setup()),
  'POST /api/setup/tos': (w, req) =>
    req.body.understood === true ? ok(w.acknowledgeTos()) : fail(422, 'validation_failed', 'understood must be true.', { field: 'understood' }),
  'POST /api/setup/restart': (w) => (w.runActive() ? runActive() : ok(w.restartSetup())),
  // Step 8's "I'll choose in Albums": the step is done, nothing is queued.
  'POST /api/setup/albums/later': (w) => ok(w.chooseAlbumsLater()),
  'POST /api/setup/complete': (w) => {
    const result = w.completeSetup();
    return 'error' in result ? fail(409, 'setup_incomplete', 'Finish the setup steps first: ' + result.steps.join(', ') + '.', { steps: result.steps }) : ok(result);
  },
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
  'GET /api/client/checklist': (w) => ok(w.readChecklist()),
  'POST /api/client/restart': (w) => (w.runActive() ? runActive() : ok(w.restartClient(), 202)),

  // Spotify Web API
  'POST /api/spotify/app': (w, req) => {
    const id = String(req.body.client_id ?? '');
    if (!/^[0-9a-f]{32}$/.test(id)) return fail(422, 'validation_failed', 'A Client ID is 32 hex characters.', { field: 'client_id' });
    return ok(w.setClientId(`${id.slice(0, 4)}…${id.slice(-4)}`));
  },
  'POST /api/spotify/auth/start': (w) => {
    if (w.data.connection.state === 'not_configured') return fail(409, 'no_client_id', 'Store a Client ID first.');
    w.data.pendingAuth = true;
    return ok({
      authorize_url: 'https://accounts.spotify.com/authorize?client_id=mock&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback&code_challenge_method=S256&code_challenge=mock&state=k7Qm2c',
      redirect_uri: 'http://127.0.0.1:8888/callback',
      expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    } satisfies Answer<'/api/spotify/auth/start', 'post'>);
  },
  'POST /api/spotify/auth/finish': (w, req) => {
    // In the controller's order (connection.py finish_auth): the address must be the callback, with
    // a code or an `error=` (a decline); then the pending authorization is claimed. A `state` other
    // than the one sent is an older authorization and leaves the pending one alone, so the right
    // address still works. A claimed one is used up, even when Spotify refuses the code (`code=bad`).
    const url = String(req.body.redirect_url ?? '');
    if (!url.startsWith('http://127.0.0.1:8888/callback')) return fail(422, 'invalid_redirect', 'That is not the callback address.');
    const params = new URL(url).searchParams;
    if (params.get('error')) return fail(422, 'access_denied', 'You declined.');
    if (!params.get('code')) return fail(422, 'invalid_redirect', 'The address has no code.');
    if (!w.data.pendingAuth) return fail(422, 'no_pending_auth', 'Press Authorize again.');
    if (params.get('state') !== 'k7Qm2c') return fail(422, 'state_mismatch', 'The address belongs to an older authorization. Press Authorize again.');
    w.data.pendingAuth = false;
    if (params.get('code') === 'bad') return fail(422, 'token_exchange_failed', 'Spotify refused the code.');
    const connection = w.connect();
    // As in the controller: the device check runs right after, and marks step 5 if ours is listed.
    if (w.data.spotify === 'ok') w.checkDevices();
    return ok(connection);
  },
  'GET /api/spotify/devices': (w) => {
    const state = w.data.connection.state;
    if (state !== 'ok' && state !== 'expiring') return fail(409, 'not_connected', 'Connect the Spotify Web API first.');
    const down = spotifyDown(w);
    if (down) return down;
    const body = w.checkDevices() ? f.devices : { ...f.devices, devices: f.devices.devices.filter((d) => d.id !== f.devices.ours?.id), ours: null };
    return ok(body satisfies Answer<'/api/spotify/devices', 'get'>);
  },
  'GET /api/spotify/connection': (w) => ok(w.data.connection),
  'DELETE /api/spotify/connection': (w) => (w.runActive() ? runActive() : ok(w.disconnect())),

  // Settings
  'GET /api/storage': (w) => ok(w.storageChecked()),
  'GET /api/settings': (w) => ok(w.data.settings),
  'PUT /api/settings': (w, req) => {
    const body = req.body as Partial<typeof w.data.settings>;
    if (body.layout) {
      const check = checkLayout(String(body.layout.pattern ?? ''));
      if (!check.valid) {
        return fail(422, 'invalid_layout', 'The layout is not valid.', { reason: check.reason, ...(check.placeholder ? { placeholder: check.placeholder } : {}) });
      }
    }
    return ok(w.saveSettings(body));
  },
  'GET /api/container': () => ok(f.container),

  // Library
  'GET /api/library/summary': (w) => ok(w.librarySummary()),
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
    return ok({ items: sortLibrary(items, req.query.get('sort')) } satisfies Answer<'/api/library', 'get'>);
  },
  'POST /api/library': (w, req) => {
    const url = String(req.body.url ?? '');
    const id = /([0-9A-Za-z]{22})/.exec(url)?.[1];
    if (id && w.data.library.some((i) => i.id === id)) return fail(409, 'already_added', 'Already in the Library.');
    const refused = needsConnection(w) ?? spotifyDown(w);
    if (refused) return refused;
    const preview = resolveLink(w, url);
    if (isReply(preview)) return preview;
    const item: LibraryItem = {
      id: preview.id, kind: preview.kind, uri: preview.uri, name: preview.name, owner: preview.owner,
      cover: `/api/library/${preview.id}/cover?size=thumb`, cover_source: 'spotify', tracked: true, item_access: preview.item_access,
      total: preview.total, recorded: 0, new: null, last_backup_at: null, status: 'never_backed_up', removable: true,
      progress: null,
    };
    w.addLibraryItem(item);
    return ok(item, 201);
  },
  'GET /api/library/suggestions': (w, req) => {
    const q = (req.query.get('q') ?? '').toLowerCase();
    const items = [...f.suggestions, ...w.data.foundSuggestions].filter(
      (s) => !w.data.library.some((i) => i.id === s.id) && `${s.name} ${s.owner}`.toLowerCase().includes(q),
    );
    return ok({ items } satisfies Answer<'/api/library/suggestions', 'get'>);
  },
  'POST /api/library/resolve': (w, req) => {
    const refused = needsConnection(w) ?? spotifyDown(w);
    if (refused) return refused;
    const preview = resolveLink(w, String(req.body.url ?? ''));
    return isReply(preview) ? preview : ok(preview satisfies Answer<'/api/library/resolve', 'post'>);
  },
  'POST /api/library/refresh': (w) => {
    // Never during a run (the run refreshes at its start), and only with a connection.
    if (w.runActive()) return runActive();
    const refused = needsConnection(w);
    if (refused) return refused;
    return ok(w.refreshLibrary() satisfies Answer<'/api/library/refresh', 'post', 202>, 202);
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
    // Without item access, only what has been recorded is known (web-ui.md § Detail view).
    const tracks = item.item_access ? f.trackList(12) : f.trackList(6, { access: false }).filter((t) => t.state === 'recorded' || t.state === 'skipped_duplicate');
    const list: TrackList = {
      item_id: item.id,
      item_access: item.item_access,
      total: item.item_access ? tracks.length : item.total,
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
      items: sortAlbums(items, req.query.get('sort')),
      summary: { total: w.data.albums.length, recorded: count('recorded'), queued: count('queued'), partial: count('partial') },
    } satisfies Answer<'/api/albums', 'get'>);
  },
  'POST /api/albums': (w, req) => {
    const refused = needsConnection(w);
    if (refused) return refused;
    const ids = req.body.all === true ? w.data.saved.map((s) => s.id) : ((req.body.ids ?? []) as string[]);
    const added: Album[] = [];
    const skipped: { id: string; reason: 'already_added' | 'not_saved' }[] = [];
    for (const id of ids) {
      const saved = w.data.saved.find((s) => s.id === id);
      if (w.data.albums.some((a) => a.id === id)) skipped.push({ id, reason: 'already_added' });
      else if (!saved) skipped.push({ id, reason: 'not_saved' });
      else {
        const album: Album = {
          id: saved.id, uri: saved.uri, name: saved.name, artist: saved.artist, year: saved.year,
          cover: `/api/albums/${saved.id}/cover?size=thumb`, total: saved.total, recorded: 0, status: 'queued',
          added_at: new Date().toISOString(), completed_at: null, progress: null,
        };
        w.data.albums.push(album);
        w.data.saved = w.data.saved.filter((s) => s !== saved);
        added.push(album);
      }
    }
    w.markDone('albums');
    return ok({ added, skipped } satisfies Answer<'/api/albums', 'post'>);
  },
  'GET /api/albums/saved': (w) => {
    const refused = needsConnection(w);
    if (refused) return refused;
    return ok({ saved_total: w.data.saved.length + w.data.albums.length, items: w.data.saved } satisfies Answer<'/api/albums/saved', 'get'>);
  },
  'DELETE /api/albums/:id': (w, req) => {
    const album = w.data.albums.find((a) => a.id === req.params.id);
    if (!album) return notFound();
    w.data.albums = w.data.albums.filter((a) => a !== album);
    // It's still a saved album, so the + modal offers it again.
    w.data.saved = [{ id: album.id, uri: album.uri, name: album.name, artist: album.artist, year: album.year, cover: null, total: album.total, saved_at: album.added_at }, ...w.data.saved];
    return noContent;
  },
  'GET /api/albums/:id/tracks': (w, req) => {
    const a = w.data.albums.find((x) => x.id === req.params.id);
    if (!a) return notFound();
    const tracks = f.albumTrackList(a);
    return ok({ item_id: a.id, item_access: true, total: a.total, duration_ms: tracks.reduce((s, t) => s + (t.duration_ms ?? 0), 0), tracks } satisfies TrackList);
  },
  'GET /api/albums/:id/cover': (w, req) =>
    w.data.albums.some((a) => a.id === req.params.id) ? cover(req.params.id ?? '') : notFound(),

  // Runs
  'GET /api/backlog': (w) => ok(w.data.backlog ?? f.backlog),
  'GET /api/status': (w) => ok(w.data.status),
  'GET /api/runs': (w, req) => {
    const limit = Number(req.query.get('limit') ?? 50);
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) return fail(422, 'validation_failed', 'limit is 1 to 100.', { field: 'limit' });
    return ok(historyPage(w, req.query.get('filter') ?? 'all', req.query.get('cursor'), limit));
  },
  'POST /api/runs': (w, req) => {
    const items = req.body.items as string[] | undefined;
    if (!w.setup().completed) return fail(409, 'setup_incomplete', 'Finish setup first.');
    const refused = needsConnection(w);
    if (refused) return refused;
    if (!w.data.client.installed) return fail(409, 'client_not_installed', 'The Spotify client is not installed.');
    // As in the controller: only a running client can be logged out. One that isn't running is
    // restarted by the run (web-ui.md § Warnings, Client not running).
    if (w.data.client.running && !w.data.client.logged_in) return fail(409, 'client_logged_out', 'The Spotify client is logged out.');
    if (items) {
      const unknown = items.filter((id) => !w.data.library.some((i) => i.id === id) && !w.data.albums.some((a) => a.id === id));
      if (unknown.length) return fail(404, 'not_found', 'Not in the Library or Albums.', { ids: unknown });
    }
    if (w.runActive()) {
      if (!items) return runActive();
      const added = w.addToRun(items);
      return ok({ run_id: w.data.status.run?.id ?? 0, started: false, added } satisfies Answer<'/api/runs', 'post', 202>, 202);
    }
    const run = w.startRunNow(items);
    return ok({ run_id: run.id, started: true, added: items ?? [] } satisfies Answer<'/api/runs', 'post', 202>, 202);
  },
  'GET /api/runs/last': (w) => {
    const run = w.data.history.find((r) => r.kind === 'run') ?? null;
    return ok({ run, issues: run?.id === f.lastRun.run?.id ? f.lastRun.issues : w.issuesOf(run?.id ?? 0) } satisfies Answer<'/api/runs/last', 'get'>);
  },
  'GET /api/runs/current': (w) =>
    ok({ run: w.data.status.run, queue: w.data.queue, current_tracks: w.data.currentTracks } satisfies Answer<'/api/runs/current', 'get'>),
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
    const live = w.liveHistoryRow();
    if (live && String(live.id) === req.params.id) return ok({ run: live, items: w.liveRunItems() } satisfies Answer<'/api/runs/{id}', 'get'>);
    const row = w.data.history.find((r) => String(r.id) === req.params.id);
    if (!row) return notFound();
    const items = row.kind !== 'run' ? [] : (w.data.runItems.get(row.id) ?? sampleRunItems(row));
    return ok({ run: row, items } satisfies Answer<'/api/runs/{id}', 'get'>);
  },
  'GET /api/runs/:id/items/:item/tracks': (w, req) => {
    const live = w.liveHistoryRow();
    if (live && String(live.id) === req.params.id) {
      // The run going on: the takes that ended so far (a take still recording isn't listed).
      if (!w.liveRunItems().some((i) => i.item_id === req.params.item)) return notFound();
      return ok({ tracks: w.data.runTracks.get(`${live.id}/${req.params.item}`) ?? [] } satisfies Answer<'/api/runs/{id}/items/{item}/tracks', 'get'>);
    }
    const row = w.data.history.find((r) => String(r.id) === req.params.id);
    if (!row || row.kind !== 'run') return notFound();
    // A run the mock ran: the item's own results. An older run: a sample, for items that played.
    const ran = w.data.runItems.get(row.id);
    const item = (ran ?? sampleRunItems(row)).find((i) => i.item_id === req.params.item);
    if (!item) return notFound();
    const tracks = ran
      ? (w.data.runTracks.get(`${row.id}/${item.item_id}`) ?? [])
      : item.started_at === null || item.state === 'up_to_date' ? [] : sampleRunTracks();
    return ok({ tracks } satisfies Answer<'/api/runs/{id}/items/{item}/tracks', 'get'>);
  },

  // History › Logs (mock/logs.ts)
  'GET /api/logs': (w, req) => {
    const source = req.query.getAll('source');
    const level = req.query.getAll('level');
    if (source.some((s) => !(LOG_SOURCES as readonly string[]).includes(s)) || source.length > 4) {
      return fail(422, 'validation_failed', `source is one of ${LOG_SOURCES.join(', ')}.`, { field: 'source' });
    }
    if (level.some((l) => !(LOG_LEVELS as readonly string[]).includes(l)) || level.length > 4) {
      return fail(422, 'validation_failed', `level is one of ${LOG_LEVELS.join(', ')}.`, { field: 'level' });
    }
    const runText = req.query.get('run');
    const run = runText === null ? null : Number(runText);
    if (run !== null && (!Number.isInteger(run) || run < 1)) return fail(422, 'validation_failed', 'run is a run id.', { field: 'run' });
    const limit = Number(req.query.get('limit') ?? 200);
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) return fail(422, 'validation_failed', 'limit is 1 to 500.', { field: 'limit' });
    const q = req.query.get('q');
    if (q !== null && (q.length < 1 || q.length > 200)) return fail(422, 'validation_failed', 'q is 1 to 200 characters.', { field: 'q' });
    const page = w.logs.page({ source, level, run, q, before: req.query.get('before'), limit });
    if (page === 'unknown_run') return fail(404, 'not_found', 'No run with this id.');
    if (page === 'bad_before') return fail(422, 'validation_failed', "before isn't a line's id.", { field: 'before' });
    return ok(page satisfies Answer<'/api/logs', 'get'>);
  },
  'GET /api/logs/download': (_w, req) => {
    const days = Number(req.query.get('days') ?? 7);
    if (!Number.isInteger(days) || days < 1 || days > 14) return fail(422, 'validation_failed', 'days is 1 to 14.', { field: 'days' });
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '-');
    return {
      status: 200,
      body: sampleZip(),
      contentType: 'application/zip',
      headers: { 'Content-Disposition': `attachment; filename="spotivault-logs-${stamp}.zip"`, 'Cache-Control': 'no-store' },
    };
  },

  // Schedule (its page isn't in M1; the Dashboard reads /api/schedule/next)
  'GET /api/schedule': (w) => ok(w.data.schedule),
  'PUT /api/schedule': (w, req) => {
    const hours = req.body.hours as typeof w.data.schedule.hours | undefined;
    if (!hours) return fail(422, 'validation_failed', 'hours is required.', { field: 'hours' });
    const total = Object.values(hours).reduce((n, day) => n + day.length, 0);
    w.data.schedule = { ...w.data.schedule, hours, hours_per_week: total, windows_per_week: total === 0 ? 0 : w.data.schedule.windows_per_week || 7 };
    return ok(w.data.schedule);
  },
  'GET /api/schedule/next': (w) => ok(w.scheduleNext()),

  'GET /api/webapi/usage': (_w, req) => {
    const days = Number(req.query.get('days') ?? 7);
    if (!Number.isInteger(days) || days < 1 || days > 90) return fail(422, 'validation_failed', 'days is 1 to 90.', { field: 'days' });
    return ok({
      days, from: '2026-11-09', to: '2026-11-15',
      totals: { requests: 812, retried: 3, rate_limited: 0, errors_4xx: 6, errors_5xx: 2 },
      by_day: [{ day: '2026-11-15', method: 'GET', endpoint: '/playlists/{id}/items', lane: 'catalog', requests: 41, retried: 0, rate_limited: 0, status_2xx: 38, status_4xx: 3, status_5xx: 0, p50_ms: 182, p95_ms: 410 }],
      rate_limits: [], warnings: [],
    } satisfies Answer<'/api/webapi/usage', 'get'>);
  },

  // --- Mock controls (not in the contract) --------------------------------------------------------
  'GET /__mock/scenario': (w) => ok({ scenario: w.data.scenario, scenarios: f.SCENARIOS }),
  'POST /__mock/scenario': (w, req) => {
    const name = req.body.scenario as f.Scenario;
    if (!f.SCENARIOS.includes(name)) return fail(422, 'validation_failed', `scenario is one of ${f.SCENARIOS.join(', ')}.`);
    // `step` (the `setup` scenario only): the wizard step it starts at.
    const step = req.body.step as SetupStepId | undefined;
    if (step !== undefined && (name !== 'setup' || !f.SETUP_STEP_IDS.includes(step))) {
      return fail(422, 'validation_failed', `step goes with the setup scenario, and is one of ${f.SETUP_STEP_IDS.join(', ')}.`);
    }
    w.reset(name, step);
    return ok({ scenario: name, step: name === 'setup' ? (w.setup().first_unfinished ?? null) : null });
  },
  'POST /__mock/takeover': (w) => (w.takeover() ? noContent : fail(409, 'no_run', 'Nothing is recording.')),
  'POST /__mock/stall': (w) => (w.stall() ? noContent : fail(409, 'no_run', 'Nothing is recording.')),
  'POST /__mock/window-end': (w) => (w.windowEnd() ? noContent : fail(409, 'no_run', 'No backup is running.')),
  'POST /__mock/error': (w, req) => {
    w.raiseError({
      withdrawn: req.body.withdrawn === true,
      fatal: req.body.fatal === true,
      source: req.body.source === 'controller' ? 'controller' : 'spytify',
      // events.md § Warnings lists the codes; the mock passes on whatever it's given.
      code: typeof req.body.code === 'string' ? (req.body.code as 'capture_silent') : undefined,
      message: typeof req.body.message === 'string' ? req.body.message : undefined,
    });
    return noContent;
  },
  'POST /__mock/checklist': (w, req) => {
    // {"rows": {"normalization": "ok", "gapless": false}} or {"ready": true}: the client's settings change.
    const rows = (req.body.rows ?? {}) as Record<string, ChecklistRowValue>;
    const allowed: ChecklistRowValue[] = ['ok', 'needs_change', 'unknown', true, false];
    if (Object.values(rows).some((v) => !allowed.includes(v))) {
      return fail(422, 'validation_failed', 'A row is "ok", "needs_change", "unknown", true or false.');
    }
    return ok(w.setChecklist({ rows, ready: req.body.ready === true }));
  },
  'POST /__mock/install-fails': (w) => {
    w.failInstall();
    return noContent;
  },
  'POST /__mock/login': (w, req) => ok(w.setLoggedIn(req.body.logged_in !== false)),
  // {"running": false}: the client stops; the next run restarts it. {"comes_back": false}: its device
  // doesn't show up again, so that run fails (device_missing). {"running": true}: it starts again.
  'POST /__mock/client': (w, req) => ok(w.setClientRunning(req.body.running !== false, req.body.comes_back !== false)),
  'POST /__mock/devices': (w, req) => {
    w.setDeviceListed(req.body.listed !== false);
    return noContent;
  },
  'POST /__mock/spotify': (w, req) => {
    const state = req.body.state as SpotifyHealth;
    if (!SPOTIFY_HEALTH.includes(state)) return fail(422, 'validation_failed', `state is one of ${SPOTIFY_HEALTH.join(', ')}.`);
    w.setSpotify(state);
    return noContent;
  },
  'POST /__mock/vnc': (w, req) => {
    w.setVncUp(req.body.up !== false);
    return noContent;
  },
  'POST /__mock/history': (w, req) => {
    const older = Number(req.body.older ?? 0);
    if (!Number.isInteger(older) || older < 0 || older > 500) return fail(422, 'validation_failed', 'older is 0 to 500.');
    w.setHistory(req.body.empty === true ? 'empty' : older);
    return noContent;
  },
  'POST /__mock/setup/next': (w) => ok(w.nextStep()),
  'POST /__mock/new-playlist': (w, req) => {
    // {"name": "Road Trip"}: a playlist you made in Spotify; {"followed": true}: one you followed.
    // The next catalog refresh (the Library's Refresh) finds it.
    const name = typeof req.body.name === 'string' ? req.body.name.trim() : '';
    if (!name) return fail(422, 'validation_failed', 'name is required.', { field: 'name' });
    // Known already: in the Library, waiting for the next refresh, or a suggestion (the fixtures' or
    // one a refresh found). The controller keeps one row per playlist, so the mock refuses it.
    const id = f.fakeId(name);
    const known =
      w.data.library.some((i) => i.id === id) ||
      w.data.inSpotify.some((p) => f.fakeId(p.name) === id) ||
      [...f.suggestions, ...w.data.foundSuggestions].some((p) => p.id === id);
    if (known) return fail(409, 'already_added', 'A playlist with that name is already there.');
    w.addInSpotify(name, req.body.followed === true);
    return noContent;
  },
  'POST /__mock/logs': (w, req) => {
    // {"empty": true}: no lines. {"burst": 500}: that many lines at once (the live cap).
    // {"read_budget": 20}: a page looks at 20 lines at most (the controller's 8 MB), until the next reset.
    // {"add": [{"source": "controller", "level": "error", "message": "…"}]}: lines now.
    if (req.body.empty === true) {
      w.logs.empty();
      return noContent;
    }
    if (req.body.read_budget !== undefined) {
      const budget = Number(req.body.read_budget);
      if (!Number.isInteger(budget) || budget < 1) return fail(422, 'validation_failed', 'read_budget is 1 or more.');
      w.logs.setReadBudget(budget);
      return noContent;
    }
    if (req.body.burst !== undefined) {
      const burst = Number(req.body.burst);
      if (!Number.isInteger(burst) || burst < 1 || burst > 5000) return fail(422, 'validation_failed', 'burst is 1 to 5000.');
      w.logs.burst(burst);
      return noContent;
    }
    const add = req.body.add;
    if (!Array.isArray(add)) return fail(422, 'validation_failed', 'Send empty, burst or add.');
    const lines = add as { source: (typeof LOG_SOURCES)[number]; level: (typeof LOG_LEVELS)[number]; message: string }[];
    if (lines.some((l) => !LOG_SOURCES.includes(l.source) || !LOG_LEVELS.includes(l.level) || typeof l.message !== 'string')) {
      return fail(422, 'validation_failed', 'Each line has a source, a level and a message.');
    }
    w.logs.addLines(lines);
    return noContent;
  },
  'POST /__mock/storage': (w, req) => {
    w.data.storage = req.body.mounted === false ? f.storageNotMounted : f.storageOk;
    return ok(w.storageChecked());
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
