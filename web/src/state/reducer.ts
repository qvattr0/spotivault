// Applies one live event to the store's state. A pure function: same state and event, same result.
// Events that only pages care about (track.finished, library.item, run.finished, ...) don't change
// this state; pages subscribe to them with useLiveEvent.

import type { ItemState, QueueItem, Status } from '../api/types.ts';
import type { LiveEvent } from './events.ts';
import { idleStatus, type Alert, type LiveState } from './live-state.ts';
import type { Snapshot } from './rest.ts';

/** The item states that mean "this is the item being recorded now". */
const CURRENT_ITEM_STATES: readonly ItemState[] = [
  'planning',
  'preflight',
  'preparing',
  'starting',
  'playing',
  'finishing',
];

export function isCurrentItemState(state: ItemState): boolean {
  return CURRENT_ITEM_STATES.includes(state);
}

export function reduce(state: LiveState, event: LiveEvent): LiveState {
  const next = event.seq === null ? state : { ...state, lastSeq: event.seq };

  switch (event.type) {
    case 'hello': {
      const hello = event.data;
      // events.md § hello: a new boot_id means the controller restarted, so nothing cached is kept.
      // The same boot_id and the same run going on: keep what hello can't give back.
      const sameRun = state.bootId === hello.boot_id && runId(state.status) !== null && runId(state.status) === runId(hello.status);
      return {
        ...next,
        ready: true,
        // Not the first snapshot: events may have been missed while the socket was down.
        resyncs: state.ready ? state.resyncs + 1 : state.resyncs,
        bootId: hello.boot_id,
        version: hello.version,
        setup: hello.setup,
        status: hello.status,
        spotify: hello.connection,
        client: hello.client,
        install: hello.client.install,
        backlog: hello.backlog,
        // The store reloads the queue through REST when there's a run. Until then the old one stays.
        queue: hello.status.run === null ? [] : sameRun ? state.queue : null,
        alerts: sameRun ? alertsFor(hello.status, state.alerts) : [],
      };
    }

    case 'run.state': {
      const { previous_state: _previous, ...run } = event.data;
      if (run.state === 'idle') {
        // The run ended. run.finished follows with its History row.
        return { ...next, status: idleStatus, queue: [], alerts: [] };
      }
      const newRun = runId(next.status) !== run.id;
      const status: Status = newRun
        ? { ...idleStatus, state: run.state, run, view_only: true }
        : { ...(next.status ?? idleStatus), state: run.state, run, view_only: true };
      return {
        ...next,
        status,
        // A new run: its queue comes with run.queue, or the store loads it.
        queue: newRun ? null : next.queue,
        alerts: newRun ? [] : alertsFor(status, next.alerts),
      };
    }

    case 'run.queue':
      return { ...next, queue: event.data.queue };

    case 'item.state': {
      const item = event.data.item;
      const queue = next.queue && replaceItem(next.queue, item);
      return { ...next, queue, status: next.status && withItem(next.status, item) };
    }

    case 'track.started': {
      if (!next.status) return next;
      const t = event.data;
      const track = {
        take_id: t.take_id,
        track_id: t.track_id,
        title: t.title,
        artist: t.artist,
        album: t.album,
        cover_url: t.cover_url,
        length_ms: t.length_ms,
        started_at: event.at,
        position: t.position,
      };
      return { ...next, status: { ...next.status, track } };
    }

    case 'session.state':
      if (!next.status) return next;
      return { ...next, status: { ...next.status, session_state: event.data.state } };

    case 'device.moved':
      return {
        ...next,
        alerts: [
          ...next.alerts.filter((a) => a.kind !== 'device_moved'),
          { kind: 'device_moved', at: event.at, event: event.data },
        ],
      };

    case 'error': {
      // A repeated code replaces the old alert; `withdrawn` removes it.
      const others = next.alerts.filter((a) => !(a.kind === 'error' && a.event.code === event.data.code));
      if (event.data.withdrawn) return { ...next, alerts: others };
      return { ...next, alerts: [...others, { kind: 'error', at: event.at, event: event.data }] };
    }

    case 'backlog':
      return { ...next, backlog: event.data };

    case 'setup.state':
      return { ...next, setup: event.data };

    case 'client.status':
      return { ...next, client: event.data, install: event.data.install };

    case 'client.install': {
      const { log_line: _line, ...install } = event.data;
      const client = next.client && { ...next.client, install };
      return { ...next, install, client };
    }

    case 'connection':
      return { ...next, spotify: event.data };

    // Page events: no store state, pages listen with useLiveEvent. `level` has its own slot (store.ts).
    case 'run.finished':
    case 'track.finished':
    case 'track.skipped':
    case 'library.item':
    case 'album.item':
    case 'catalog.refresh':
    case 'level':
    case 'log.lines':
      return next;
  }
}

/** Applies a snapshot read through REST (rest.ts): after a seq gap, or while the socket is down. */
export function applySnapshot(state: LiveState, snapshot: Snapshot): LiveState {
  const sameRun = runId(state.status) !== null && runId(state.status) === runId(snapshot.status);
  return {
    ...state,
    ready: true,
    resyncs: state.resyncs + 1,
    setup: snapshot.setup,
    status: snapshot.status,
    spotify: snapshot.connection,
    client: snapshot.client,
    install: snapshot.client.install,
    queue: snapshot.queue,
    alerts: sameRun ? alertsFor(snapshot.status, state.alerts) : [],
  };
}

/**
 * The status after an item.state event. No event says "the track is over", so the item's moves
 * stand in for one. Without this, the strip would show the last item's track under the next
 * item's name. The mock's REST status drops the track at the end of each item too.
 */
function withItem(status: Status, item: QueueItem): Status {
  const wasCurrent = status.item?.item_id === item.item_id;
  if (isCurrentItemState(item.state)) {
    if (wasCurrent) return { ...status, item };
    // Another item became the current one: the last one's track and recorder session are over.
    return { ...status, item, track: null, session_state: null };
  }
  if (!wasCurrent) return status;
  // The current item ended. `interrupted` keeps its track: after a takeover the run pauses on it.
  if (item.state === 'interrupted') return { ...status, item };
  return { ...status, item, track: null };
}

function runId(status: Status | null): number | null {
  return status?.run?.id ?? null;
}

/** The alerts still true for this status: playback-moved only while the run is paused. */
function alertsFor(status: Status, alerts: Alert[]): Alert[] {
  if (status.state === 'paused') return alerts;
  // Playback moved away and then came back: the takeover alert is no longer true.
  const kept = alerts.filter((a) => a.kind !== 'device_moved');
  return kept.length === alerts.length ? alerts : kept;
}

function replaceItem(queue: QueueItem[], item: QueueItem): QueueItem[] {
  const index = queue.findIndex((q) => q.item_id === item.item_id);
  if (index === -1) return queue;
  const copy = queue.slice();
  copy[index] = item;
  return copy;
}
