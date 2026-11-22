// A fake WebSocket for live-store tests: the test plays the server.
//
//   const sockets = fakeSockets();
//   const store = createLiveStore({ openSocket: sockets.open, rest: fakeRest() });
//   store.connect('ws://test/api/events');
//   sockets.latest().accept();                         // the server accepts
//   sockets.latest().deliver(envelope('hello', ...));  // and sends hello
//   sockets.latest().drop();                           // the line goes down (close code 1006)

import type { OpenSocket, WebSocketLike } from '@/state/socket.ts';

export class FakeSocket implements WebSocketLike {
  url: string;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  /** True once the client closed it. */
  closedByClient = false;
  /** The frames the client sent. */
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
  }

  /** The server accepts the connection. */
  accept() {
    this.onopen?.({});
  }

  /** The server sends one frame: an object is sent as JSON, a string as it is. */
  deliver(message: unknown) {
    this.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) });
  }

  /** The connection ends from the server's side, or the network's (1006 by default). */
  drop(code = 1006, reason = '') {
    this.onerror?.({});
    this.onclose?.({ code, reason });
  }

  /** The client sends a frame. */
  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.closedByClient = true;
  }
}

export interface FakeSockets {
  /** Pass as `openSocket` to createLiveStore. */
  open: OpenSocket;
  /** Every socket opened so far, oldest first. */
  all: FakeSocket[];
  /** The newest one. Throws if none was opened. */
  latest(): FakeSocket;
}

export function fakeSockets(): FakeSockets {
  const all: FakeSocket[] = [];
  return {
    open(url) {
      const socket = new FakeSocket(url);
      all.push(socket);
      return socket;
    },
    all,
    latest() {
      const socket = all.at(-1);
      if (!socket) throw new Error('no socket was opened');
      return socket;
    },
  };
}
