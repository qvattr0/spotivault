// @vitest-environment node
// The mock's S8 additions against the contract and web-ui.md: the scenarios and controls the
// pages' states need, link resolving, Back up now's `added`, and the run cut short.

import { afterEach, describe, expect, it } from 'vitest';
import { createHub, type Hub } from './hub.ts';
import { ELSEWHERE, fakeId, suggestions } from './fixtures.ts';
import { handle } from './routes.ts';
import { createWorld, type World } from './world.ts';
import type { Scenario } from './fixtures.ts';
import type { EventMap } from '../src/state/events.ts';

let open: { world: World; hub: Hub }[] = [];

function worldIn(scenario: Scenario, speed = 50): World {
  const hub = createHub({ background: true });
  const world = createWorld(hub, scenario, { speed });
  open.push({ world, hub });
  return world;
}

afterEach(() => {
  for (const { world, hub } of open) {
    world.close();
    hub.close();
  }
  open = [];
});

function call(world: World, method: string, path: string, body: Record<string, unknown> = {}) {
  return handle(world, method, new URL(`http://mock${path}`), body);
}

const until = async (check: () => boolean, ms = 8000) => {
  await expect.poll(check, { timeout: ms, interval: 20 }).toBe(true);
};

/** The `error` events the world publishes from now on. */
function recordErrors(world: World): EventMap['error'][] {
  const errors: EventMap['error'][] = [];
  const publish = world.hub.publish.bind(world.hub);
  world.hub.publish = (type, data) => {
    if (type === 'error') errors.push(data as EventMap['error']);
    publish(type, data);
  };
  return errors;
}

describe('scenarios', () => {
  it('starts the wizard at any step, with the facts behind it', () => {
    const world = worldIn('idle');
    expect(call(world, 'POST', '/__mock/scenario', { scenario: 'setup', step: 'webapi' }).body).toMatchObject({ step: 'webapi' });
    expect(world.setup().first_unfinished).toBe('webapi');
    expect(world.data.client.logged_in).toBe(true);
    expect(world.data.connection.state).toBe('not_configured');

    call(world, 'POST', '/__mock/scenario', { scenario: 'setup', step: 'output' });
    expect(world.setup().first_unfinished).toBe('output');
    call(world, 'POST', '/__mock/storage', { mounted: true });
    expect(world.setup().first_unfinished).toBe('playlists');

    expect(call(world, 'POST', '/__mock/scenario', { scenario: 'idle', step: 'tos' }).status).toBe(422);
  });

  it("has a 'new' scenario: never run, no schedule, no albums", () => {
    const world = worldIn('new');
    expect(call(world, 'GET', '/api/runs').body).toMatchObject({ runs: [] });
    expect(call(world, 'GET', '/api/runs/last').body).toEqual({ run: null, issues: [] });
    expect(call(world, 'GET', '/api/schedule/next').body).toMatchObject({ at: null, held_reason: null });
    expect(call(world, 'GET', '/api/albums').body).toMatchObject({ items: [], summary: { total: 0 } });
  });
});

