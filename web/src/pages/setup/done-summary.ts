// Step 9's summary lines (web-ui.md § 9; BAzX6):
//   Account   Lorne · expires 12 May 2027
//   Format    AAC 256 · .m4a
//   Folder    /music → /Music
//   Tracking  23 playlists + Liked Songs · 42 albums
//   Schedule  None yet

import type { Connection, LibrarySummary, Schedule, Settings } from '@/api';
import { formatChoiceOf } from '@/lib/formats.ts';
import { formatDate } from '@/shell';

export function accountLine(connection: Connection | null): string {
  if (!connection || connection.state === 'not_configured' || connection.state === 'disconnected') return 'Not connected';
  const name = connection.display_name ?? 'Connected';
  if (!connection.expires_at) return name;
  return `${name} · ${connection.state === 'expired' ? 'expired' : 'expires'} ${formatDate(connection.expires_at)}`;
}

export function formatLine(settings: Pick<Settings, 'format' | 'bitrate' | 'extension'>): string {
  return `${formatChoiceOf(settings).label} · .${settings.extension}`;
}

/** The right side is the shared folder's own path (web-ui.md § Files, Music folder). */
export function folderLine(musicSource: string | null): string {
  return musicSource ? `/music → ${musicSource}` : '/music';
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * "23 playlists + Liked Songs · 42 albums". The playlists are every tracked item but Liked Songs
 * (followed and linked ones included); `albums` is null while unknown.
 */
export function trackingLine(summary: Pick<LibrarySummary, 'tracked_count' | 'liked_tracked'>, albums: number | null): string {
  const playlists = summary.tracked_count - (summary.liked_tracked ? 1 : 0);
  const parts: string[] = [];
  if (playlists > 0 || !summary.liked_tracked) parts.push(count(playlists, 'playlist', 'playlists'));
  if (summary.liked_tracked) parts.push('Liked Songs');
  const items = parts.join(' + ');
  return albums === null ? items : `${items} · ${count(albums, 'album', 'albums')}`;
}

/**
 * web-ui.md's "None yet · set it in Schedule" points at the Schedule page, which isn't in M1: so
 * "None yet" alone, with no link (cautious: no dead links). A schedule set some other way shows
 * its size.
 */
export function scheduleLine(schedule: Pick<Schedule, 'hours_per_week' | 'windows_per_week'>): string {
  if (schedule.hours_per_week === 0) return 'None yet';
  return `${count(schedule.windows_per_week, 'window', 'windows')} a week, ${schedule.hours_per_week} h`;
}
