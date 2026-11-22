// The backlog estimate in words (design.md § Backlog estimate): the Dashboard's Full backup card
// and wizard step 9's Backup length row. Plain functions of `Backlog`, tested on their own
// (backlog-words.test.ts). Wording from web-ui.md § Idle, card 2, and § 9. Done; where it gives
// none, ours, listed in web-ui.md § What the drawings leave out (Pages, S8).

import type { Backlog } from '@/api';
import { formatCount, formatDay, formatDayTime, formatHours, formatTime } from '@/shell';

/**
 * Which way the estimate is shown:
 * - `measuring`: no estimate yet, or items are still being measured and nothing is known yet.
 * - `empty`: nothing tracked, or nothing in what's tracked (ours).
 * - `unknown_only`: only playlists of unknown length are tracked (ours).
 * - `complete`: everything is recorded, and nothing is unknown or still being measured.
 * - `known_done`: everything of known length is recorded, but some playlists are of unknown
 *   length or still being measured (ours: not "Everything is backed up").
 * - `in_progress`: something of known length is left to record.
 */
export type BacklogState = 'measuring' | 'empty' | 'unknown_only' | 'complete' | 'known_done' | 'in_progress';

export function backlogState(backlog: Backlog | null): BacklogState {
  if (!backlog) return 'measuring';
  const { tracks_total, seconds_left, unknown_items, items_measuring } = backlog;
  if (tracks_total === 0) {
    if (items_measuring > 0) return 'measuring';
    return unknown_items > 0 ? 'unknown_only' : 'empty';
  }
  if (seconds_left > 0) return 'in_progress';
  return unknown_items === 0 && items_measuring === 0 ? 'complete' : 'known_done';
}

/**
 * The newer of two estimates, by `as_of`: the hello's or a `backlog` event's, and GET
 * /api/backlog's answer. On a tie, the first (the live one).
 */
export function newestBacklog(live: Backlog | null, read: Backlog | null): Backlog | null {
  if (!live) return read;
  if (!read) return live;
  return Date.parse(read.as_of) > Date.parse(live.as_of) ? read : live;
}

/** Recorded time out of total time, from 0 to 1 (backlogPercent rounds it for the bar and the line). */
export function backlogProgress(backlog: Backlog): number {
  return backlog.seconds_total > 0 ? backlog.seconds_recorded / backlog.seconds_total : 0;
}

/**
 * The share of the music recorded, as a whole percent, rounded down: the bar and the line under it.
 * It never says 100 until every track is recorded: half a second left can round the seconds up
 * to the total.
 */
export function backlogPercent(backlog: Backlog): number {
  const percent = Math.floor(backlogProgress(backlog) * 100);
  const allRecorded = backlog.tracks_recorded >= backlog.tracks_total;
  return allRecorded ? percent : Math.min(percent, 99);
}

/**
 * The line under the bar: "4,708 of 5,120 tracks · 87% of the music". The bar measures time and
 * the line counts tracks, so the percent says it's of the music (agreed with the user).
 */
export function tracksLine(backlog: Backlog): string {
  const tracks = `${formatCount(backlog.tracks_recorded)} of ${plural(backlog.tracks_total, 'track', 'tracks')}`;
  return `${tracks} · ${backlogPercent(backlog)}% of the music`;
}

/** "About 27 h of recording left", or "About 40 min of recording left" under an hour. */
export function timeLeftLine(backlog: Pick<Backlog, 'seconds_left'>): string {
  return `About ${formatHours(backlog.seconds_left)} of recording left`;
}

/**
 * When the rest is done: "Done around Sat 16 Nov at this schedule" (from `finish_at`), or, with
 * Manual only (no `finish_at`), "Run now to start; recording is real time".
 */
export function finishLine(backlog: Pick<Backlog, 'finish_at'>): string {
  if (!backlog.finish_at) return 'Run now to start; recording is real time';
  return `Done around ${formatDay(backlog.finish_at)} at this schedule`;
}

/** "+ 2 followed playlists (unknown length)", or null when there are none. */
export function unknownLine(backlog: Pick<Backlog, 'unknown_items'>): string | null {
  const n = backlog.unknown_items;
  return n > 0 ? `+ ${plural(n, 'followed playlist', 'followed playlists')} (unknown length)` : null;
}

/**
 * "+ 1 playlist or album still being measured": items whose track list isn't read yet, next to
 * what's measured already (ours). Null when there are none.
 */
export function measuringLine(backlog: Pick<Backlog, 'items_measuring'>): string | null {
  const n = backlog.items_measuring;
  return n > 0 ? `+ ${plural(n, 'playlist or album', 'playlists or albums')} still being measured` : null;
}

/** "Everything is backed up · 298 h of music" (Complete). */
export function completeLine(backlog: Pick<Backlog, 'seconds_total'>): string {
  return `Everything is backed up · ${formatHours(backlog.seconds_total)} of music`;
}

/** "Everything of known length is backed up · 298 h of music" (ours: some are of unknown length). */
export function knownDoneLine(backlog: Pick<Backlog, 'seconds_total'>): string {
  return `Everything of known length is backed up · ${formatHours(backlog.seconds_total)} of music`;
}

/** Only playlists of unknown length: "2 followed playlists (unknown length)" (ours). */
export function unknownOnlyLine(backlog: Pick<Backlog, 'unknown_items'>): string {
  return `${plural(backlog.unknown_items, 'followed playlist', 'followed playlists')} (unknown length)`;
}

/**
 * The quiet freshness line: "Updated 01:00", with the day too when it wasn't today ("Updated Tue
 * 12 Nov 01:00", ours). Local time, as the rest of the Dashboard.
 */
export function updatedLine(asOf: string, now: number): string {
  const sameDay = new Date(asOf).toDateString() === new Date(now).toDateString();
  return `Updated ${sameDay ? formatTime(asOf) : formatDayTime(asOf)}`;
}

/**
 * Step 9's Backup length row (web-ui.md § 9): its value, and the lines under it.
 * - "About 298 h of music to record" (`seconds_left`), with "+ 2 followed playlists (unknown
 *   length)" and "+ 1 playlist or album still being measured" under it when there are any.
 * - "Measuring…" while nothing is measured yet.
 * - Ours: "Everything is backed up" when nothing is left (after Run setup again), "Everything of
 *   known length is backed up" with the lines under it, "2 followed playlists (unknown length)"
 *   when only those are tracked, and "Nothing to back up yet".
 */
export function backupLengthRow(backlog: Backlog | null): { value: string; notes: string[] } {
  const state = backlogState(backlog);
  if (!backlog || state === 'measuring') return { value: 'Measuring…', notes: [] };
  const notes = [unknownLine(backlog), measuringLine(backlog)].filter((line): line is string => line !== null);
  switch (state) {
    case 'empty':
      return { value: 'Nothing to back up yet', notes: [] };
    case 'unknown_only':
      return { value: unknownOnlyLine(backlog), notes: [] };
    case 'complete':
      return { value: 'Everything is backed up', notes: [] };
    case 'known_done':
      return { value: 'Everything of known length is backed up', notes };
    case 'in_progress':
      return { value: `About ${formatHours(backlog.seconds_left)} of music to record`, notes };
  }
}

function plural(n: number, one: string, many: string): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}