describe('the Library', () => {
  it('resolves links as the controller does', () => {
    const world = worldIn('idle');
    const resolve = (url: string) => call(world, 'POST', '/api/library/resolve', { url });
    expect(resolve('not a link').body).toMatchObject({ error: { code: 'invalid_url' } });
    expect(resolve('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M').body).toMatchObject({ error: { code: 'spotify_owned' } });
    expect(resolve(`spotify:playlist:${'privateplaylist'.padEnd(22, '0')}`).body).toMatchObject({ error: { code: 'private' } });
    expect(resolve(`spotify:playlist:${'nosuchplaylist'.padEnd(22, '0')}`).body).toMatchObject({ error: { code: 'not_found' } });
    expect(resolve(`https://open.spotify.com/playlist/${fakeId('fridayfinds')}?si=x`).body).toMatchObject({ kind: 'linked', total: null });
    expect(resolve(`spotify:playlist:${suggestions[0]?.id}`).body).toMatchObject({ kind: 'followed', total: 50, already_added: false });
  });

  it('adds a followed playlist with its total, then refuses it again; 409 and 503 when Spotify cannot be asked', () => {
    const world = worldIn('idle');
    const url = `spotify:playlist:${suggestions[0]?.id}`;
    expect(call(world, 'POST', '/api/library', { url })).toMatchObject({ status: 201, body: { kind: 'followed', total: 50, tracked: true } });
    expect(call(world, 'POST', '/api/library', { url }).body).toMatchObject({ error: { code: 'already_added' } });
    call(world, 'POST', '/__mock/spotify', { state: 'rate_limited' });
    expect(call(world, 'POST', '/api/library/resolve', { url })).toMatchObject({ status: 503, body: { error: { code: 'rate_limited' } } });
    call(world, 'POST', '/__mock/connection', { state: 'disconnected' });
    expect(call(world, 'POST', '/api/library/resolve', { url })).toMatchObject({ status: 409, body: { error: { code: 'not_connected' } } });
  });

  it('counts the summary from the Library, and untracks with auto-tracking off before setup completes', () => {
    const world = worldIn('setup');
    expect(call(world, 'GET', '/api/library/summary').body).toMatchObject({ owned_count: 5, liked_tracked: true });
    call(world, 'PUT', '/api/settings', { auto_track_owned: false });
    expect(call(world, 'GET', '/api/library/summary').body).toMatchObject({ owned_tracked: 0, liked_tracked: false, auto_track_owned: false });
    expect(world.setup().steps.find((s) => s.id === 'playlists')?.state).toBe('done');
  });

  it('refreshes the Library as the controller does: one at a time, and finds what was made in Spotify', async () => {
    const world = worldIn('idle');
    const seen: { type: string; data: unknown }[] = [];
    const publish = world.hub.publish.bind(world.hub);
    world.hub.publish = (type, data) => {
      if (type === 'catalog.refresh' || type === 'library.item') seen.push({ type, data });
      publish(type, data);
    };
    expect(call(world, 'POST', '/__mock/new-playlist', { name: 'Test Playlist' }).status).toBe(204);
    expect(call(world, 'POST', '/__mock/new-playlist', { name: 'Friday Mix', followed: true }).status).toBe(204);
    expect(call(world, 'POST', '/__mock/new-playlist', { name: 'Test Playlist' }).status).toBe(409);
    expect(call(world, 'GET', '/api/library').body).not.toMatchObject({ items: expect.arrayContaining([expect.objectContaining({ name: 'Test Playlist' })]) });

    expect(call(world, 'POST', '/api/library/refresh')).toEqual({ status: 202, body: { state: 'started', refresh_id: null } });
    expect(call(world, 'POST', '/api/library/refresh')).toEqual({ status: 202, body: { state: 'running', refresh_id: 57 } });
    await until(() => seen.some((e) => e.type === 'catalog.refresh' && (e.data as { state: string }).state === 'ended'));

    const id = fakeId('Test Playlist');
    expect(seen.map((e) => [e.type, (e.data as { state?: string; id?: string }).state ?? (e.data as { id: string }).id])).toEqual([
      ['catalog.refresh', 'started'],
      ['library.item', id],
      ['catalog.refresh', 'ended'],
    ]);
    expect(seen.at(-1)?.data).toEqual({
      refresh_id: 57, trigger: 'manual', state: 'ended', outcome: 'ok', items_changed: 1, items_added: 1, suggestions_added: 1,
      reason: null,
    });
    expect(call(world, 'GET', '/api/library').body).toMatchObject({
      items: expect.arrayContaining([expect.objectContaining({ id, kind: 'owned', tracked: true, status: 'never_backed_up' })]),
    });
    expect(call(world, 'GET', '/api/library/suggestions').body).toMatchObject({
      items: expect.arrayContaining([expect.objectContaining({ name: 'Friday Mix', kind: 'followed' })]),
    });

    // Both are known now, as in the controller (one row per playlist): the same again is refused.
    expect(call(world, 'POST', '/__mock/new-playlist', { name: 'Friday Mix', followed: true }).status).toBe(409);
    expect(call(world, 'POST', '/__mock/new-playlist', { name: 'Test Playlist' }).status).toBe(409);

    // The next one finds nothing new, and the + modal lists each suggestion once.
    expect(call(world, 'POST', '/api/library/refresh').body).toEqual({ state: 'started', refresh_id: null });
    await until(() => seen.filter((e) => e.type === 'catalog.refresh').length === 4);
    expect(seen.at(-1)?.data).toMatchObject({ refresh_id: 58, items_added: 0, suggestions_added: 0 });
    const listed = (call(world, 'GET', '/api/library/suggestions').body as { items: { id: string }[] }).items.map((s) => s.id);
    expect(new Set(listed).size).toBe(listed.length);
  });

  it('refuses a refresh during a run, and without a connection', () => {
    expect(call(worldIn('running'), 'POST', '/api/library/refresh')).toMatchObject({ status: 409, body: { error: { code: 'run_active' } } });
    const world = worldIn('idle');
    call(world, 'POST', '/__mock/connection', { state: 'disconnected' });
    expect(call(world, 'POST', '/api/library/refresh')).toMatchObject({ status: 409, body: { error: { code: 'not_connected' } } });
  });

  it('refuses an invalid layout with its reason', () => {
    const world = worldIn('idle');
    const layout = { pattern: '{album_artist}/{genre}', prefix: 'none', underscores: false, strip_accents: false };
    expect(call(world, 'PUT', '/api/settings', { layout }).body).toMatchObject({
      error: { code: 'invalid_layout', details: { reason: 'unknown_placeholder', placeholder: '{genre}' } },
    });
  });
});

