// What the Dashboard says, as plain functions of the API's data, so the wording is tested on its
// own (words.test.ts). Wording from web-ui.md § Dashboard; where it gives none, ours, marked so.

import type { Backlog, HistoryRow, QueueItem, RunSummary, RunTrack, ScheduleNext } from '@/api';
import { formatBytes, formatDay, formatHours, formatRunLength, formatTime, formatWhen } from '@/shell';
import { TRIGGER, trackReasonText } from '@/lib/run-words.ts';
import { isCurrentItemState } from '@/state';

// --- Idle: Next backup -------------------------------------------------------------------------

/** "in 9 h", "in 40 min", "in 3 days": how long until `iso`, seen from `now`. */
export function inText(iso: string, now: number): string {
  const minutes = Math.round((Date.parse(iso) - now) / 60_000);
  if (minutes <= 0) return 'now';
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours} h`;
  return `in ${Math.round(hours / 24)} days`;
}

/**
 * The Next backup card's big line (web-ui.md § Idle): "Tonight 01:00–07:00 · in 9 h", or "No backup
 * scheduled" with Manual only. Inside a window with no run going: "Backup window open · until 07:00",
 * as the sidebar's status card says it.
 */
export function nextBackupTitle(next: ScheduleNext, now: number): string {
  if (!next.at) return 'No backup scheduled';
  if (next.in_progress && next.window_end) return `Backup window open · until ${formatTime(next.window_end)}`;
  const when = capitalise(formatWhen(next.at, now));
  const until = next.window_end ? `–${formatTime(next.window_end)}` : '';
  return `${when}${until} · ${inText(next.at, now)}`;
}

/** What the next run (or Run now) will cover: "18 playlists to check · 3 albums queued". */
export function coverageText(next: Pick<ScheduleNext, 'playlists_to_check' | 'albums_queued'>): string {
  const parts: string[] = [];
  if (next.playlists_to_check > 0) parts.push(plural(next.playlists_to_check, 'playlist', 'playlists') + ' to check');
  if (next.albums_queued > 0) parts.push(plural(next.albums_queued, 'album', 'albums') + ' queued');
  // Ours: web-ui.md gives no words for an empty Library.
  return parts.length > 0 ? parts.join(' · ') : 'Nothing tracked yet';
}

export interface HeldWords {
  /** Why the card is red. */
  text: string;
  /** The button that takes Run now's place. */
  action: { label: string; to: string };
}

/**
 * The Held variant (web-ui.md § Idle › Variants): the card turns red and says why; its main button
 * becomes Reconnect, or "Log in again" (wizard step 3). The sentences are ours. Null for the reasons
 * that don't hold a run from this card (a paused run shows the running Dashboard; setup_incomplete
 * never reaches it).
 */
export function heldWords(reason: ScheduleNext['held_reason']): HeldWords | null {
  switch (reason) {
    case 'connection_expired':
      return {
        text: 'The Spotify connection has expired. Backups wait until you reconnect.',
        action: { label: 'Reconnect', to: '/reconnect' },
      };
    case 'not_connected':
      return {
        text: "spotivault isn't connected to Spotify. Backups wait until you connect it.",
        action: { label: 'Reconnect', to: '/reconnect' },
      };
    case 'client_logged_out':
      return {
        text: 'The Spotify client is logged out. Backups wait until you log in again.',
        action: { label: 'Log in again', to: '/setup/login' },
      };
    default:
      return null;
  }
}

// --- Idle: Last run ----------------------------------------------------------------------------

/** "Tue 12 Nov · 01:00 · 5 h 12 m · Scheduled" (fzNDm). */
export function lastRunTitle(run: Pick<HistoryRow, 'started_at' | 'duration_s' | 'trigger'>): string {
  const parts = [formatDay(run.started_at), formatTime(run.started_at)];
  if (run.duration_s !== null) parts.push(formatRunLength(run.duration_s));
  parts.push(TRIGGER[run.trigger]);
  return parts.join(' · ');
}

// --- Running: the run header -------------------------------------------------------------------

/** Time since `iso` as hours and minutes: "0:42", "5:12". */
export function elapsedText(iso: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`;
}

/**
 * The run header's line (web-ui.md § Run header): "started 01:00 · 0:42 elapsed · Scheduled · stops
 * by 07:00", the last part for scheduled runs only, then the backlog's "about 26 h left".
 */
export function runMetaLine(run: RunSummary, now: number, backlog: Backlog | null): string {
  return runMetaParts(run, now, backlog).join(' · ');
}

