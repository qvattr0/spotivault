import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BOOT_ID, helloFor, queueItem, runRunning, statusRunning } from '@mock/fixtures.ts';
import type { QueueItem } from '@/api/types.ts';
import { fakeSockets, type FakeSocket, type FakeSockets } from '@/test/fake-socket.ts';
import { envelope } from '@/test/live.ts';
import type { EventMap, EventType, Hello } from './events.ts';
import type { LiveRest, Snapshot } from './rest.ts';
import { createLiveStore, FALLBACK_AFTER_MS, FALLBACK_EVERY_MS, QUEUE_RETRY_FIRST_MS, type LiveStore } from './store.ts';

// --- Helpers: a fake REST side, and a server that numbers its events --------------------------------

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** REST reads that wait until the test answers them. */
function fakeRest() {
  const snapshots: Deferred<Snapshot>[] = [];
  const queues: Deferred<QueueItem[]>[] = [];
  const rest: LiveRest = {
    snapshot: vi.fn(() => {
      const d = deferred<Snapshot>();
      snapshots.push(d);
      return d.promise;
    }),
    queue: vi.fn(() => {
      const d = deferred<QueueItem[]>();
      queues.push(d);
      return d.promise;
    }),
    bootId: vi.fn(async () => BOOT_ID),
  };
  return { rest, snapshots, queues };
}

/** Lets awaited promises run. */
async function settle() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

/** The server's side of one connection: hello, then events numbered from hello.seq + 1. */
function server(socket: FakeSocket, firstSeq = 100) {
  let seq = firstSeq;
  const at = '2026-11-15T01:00:00.000Z';
  return {
    hello(data: Hello) {
      socket.accept();
      socket.deliver({ seq, type: 'hello', at, data });
    },
    send<K extends Exclude<EventType, 'hello' | 'level'>>(type: K, data: EventMap[K]) {
      seq += 1;
      socket.deliver({ seq, type, at, data });
    },
    /** An event the client never gets: the next one shows a gap. */
    lose() {
      seq += 1;
    },
    level(peak: number) {
      socket.deliver({ seq: null, type: 'level', at, data: { peak_dbfs: peak, rms_dbfs: peak - 14, channels: [] } });
    },
  };
}

const playing = statusRunning.item!;
const upNext = queueItem({ item_id: 'liked', kind: 'liked', name: 'Liked Songs' });
const runningQueue = [playing, upNext];

function snapshotFrom(hello: Hello, queue: QueueItem[] = []): Snapshot {
  return { setup: hello.setup, status: hello.status, connection: hello.connection, client: hello.client, queue };
}

let sockets: FakeSockets;
let rest: ReturnType<typeof fakeRest>;
let store: LiveStore;

beforeEach(() => {
  sockets = fakeSockets();
  rest = fakeRest();
  store = createLiveStore({ openSocket: sockets.open, rest: rest.rest });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'info').mockImplementation(() => {});
});

