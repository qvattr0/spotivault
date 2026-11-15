import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeSockets, type FakeSockets } from '@/test/fake-socket.ts';
import { createEventSocket, LATE_MS, PROBE_FRAME, QUIET_MS, type EventSocket } from './socket.ts';
import type { SocketState } from './live-state.ts';

let sockets: FakeSockets;
let states: SocketState[];
let texts: string[];
let started: EventSocket[];

function start(checkLine?: () => Promise<boolean>): EventSocket {
  const socket = createEventSocket({
    url: 'ws://test/api/events',
    open: sockets.open,
    onState: (s) => states.push(s),
    onText: (t) => texts.push(t),
    checkLine,
  });
  socket.start();
  started.push(socket);
  return socket;
}

beforeEach(() => {
  vi.useFakeTimers();
  sockets = fakeSockets();
  states = [];
  texts = [];
  started = [];
});
afterEach(() => {
  for (const socket of started) socket.stop();
  vi.useRealTimers();
});

describe('createEventSocket', () => {
  it('passes text frames on and reports the state', () => {
    start();
    sockets.latest().accept();
    sockets.latest().deliver('{"type":"x"}');
    sockets.latest().onmessage?.({ data: new ArrayBuffer(2) }); // binary: not for us
    expect(states).toEqual(['open']);
    expect(texts).toEqual(['{"type":"x"}']);
  });

  it('reconnects with backoff: 1 s doubling to 15 s (events.md § Connection)', () => {
    start();
    const waits: number[] = [];
    for (let i = 0; i < 6; i++) {
      sockets.latest().drop();
      const before = sockets.all.length;
      let waited = 0;
      while (sockets.all.length === before) {
        vi.advanceTimersByTime(500);
        waited += 500;
      }
      waits.push(waited);
    }
    expect(waits).toEqual([1000, 2000, 4000, 8000, 15000, 15000]);
    expect(states.filter((s) => s === 'reconnecting')).toHaveLength(6);
  });

  it('waits 1 s again once a connection has worked', () => {
    const socket = start();
    sockets.latest().drop();
    vi.advanceTimersByTime(1000);
    sockets.latest().drop();
    vi.advanceTimersByTime(2000);
    sockets.latest().accept();
    socket.healthy(); // hello arrived
    sockets.latest().drop();
    vi.advanceTimersByTime(999);
    expect(sockets.all).toHaveLength(3);
    vi.advanceTimersByTime(1);
    expect(sockets.all).toHaveLength(4);
  });

  it('treats close code 1013 as an ordinary reconnect', () => {
    start();
    sockets.latest().accept();
    sockets.latest().drop(1013, 'Try again later');
    expect(states.at(-1)).toBe('reconnecting');
    vi.advanceTimersByTime(1000);
    expect(sockets.all).toHaveLength(2);
  });

  it('reconnect() opens a new socket at once and ignores the old one', () => {
    const socket = start();
    const old = sockets.latest();
    old.accept();
    socket.reconnect();
    expect(old.closedByClient).toBe(true);
    expect(sockets.all).toHaveLength(2);
    old.deliver('late');
    old.drop();
    expect(texts).toEqual([]);
    expect(states).toEqual(['open', 'reconnecting']);
  });

  it('stop() closes the socket and stops reconnecting', () => {
    const socket = start();
    sockets.latest().drop();
    socket.stop();
    vi.advanceTimersByTime(60_000);
    expect(sockets.all).toHaveLength(1);
  });

  it('after 45 s of quiet, checks the line and keeps a socket that is fine', async () => {
    const checkLine = vi.fn(async () => true);
    start(checkLine);
    sockets.latest().accept();
    await vi.advanceTimersByTimeAsync(QUIET_MS - 1);
    sockets.latest().deliver('{}'); // anything heard starts the wait over
    await vi.advanceTimersByTimeAsync(QUIET_MS - 1);
    expect(checkLine).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(checkLine).toHaveBeenCalledTimes(1);
    expect(sockets.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(QUIET_MS);
    expect(checkLine).toHaveBeenCalledTimes(2);
  });

  it('reconnects when the quiet check fails', async () => {
    start(async () => {
      throw new Error('no answer');
    });
    sockets.latest().accept();
    await vi.advanceTimersByTimeAsync(QUIET_MS);
    expect(sockets.all).toHaveLength(2);
    expect(sockets.all[0]?.closedByClient).toBe(true);
  });

  it('probes a quiet line, so a connection the server dropped closes', async () => {
    start(async () => true);
    const first = sockets.latest();
    first.accept();
    await vi.advanceTimersByTimeAsync(QUIET_MS);
    expect(first.sent).toEqual([PROBE_FRAME]);
    // The server had dropped it: the probe gets a reset, and the browser closes the socket.
    first.drop();
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets.all).toHaveLength(2);
  });

  it('probes a quiet line without a checkLine too', async () => {
    start();
    sockets.latest().accept();
    await vi.advanceTimersByTimeAsync(2 * QUIET_MS);
    expect(sockets.latest().sent).toEqual([PROBE_FRAME, PROBE_FRAME]);
  });

  it('reconnects when the quiet timer fires far too late: the computer slept', async () => {
    const checkLine = vi.fn(async () => true);
    start(checkLine);
    sockets.latest().accept();
    // Asleep: the clock moves on, the timers don't run.
    vi.setSystemTime(Date.now() + QUIET_MS + LATE_MS);
    await vi.advanceTimersByTimeAsync(QUIET_MS);
    expect(checkLine).not.toHaveBeenCalled();
    expect(sockets.all).toHaveLength(2);
    expect(sockets.all[0]?.closedByClient).toBe(true);
    expect(states).toEqual(['open', 'reconnecting']);
  });

  it('checks an overdue line as soon as the tab is visible again', () => {
    start(async () => true);
    sockets.latest().accept();
    vi.setSystemTime(Date.now() + 10 * 60_000); // asleep for 10 minutes; the timer hasn't fired yet
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sockets.all).toHaveLength(2);
  });

  it('leaves a fresh line alone when the tab is visible again', () => {
    start(async () => true);
    sockets.latest().accept();
    document.dispatchEvent(new Event('visibilitychange'));
    expect(sockets.latest().sent).toEqual([]);
    expect(sockets.all).toHaveLength(1);
  });

  it('checks an open line when the browser comes back online', async () => {
    const checkLine = vi.fn(async () => true);
    start(checkLine);
    sockets.latest().accept();
    window.dispatchEvent(new Event('online'));
    expect(sockets.latest().sent).toEqual([PROBE_FRAME]);
    await vi.advanceTimersByTimeAsync(0);
    expect(checkLine).toHaveBeenCalledTimes(1);
    expect(sockets.all).toHaveLength(1);
  });

  it('tries at once when the browser comes back online', () => {
    start();
    sockets.latest().drop(); // the retry is 1 s away
    expect(sockets.all).toHaveLength(1);
    window.dispatchEvent(new Event('online'));
    expect(sockets.all).toHaveLength(2);
  });
});