describe('step 4 and Run setup again', () => {
  it('reads the checklist without changing it; the control changes it', () => {
    const world = worldIn('setup');
    const read = () => call(world, 'GET', '/api/client/checklist').body as { ready: boolean; rows: { id: string; state: string | null }[] };
    expect(read().ready).toBe(false);
    expect(read().rows.find((r) => r.id === 'normalization')?.state).toBe('needs_change');
    call(world, 'POST', '/__mock/checklist', { rows: { normalization: 'ok', gapless: false } });
    expect(read().rows.find((r) => r.id === 'normalization')?.state).toBe('ok');
    expect(world.setup().first_unfinished).toBe('client_settings');
    expect(call(world, 'POST', '/__mock/checklist', { rows: { mono: 'maybe' } }).status).toBe(422);
    call(world, 'POST', '/__mock/checklist', { ready: true });
    expect(read().ready).toBe(true);
    expect(world.setup().first_unfinished).toBe('webapi');
  });

  it("tidies the client's settings a few seconds after a login in the wizard", async () => {
    const world = worldIn('setup');
    call(world, 'POST', '/__mock/scenario', { scenario: 'setup', step: 'login' });
    expect(world.data.checklist.ready).toBe(false);
    call(world, 'POST', '/__mock/login', { logged_in: true });
    await until(() => world.data.checklist.ready);
  });

  it('answers Run setup again with step 2 first, as the contract says, then checks the facts at once', () => {
    const world = worldIn('idle');
    const answer = call(world, 'POST', '/api/setup/restart').body as { first_unfinished: string; completed: boolean };
    expect(answer).toMatchObject({ first_unfinished: 'client', completed: false });
    // As in the controller (tests/test_setup.py): the live checks follow the reset and turn steps 2
    // to 4 and 6 done again, so the wizard walks on from step 2. Step 5 isn't a live check: it
    // waits for its device check, which its page runs (GET /api/spotify/devices).
    const steps = () => Object.fromEntries(world.setup().steps.map((s) => [s.id, s.state]));
    expect(world.setup()).toMatchObject({ first_unfinished: 'webapi', completed: false });
    expect(steps()).toMatchObject({ client: 'done', login: 'done', client_settings: 'done', webapi: 'active', output: 'done' });
    expect(call(world, 'GET', '/api/spotify/devices').body).toMatchObject({ ours: { name: 'spotivault' } });
    expect(world.setup()).toMatchObject({ first_unfinished: 'playlists', completed: false });
  });
});

