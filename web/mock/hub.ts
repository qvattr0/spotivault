// The mock's side of WS /api/events (contracts/events.md): it numbers events, keeps the sockets,
// and sends each new socket a `hello` first. It can also misbehave on purpose, so the UI's
// reconnect and resync code can be seen working: drop the line, restart, lose an event, or close
// a "slow" client with 1013.
//
// The client's own messages (`logs.follow`, `logs.unfollow`; events.md § Logs) go to the handler
// set with onMessage (mock/logs.ts), and `log.lines` goes to one socket at a time (sendVolatile).

import { randomUUID } from 'node:crypto';
import type { WebSocket } from 'ws';
import { BOOT_ID } from './fixtures.ts';
import type { EventMap, EventType, Hello } from '../src/state/events.ts';

/** A JSON message a client sent on the socket. */
export type ClientMessage = Record<string, unknown>;

export interface Hub {
  /** Sends an event to every socket. `level` goes out with `seq: null` and isn't counted. */
  publish<K extends EventType>(type: K, data: EventMap[K]): void;
  /** Sends a volatile event (`seq: null`, not counted) to one socket: `log.lines`. */
  sendVolatile<K extends EventType>(socket: WebSocket, type: K, data: EventMap[K]): void;
  /** Calls `listener` after each published event (the log book turns them into log lines). */
  onPublish(listener: <K extends EventType>(type: K, data: EventMap[K]) => void): void;
  /** Calls `handler` with each JSON object a client sends, and with null when its socket closes. */
  onMessage(handler: (socket: WebSocket, message: ClientMessage | null) => void): void;
  /** Adds a socket and sends it the hello snapshot. */
  add(socket: WebSocket, hello: Hello): void;
  /** This "controller process"'s boot_id: changes on restart(). */
  bootId(): string;
  /** A controller restart: a new boot_id, seq starts over, and every socket closes with 1012. */
  restart(): void;
  /** The line drops (no close frame; the browser sees 1006). Clients reconnect to the same process. */
  drop(): void;
  /** Repeats drop() every `seconds` (0 stops it). */
  dropEvery(seconds: number): void;
  /** Closes every socket with 1013, as the controller does when a client falls 256 events behind. */
  closeSlow(): void;
  /** Loses the next event: clients see a seq gap and read the state through REST. */
  loseNext(): void;
  close(): void;
}

/** Keep-alive from events.md: a WebSocket ping every 20 s. */
const PING_MS = 20_000;

export function createHub(options: { background?: boolean } = {}): Hub {
  const sockets = new Set<WebSocket>();
  const publishListeners: (<K extends EventType>(type: K, data: EventMap[K]) => void)[] = [];
  let messageHandler: ((socket: WebSocket, message: ClientMessage | null) => void) | null = null;
  let seq = 0;
  let bootId = BOOT_ID;
  let dropTimer: ReturnType<typeof setInterval> | null = null;

  const pinger = setInterval(() => {
    for (const socket of sockets) socket.ping();
  }, PING_MS);
  if (options.background) pinger.unref();

  function send(socket: WebSocket, message: unknown) {
    if (socket.readyState === socket.OPEN) socket.send(JSON.stringify(message));
  }

  function drop() {
    for (const socket of sockets) socket.terminate();
    sockets.clear();
  }

  return {
    publish(type, data) {
      const volatile = type === 'level' || type === 'log.lines';
      if (!volatile) seq += 1;
      const message = { seq: volatile ? null : seq, type, at: new Date().toISOString(), data };
      for (const socket of sockets) send(socket, message);
      for (const listener of publishListeners) listener(type, data);
    },
    sendVolatile(socket, type, data) {
      send(socket, { seq: null, type, at: new Date().toISOString(), data });
    },
    onPublish(listener) {
      publishListeners.push(listener);
    },
    onMessage(handler) {
      messageHandler = handler;
    },
    add(socket, hello) {
      sockets.add(socket);
      socket.on('close', () => {
        sockets.delete(socket);
        messageHandler?.(socket, null);
      });
      // Text frames that are JSON objects go to the handler; anything else (the UI's quiet-line
      // probe) is ignored, as the controller does.
      socket.on('message', (raw, isBinary) => {
        if (isBinary || !messageHandler) return;
        try {
          const parsed: unknown = JSON.parse(String(raw));
          if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) messageHandler(socket, parsed as ClientMessage);
        } catch {
          // not JSON
        }
      });
      // hello.seq is the last event the snapshot already reflects; the next event is seq + 1.
      send(socket, { seq, type: 'hello', at: new Date().toISOString(), data: hello });
    },
    bootId: () => bootId,
    restart() {
      bootId = randomUUID();
      seq = 0;
      for (const socket of sockets) socket.close(1012, 'Service restart');
    },
    drop,
    dropEvery(seconds) {
      if (dropTimer) clearInterval(dropTimer);
      dropTimer = null;
      if (seconds > 0) {
        dropTimer = setInterval(drop, seconds * 1000);
        if (options.background) dropTimer.unref();
      }
    },
    closeSlow() {
      for (const socket of sockets) socket.close(1013, 'Try again later');
    },
    loseNext() {
      seq += 1;
    },
    close() {
      clearInterval(pinger);
      if (dropTimer) clearInterval(dropTimer);
      for (const socket of sockets) socket.terminate();
      sockets.clear();
    },
  };
}