/** The run line's parts, which the header draws with wider gaps around the dots. */
export function runMetaParts(run: RunSummary, now: number, backlog: Backlog | null): string[] {
  const parts = [`started ${formatTime(run.started_at)}`, `${elapsedText(run.started_at, now)} elapsed`, TRIGGER[run.trigger]];
  if (run.window_end) parts.push(`stops by ${formatTime(run.window_end)}`);
  if (backlog && backlog.seconds_left > 0) parts.push(`about ${formatHours(backlog.seconds_left)} left`);
  return parts;
}

/** The header's title: "Backing up", or "Paused" (hJlHj). */
export function runTitle(run: RunSummary): string {
  return run.state === 'paused' ? 'Paused' : 'Backing up';
}

// --- Running: the queue ------------------------------------------------------------------------

export interface QueueSections {
  /** Items that ended in this run, in order: collapsed rows. */
  finished: QueueItem[];
  /** The item being recorded, or the one a takeover interrupted while the run is paused. */
  current: QueueItem | null;
  /** Waiting: Up next, and "Interrupted · will retry". */
  upNext: QueueItem[];
}

/**
 * Splits the queue as the Dashboard shows it (t4YEY): QUEUE (ended items, then the current one) and
 * UP NEXT. `currentId` is the live status's item: while a run is `paused` after a takeover, its item
 * is `interrupted` but is still the current one (Resume restarts it). Otherwise an interrupted item
 * waits at the end of the queue ("Interrupted · will retry"). Removed items aren't shown: you took
 * them out of this run.
 */
export function queueSections(queue: QueueItem[], currentId: string | null, paused: boolean): QueueSections {
  const sections: QueueSections = { finished: [], current: null, upNext: [] };
  for (const item of queue) {
    if (item.state === 'removed') continue;
    if (isCurrentItemState(item.state) || (paused && item.item_id === currentId && item.state === 'interrupted')) {
      sections.current ??= item;
    } else if (item.state === 'up_next' || item.state === 'interrupted') {
      sections.upNext.push(item);
    } else {
      sections.finished.push(item);
    }
  }
  return sections;
}

/** An Up next row's "what to expect" (web-ui.md § Queue): "84 new", "11 tracks" or "checking". */
export function expectText(item: Pick<QueueItem, 'expect'>): string {
  const { kind, count } = item.expect;
  if (kind === 'checking' || count === null) return 'checking';
  if (kind === 'tracks') return plural(count, 'track', 'tracks');
  // Ours: a playlist with nothing missing says so, as its collapsed row will.
  return count === 0 ? 'nothing new' : `${count} new`;
}

/** "12 recorded · 0 failed", the end of a Done row. */
export function countsText(item: Pick<QueueItem, 'counts'>): string {
  return `${item.counts.recorded} recorded · ${item.counts.failed} failed`;
}

// --- Running: the current item's track table ---------------------------------------------------

/** What a row of the live track table says at its right (t4YEY). The Recording row adds its clock. */
export function trackStateText(track: Pick<RunTrack, 'state' | 'reason' | 'size_bytes'>): string {
  switch (track.state) {
    case 'recorded':
      return track.size_bytes !== null ? `Recorded · ${formatBytes(track.size_bytes)}` : 'Recorded';
    case 'skipped_duplicate':
      return 'Skipped (duplicate)';
    case 'skipped':
      return `Skipped (${trackReasonText(track.reason) ?? 'other'})`;
    case 'failed': {
      const reason = trackReasonText(track.reason);
      return reason ? `Failed · ${reason}` : 'Failed';
    }
    case 'recording':
      return 'Recording';
    case 'pending':
      return 'Pending';
  }
}

/**
 * The current item's progress (t4YEY: "41 / 88"): tracks done out of the table's tracks. Null when
 * the item plays whole (a followed or linked playlist): then the header says "n recorded" with no
 * total (web-ui.md § Current item).
 */
export function itemProgress(item: Pick<QueueItem, 'planned' | 'counts'>, tracks: RunTrack[]): { done: number; total: number } | null {
  if (item.planned === null) return null;
  const total = Math.max(tracks.length, item.planned);
  const done =
    tracks.length > 0
      ? tracks.filter((t) => t.state !== 'pending' && t.state !== 'recording').length
      : item.counts.recorded + item.counts.skipped + item.counts.failed;
  return { done, total };
}

// --- Helpers -----------------------------------------------------------------------------------

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