describe('step 5', () => {
  it('takes a pasted address once per Authorize, and checks our device', () => {
    const world = worldIn('setup');
    call(world, 'POST', '/__mock/scenario', { scenario: 'setup', step: 'webapi' });
    call(world, 'POST', '/api/spotify/app', { client_id: '0123456789abcdef0123456789abcdef' });
    const finish = (url: string) => call(world, 'POST', '/api/spotify/auth/finish', { redirect_url: url });
    expect(finish('http://127.0.0.1:8888/callback?code=x&state=k7Qm2c').body).toMatchObject({ error: { code: 'no_pending_auth' } });
    call(world, 'POST', '/api/spotify/auth/start');
    // As in the controller: a decline or an older address leaves the pending authorization alone.
    expect(finish('http://127.0.0.1:8888/callback?error=access_denied&state=k7Qm2c').body).toMatchObject({ error: { code: 'access_denied' } });
    expect(finish('http://127.0.0.1:8888/callback?code=x&state=old').body).toMatchObject({ error: { code: 'state_mismatch' } });
    // A refused code uses it up.
    expect(finish('http://127.0.0.1:8888/callback?code=bad&state=k7Qm2c').body).toMatchObject({ error: { code: 'token_exchange_failed' } });
    expect(finish('http://127.0.0.1:8888/callback?code=x&state=k7Qm2c').body).toMatchObject({ error: { code: 'no_pending_auth' } });
    call(world, 'POST', '/api/spotify/auth/start');
    call(world, 'POST', '/__mock/devices', { listed: false });
    expect(finish('http://127.0.0.1:8888/callback?code=x&state=k7Qm2c').body).toMatchObject({ state: 'ok', display_name: 'Lorne' });
    expect(call(world, 'GET', '/api/spotify/devices').body).toMatchObject({ ours: null });
    expect(world.setup().first_unfinished).toBe('webapi');
    // Listed now: step 5 turns done at the next device check (Retry), not by itself.
    call(world, 'POST', '/__mock/devices', { listed: true });
    expect(world.setup().first_unfinished).toBe('webapi');
    call(world, 'GET', '/api/spotify/devices');
    expect(world.setup().first_unfinished).toBe('playlists');
  });

  it('marks step 5 done right after the authorization when our device is listed', () => {
    const world = worldIn('setup');
    call(world, 'POST', '/__mock/scenario', { scenario: 'setup', step: 'webapi' });
    call(world, 'POST', '/api/spotify/app', { client_id: '0123456789abcdef0123456789abcdef' });
    call(world, 'POST', '/api/spotify/auth/start');
    call(world, 'POST', '/api/spotify/auth/finish', { redirect_url: 'http://127.0.0.1:8888/callback?code=x&state=k7Qm2c' });
    expect(world.setup().first_unfinished).toBe('playlists');
  });
});

