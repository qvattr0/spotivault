// What the shell says about the run and the connection: the sidebar's status card and the
// now-playing strip. Plain functions of the live state, so the wording is tested on its own.

import { AudioLines, CircleAlert, CircleDotDashed, CirclePause, Moon, type LucideIcon } from 'lucide-react';
import type { Connection, QueueItem, ScheduleNext, Status } from '@/api';
import { formatTime, formatWhen } from './format.ts';
import type { PillTone } from '@/components/ui-a';

/** The colours a status card line comes in. */
export type LineTone = 'sub' | 'accent' | 'warn' | 'danger' | 'muted';

export interface StatusLine {
  icon: LucideIcon;
  text: string;
  tone: LineTone;
}

const PAUSED: Record<string, string> = {
  device_moved: 'Paused · playback moved',
  device_busy: 'Paused · another device is playing',
};

const HELD: Record<NonNullable<ScheduleNext['held_reason']>, string> = {
  connection_expired: 'connection expired',
  not_connected: 'not connected to Spotify',
  client_logged_out: 'client logged out',
  run_paused: 'a backup is paused',
  setup_incomplete: "setup isn't finished",
};

/** Which item of the run is the current one, for "item 3 of 7". Null until the queue is known. */
export function itemPosition(status: Status | null, queue: QueueItem[] | null): { index: number; total: number } | null {
  const current = status?.item;
  if (!current || !queue) return null;
  const items = queue.filter((q) => q.state !== 'removed');
  const index = items.findIndex((q) => q.item_id === current.item_id);
  return index === -1 ? null : { index: index + 1, total: items.length };
}

/**
 * The status card's first line (components.md § Sidebar › Status card): the run while one is
 * going, otherwise the next backup. Lines the drawing doesn't show (starting, stopping, held,
 * no schedule) follow web-ui.md's wording for the same states elsewhere.
 */
export function statusLine(
  status: Status | null,
  queue: QueueItem[] | null,
  next: ScheduleNext | null,
  now: number,
): StatusLine {
  const run = status?.run;
  const position = itemPosition(status, queue);

  switch (status?.state ?? 'idle') {
    case 'idle':
      return idleLine(next, now);
    case 'paused':
      return { icon: CirclePause, tone: 'warn', text: PAUSED[run?.paused_reason ?? ''] ?? 'Paused' };
    case 'starting':
      return { icon: AudioLines, tone: 'accent', text: 'Starting a backup…' };
    default:
      // running, finishing or stopping. web-ui.md § Running: "Stopping after this track…" until it ends.
      if (run?.stop_mode === 'after_track') return { icon: AudioLines, tone: 'accent', text: 'Stopping after this track…' };
      if (status?.state === 'stopping') return { icon: AudioLines, tone: 'accent', text: 'Stopping…' };
      return {
        icon: AudioLines,
        tone: 'accent',
        text: position ? `Backing up · item ${position.index} of ${position.total}` : 'Backing up',
      };
  }
}

function idleLine(next: ScheduleNext | null, now: number): StatusLine {
  if (!next) return { icon: Moon, tone: 'sub', text: 'Idle' };
  if (next.held_reason) return { icon: CircleAlert, tone: 'danger', text: `Backups held · ${HELD[next.held_reason]}` };
  // web-ui.md § Next backup › No schedule: "No backup scheduled".
  if (!next.at) return { icon: Moon, tone: 'sub', text: 'No backup scheduled' };
  if (next.in_progress && next.window_end) {
    return { icon: Moon, tone: 'sub', text: `Backup window open · until ${formatTime(next.window_end)}` };
  }
  return { icon: Moon, tone: 'sub', text: `Next backup · ${formatWhen(next.at, now)}` };
}

/** The status card's second line: the Web API connection, after a coloured dot. */
export function connectionLine(connection: Connection | null): { text: string; tone: LineTone } | null {
  if (!connection) return null;
  const name = connection.display_name;
  switch (connection.state) {
    case 'ok':
    case 'expiring':
      // Still connected: the dot stays green while expiring, as drawn in fzNDm. The banner gives
      // the date.
      return { tone: 'accent', text: name ? `Connected as ${name}` : 'Connected to Spotify' };
    case 'expired':
      return { tone: 'danger', text: 'Spotify connection expired' };
    default:
      return { tone: 'muted', text: 'Not connected to Spotify' };
  }
}

/**
 * The now-playing strip's session pill. web-ui.md § Now-playing strip: "Waiting, Recording, Paused
 * or Stopping". Spytify's `idle` and `ad` states have no label of their own, so they show Waiting.
 */
export function sessionPill(status: Status): { tone: PillTone; label: string; icon?: LucideIcon } {
  if (status.state === 'paused' || status.session_state === 'paused') return { tone: 'yellow', label: 'Paused' };
  if (status.state === 'stopping' || status.session_state === 'stopping' || status.run?.stop_mode) {
    return { tone: 'neutral', label: 'Stopping' };
  }
  if (status.session_state === 'recording') return { tone: 'green', label: 'Recording', icon: CircleDotDashed };
  return { tone: 'neutral', label: 'Waiting' };
}

/**
 * Whether the strip's track clock ticks. It follows the recorder, not the pill: after "Stop after
 * this track" the pill says Stopping, but the track records to its end, so the clock goes on.
 */
export function trackClockRuns(status: Status): boolean {
  if (!status.track || status.state === 'paused') return false;
  return status.session_state === 'recording' || status.session_state === 'stopping';
}

/**
 * The strip's two lines: the track, then "Artist · Item · track 42". The drawing writes "track 42
 * of 88", but Status carries no track count for the item (`planned` counts only the tracks to
 * record), so the count is left out. Docked on the Dashboard, the queue below names the item.
 */
export function trackLines(status: Status, docked: boolean): { title: string; sub: string } {
  const { track, item } = status;
  if (track) {
    const parts = [track.artist, docked ? null : item?.name, track.position ? `track ${track.position}` : null];
    return { title: track.title, sub: parts.filter(Boolean).join(' · ') };
  }
  const title = item?.name ?? 'Starting a backup';
  switch (status.state) {
    case 'starting':
      return { title, sub: 'Checking settings and playlists…' };
    case 'finishing':
      return { title, sub: 'Saving the last track…' };
    case 'paused':
      return { title, sub: 'Paused' };
    default:
      return { title, sub: 'Waiting for the next track…' };
  }
}
