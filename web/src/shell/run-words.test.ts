import { describe, expect, it } from 'vitest';
import {
  connectionExpired,
  connectionExpiring,
  connectionNotConfigured,
  connectionOk,
  queueItem,
  runRunning,
  scheduleNext,
  statusIdle,
  statusRunning,
} from '@mock/fixtures.ts';
import type { Status } from '@/api';
import { connectionLine, itemPosition, sessionPill, statusLine, trackClockRuns, trackLines } from './run-words.ts';

const queue = [
  queueItem({ item_id: 'liked', name: 'Liked Songs', state: 'done' }),
  queueItem({ item_id: 'gone', name: 'Removed', state: 'removed' }),
  queueItem({ item_id: statusRunning.item!.item_id, name: 'Elsewhere', state: 'playing' }),
  queueItem({ item_id: 'next', name: 'Up next' }),
];
const paused: Status = { ...statusRunning, state: 'paused', run: { ...runRunning, state: 'paused', paused_reason: 'device_moved' } };
const now = Date.parse('2026-11-15T12:00:00Z');

describe('statusLine', () => {
  it('counts the items of a running run, once the queue is known', () => {
    expect(statusLine(statusRunning, queue, null, now).text).toBe('Backing up · item 2 of 3');
    expect(statusLine(statusRunning, null, null, now).text).toBe('Backing up');
  });

  it('says why a run is paused', () => {
    expect(statusLine(paused, queue, null, now)).toMatchObject({ text: 'Paused · playback moved', tone: 'warn' });
  });

  it('says a stop is coming', () => {
    const stopping: Status = { ...statusRunning, run: { ...runRunning, stop_mode: 'after_track' } };
    expect(statusLine(stopping, queue, null, now).text).toBe('Stopping after this track…');
  });

  it('gives the next backup when idle, or why backups are held', () => {
    expect(statusLine(statusIdle, null, scheduleNext, now).text).toMatch(/^Next backup · /);
    expect(statusLine(statusIdle, null, { ...scheduleNext, at: null, window_end: null }, now).text).toBe('No backup scheduled');
    expect(statusLine(statusIdle, null, { ...scheduleNext, held_reason: 'connection_expired' }, now)).toMatchObject({
      text: 'Backups held · connection expired',
      tone: 'danger',
    });
    expect(statusLine(statusIdle, null, null, now).text).toBe('Idle');
  });
});

describe('itemPosition', () => {
  it('skips items removed from the run', () => {
    expect(itemPosition(statusRunning, queue)).toEqual({ index: 2, total: 3 });
    expect(itemPosition(statusIdle, queue)).toBeNull();
  });
});

describe('connectionLine', () => {
  it('follows the connection state', () => {
    expect(connectionLine(connectionOk)).toEqual({ tone: 'accent', text: 'Connected as Lorne' });
    // Still connected while expiring: green, as drawn (fzNDm). The banner warns.
    expect(connectionLine(connectionExpiring)).toEqual({ tone: 'accent', text: 'Connected as Lorne' });
    expect(connectionLine(connectionExpired)).toEqual({ tone: 'danger', text: 'Spotify connection expired' });
    expect(connectionLine(connectionNotConfigured)).toEqual({ tone: 'muted', text: 'Not connected to Spotify' });
    expect(connectionLine(null)).toBeNull();
  });
});

describe('sessionPill', () => {
  it('shows Recording, Paused, Stopping or Waiting', () => {
    expect(sessionPill(statusRunning)).toMatchObject({ tone: 'green', label: 'Recording' });
    expect(sessionPill(paused)).toMatchObject({ tone: 'yellow', label: 'Paused' });
    expect(sessionPill({ ...statusRunning, session_state: 'stopping' }).label).toBe('Stopping');
    expect(sessionPill({ ...statusRunning, session_state: 'ad' }).label).toBe('Waiting');
  });
});

describe('trackClockRuns', () => {
  it('ticks while a track records, also once a stop waits for it to end', () => {
    expect(trackClockRuns(statusRunning)).toBe(true);
    const stopping: Status = { ...statusRunning, state: 'stopping', run: { ...runRunning, state: 'stopping', stop_mode: 'after_track' } };
    expect(sessionPill(stopping).label).toBe('Stopping');
    expect(trackClockRuns(stopping)).toBe(true);
    expect(trackClockRuns({ ...statusRunning, session_state: 'stopping' })).toBe(true);
  });

  it('stands still while paused, waiting, or without a track', () => {
    expect(trackClockRuns(paused)).toBe(false);
    expect(trackClockRuns({ ...statusRunning, session_state: 'paused' })).toBe(false);
    expect(trackClockRuns({ ...statusRunning, session_state: 'waiting' })).toBe(false);
    expect(trackClockRuns({ ...statusRunning, track: null })).toBe(false);
  });
});

describe('trackLines', () => {
  it('names the artist, the item and the position', () => {
    expect(trackLines(statusRunning, false)).toEqual({ title: 'Last Hours', sub: 'fakename · Elsewhere · track 5' });
    expect(trackLines(statusRunning, true).sub).toBe('fakename · track 5');
  });

  it('says what is happening before the first track', () => {
    const starting: Status = { ...statusRunning, state: 'starting', item: null, track: null };
    expect(trackLines(starting, false)).toEqual({ title: 'Starting a backup', sub: 'Checking settings and playlists…' });
  });
});
