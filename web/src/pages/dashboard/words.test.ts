import { describe, expect, it } from 'vitest';
import { queueItem, runRunning, scheduleNext } from '@mock/fixtures.ts';
import type { RunTrack } from '@/api';
import {
  coverageText,
  elapsedText,
  expectText,
  heldWords,
  inText,
  itemProgress,
  lastRunTitle,
  nextBackupTitle,
  queueSections,
  runLeftText,
  runMetaLine,
  runTitle,
  trackStateText,
} from './words.ts';

/** A local time today, as the browser sees it. */
function at(hour: number, minute = 0, dayOffset = 0): Date {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  d.setDate(d.getDate() + dayOffset);
  return d;
}

function track(state: RunTrack['state'], extra: Partial<RunTrack> = {}): RunTrack {
  return { position: 1, track_id: null, title: 'T', artists: ['A'], duration_ms: 1000, state, size_bytes: null, reason: null, take_id: null, ...extra };
}

describe('Next backup', () => {
  it('says when, until when, and how long until then', () => {
    const now = at(16).getTime();
    const next = { ...scheduleNext, at: at(1, 0, 1).toISOString(), window_end: at(7, 0, 1).toISOString() };
    expect(nextBackupTitle(next, now)).toBe('Tonight 01:00–07:00 · in 9 h');
  });

  it('says No backup scheduled with Manual only', () => {
    expect(nextBackupTitle({ ...scheduleNext, at: null, window_end: null }, Date.now())).toBe('No backup scheduled');
  });

  it('says the window is open when now is inside it', () => {
    const next = { ...scheduleNext, at: at(1).toISOString(), window_end: at(23, 0).toISOString(), in_progress: true };
    expect(nextBackupTitle(next, at(2).getTime())).toBe('Backup window open · until 23:00');
  });

  it('counts down in minutes, hours, then days', () => {
    const now = Date.parse('2026-11-17T10:00:00Z');
    expect(inText('2026-11-17T10:40:00Z', now)).toBe('in 40 min');
    expect(inText('2026-11-17T19:00:00Z', now)).toBe('in 9 h');
    expect(inText('2026-11-20T10:00:00Z', now)).toBe('in 3 days');
    expect(inText('2026-11-17T09:00:00Z', now)).toBe('now');
  });

  it('says what it covers, leaving out what is zero', () => {
    expect(coverageText({ playlists_to_check: 18, albums_queued: 3 })).toBe('18 playlists to check · 3 albums queued');
    expect(coverageText({ playlists_to_check: 1, albums_queued: 0 })).toBe('1 playlist to check');
    expect(coverageText({ playlists_to_check: 0, albums_queued: 1 })).toBe('1 album queued');
    expect(coverageText({ playlists_to_check: 0, albums_queued: 0 })).toBe('Nothing tracked yet');
  });

  it('holds with Reconnect or Log in again', () => {
    expect(heldWords('connection_expired')?.action).toEqual({ label: 'Reconnect', to: '/reconnect' });
    expect(heldWords('not_connected')?.action).toEqual({ label: 'Reconnect', to: '/reconnect' });
    expect(heldWords('client_logged_out')?.action).toEqual({ label: 'Log in again', to: '/setup/login' });
    expect(heldWords(null)).toBeNull();
    expect(heldWords('run_paused')).toBeNull();
  });
});

describe('Last run', () => {
  it('writes when, how long and the trigger', () => {
    const started = at(1).toISOString();
    expect(lastRunTitle({ started_at: started, duration_s: 18_720, trigger: 'scheduled' })).toMatch(/^\w{3} \d+ \w{3} · 01:00 · 5 h 12 m · Scheduled$/);
    expect(lastRunTitle({ started_at: started, duration_s: null, trigger: 'run_now' })).toMatch(/· 01:00 · Run now$/);
  });
});

