// The WebSocket to /api/events, kept open: it reconnects with backoff, and checks the line when it
// has been quiet for a while. It only carries text; store.ts makes sense of what arrives.
//
// contracts/events.md § Connection:
// - Reconnecting: 1 s, doubling to 15 s at most. The wait starts over at 1 s once a connection has
//   worked (store.ts calls healthy() when `hello` arrives), so a server that accepts and then drops
//   at once doesn't get retried every second.
// - Close code 1013 (the server's buffer for us filled up): an ordinary reconnect, with a new hello.
// - Keep-alive: the server pings every 20 s, but a browser never sees WebSocket pings, so the
//   "nothing heard for 45 s, reconnect" rule can't work as written: an idle app would reconnect
//   every 45 s. The cautious version here: after 45 s of quiet, send a frame the server ignores
//   (so a connection the server already dropped closes), ask checkLine() (store.ts reads
//   GET /api/health), and reconnect only if the controller doesn't answer or has restarted.
// - A browser can think a socket is open long after the server dropped it: the computer slept,
//   or the network changed. So it also reconnects when the quiet timer fires a minute or more late
//   (the computer slept), and checks the line at once when the browser comes back online.

import type { SocketState } from './live-state.ts';

/** The part of the browser's WebSocket this file uses. Tests pass a fake one (src/test/fake-socket.ts). */
export interface WebSocketLike {
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number; reason: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

/** Opens a WebSocket to `url`. */
export type OpenSocket = (url: string) => WebSocketLike;

export interface EventSocketOptions {
  url: string;
  /** Called with each text frame. */
  onText(text: string): void;
  /** Called when the socket opens, or is lost. */
  onState(state: SocketState): void;
  /** After QUIET_MS with nothing heard: resolve true if the line is fine, false to reconnect. */
  checkLine?(): Promise<boolean>;
  /** Default: the browser's WebSocket. */
  open?: OpenSocket;
}

export interface EventSocket {
  /** Opens the socket and keeps it open. */
  start(): void;
  /** Closes it for good. */
  stop(): void;
  /** Drops this connection and opens a new one now, without waiting out the backoff. */
  reconnect(): void;
  /** The connection works (hello arrived): the next reconnect waits BACKOFF_FIRST_MS again. */
  healthy(): void;
}

export const BACKOFF_FIRST_MS = 1_000;
export const BACKOFF_MAX_MS = 15_000;
/** events.md: "A client that hears nothing for 45 s reconnects." Here it checks first. */
export const QUIET_MS = 45_000;
/** A quiet timer that fires this much later than due: the computer slept, or the tab was frozen. */
export const LATE_MS = 60_000;
/** Sent to check a quiet line. events.md § Connection: the server ignores what the client sends. */
export const PROBE_FRAME = 'probe';

const browserSocket: OpenSocket = (url) => new WebSocket(url) as unknown as WebSocketLike;

export function createEventSocket(options: EventSocketOptions): EventSocket {
  const openSocket = options.open ?? browserSocket;
  let socket: WebSocketLike | null = null;
  let wanted = false;
  let backoff = BACKOFF_FIRST_MS;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let quietTimer: ReturnType<typeof setTimeout> | null = null;
  /** When the quiet wait started, to tell a timer that fired far too late. */
  let quietSince = 0;

  function open() {
    retryTimer = null;
    const ws = openSocket(options.url);
    socket = ws;
    // Each handler first checks that this is still the current socket: an old one can still fire.
    ws.onopen = () => {
      if (socket !== ws) return;
      options.onState('open');
      waitForQuiet();
    };
    ws.onmessage = (event) => {
      if (socket !== ws) return;
      waitForQuiet();
      if (typeof event.data === 'string') options.onText(event.data);
    };
    ws.onclose = (event) => {
      if (socket !== ws) return;
      socket = null;
      stopQuietTimer();
      if (!wanted) return;
      if (event.code === 1013) console.info('live: the server closed the socket (1013, too far behind); reconnecting');
      options.onState('reconnecting');
      retryLater();
    };
    // A close event always follows an error, and is handled there.
    ws.onerror = () => {};
  }

  function retryLater() {
    retryTimer = setTimeout(open, backoff);
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
  }

  /** Throws away the current socket without waiting for its close event. */
  function dropSocket() {
    const ws = socket;
    socket = null;
    stopQuietTimer();
    if (!ws) return;
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close();
    } catch {}
  }

  function waitForQuiet() {
    stopQuietTimer();
    quietSince = Date.now();
    quietTimer = setTimeout(checkQuiet, QUIET_MS);
  }

  /** Nothing heard for QUIET_MS, or the browser came back online: is this connection still there? */
  function checkQuiet() {
    stopQuietTimer();
    const ws = socket;
    if (!ws || !wanted) return;
    // Far later than due: the computer slept, and the server has dropped us meanwhile. Start over.
    if (Date.now() - quietSince >= QUIET_MS + LATE_MS) {
      reconnect();
      return;
    }
    // If the server already dropped this connection, sending makes the network say so: the
    // socket closes, and onclose reconnects.
    try {
      ws.send(PROBE_FRAME);
    } catch {}
    const checkLine = options.checkLine;
    if (!checkLine) {
      waitForQuiet();
      return;
    }
    void checkLine()
      .catch(() => false)
      .then((fine) => {
        if (socket !== ws || !wanted) return;
        if (fine) waitForQuiet();
        else reconnect();
      });
  }

  function stopQuietTimer() {
    if (quietTimer) clearTimeout(quietTimer);
    quietTimer = null;
  }

  function reconnect() {
    if (!wanted) return;
    dropSocket();
    if (retryTimer) clearTimeout(retryTimer);
    options.onState('reconnecting');
    open();
  }

  /**
   * Back online, or the tab is visible again. While reconnecting: try now rather than at the end
   * of a long backoff. While open: check the line now if the network may have changed (online) or
   * the quiet check is overdue (the computer slept and its timer hasn't fired yet).
   */
  function wakeUp(event: Event) {
    if (!wanted) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    if (socket) {
      const overdue = Date.now() - quietSince >= QUIET_MS;
      if (quietTimer && (event.type === 'online' || overdue)) checkQuiet();
      return;
    }
    if (!retryTimer) return;
    clearTimeout(retryTimer);
    open();
  }

  return {
    start() {
      if (wanted) return;
      wanted = true;
      backoff = BACKOFF_FIRST_MS;
      if (typeof window !== 'undefined') {
        window.addEventListener('online', wakeUp);
        document.addEventListener('visibilitychange', wakeUp);
      }
      open();
    },
    stop() {
      wanted = false;
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = null;
      dropSocket();
      if (typeof window !== 'undefined') {
        window.removeEventListener('online', wakeUp);
        document.removeEventListener('visibilitychange', wakeUp);
      }
    },
    reconnect,
    healthy() {
      backoff = BACKOFF_FIRST_MS;
    },
  };
}
