// The Library's words and pills, in one place (web-ui.md § Library): the filter chips, the sort
// menu, each item's status pill, the owner line, the track counts, and the track states of the
// detail view. Pure functions, so they're unit-tested (library-words.test.ts).

import { CircleDotDashed, type LucideIcon } from 'lucide-react';
import type { ItemTrack, LibraryItem, LibraryStatus } from '@/api';
import type { PillTone } from '@/components/ui-a';
import type { TrackStatusKind } from '@/components/ui-b';
import type { CatalogRefreshEvent, CatalogRefreshReason } from '@/state';
import { trackReasonText } from '@/lib/run-words.ts';
import { formatBytes, formatDayTime, formatDuration, formatTime } from '@/shell/format.ts';

/** The filter chips (web-ui.md § Header: "All · Tracked · Not tracked · Created by you · Added"). */
export type LibraryFilter = 'all' | 'tracked' | 'not_tracked' | 'owned' | 'added';
export const FILTERS: { value: LibraryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'tracked', label: 'Tracked' },
  { value: 'not_tracked', label: 'Not tracked' },
  { value: 'owned', label: 'Created by you' },
  { value: 'added', label: 'Added' },
];

/** Back up now's tooltip: it records once, now; the tracking check is about the scheduled backups. */
export const BACK_UP_HINT = 'Back up now: record it once, right away';

/** The sort menu (web-ui.md § Header: "Recently backed up · Name · Recently added · Track count"). */
export type LibrarySort = 'recently_backed_up' | 'name' | 'recently_added' | 'track_count';
export const SORTS: { value: LibrarySort; label: string }[] = [
  { value: 'recently_backed_up', label: 'Recently backed up' },
  { value: 'name', label: 'Name' },
  { value: 'recently_added', label: 'Recently added' },
  { value: 'track_count', label: 'Track count' },
];

/** One status pill: its words, colour and (for a part of the current run) its icon and link. */
export interface StatusView {
  label: string;
  tone: PillTone;
  icon?: LucideIcon;
  /** Recording and Queued link to the Dashboard (web-ui.md § Item states). */
  to?: string;
}

const STATUS: Record<Exclude<LibraryStatus, 'new'>, StatusView> = {
  not_tracked: { label: 'Not tracked', tone: 'neutral' },
  never_backed_up: { label: 'Never backed up', tone: 'neutral' },
  up_to_date: { label: 'Up to date', tone: 'green' },
  partial: { label: 'Partial', tone: 'yellow' },
  queued: { label: 'Queued', tone: 'neutral', to: '/dashboard' },
  recording: { label: 'Recording', tone: 'green', icon: CircleDotDashed, to: '/dashboard' },
  unavailable: { label: 'Unavailable', tone: 'red' },
};

/** The pill for an item: "n new" for tracks added since the last backup, the rest from STATUS. */
export function statusView(item: LibraryItem): StatusView {
  if (item.status === 'new') return { label: `${item.new ?? 0} new`, tone: 'blue' };
  return STATUS[item.status];
}

/** What the item is, under its name: "by you", "by Lorde", "added by link", "Playlist · pinned · 412 songs". */
export function ownerLine(item: LibraryItem): string {
  if (item.kind === 'liked') return item.total === null ? 'Playlist · pinned' : `Playlist · pinned · ${item.total} songs`;
  if (item.kind === 'followed') return `by ${item.owner}`;
  if (item.kind === 'linked') return 'added by link';
  return 'by you';
}

/** The cover's kind: Liked Songs always shows its tile. */
export function coverKindOf(item: LibraryItem): 'liked' | 'playlist' {
  return item.kind === 'liked' ? 'liked' : 'playlist';
}

/** "84 / 120 recorded", or "32 recorded" when the total is unknown (a linked playlist). */
export function recordedText(item: LibraryItem): string {
  return item.total === null ? `${item.recorded} recorded` : `${item.recorded} / ${item.total} recorded`;
}

/** A followed playlist has Spotify's total but no track list, so its count gets an info tooltip (web-ui.md § List view). */
export function hasTotalTooltip(item: LibraryItem): boolean {
  return item.kind === 'followed' && !item.item_access && item.total !== null;
}

/** A progress ring's fill, from 0 to 1, while the item is in the current run; null otherwise. */
export function progressOf(item: LibraryItem): number | null {
  if (!item.progress) return null;
  const { recorded, planned } = item.progress;
  if (planned === null || planned === 0) return 0;
  return Math.min(1, recorded / planned);
}

/** Calendar-day test in the browser's time zone. */
function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** "03:12 today", "14:00 yesterday", or "Tue 12 Nov 03:12": a last backup, seen from `now`. */
export function lastBackupAt(iso: string, now: number): string {
  const at = new Date(iso);
  if (sameDay(at, new Date(now))) return `${formatTime(iso)} today`;
  if (sameDay(at, new Date(now - 86_400_000))) return `${formatTime(iso)} yesterday`;
  return formatDayTime(iso);
}