describe('the run header', () => {
  it('writes elapsed time as hours and minutes', () => {
    const start = Date.parse('2026-11-17T01:00:00Z');
    expect(elapsedText('2026-11-17T01:00:00Z', start + 42 * 60_000)).toBe('0:42');
    expect(elapsedText('2026-11-17T01:00:00Z', start + 312 * 60_000)).toBe('5:12');
    expect(elapsedText('2026-11-17T01:00:00Z', start - 5000)).toBe('0:00');
  });

  it("writes the run line, with the window for scheduled runs and this run's own time left", () => {
    const now = at(1, 42).getTime();
    const left = { seconds: 540, unknown_items: 0, as_of: new Date(now).toISOString() };
    const run = { ...runRunning, started_at: at(1).toISOString(), window_end: at(7).toISOString(), time_left: left };
    expect(runMetaLine(run, now)).toBe('started 01:00 · 0:42 elapsed · Scheduled · stops by 07:00 · about 9 min left in this run');
    expect(runMetaLine({ ...run, trigger: 'run_now', window_end: null }, now)).toBe('started 01:00 · 0:42 elapsed · Run now · about 9 min left in this run');
    // Starting (the queue isn't built yet), or nothing left: no time left in the line.
    expect(runMetaLine({ ...run, time_left: null }, now)).toBe('started 01:00 · 0:42 elapsed · Scheduled · stops by 07:00');
    expect(runMetaLine({ ...run, time_left: { ...left, seconds: 0 } }, now)).toBe('started 01:00 · 0:42 elapsed · Scheduled · stops by 07:00');
  });

  it("counts the run's time left down while it records, and holds it while it's paused", () => {
    const t0 = Date.parse('2026-11-17T01:00:00Z');
    const run = {
      ...runRunning,
      trigger: 'run_now' as const,
      window_end: null,
      time_left: { seconds: 540, unknown_items: 0, as_of: '2026-11-17T01:00:00Z' },
    };
    expect(runLeftText(run, t0)).toBe('about 9 min left in this run');
    expect(runLeftText(run, t0 + 4 * 60_000)).toBe('about 5 min left in this run');
    expect(runLeftText({ ...run, state: 'finishing' }, t0 + 4 * 60_000)).toBe('about 5 min left in this run');
    expect(runLeftText({ ...run, state: 'stopping' }, t0 + 4 * 60_000)).toBe('about 5 min left in this run');
    expect(runLeftText({ ...run, state: 'paused' }, t0 + 4 * 60_000)).toBe('about 9 min left in this run');
    expect(runLeftText(run, t0 + 9 * 60_000)).toBeNull(); // counted down to nothing
    expect(runLeftText(run, t0 - 60_000)).toBe('about 9 min left in this run'); // never more than sent
    expect(runLeftText({ ...run, time_left: { ...run.time_left, seconds: 2 * 3600 + 600 } }, t0)).toBe('about 2 h left in this run');
    expect(runLeftText({ ...run, time_left: { ...run.time_left, seconds: 20 } }, t0)).toBe('about 1 min left in this run');
  });

  it('says briefly how many playlists are of unknown length', () => {
    const t0 = Date.parse('2026-11-17T01:00:00Z');
    const left = { seconds: 540, unknown_items: 2, as_of: '2026-11-17T01:00:00Z' };
    const run = { ...runRunning, window_end: '2026-11-17T07:00:00Z' };
    expect(runLeftText({ ...run, time_left: left }, t0)).toBe('about 9 min left in this run + 2 playlists of unknown length');
    expect(runLeftText({ ...run, time_left: { ...left, seconds: 0, unknown_items: 1 } }, t0)).toBe('1 playlist of unknown length left in this run');
    expect(runLeftText({ ...run, time_left: null }, t0)).toBeNull();
  });

  it("stops a scheduled run's time left at its window's end, as the run stops there", () => {
    const t0 = Date.parse('2026-11-17T06:30:00Z');
    // 3 h of tracks and 2 playlists of unknown length, with 30 min left of the window.
    const left = { seconds: 3 * 3600, unknown_items: 2, as_of: '2026-11-17T06:30:00Z' };
    const run = { ...runRunning, window_end: '2026-11-17T07:00:00Z', time_left: left };
    expect(runLeftText(run, t0)).toBe('about 30 min left in this run');
    expect(runLeftText(run, t0 + 20 * 60_000)).toBe('about 10 min left in this run');
    expect(runMetaLine({ ...run, started_at: '2026-11-17T06:00:00Z' }, t0)).toMatch(/ · stops by \d\d:\d\d · about 30 min left in this run$/);
    // Paused, the figure holds, but the window's end comes closer.
    expect(runLeftText({ ...run, state: 'paused', time_left: { ...left, seconds: 20 * 60 } }, t0 + 15 * 60_000)).toBe(
      'about 15 min left in this run',
    );
    // A window longer than the run: the run's own figure.
    expect(runLeftText({ ...run, time_left: { ...left, seconds: 540 } }, t0)).toBe('about 9 min left in this run + 2 playlists of unknown length');
    // Once a stop is asked for (the window's end asks for one), the track playing plays on past it.
    const stopping = { ...run, state: 'stopping' as const, stop_mode: 'after_track' as const };
    expect(runLeftText({ ...stopping, time_left: { seconds: 180, unknown_items: 0, as_of: '2026-11-17T07:01:00Z' } }, t0 + 31 * 60_000)).toBe(
      'about 3 min left in this run',
    );
  });

  it('titles a paused run Paused', () => {
    expect(runTitle(runRunning)).toBe('Backing up');
    expect(runTitle({ ...runRunning, state: 'paused' })).toBe('Paused');
  });
});

