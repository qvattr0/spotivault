// @vitest-environment node
// The mock against the contract: it answers every operation in contracts/openapi.yaml, and the
// live store works over its socket: a whole run, and the socket misbehaving.

import { readFileSync } from 'node:fs';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { createApiClient } from '../src/api/client.ts';
import type { EventType, RunStateEvent } from '../src/state/events.ts';
import { createLiveRest } from '../src/state/rest.ts';
import { createLiveStore, type LiveStore } from '../src/state/store.ts';
import { route } from './routes.ts';
import { startMockServer, type MockServer } from './server.ts';

/** Every `METHOD /path` in the contract, read from openapi.yaml's layout (two-space path keys). */
function contractOperations(): string[] {
  const yaml = readFileSync(new URL('../../contracts/openapi.yaml', import.meta.url), 'utf8');
  const ops: string[] = [];
  let path = '';
  for (const line of yaml.split('\n')) {
    const p = /^ {2}(\/api\/[^:]*):\s*$/.exec(line);
    if (p) path = p[1] ?? '';
    const m = /^ {4}(get|put|post|patch|delete):\s*$/.exec(line);
    if (m && path) ops.push(`${m[1]?.toUpperCase()} ${path}`);
  }
  return ops;
}

let mock: MockServer;
let base: string;

beforeAll(async () => {
  // 20 times faster: a run of Liked Songs takes about a second.
  mock = await startMockServer({ port: 0, quiet: true, speed: 20 });
  base = `http://localhost:${mock.port}`;
});
afterAll(() => mock.close());

function post(path: string, body: unknown = {}) {
  return fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/** A live store on the mock's socket, reading REST from the mock too, once its hello is in. */
async function connectedStore(): Promise<LiveStore> {
  const store = createLiveStore({ rest: createLiveRest(createApiClient(base)) });
  store.connect(`ws://localhost:${mock.port}/api/events`);
  await expect.poll(() => store.getState().ready).toBe(true);
  return store;
}

describe('mock backend', () => {
  it('has a route for every operation in the contract', () => {
    const ops = contractOperations();
    expect(ops.length).toBeGreaterThan(40);
    const missing = ops.filter((op) => {
      const [method, path] = op.split(' ') as [string, string];
      // {id} -> a sample value, so the mock's :id patterns match.
      return route(method, path.replace(/\{[^}]+\}/g, 'x')) === null;
    });
    expect(missing).toEqual([]);
  });

  it('answers every GET without parameters with 200', async () => {
    const gets = contractOperations().filter((op) => op.startsWith('GET ') && !op.includes('{'));
    for (const op of gets) {
      const response = await fetch(base + op.slice(4));
      expect(response.status, op).toBe(200);
    }
  });

  it('sends hello, then run events after Run now', async () => {
    const store = createLiveStore();
    store.connect(`ws://localhost:${mock.port}/api/events`);
    await expect.poll(() => store.getState().ready).toBe(true);
    expect(store.getState().status?.state).toBe('idle');

    const response = await fetch(`${base}/api/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    expect(response.status).toBe(202);
    await expect.poll(() => store.getState().status?.state, { timeout: 4000 }).toBe('running');

    store.disconnect();
  });
});

describe('the live store against the mock', () => {
  it('follows a whole run: phases, tracks, levels, the backlog, the end', async () => {
    await post('/__mock/scenario', { scenario: 'idle' });
    const store = await connectedStore();
    const runStates: RunStateEvent['state'][] = [];
    const seen = new Set<EventType>();
    store.onAnyEvent((event) => {
      seen.add(event.type);
      if (event.type === 'run.state' && runStates.at(-1) !== event.data.state) runStates.push(event.data.state);
    });

    expect((await post('/api/runs', { items: ['liked'] })).status).toBe(202);
    await expect.poll(() => store.getState().queue?.length, { timeout: 3000 }).toBe(1);
    await expect.poll(() => runStates.at(-1), { timeout: 8000 }).toBe('idle');

    expect(runStates).toEqual(['starting', 'running', 'finishing', 'running', 'idle']);
    for (const type of ['run.queue', 'item.state', 'session.state', 'track.started', 'track.skipped', 'track.finished', 'level', 'backlog', 'run.finished', 'library.item'] as const) {
      expect(seen, type).toContain(type);
    }
    expect(store.getState().queue).toEqual([]);
    expect(store.getLevel()).toBeNull();
    store.disconnect();
  });

  it('copes with the socket misbehaving: a drop, a lost event, a 1013, a restart', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'info').mockImplementation(() => {});
    await post('/__mock/scenario', { scenario: 'idle' });
    const store = await connectedStore();
    const boot = store.getState().bootId;

    // The line drops: it reconnects to the same controller, and counts a resync.
    await post('/__mock/drop');
    await expect.poll(() => store.getState().resyncs, { timeout: 4000 }).toBe(1);
    expect(store.getState().socket).toBe('open');
    expect(store.getState().bootId).toBe(boot);

    // An event goes missing: the state is read again through REST.
    await post('/__mock/gap');
    await expect.poll(() => store.getState().resyncs, { timeout: 4000 }).toBe(2);
    expect(console.warn).toHaveBeenCalledWith(expect.stringContaining('seq gap'));

    // Too slow: 1013, then a new hello.
    await post('/__mock/slow');
    await expect.poll(() => store.getState().resyncs, { timeout: 4000 }).toBe(3);

    // A restart: a new boot_id.
    const restarted = (await (await post('/__mock/restart')).json()) as { boot_id: string };
    await expect.poll(() => store.getState().bootId, { timeout: 4000 }).toBe(restarted.boot_id);
    expect(restarted.boot_id).not.toBe(boot);
    expect(store.getState().lastSeq).toBe(0);

    store.disconnect();
    vi.restoreAllMocks();
  });
});
