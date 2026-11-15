import { describe, expect, it } from 'vitest';
import { connectionExpired, helloFor, installInstalled, queueItem, runRunning, statusRunning } from '@mock/fixtures.ts';
import { envelope } from '@/test/live.ts';
import type { DeviceMovedEvent } from './events.ts';
import { initialLiveState } from './live-state.ts';
import { applySnapshot, reduce } from './reducer.ts';

const idle = reduce(initialLiveState, envelope('hello', helloFor('idle')));

describe('reduce', () => {
  it('takes everything from hello', () => {
    expect(idle.ready).toBe(true);
    expect(idle.setup?.completed).toBe(true);
    expect(idle.status?.state).toBe('idle');
    expect(idle.spotify?.state).toBe('ok');
    // No run: the queue is known to be empty. The first hello isn't a resync.
    expect(idle.queue).toEqual([]);
    expect(idle.resyncs).toBe(0);
  });

  it('leaves the queue unknown after a hello with a run', () => {
    const running = reduce(initialLiveState, envelope('hello', helloFor('running')));
    expect(running.queue).toBeNull();
  });

  it('counts every hello after the first as a resync', () => {
    const again = reduce(idle, envelope('hello', helloFor('idle')));
    expect(again.resyncs).toBe(1);
  });

  it('keeps alerts and the queue over a reconnect to the same run, not over a restart', () => {
    const moved: DeviceMovedEvent = { run_id: 42, item_id: null, device: { id: null, name: 'Pixel 9', type: 'Smartphone' }, discarded_take_id: null };
    const queue = [queueItem({ item_id: 'liked', name: 'Liked Songs' })];
    let paused = reduce(initialLiveState, envelope('hello', helloFor('paused')));
    paused = reduce(paused, envelope('run.queue', { run_id: 42, queue }));
    paused = reduce(paused, envelope('device.moved', moved));

    const reconnected = reduce(paused, envelope('hello', helloFor('paused')));
    expect(reconnected.alerts).toHaveLength(1);
    expect(reconnected.queue).toBe(queue);

    // Resumed while the socket was down: the takeover alert is no longer true.
    const resumed = reduce(paused, envelope('hello', helloFor('running')));
    expect(resumed.alerts).toEqual([]);

    const restarted = reduce(paused, envelope('hello', { ...helloFor('paused'), boot_id: 'new' }));
    expect(restarted.alerts).toEqual([]);
    expect(restarted.queue).toBeNull();
  });

  it('follows run.state into a run and back to idle', () => {
    const running = reduce(idle, envelope('run.state', { ...runRunning, previous_state: 'idle' }));
    expect(running.status?.state).toBe('running');
    expect(running.status?.run?.id).toBe(42);
    expect(running.status?.view_only).toBe(true);

    const ended = reduce(running, envelope('run.state', { ...runRunning, state: 'idle', previous_state: 'running' }));
    expect(ended.status).toEqual({ state: 'idle', run: null, item: null, track: null, session_state: null, view_only: false });
    expect(ended.queue).toEqual([]);
  });

  it('starts a new run clean: no item, no track, no alerts, queue unknown', () => {
    const old = reduce(idle, envelope('hello', helloFor('running')));
    const withAlert = reduce(old, envelope('error', {
      source: 'controller', code: 'webapi', message: 'x', fatal: false, withdrawn: false, run_id: 42, item_id: null, facts: null,
    }));
    const next = reduce(withAlert, envelope('run.state', { ...runRunning, id: 43, state: 'starting', previous_state: 'idle' }));
    expect(next.status).toMatchObject({ state: 'starting', item: null, track: null, session_state: null });
    expect(next.alerts).toEqual([]);
    expect(next.queue).toBeNull();
  });

  it('applies a snapshot read through REST', () => {
    const hello = helloFor('running');
    const snapshot = { setup: hello.setup, status: hello.status, connection: connectionExpired, client: hello.client, queue: [] };
    const next = applySnapshot(initialLiveState, snapshot);
    expect(next.ready).toBe(true);
    expect(next.resyncs).toBe(1);
    expect(next.status?.state).toBe('running');
    expect(next.spotify?.state).toBe('expired');
    expect(next.install).toBe(hello.client.install);
  });

  it('keeps the current item, track and session state', () => {
    const running = reduce(idle, envelope('hello', helloFor('running')));
    const item = { ...statusRunning.item!, state: 'finishing' as const };
    const s1 = reduce(running, envelope('item.state', { run_id: 42, item, previous_state: 'playing' }));
    expect(s1.status?.item?.state).toBe('finishing');

    const s2 = reduce(
      s1,
      envelope('track.started', {
        run_id: 42, item_id: item.item_id, take_id: 't2', artist: 'fakename', title: 'Weightless', album: 'Elsewhere',
        length_ms: 1000, cover_url: null, track_id: null, position: 6, planned: true,
      }, '2026-11-15T01:00:00.000Z'),
    );
    expect(s2.status?.track).toMatchObject({ title: 'Weightless', started_at: '2026-11-15T01:00:00.000Z' });

    const s3 = reduce(s2, envelope('session.state', { run_id: 42, item_id: item.item_id, state: 'paused' }));
    expect(s3.status?.session_state).toBe('paused');
  });

  it("drops the last item's track when the item ends and the next one starts", () => {
    const running = reduce(idle, envelope('hello', helloFor('running')));
    expect(running.status?.track?.title).toBe('Last Hours');
    const done = { ...statusRunning.item!, state: 'done' as const };
    const s1 = reduce(running, envelope('session.state', { run_id: 42, item_id: done.item_id, state: 'idle' }));
    const s2 = reduce(s1, envelope('item.state', { run_id: 42, item: done, previous_state: 'finishing' }));
    expect(s2.status?.item?.state).toBe('done');
    expect(s2.status?.track).toBeNull();

    const nextItem = queueItem({ item_id: 'indie', name: 'Indie Finds', state: 'planning' });
    const s3 = reduce(s2, envelope('item.state', { run_id: 42, item: nextItem, previous_state: 'up_next' }));
    expect(s3.status).toMatchObject({ item: { name: 'Indie Finds' }, track: null, session_state: null });
  });

  it('drops the track and session when another item becomes current without the last one ending', () => {
    const running = reduce(idle, envelope('hello', helloFor('running')));
    const nextItem = queueItem({ item_id: 'indie', name: 'Indie Finds', state: 'planning' });
    const next = reduce(running, envelope('item.state', { run_id: 42, item: nextItem, previous_state: 'up_next' }));
    expect(next.status).toMatchObject({ item: { name: 'Indie Finds' }, track: null, session_state: null });
  });

  it('keeps the track of an item interrupted by a takeover: the run pauses on it', () => {
    const running = reduce(idle, envelope('hello', helloFor('running')));
    const interrupted = { ...statusRunning.item!, state: 'interrupted' as const };
    const next = reduce(running, envelope('item.state', { run_id: 42, item: interrupted, previous_state: 'playing' }));
    expect(next.status?.item?.state).toBe('interrupted');
    expect(next.status?.track?.title).toBe('Last Hours');
  });

  it('leaves the status alone when an item that is not current changes', () => {
    const running = reduce(idle, envelope('hello', helloFor('running')));
    const removed = queueItem({ item_id: 'liked', name: 'Liked Songs', state: 'removed' });
    const next = reduce(running, envelope('item.state', { run_id: 42, item: removed, previous_state: 'up_next' }));
    expect(next.status).toBe(running.status);
  });

  it('adds and withdraws error alerts by code', () => {
    const error = {
      source: 'spytify' as const, code: 'capture_silent' as const, message: 'Silent.', fatal: false, withdrawn: false,
      run_id: 42, item_id: null, facts: null,
    };
    const raised = reduce(idle, envelope('error', error));
    expect(raised.alerts).toHaveLength(1);
    const withdrawn = reduce(raised, envelope('error', { ...error, message: '', withdrawn: true }));
    expect(withdrawn.alerts).toHaveLength(0);
  });

  it('updates the connection, the client and the install', () => {
    const s1 = reduce(idle, envelope('connection', connectionExpired));
    expect(s1.spotify?.state).toBe('expired');
    const s2 = reduce(s1, envelope('client.install', { ...installInstalled, state: 'installing', log_line: 'x' }));
    expect(s2.install?.state).toBe('installing');
    expect(s2.client?.install.state).toBe('installing');
    expect(s2.install).not.toHaveProperty('log_line');
  });

  it('ignores level, which has its own slot', () => {
    const next = reduce(idle, envelope('level', { peak_dbfs: -3, rms_dbfs: -17, channels: [] }));
    expect(next).toBe(idle);
  });
});