afterEach(() => {
  store.disconnect();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// --- Without a socket (tests and the gallery) ---------------------------------------------------------

describe('createLiveStore without a socket', () => {
  it('notifies subscribers and event handlers after the state changes', () => {
    const local = createLiveStore();
    const listener = vi.fn();
    const seen: string[] = [];
    local.subscribe(listener);
    local.onEvent('hello', (e) => seen.push(`${e.data.version}:${local.getState().ready}`));

    local.dispatch(envelope('hello', helloFor('idle')));

    expect(listener).toHaveBeenCalledTimes(1);
    expect(seen).toEqual(['0.1.0:true']);
  });

  it('keeps level apart from the state, and drops it when the run ends', () => {
    const local = createLiveStore();
    local.dispatch(envelope('hello', helloFor('running')));
    const stateListener = vi.fn();
    local.subscribe(stateListener);

    local.dispatch(envelope('level', { peak_dbfs: -3, rms_dbfs: -17, channels: [] }));
    expect(local.getLevel()?.level.peak_dbfs).toBe(-3);
    expect(stateListener).not.toHaveBeenCalled();

    local.dispatch(envelope('run.state', { ...runRunning, state: 'idle', previous_state: 'running' }));
    expect(local.getLevel()).toBeNull();
  });

  it('starts from the given state', () => {
    const local = createLiveStore({ initial: { socket: 'open' } });
    expect(local.getState().socket).toBe('open');
    expect(local.getState().ready).toBe(false);
  });
});

// --- Over the socket ----------------------------------------------------------------------------------

describe('createLiveStore over the socket', () => {
  it('opens /api/events, and takes the state from hello', () => {
    store.connect('ws://test/api/events');
    expect(store.getState().socket).toBe('connecting');
    expect(sockets.latest().url).toBe('ws://test/api/events');

    server(sockets.latest()).hello(helloFor('idle'));
    const state = store.getState();
    expect(state.socket).toBe('open');
    expect(state.ready).toBe(true);
    expect(state.lastSeq).toBe(100);
    // No run: the queue is known to be empty, and nothing is read through REST.
    expect(state.queue).toEqual([]);
    expect(rest.rest.queue).not.toHaveBeenCalled();
  });

  it('reads the queue after a hello with a run, and holds events back until it is in', async () => {
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('running'));
    expect(store.getState().queue).toBeNull();
    expect(rest.rest.queue).toHaveBeenCalledTimes(1);

    const seen: string[] = [];
    store.onEvent('item.state', (e) => seen.push(e.data.item.state));
    srv.send('item.state', { run_id: 42, item: { ...playing, state: 'finishing' }, previous_state: 'playing' });
    // Held back: not applied yet.
    expect(store.getState().status?.item?.state).toBe('playing');
    expect(seen).toEqual([]);

    rest.queues[0]?.resolve(runningQueue);
    await settle();
    const state = store.getState();
    expect(state.queue?.map((q) => q.state)).toEqual(['finishing', 'up_next']);
    expect(state.status?.item?.state).toBe('finishing');
    expect(state.lastSeq).toBe(101);
    expect(seen).toEqual(['finishing']);
  });

  it('reads the queue of a new run', async () => {
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('idle'));
    srv.send('run.state', { ...runRunning, id: 43, state: 'starting', previous_state: 'idle' });
    expect(store.getState().status?.run?.id).toBe(43);
    expect(store.getState().queue).toBeNull();
    expect(rest.rest.queue).toHaveBeenCalledTimes(1);

    rest.queues[0]?.resolve([upNext]);
    await settle();
    expect(store.getState().queue).toEqual([upNext]);
  });

  it('reloads the state through REST after a seq gap', async () => {
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('idle'));
    srv.lose();
    srv.send('backlog', { ...helloFor('idle').backlog!, items_to_record: 3 });
    expect(console.warn).toHaveBeenCalledWith(expect.stringContaining('seq gap, expected 101, got 102'));
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(1);

    // Events during the read wait for it.
    srv.send('session.state', { run_id: 42, item_id: playing.item_id, state: 'paused' });
    rest.snapshots[0]?.resolve(snapshotFrom(helloFor('running'), runningQueue));
    await settle();

    const state = store.getState();
    expect(state.status?.state).toBe('running');
    expect(state.status?.session_state).toBe('paused'); // applied after the snapshot
    expect(state.queue).toEqual(runningQueue);
    expect(state.backlog?.items_to_record).toBe(3); // the backlog isn't read through REST
    expect(state.resyncs).toBe(1);
  });

  it('reconnects for a fresh hello when the REST read after a gap fails', async () => {
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('idle'));
    srv.lose();
    srv.send('setup.state', helloFor('idle').setup);
    rest.snapshots[0]?.reject(new Error('network'));
    await settle();
    expect(sockets.all).toHaveLength(2);
    expect(sockets.all[0]?.closedByClient).toBe(true);
  });

  it('ignores events before hello, unknown types, malformed events and frames that are not JSON', () => {
    store.connect('ws://test/api/events');
    const socket = sockets.latest();
    socket.accept();
    socket.deliver({ seq: 5, type: 'setup.state', at: '', data: helloFor('fresh').setup });
    expect(store.getState().setup).toBeNull();

    server(socket).hello(helloFor('idle'));
    const before = store.getState();
    socket.deliver({ seq: 101, type: 'log.line', at: '', data: { line: 'x' } });
    socket.deliver({ seq: 'x', type: 'backlog', at: '', data: {} });
    socket.deliver({ seq: 101, type: 'backlog', at: '', data: null });
    socket.deliver('not json');
    expect(store.getState()).toBe(before);
  });

  it('keeps the state on screen while reconnecting, and resyncs on the next hello', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('running'));
    rest.queues[0]?.resolve(runningQueue);
    await settle();
    srv.send('device.moved', { run_id: 42, item_id: playing.item_id, device: { id: 'p', name: 'Pixel 9', type: 'Smartphone' }, discarded_take_id: null });
    srv.send('run.state', { ...runRunning, state: 'paused', paused_reason: 'device_moved', previous_state: 'running' });
    srv.level(-3);
    expect(store.getLevel()).not.toBeNull();

    sockets.latest().drop();
    expect(store.getState().socket).toBe('reconnecting');
    expect(store.getState().status?.state).toBe('paused');
    expect(store.getLevel()).toBeNull(); // the meter falls silent

    vi.advanceTimersByTime(1000);
    expect(sockets.all).toHaveLength(2);
    const paused = helloFor('paused');
    server(sockets.latest(), 200).hello(paused);
    const state = store.getState();
    expect(state.resyncs).toBe(1);
    expect(state.lastSeq).toBe(200);
    // Same controller, same run: the alert and the old queue stay until the queue is read again.
    expect(state.alerts.map((a) => a.kind)).toEqual(['device_moved']);
    expect(state.queue).toEqual(runningQueue);
    expect(rest.rest.queue).toHaveBeenCalledTimes(2);
  });

  it('drops what hello cannot give back when the controller restarted', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    server(sockets.latest()).hello(helloFor('paused'));
    rest.queues[0]?.resolve(runningQueue);
    await settle();
    store.dispatch(envelope('device.moved', { run_id: 42, item_id: null, device: { id: null, name: 'Pixel 9', type: 'Smartphone' }, discarded_take_id: null }));

    sockets.latest().drop(1012);
    vi.advanceTimersByTime(1000);
    server(sockets.latest(), 0).hello({ ...helloFor('paused'), boot_id: 'a-new-boot' });
    const state = store.getState();
    expect(state.bootId).toBe('a-new-boot');
    expect(state.alerts).toEqual([]);
    expect(state.queue).toBeNull();
    expect(console.info).toHaveBeenCalledWith(expect.stringContaining('controller restarted'));
  });

  it('reads the state through REST while the socket is down, until hello', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    // The socket never opens (a proxy that doesn't pass WebSockets, say).
    await vi.advanceTimersByTimeAsync(FALLBACK_AFTER_MS);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(1);
    rest.snapshots[0]?.resolve(snapshotFrom(helloFor('idle')));
    await settle();
    expect(store.getState().ready).toBe(true);
    expect(store.getState().setup?.completed).toBe(true);

    await vi.advanceTimersByTimeAsync(FALLBACK_EVERY_MS);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(2);
    rest.snapshots[1]?.reject(new Error('down'));
    await settle();
    expect(console.warn).not.toHaveBeenCalled(); // quiet while polling

    server(sockets.latest()).hello(helloFor('idle'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(2);
  });

  it('reads the queue again after a failed read, while the run goes on', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    server(sockets.latest()).hello(helloFor('running'));
    rest.queues[0]?.reject(new Error('503: the database is still opening'));
    await settle();
    expect(store.getState().queue).toBeNull();

    await vi.advanceTimersByTimeAsync(QUEUE_RETRY_FIRST_MS);
    expect(rest.rest.queue).toHaveBeenCalledTimes(2);
    rest.queues[1]?.reject(new Error('503'));
    await settle();
    // The wait doubles.
    await vi.advanceTimersByTimeAsync(2 * QUEUE_RETRY_FIRST_MS - 1);
    expect(rest.rest.queue).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(rest.rest.queue).toHaveBeenCalledTimes(3);
    rest.queues[2]?.resolve(runningQueue);
    await settle();
    expect(store.getState().queue).toEqual(runningQueue);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(rest.rest.queue).toHaveBeenCalledTimes(3);
  });

  it('stops retrying the queue once the run has ended', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    const srv = server(sockets.latest());
    srv.hello(helloFor('running'));
    rest.queues[0]?.reject(new Error('503'));
    await settle();
    srv.send('run.state', { ...runRunning, state: 'idle', previous_state: 'running' });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(rest.rest.queue).toHaveBeenCalledTimes(1);
    expect(store.getState().queue).toEqual([]);
  });

  it('keeps one poll chain when the socket drops again while a poll is in flight', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    await vi.advanceTimersByTimeAsync(FALLBACK_AFTER_MS);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(1); // in flight
    server(sockets.latest()).hello(helloFor('idle'));
    sockets.latest().drop();
    rest.snapshots[0]?.reject(new Error('down'));
    await settle();

    // One chain: a poll FALLBACK_AFTER_MS after the drop, then one every FALLBACK_EVERY_MS.
    await vi.advanceTimersByTimeAsync(FALLBACK_AFTER_MS);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(2);
    rest.snapshots[1]?.reject(new Error('down'));
    await settle();
    await vi.advanceTimersByTimeAsync(FALLBACK_EVERY_MS);
    expect(rest.rest.snapshot).toHaveBeenCalledTimes(3);
  });

  it('a hello wins over a REST read still in flight', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    await vi.advanceTimersByTimeAsync(FALLBACK_AFTER_MS);
    server(sockets.latest()).hello(helloFor('expired'));
    rest.snapshots[0]?.resolve(snapshotFrom(helloFor('idle')));
    await settle();
    expect(store.getState().spotify?.state).toBe('expired');
  });

  it('disconnect() closes the socket and stops everything', async () => {
    vi.useFakeTimers();
    store.connect('ws://test/api/events');
    store.disconnect();
    expect(sockets.latest().closedByClient).toBe(true);
    expect(store.getState().socket).toBe('idle');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(sockets.all).toHaveLength(1);
    expect(rest.rest.snapshot).not.toHaveBeenCalled();
  });
});
