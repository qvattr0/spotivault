// A run's own time left (RunSummary.time_left), summed as the controller sums it
// (controller/src/spotivault/engine/time_left.py), and checked against the same vectors
// (contracts/vectors/run-time-left.json, in time-left.test.ts). The world (world.ts) feeds it its
// runs: the current item's take and planned tracks, and each waiting item's tracks.

/** A track still to record: its key (the controller's is Spytify's; the mock's is the track id) and length. */
export interface MissingTrack {
  key: string;
  duration_ms: number;
}

/** What's left of the current item to play (the controller's ItemLive.left). */
export interface ItemLeft {
  /** The rest of the take recording now, if it plays on; else 0. */
  take_ms: number;
  take_key: string | null;
  /** Its planned tracks that haven't started; null when it plays whole (its length unknown). */
  tracks: MissingTrack[] | null;
}

export interface TimeLeftSum {
  ms: number;
  /** ms rounded half up to whole seconds. */
  seconds: number;
  unknown_items: number;
}

/** The backlog estimate's 35 s per item: a few seconds to start, and the Finishing tail. */
export const ITEM_OVERHEAD_MS = 35_000;

export interface WorkOutOptions {
  /** The keys this run has recorded so far (the current item's takes, and the items that ended): they don't count again. */
  recorded?: Iterable<string>;
  /** What's left of a scheduled run's window; null with no window. Without a stop, the sum is capped at it. */
  windowMs?: number | null;
  /** Added for each waiting item with a track to record. */
  overheadMs?: number;
}

/**
 * The sum (openapi.yaml RunTimeLeft): the current item's take and its planned tracks, then each
 * waiting item's tracks plus `overheadMs`, each key once and none this run recorded; items of
 * unknown length counted apart. Without a stop, capped at what's left of the window, with no
 * unknown items past it. After Stop after this track, only the take; after Stop now, nothing.
 */
export function workOut(
  current: ItemLeft | null,
  waiting: (MissingTrack[] | null)[],
  stopMode: 'after_track' | 'now' | null,
  { recorded = [], windowMs = null, overheadMs = ITEM_OVERHEAD_MS }: WorkOutOptions = {},
): TimeLeftSum {
  if (stopMode === 'now') return sum(0, 0);
  let ms = 0;
  let unknown = 0;
  const seen = new Set<string>(recorded);
  if (current) {
    ms += current.take_ms;
    if (current.take_key !== null) seen.add(current.take_key);
  }
  if (stopMode !== null) return sum(ms, 0);
  if (current) {
    if (current.tracks === null) unknown += 1;
    else ms += newMs(current.tracks, seen).ms;
  }
  for (const tracks of waiting) {
    if (tracks === null) {
      unknown += 1;
      continue;
    }
    const item = newMs(tracks, seen);
    if (item.any) ms += item.ms + overheadMs;
  }
  // A scheduled run stops at its window's end: nothing past it runs.
  if (windowMs !== null && ms >= windowMs) return sum(Math.max(0, windowMs), 0);
  return sum(ms, unknown);
}

/** The tracks whose key hasn't come yet, each once: their length, and whether there was one. */
function newMs(tracks: MissingTrack[], seen: Set<string>): { ms: number; any: boolean } {
  let ms = 0;
  let any = false;
  for (const track of tracks) {
    if (seen.has(track.key)) continue;
    seen.add(track.key);
    ms += track.duration_ms;
    any = true;
  }
  return { ms, any };
}

function sum(ms: number, unknown: number): TimeLeftSum {
  return { ms, seconds: Math.floor((ms + 500) / 1000), unknown_items: unknown };
}