describe('the queue', () => {
  const done = queueItem({ item_id: 'a', name: 'A', state: 'done' });
  const playing = queueItem({ item_id: 'b', name: 'B', state: 'playing' });
  const next = queueItem({ item_id: 'c', name: 'C' });
  const stalled = queueItem({ item_id: 'd', name: 'D', state: 'interrupted' });
  const removed = queueItem({ item_id: 'e', name: 'E', state: 'removed' });

  it('splits ended items, the current one and Up next; removed items are left out', () => {
    const sections = queueSections([done, playing, next, removed, stalled], 'b', false);
    expect(sections.finished).toEqual([done]);
    expect(sections.current).toEqual(playing);
    expect(sections.upNext).toEqual([next, stalled]);
  });

  it('keeps the interrupted item current only while the run is paused', () => {
    expect(queueSections([done, stalled, next], 'd', true).current).toEqual(stalled);
    expect(queueSections([done, stalled, next], 'd', false).upNext).toEqual([stalled, next]);
  });

  it('says what to expect', () => {
    expect(expectText({ expect: { kind: 'new_tracks', count: 84 } })).toBe('84 new');
    expect(expectText({ expect: { kind: 'new_tracks', count: 0 } })).toBe('nothing new');
    expect(expectText({ expect: { kind: 'tracks', count: 11 } })).toBe('11 tracks');
    expect(expectText({ expect: { kind: 'tracks', count: 1 } })).toBe('1 track');
    expect(expectText({ expect: { kind: 'checking', count: null } })).toBe('checking');
  });

  it("counts the item's progress from its track table, or none when it plays whole", () => {
    const tracks = [track('recorded'), track('skipped_duplicate'), track('failed'), track('recording'), track('pending')];
    expect(itemProgress({ planned: 5, counts: { recorded: 1, skipped: 1, failed: 1 } }, tracks)).toEqual({ done: 3, total: 5 });
    expect(itemProgress({ planned: 2, counts: { recorded: 1, skipped: 0, failed: 0 } }, [])).toEqual({ done: 1, total: 2 });
    expect(itemProgress({ planned: null, counts: { recorded: 4, skipped: 0, failed: 0 } }, tracks)).toBeNull();
  });
});

describe('the track table', () => {
  it('words each state', () => {
    expect(trackStateText(track('recorded', { size_bytes: 8_400_000 }))).toBe('Recorded · 8.4 MB');
    expect(trackStateText(track('recorded'))).toBe('Recorded');
    expect(trackStateText(track('skipped_duplicate'))).toBe('Skipped (duplicate)');
    expect(trackStateText(track('skipped', { reason: 'ad' }))).toBe('Skipped (ad)');
    expect(trackStateText(track('skipped', { reason: 'discarded' }))).toBe('Skipped (backup stopped mid-track)');
    expect(trackStateText(track('failed', { reason: 'discarded' }))).toBe('Failed · partial take');
    expect(trackStateText(track('failed', { reason: 'low_volume' }))).toBe('Failed · low volume');
    expect(trackStateText(track('failed'))).toBe('Failed');
    expect(trackStateText(track('recording'))).toBe('Recording');
    expect(trackStateText(track('pending'))).toBe('Pending');
  });
});
