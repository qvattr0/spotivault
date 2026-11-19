// The live store: one WebSocket to /api/events (socket.ts), the state it builds (LiveState), and
// listeners. The app has one store (app-store.ts), started in main.tsx. Tests and the gallery make
// their own with createLiveStore() and feed it events with dispatch(), without a socket.
//
// What it does with the socket, per contracts/events.md:
// - `hello` replaces the state. If a run is going, the queue (not in hello) is read through REST.
// - `seq` must go up by one per event. A gap means events were lost: the state is read again
//   through REST (rest.ts), and if that fails the socket reconnects for a fresh hello.
// - While a REST read is in flight, new events wait, and are applied after it in order. Applying an
//   event the read already shows changes nothing, so nothing is lost and nothing goes backwards.
//   A read gives up after 10 s (rest.ts), so a stalled one can't hold the events for long.
// - If the queue can't be read, it's tried again (2 s, doubling to 30 s) while the same run goes on.
// - While the socket is down for more than 5 s, the state is read through REST every 10 s, so the
//   app still works behind a proxy that doesn't pass WebSockets. (Cautious extra: events.md has
//   no rule for it.)
// - `level` (10 a second) is kept apart from the state, so the meter re-renders and nothing else.

import type { QueueItem } from '../api/types.ts';
import type { EventType, Envelope, LevelEvent, LiveEvent } from './events.ts';
import { isKnownEvent } from './events.ts';
import { initialLiveState, type LevelReading, type LiveState } from './live-state.ts';
import { applySnapshot, reduce } from './reducer.ts';
import { createLiveRest, type LiveRest, type Snapshot } from './rest.ts';
import { createEventSocket, type EventSocket, type OpenSocket } from './socket.ts';

export type EventHandler<K extends EventType> = (event: Envelope<K>) => void;

export interface LiveStore {
  /** The current state. Same object until something changes, so it's safe for useSyncExternalStore. */
  getState(): LiveState;
  /** Called after every state change. Returns the unsubscribe function. */
  subscribe(listener: () => void): () => void;

  /** The latest level reading, or null when not recording. Changes up to 10 times a second. */
  getLevel(): LevelReading | null;
  subscribeLevel(listener: () => void): () => void;

  /** Calls `handler` for every event of this type, after the state is updated. Returns the unsubscribe function. */
  onEvent<K extends EventType>(type: K, handler: EventHandler<K>): () => void;
  /** Calls `handler` for every event. */
  onAnyEvent(handler: (event: LiveEvent) => void): () => void;

  /** Applies an event as if it came from the socket, without the seq checks. For tests and the gallery. */
  dispatch(event: LiveEvent): void;

  /** Opens the socket (by default ws(s)://<this host>/api/events) and keeps it open. */
  connect(url?: string): void;
  /** Closes the socket and stops reconnecting. */
  disconnect(): void;
  /** Drops the connection and opens a new one now: a "Retry" button while reconnecting. */
  reconnect(): void;
}

export interface LiveStoreOptions {
  /** Starting state, for tests and the gallery. */
  initial?: Partial<LiveState>;
  /** How the store reads state through REST. Default: the app's api client. */
  rest?: LiveRest;
  /** How it opens a WebSocket. Default: the browser's. Tests pass a fake one. */
  openSocket?: OpenSocket;
}

/** While the socket is down, read the state through REST after this long, then this often. */
export const FALLBACK_AFTER_MS = 5_000;
export const FALLBACK_EVERY_MS = 10_000;
/** After a failed queue read, wait this long before the next try, doubling up to the most. */
export const QUEUE_RETRY_FIRST_MS = 2_000;
export const QUEUE_RETRY_MAX_MS = 30_000;