describe('runs', () => {
  it("answers Back up now's `added` as the contract says", async () => {
    const world = worldIn('idle');
    const started = call(world, 'POST', '/api/runs', { items: ['liked', fakeId('chillmix')] });
    expect(started.body).toMatchObject({ started: true, added: ['liked', fakeId('chillmix')] });
    await until(() => world.data.status.item?.item_id === 'liked');
    // The current item isn't added again; a waiting one moves up with a new one.
    const joined = call(world, 'POST', '/api/runs', { items: ['liked', fakeId('indiefinds'), fakeId('chillmix')] });
    expect(joined.body).toMatchObject({ started: false, added: [fakeId('indiefinds'), fakeId('chillmix')] });
    expect(world.data.library.find((i) => i.id === fakeId('indiefinds'))?.status).toBe('queued');
    expect(call(world, 'DELETE', `/api/runs/current/items/${fakeId('indiefinds')}`).status).toBe(204);
    expect(world.data.queue.find((q) => q.item_id === fakeId('indiefinds'))).toMatchObject({ state: 'removed', badges: ['removed'] });
    expect(call(world, 'POST', '/api/runs', { items: [fakeId('indiefinds')] }).body).toMatchObject({ added: [] });
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
    expect(world.data.library.find((i) => i.id === fakeId('indiefinds'))?.status).toBe('up_to_date');
  });

  it('builds the queue after the pre-run check, as the controller does; Back up now meanwhile goes first', async () => {
    const world = worldIn('idle', 10);
    call(world, 'POST', '/__mock/client', { running: false });
    const started = call(world, 'POST', '/api/runs', {}).body as { run_id: number };
    // Starting: the run has no items yet, on the Dashboard or on its run page.
    expect(call(world, 'GET', '/api/runs/current').body).toMatchObject({ run: { state: 'starting' }, queue: [] });
    expect(call(world, 'GET', `/api/runs/${started.run_id}`).body).toMatchObject({ items: [] });
    // Back up now while it starts: answered as added, and first once the queue is built.
    const album = world.data.albums.find((a) => a.status === 'queued')?.id ?? '';
    expect(call(world, 'POST', '/api/runs', { items: [album] }).body).toMatchObject({ started: false, added: [album] });
    expect(call(world, 'POST', '/api/runs', { items: [album] }).body).toMatchObject({ added: [] });
    await until(() => world.data.status.state === 'running');
    const queue = (call(world, 'GET', '/api/runs/current').body as { queue: { item_id: string }[] }).queue;
    expect(queue.map((q) => q.item_id).slice(0, 2)).toEqual([album, 'liked']);
    expect((call(world, 'GET', `/api/runs/${started.run_id}`).body as { items: unknown[] }).items).toHaveLength(queue.length);
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
  });

  it('a stop while the run starts ends it before its queue is built: no items', async () => {
    const world = worldIn('idle');
    call(world, 'POST', '/api/runs', {});
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
    const row = world.data.history[0];
    expect(row).toMatchObject({ outcome: 'stopped' });
    expect(call(world, 'GET', `/api/runs/${row?.id}`).body).toMatchObject({ items: [] });
  });

  it('a takeover sends its events in the controller\'s order: item.state, run.state paused, then device.moved', async () => {
    const world = worldIn('idle', 10);
    call(world, 'POST', '/api/runs', { items: ['liked'] });
    // Only mid-track: before a track records, the control is refused.
    expect(call(world, 'POST', '/__mock/takeover').status).toBe(409);
    await until(() => world.data.status.session_state === 'recording');
    const events: string[] = [];
    const publish = world.hub.publish.bind(world.hub);
    world.hub.publish = (type, data) => {
      if (type === 'item.state') events.push(`item.state ${(data as EventMap['item.state']).item.state}`);
      else if (type === 'run.state') events.push(`run.state ${(data as EventMap['run.state']).state}`);
      else if (type === 'device.moved') events.push(`device.moved ${(data as EventMap['device.moved']).device.name}`);
      publish(type, data);
    };
    expect(call(world, 'POST', '/__mock/takeover').status).toBe(204);
    await until(() => world.data.status.state === 'paused');
    expect(events).toEqual(['item.state interrupted', 'run.state paused', "device.moved Lorne's iPhone"]);
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
  });

  it('a scenario switch ends a paused run for good: it never ends the next world\'s run', async () => {
    const world = worldIn('idle', 10);
    call(world, 'POST', '/api/runs', { items: ['liked'] });
    await until(() => world.data.status.session_state === 'recording');
    call(world, 'POST', '/__mock/takeover');
    await until(() => world.data.status.state === 'paused');
    call(world, 'POST', '/__mock/scenario', { scenario: 'idle' });
    call(world, 'POST', '/api/runs', { items: ['liked'] });
    // Longer than the old run's wrap-up, which used to end this one.
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(world.data.status.state).not.toBe('idle');
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
  });

  it('moves a stalled item to the end as Interrupted · will retry', async () => {
    const world = worldIn('idle');
    call(world, 'POST', '/api/runs', { items: [fakeId('chillmix'), 'liked'] });
    await until(() => world.data.status.session_state === 'recording');
    expect(call(world, 'POST', '/__mock/stall').status).toBe(204);
    await until(() => world.data.queue.at(-1)?.state === 'interrupted');
    expect(world.data.queue.at(-1)?.item_id).toBe(fakeId('chillmix'));
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
  });

  it('ends the window: Carried over, then Window ended', async () => {
    const world = worldIn('idle');
    call(world, 'POST', '/api/runs', { items: [fakeId('chillmix'), 'liked'] });
    await until(() => world.data.status.session_state === 'recording');
    expect(call(world, 'POST', '/__mock/window-end').status).toBe(204);
    await until(() => world.data.status.state === 'idle');
    const row = world.data.history[0];
    expect(row?.outcome).toBe('window_ended');
    const items = (call(world, 'GET', `/api/runs/${row?.id}`).body as { items: { state: string; badges: string[] }[] }).items;
    expect(items.map((i) => i.state)).toEqual(['carried_over', 'stopped']);
    expect(items[0]?.badges).toContain('carried_over_out');
  });

  it('remembers the item a window end cut off: the next run marks it Carried over', async () => {
    const world = worldIn('running');
    await until(() => world.data.status.session_state === 'recording');
    call(world, 'POST', '/__mock/window-end');
    await until(() => world.data.status.state === 'idle');
    expect([...world.data.carriedOver]).toEqual(['liked']);
    // A run of one album; then Back up now on Liked Songs: it waits after the album, Carried over.
    const album = world.data.albums.find((a) => a.status === 'queued')?.id ?? '';
    call(world, 'POST', '/api/runs', { items: [album] });
    await until(() => world.data.status.item?.item_id === album);
    call(world, 'POST', '/api/runs', { items: ['liked'] });
    expect(world.data.queue.map((q) => [q.item_id, q.badges])).toEqual([[album, []], ['liked', ['carried_over_in']]]);
    // Stopped before its turn came: it's still waiting from the last window.
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
    expect(world.data.carriedOver.has('liked')).toBe(true);
  });

  it('a client that is not running is restarted by the run, which goes on', async () => {
    const world = worldIn('idle');
    const errors = recordErrors(world);
    expect(call(world, 'POST', '/__mock/client', { running: false }).body).toMatchObject({ running: false, logged_in: false });
    // Not held, and Run now is allowed: the run restarts the client (controller: engine/precheck.py).
    expect(call(world, 'GET', '/api/schedule/next').body).toMatchObject({ held_reason: null });
    expect(call(world, 'POST', '/api/runs', {}).status).toBe(202);
    await until(() => world.data.status.state === 'running');
    expect(errors).toEqual([expect.objectContaining({ source: 'controller', code: 'client_restarted', fatal: false })]);
    expect(world.data.client).toMatchObject({ running: true, logged_in: true });
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
  });

  it("fails the run when the client's device doesn't come back", async () => {
    const world = worldIn('idle');
    call(world, 'POST', '/__mock/client', { running: false, comes_back: false });
    call(world, 'POST', '/api/runs', {});
    await until(() => world.data.status.state === 'idle');
    const row = world.data.history[0];
    expect(row).toMatchObject({ outcome: 'failed', reason: 'device_missing' });
    expect(call(world, 'GET', `/api/runs/${row?.id}`).body).toMatchObject({ items: [] });
  });

  it("keeps each item's track results for its run page", async () => {
    const world = worldIn('idle');
    call(world, 'POST', '/api/runs', { items: ['liked'] });
    await until(() => world.data.status.session_state === 'recording');
    call(world, 'POST', '/api/runs/current/stop', { mode: 'now' });
    await until(() => world.data.status.state === 'idle');
    const id = world.data.history[0]?.id;
    const tracks = (call(world, 'GET', `/api/runs/${id}/items/liked/tracks`).body as { tracks: { result: string; reason: string | null }[] }).tracks;
    expect(tracks.map((t) => [t.result, t.reason])).toEqual([['skipped', 'duplicate'], ['failed', 'discarded']]);
    expect(call(world, 'GET', `/api/runs/${id}/items/nothere/tracks`).status).toBe(404);
    // A sample run's up-to-date item played nothing.
    expect(call(world, 'GET', `/api/runs/41/items/${ELSEWHERE}/tracks`).body).toEqual({ tracks: [] });
  });

  it("lists an album's tracks as its state says, with ids unique per album", () => {
    const world = worldIn('idle');
    const tracksOf = (name: string) => {
      const album = world.data.albums.find((a) => a.name === name);
      return (call(world, 'GET', `/api/albums/${album?.id}/tracks`).body as { tracks: { track_id: string; state: string; path: string | null }[] }).tracks;
    };
    const queued = tracksOf('In Rainbows');
    expect(new Set(queued.map((t) => t.state))).toEqual(new Set(['missing']));
    expect(queued.every((t) => t.path === null)).toBe(true);
    const partial = tracksOf('Elsewhere');
    expect(partial.map((t) => t.state).slice(-2)).toEqual(['failed', 'missing']);
    expect(new Set(partial.map((t) => t.track_id)).size).toBe(partial.length);
  });

  it('pages History with a cursor', () => {
    const world = worldIn('idle');
    call(world, 'POST', '/__mock/history', { older: 60 });
    const first = call(world, 'GET', '/api/runs?limit=50').body as { runs: unknown[]; next_cursor: string | null };
    expect(first.runs).toHaveLength(50);
    const second = call(world, 'GET', `/api/runs?limit=50&cursor=${first.next_cursor}`).body as { runs: unknown[]; next_cursor: string | null };
    expect(second.runs).toHaveLength(19);
    expect(second.next_cursor).toBeNull();
  });
});
