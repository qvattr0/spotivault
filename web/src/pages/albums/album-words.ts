// What the Albums pages say about an album, its status and its tracks (web-ui.md § Albums). Pill
// colours are components.md § Status pill. Pure functions, so the unit tests check them directly.

import { CircleDotDashed, type LucideIcon } from 'lucide-react';
import type { Album, AlbumStatus, AlbumsSummary, ItemTrack, TrackList } from '@/api';
import type { PillTone } from '@/components/ui-a';
import type { TrackStatusKind } from '@/components/ui-b';
import { formatBytes, formatCount, formatDate } from '@/shell';
import { trackReasonText } from '@/lib/run-words.ts';

export interface AlbumStatusView {
  label: string;
  tone: PillTone;
  /** The icon form of the pill (Recording: a dashed circle). */
  icon?: LucideIcon;
  /** Queued and Recording link to the Dashboard (web-ui.md § Album states). */
  toDashboard: boolean;
}

/** web-ui.md § Album states. The contract's status decides; Unavailable is checked before Recorded. */
export const ALBUM_STATUS: Record<AlbumStatus, AlbumStatusView> = {
  queued: { label: 'Queued', tone: 'neutral', toDashboard: true },
  recording: { label: 'Recording', tone: 'green', icon: CircleDotDashed, toDashboard: true },
  recorded: { label: 'Recorded', tone: 'green', toDashboard: false },
  partial: { label: 'Partial', tone: 'yellow', toDashboard: false },
  unavailable: { label: 'Unavailable', tone: 'red', toDashboard: false },
};

/** "42 albums · 39 recorded · 3 queued" (web-ui.md § Albums, Header). */
export function summaryText(summary: AlbumsSummary): string {
  const count = summary.total === 1 ? 'album' : 'albums';
  return `${formatCount(summary.total)} ${count} · ${formatCount(summary.recorded)} recorded · ${formatCount(summary.queued)} queued`;
}

/** "Radiohead · 1997" (the grid's line under the name). The year is left out when unknown. */
export function albumSub(album: Pick<Album, 'artist' | 'year'>): string {
  return album.year === null ? album.artist : `${album.artist} · ${album.year}`;
}

/** "11 / 11": recorded tracks over the album's total (web-ui.md § List view). */
export function tracksText(album: Pick<Album, 'recorded' | 'total'>): string {
  return `${album.recorded} / ${album.total}`;
}

/** The date an album was completed, or "—". */
export function recordedText(album: Pick<Album, 'completed_at'>): string {
  return album.completed_at ? formatDate(album.completed_at) : '—';
}

/** A track's state as a row shows it: its icon, and its words (components.md § Row/Track). */
export function trackView(track: ItemTrack): { kind: TrackStatusKind; text: string } {
  switch (track.state) {
    case 'recorded':
      return { kind: 'recorded', text: track.size_bytes === null ? 'Recorded' : `Recorded · ${formatBytes(track.size_bytes)}` };
    case 'skipped_duplicate':
      return { kind: 'skipped', text: 'Skipped (duplicate)' };
    case 'missing':
      return { kind: 'missing', text: 'Missing' };
    case 'failed': {
      const reason = trackReasonText(track.reason);
      return { kind: 'failed', text: reason ? `Failed · ${reason}` : 'Failed' };
    }
    case 'new':
      return { kind: 'new', text: 'New' };
    case 'unplayable':
      return { kind: 'unplayable', text: 'Unplayable' };
  }
}

/**
 * The toast after "Show files path" (web-ui.md § List view says "Show files path"; no endpoint gives
 * a path, so ours is the folder of the album's first recorded track, relative to the music folder).
 */
export function filesText(list: Pick<TrackList, 'tracks'>): string {
  const recorded = list.tracks.find((track) => track.path);
  if (!recorded?.path) return 'Nothing is recorded yet, so there are no files.';
  const folder = recorded.path.split('/').slice(0, -1).join('/');
  return `Recorded in ${folder || 'the music folder'}`;
}