/**
 * The line under the header: "18 of 23 tracked · last backup 03:12 today". Counted from the whole
 * Library, not the filtered list; the last backup is the newest of any item.
 */
export function librarySummaryText(items: LibraryItem[], now: number): string {
  const tracked = items.filter((item) => item.tracked).length;
  const newest = items
    .map((item) => item.last_backup_at)
    .filter((value): value is string => value !== null)
    .sort()
    .at(-1);
  const parts = [`${tracked} of ${items.length} tracked`];
  if (newest) parts.push(`last backup ${lastBackupAt(newest, now)}`);
  return parts.join(' · ');
}

/** A track's state in the detail view's table: its icon kind, its text and the hover text (its file path). */
export interface TrackView {
  kind: TrackStatusKind;
  text: string;
  hint?: string;
}

/** web-ui.md § Detail view, State: "Recorded (with file size, and the file path on hover) · Skipped (duplicate) · Missing · Failed (reason) · New". */
export function trackView(track: ItemTrack): TrackView {
  switch (track.state) {
    case 'recorded':
      return {
        kind: 'recorded',
        text: track.size_bytes === null ? 'Recorded' : `Recorded · ${formatBytes(track.size_bytes)}`,
        hint: track.path ?? undefined,
      };
    case 'skipped_duplicate':
      return { kind: 'skipped', text: 'Skipped (duplicate)' };
    case 'failed': {
      const reason = trackReasonText(track.reason);
      return { kind: 'failed', text: reason ? `Failed · ${reason}` : 'Failed' };
    }
    case 'missing':
      return { kind: 'missing', text: 'Missing' };
    case 'new':
      return { kind: 'new', text: 'New' };
    // Not in web-ui.md: a local file or one Spotify marks unplayable. Named plainly; never recorded.
    case 'unplayable':
      return { kind: 'unplayable', text: 'Unplayable' };
  }
}

/** A track's length in the table: "4:18", or "" when unknown. */
export function trackLength(track: ItemTrack): string {
  return track.duration_ms === null ? '' : formatDuration(track.duration_ms);
}

/**
 * The detail header's line: "by you · 120 tracks · 7 h 48 min · 118 recorded" (web-ui.md § Detail
 * view). `durationMs` is the track list's total, null when unknown. `length` writes it: formatLength.
 */
export function detailMeta(item: LibraryItem, durationMs: number | null, length: (ms: number) => string): string {
  const owner = item.kind === 'followed' || item.kind === 'linked' ? `by ${item.owner}` : 'by you';
  const parts = [owner];
  if (item.total !== null) parts.push(`${item.total} tracks`);
  if (durationMs !== null) parts.push(length(durationMs));
  parts.push(`${item.recorded} recorded`);
  return parts.join(' · ');
}

/** "1 new playlist", "2 new playlists". */
function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Why a refresh didn't happen, by the `ended` event's `reason`. Waiting only helps for some. */
const NOT_REFRESHED: Partial<Record<CatalogRefreshReason, string>> = {
  run_active: "The Library wasn't refreshed: a backup started, and each backup refreshes it first.",
  not_connected: "The Library wasn't refreshed: the Spotify Web API isn't connected.",
  connection_expired: 'The Spotify connection expired. Reconnect to refresh the Library.',
  rate_limited: "The Library couldn't be refreshed: Spotify asked spotivault to wait. Try again in a few minutes.",
  spotify_unavailable: "The Library couldn't be refreshed: Spotify didn't answer. Try again later.",
};

/**
 * The toast when the Refresh button's refresh ends (web-ui.md § Header): what it found, from the
 * `catalog.refresh` `ended` event. "Library refreshed · 1 new playlist · 1 followed playlist to add
 * with +". A failed or skipped one says why, from its `reason`.
 */
export function refreshedText(event: CatalogRefreshEvent): string {
  if (event.outcome === 'failed' || event.outcome === 'skipped') {
    return (event.reason && NOT_REFRESHED[event.reason]) ?? "The Library couldn't be refreshed. Try again later.";
  }
  const parts = ['Library refreshed'];
  const added = event.items_added ?? 0;
  const suggested = event.suggestions_added ?? 0;
  if (added > 0) parts.push(count(added, 'new playlist', 'new playlists'));
  // Followed playlists wait in the + modal's suggestions: the list doesn't change, so say where.
  if (suggested > 0) parts.push(count(suggested, 'followed playlist to add with +', 'followed playlists to add with +'));
  if (event.outcome === 'partial') parts.push("some playlists couldn't be read");
  return parts.join(' · ');
}

/** The Refresh button's tooltip. */
export const REFRESH_HINT = 'Check Spotify for new and changed playlists now';

/** The Refresh button's own words for a refused press (errors.ts has the general lines). */
export const REFRESH_ERRORS = {
  run_active: 'Not available while a backup is recording. Each backup refreshes the Library first.',
} as const;
