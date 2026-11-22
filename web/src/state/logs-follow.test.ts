// The live store's part in History › Logs (events.md § Logs): `logs.follow` goes out once the
// connection has its hello, again after every reconnect, and `logs.unfollow` when the tab closes;
// `log.lines` (seq null) reaches its listeners without upsetting the seq checks.

import { describe, expect, it, vi } from 'vitest';
import { BOOT_ID, helloFor } from '@mock/fixtures.ts';
import { fakeSockets } from '@/test/fake-socket.ts';
import type { QueueItem } from '@/api/types.ts';
import type { LiveRest, Snapshot } from './rest.ts';
import { createLiveStore } from './store.ts';

const rest: LiveRest = {
  snapshot: vi.fn(() => new Promise<Snapshot>(() => {})),
  queue: vi.fn(() => new Promise<QueueItem[]>(() => {})),
  bootId: vi.fn(async () => BOOT_ID),
};
const AT = '2026-11-15T01:00:00.000Z';
const line = { id: '1-0-controller', at: AT, source: 'controller', service: 'controller', level: 'info', message: 'hi', run_id: null };

function connected() {
  const sockets = fakeSockets();
  const store = createLiveStore({ openSocket: sockets.open, rest });
  store.connect('ws://test/api/events');
  return { store, sockets };
}

function sentTypes(frames: string[]): unknown[] {
  return frames.map((frame) => JSON.parse(frame) as unknown);
}

describe('following the logs', () => {
  it('sends logs.follow after the hello, again after a reconnect, and logs.unfollow at the end', () => {
    vi.useFakeTimers();
    try {
      const { store, sockets } = connected();
      const filter = { source: ['spytify'], level: ['error'], run: 42, q: null };
      // Before the hello, nothing is sent: the follow waits for it.
      store.followLogs({ follow_id: 7, filter });
      expect(sockets.latest().sent).toEqual([]);

      sockets.latest().accept();
      sockets.latest().deliver({ seq: 10, type: 'hello', at: AT, data: helloFor('idle') });
      expect(sentTypes(sockets.latest().sent)).toEqual([{ type: 'logs.follow', follow_id: 7, filter }]);

      // The line drops: the new connection gets the follow again after its own hello.
      sockets.latest().drop();
      vi.advanceTimersByTime(1_000);
      sockets.latest().accept();
      sockets.latest().deliver({ seq: 1, type: 'hello', at: AT, data: helloFor('idle') });
      expect(sentTypes(sockets.latest().sent)).toEqual([{ type: 'logs.follow', follow_id: 7, filter }]);

      store.followLogs(null);
      expect(sentTypes(sockets.latest().sent).at(-1)).toEqual({ type: 'logs.unfollow' });
      // Not following: a later hello sends nothing more.
      const count = sockets.latest().sent.length;
      sockets.latest().drop();
      vi.advanceTimersByTime(1_000);
      sockets.latest().accept();
      sockets.latest().deliver({ seq: 1, type: 'hello', at: AT, data: helloFor('idle') });
      expect(sockets.all.at(-2)?.sent).toHaveLength(count);
      expect(sockets.latest().sent).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('passes log.lines on, volatile: the seq checks go on as if it never came', () => {
    const { store, sockets } = connected();
    const batches: unknown[] = [];
    store.onEvent('log.lines', (event) => batches.push(event.data));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    sockets.latest().accept();
    sockets.latest().deliver({ seq: 10, type: 'hello', at: AT, data: helloFor('idle') });
    sockets.latest().deliver({ seq: null, type: 'log.lines', at: AT, data: { lines: [line], dropped: 0, follow_id: 1 } });
    sockets.latest().deliver({ seq: 11, type: 'setup.state', at: AT, data: helloFor('idle').setup });
    expect(batches).toEqual([{ lines: [line], dropped: 0, follow_id: 1 }]);
    expect(warn).not.toHaveBeenCalled(); // no seq gap
    // A log.lines with a seq isn't one: it's dropped as malformed.
    sockets.latest().deliver({ seq: 12, type: 'log.lines', at: AT, data: { lines: [line], dropped: 0, follow_id: 1 } });
    expect(batches).toHaveLength(1);
    warn.mockRestore();
  });
});