export function eventsUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/api/events`;
}

export function createLiveStore(options: LiveStoreOptions = {}): LiveStore {
  const rest = options.rest ?? createLiveRest();
  let state: LiveState = { ...initialLiveState, ...options.initial };
  let level: LevelReading | null = null;

  const stateListeners = new Set<() => void>();
  const levelListeners = new Set<() => void>();
  const eventHandlers = new Map<string, Set<(event: LiveEvent) => void>>();
  const anyHandlers = new Set<(event: LiveEvent) => void>();

  let socket: EventSocket | null = null;
  /** The seq of the last event on this connection. Null until its hello. */
  let lastSeq: number | null = null;
  /** Events that arrived while a REST read was in flight, to apply after it. Null when none is. */
  let held: LiveEvent[] | null = null;
  /** Counts REST reads. A read only applies if no newer read or hello started after it. */
  let readCount = 0;
  /** What the REST read in flight covers. */
  let reading: 'queue' | 'all' | null = null;
  let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
  /** Counts the fallback's poll chains: a poll from a chain that was stopped doesn't schedule another. */
  let fallbackChain = 0;
  let queueRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let queueRetryWait = QUEUE_RETRY_FIRST_MS;

  function setState(next: LiveState) {
    if (next === state) return;
    state = next;
    for (const listener of stateListeners) listener();
  }

  function setLevel(next: LevelReading | null) {
    if (next === level) return;
    level = next;
    for (const listener of levelListeners) listener();
  }

  /** Updates the state for one event, then tells the event's listeners. */
  function apply(event: LiveEvent) {
    if (event.type === 'level') {
      setLevel({ level: event.data as LevelEvent, receivedAt: Date.now() });
    } else {
      setState(reduce(state, event));
      // The meter falls silent when the run stops recording.
      if (event.type === 'run.state' && event.data.state === 'idle') setLevel(null);
      if (event.type === 'session.state' && event.data.state !== 'recording' && event.data.state !== 'stopping') {
        setLevel(null);
      }
    }
    for (const handler of eventHandlers.get(event.type) ?? []) handler(event);
    for (const handler of anyHandlers) handler(event);
  }

  /** One text frame from the socket. */
  function receive(text: string) {
    const event = parseEvent(text);
    if (!event) return;
    if (event.type === 'level') {
      apply(event); // Volatile: no seq, never held back.
      return;
    }
    if (event.type === 'hello') {
      receiveHello(event);
      return;
    }
    if (lastSeq === null) {
      console.warn(`live: ${event.type} before hello; ignored`);
      return;
    }
    const gap = event.seq !== lastSeq + 1;
    if (gap) console.warn(`live: seq gap, expected ${lastSeq + 1}, got ${event.seq}; reloading the state through REST`);
    lastSeq = event.seq;

    const newRun = event.type === 'run.state' && event.data.state !== 'idle' && event.data.id !== state.status?.run?.id;
    if (held) held.push(event);
    else apply(event);

    if (gap) void readThroughRest('all');
    // A new run's queue may come with run.queue, but events.md doesn't promise it: read it too.
    else if (newRun) void readThroughRest('queue');
  }

  function receiveHello(event: Envelope<'hello'>) {
    if (state.bootId !== null && state.bootId !== event.data.boot_id) {
      console.info('live: the controller restarted (new boot_id); dropping cached state');
    }
    lastSeq = event.seq;
    // The snapshot is newer than anything held back or being read: drop those.
    held = null;
    reading = null;
    readCount += 1;
    stopFallback();
    stopQueueRetry();
    socket?.healthy();
    apply(event);
    if (event.data.status.run) void readThroughRest('queue');
  }

  /**
   * Reads the queue, or the whole state, through REST. Events that arrive meanwhile are held back
   * and applied after it. If the state can't be read after a gap, the socket reconnects: the new
   * connection's hello is a full snapshot. `polling`: the fallback while the socket is down, which
   * neither logs nor reconnects.
   */
  async function readThroughRest(what: 'queue' | 'all', polling = false) {
    // This read takes over from one in flight, so it must cover what that one did.
    if (reading === 'all') what = 'all';
    reading = what;
    const id = ++readCount;
    held ??= [];
    let snapshot: Snapshot | null = null;
    let queue: QueueItem[] | null = null;
    try {
      if (what === 'all') snapshot = await rest.snapshot();
      else queue = await rest.queue();
    } catch (error) {
      if (!polling) console.warn(`live: couldn't read the ${what === 'all' ? 'state' : 'queue'} through REST`, error);
    }
    if (id !== readCount) return; // A newer read or a hello took over, with these held events.
    const events = held ?? [];
    held = null;
    reading = null;
    if (snapshot) setState(applySnapshot(state, snapshot));
    if (queue) setState({ ...state, queue });
    for (const event of events) apply(event);
    if (what === 'all' && !snapshot && !polling && state.socket === 'open') socket?.reconnect();
    if (what === 'queue') {
      if (queue) queueRetryWait = QUEUE_RETRY_FIRST_MS;
      else retryQueueLater();
    }
  }

  /**
   * The queue read failed (the controller was still starting, say). run.queue only comes when the
   * queue's order changes, so read it again later, while the same run goes on and the socket is open.
   */
  function retryQueueLater() {
    if (queueRetryTimer) return;
    const runId = state.status?.run?.id;
    queueRetryTimer = setTimeout(() => {
      queueRetryTimer = null;
      // A read in flight covers the queue too; a new run reads its own; while the socket is down
      // the fallback reads everything.
      if (reading || state.socket !== 'open' || runId === undefined || state.status?.run?.id !== runId) return;
      void readThroughRest('queue');
    }, queueRetryWait);
    queueRetryWait = Math.min(queueRetryWait * 2, QUEUE_RETRY_MAX_MS);
  }

  function stopQueueRetry() {
    if (queueRetryTimer) clearTimeout(queueRetryTimer);
    queueRetryTimer = null;
  }

  function onSocketState(next: LiveState['socket']) {
    setState({ ...state, socket: next });
    if (next === 'reconnecting') {
      lastSeq = null; // The next connection starts with its own hello.
      setLevel(null);
      startFallback();
    }
  }

  /** Reads the state through REST every FALLBACK_EVERY_MS until a hello arrives. */
  function startFallback() {
    if (fallbackTimer) return;
    const chain = fallbackChain;
    const poll = () => {
      void readThroughRest('all', true).finally(() => {
        // Stopped while this read was in flight (and maybe started again since): this chain ends.
        if (chain === fallbackChain) fallbackTimer = setTimeout(poll, FALLBACK_EVERY_MS);
      });
    };
    fallbackTimer = setTimeout(poll, FALLBACK_AFTER_MS);
  }

  function stopFallback() {
    if (fallbackTimer) clearTimeout(fallbackTimer);
    fallbackTimer = null;
    fallbackChain += 1;
  }

  /** For the socket's quiet check: does the controller answer, as the same process? */
  async function lineIsFine(): Promise<boolean> {
    return (await rest.bootId()) === state.bootId;
  }

  return {
    getState: () => state,
    subscribe(listener) {
      stateListeners.add(listener);
      return () => stateListeners.delete(listener);
    },
    getLevel: () => level,
    subscribeLevel(listener) {
      levelListeners.add(listener);
      return () => levelListeners.delete(listener);
    },
    onEvent(type, handler) {
      let set = eventHandlers.get(type);
      if (!set) {
        set = new Set();
        eventHandlers.set(type, set);
      }
      const generic = handler as (event: LiveEvent) => void;
      set.add(generic);
      return () => set.delete(generic);
    },
    onAnyEvent(handler) {
      anyHandlers.add(handler);
      return () => anyHandlers.delete(handler);
    },
    dispatch: apply,
    connect(url = eventsUrl()) {
      if (socket) return;
      socket = createEventSocket({
        url,
        onText: receive,
        onState: onSocketState,
        checkLine: lineIsFine,
        open: options.openSocket,
      });
      setState({ ...state, socket: 'connecting' });
      startFallback();
      socket.start();
    },
    disconnect() {
      socket?.stop();
      socket = null;
      stopFallback();
      stopQueueRetry();
      lastSeq = null;
      held = null;
      reading = null;
      readCount += 1;
      setLevel(null);
      setState({ ...state, socket: 'idle' });
    },
    reconnect() {
      socket?.reconnect();
    },
  };
}

/** A frame as an event, or null for one that isn't JSON or has a type this UI doesn't know (events.md). */
function parseEvent(text: string): LiveEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    console.warn("live: a message that isn't JSON", text.slice(0, 200));
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || !isKnownEvent(parsed)) return null;
  const { seq, data } = parsed as { seq: unknown; data: unknown };
  const seqOk = parsed.type === 'level' ? seq === null : Number.isInteger(seq);
  if (!seqOk || typeof data !== 'object' || data === null) {
    console.warn('live: a malformed event; ignored', parsed.type);
    return null;
  }
  return parsed;
}
