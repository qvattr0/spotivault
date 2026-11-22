// How runs, their items and their tracks are worded and coloured, where more than one page shows
// them: the Dashboard (Last run, the live queue and track table), History (the run list and the
// run page), and the Library's and Albums' track tables. Wording from web-ui.md; pill colours from
// components.md § Status pill.

import type { HistoryRow, ItemBadge, Outcome, RunCreated, TrackResult, Trigger } from '@/api';
import type { PillTone } from '@/components/ui-a';

/** web-ui.md § Runs tab, Outcome: "Completed · Completed with issues · Window ended · Stopped · Failed". */
export const OUTCOME: Record<Outcome, { label: string; tone: PillTone }> = {
  completed: { label: 'Completed', tone: 'green' },
  completed_with_issues: { label: 'Completed with issues', tone: 'yellow' },
  window_ended: { label: 'Window ended', tone: 'blue' },
  stopped: { label: 'Stopped', tone: 'neutral' },
  failed: { label: 'Failed', tone: 'red' },
};

/** web-ui.md § Runs tab, Trigger: "Scheduled · Run now · Start-up". */
export const TRIGGER: Record<Trigger, string> = {
  scheduled: 'Scheduled',
  run_now: 'Run now',
  startup: 'Start-up',
};

/** A run that didn't happen, as its greyed row says (web-ui.md § Runs tab, "Rows with no run"). */
export function noRunText(row: Pick<HistoryRow, 'kind' | 'reason'>): string {
  switch (row.kind) {
    case 'missed':
      return 'Missed: spotivault was not running';
    case 'skipped':
      return 'Skipped: the previous run was paused';
    case 'held':
      return row.reason === 'client_logged_out' ? 'Held: the Spotify client was logged out' : 'Held: Spotify connection expired';
    default:
      return '';
  }
}

/** Why a run failed (HistoryRow.reason), in words: "container restarted". Unknown reasons pass through. */
export function failureText(reason: string | null): string | null {
  if (!reason) return null;
  const words: Record<string, string> = {
    container_restarted: 'container restarted',
    setting_drifted: 'a client setting changed',
    client_logged_out: 'the Spotify client was logged out',
    connection_expired: 'the Spotify connection expired',
    not_running: 'spotivault was not running',
    previous_paused: 'the previous run was paused',
    storage: 'the music folder is not usable',
    // Our device wasn't listed, even after the client restart (web-ui.md § Warnings, Client not
    // running), or it went away mid-run. Worded as wizard step 5's check.
    device_missing: "the container's client isn't listed as a playback device",
    recorder: 'the recorder failed',
  };
  return words[reason] ?? reason.replace(/_/g, ' ');
}

/** The run page's item badges (web-ui.md § Run page, "Badges where they apply"). */
export const BADGE: Record<ItemBadge, { label: string; tone: PillTone }> = {
  up_to_date: { label: 'Up to date: nothing new', tone: 'neutral' },
  interrupted_retried: { label: 'Interrupted, retried', tone: 'yellow' },
  interrupted_twice: { label: 'Interrupted twice: Partial', tone: 'yellow' },
  carried_over_in: { label: 'Carried over from the previous run', tone: 'neutral' },
  carried_over_out: { label: 'Carried over to the next run', tone: 'blue' },
  removed: { label: 'Removed from run', tone: 'neutral' },
  stopped: { label: 'Stopped', tone: 'neutral' },
};

/**
 * A failed track's reason, or a skipped one's, in words (web-ui.md § Run page: "low volume",
 * "recorder error", "track unavailable", "interrupted", "discarded by Stop now"; and Spytify's skip
 * reasons, shown as "Skipped (ad)"). Used after "Failed · "; a skipped track's goes through
 * skipReasonText, since `discarded` means something else there.
 */
export function trackReasonText(reason: string | null): string | null {
  if (!reason) return null;
  const words: Record<string, string> = {
    low_volume: 'low volume',
    recorder_error: 'recorder error',
    unavailable: 'track unavailable',
    interrupted: 'interrupted',
    // Failed `discarded` with no file: a take Stop now cut in an older run, from before such a
    // take was skipped. It's every one stored so far, and the Library's and Albums' failed rows
    // carry no file. One with a file is a partial take (trackResultText).
    discarded: 'discarded by Stop now',
    duplicate: 'duplicate',
    ad: 'ad',
    too_short: 'too short',
    incomplete: 'incomplete',
    seeked: 'seeked',
    low_quality: 'low quality',
    silent: 'silent',
  };
  return words[reason] ?? reason.replace(/_/g, ' ');
}

/**
 * A skipped track's reason, inside "Skipped (…)": Spytify's skip reasons, and `discarded`, a take
 * dropped because the backup was stopped mid-track (Stop now, or the container stopping). That's
 * not a failure: the track is recorded next time (web-ui.md § Run page).
 */
export function skipReasonText(reason: string | null): string | null {
  if (reason === 'discarded') return 'backup stopped mid-track';
  return trackReasonText(reason);
}

/** A failed `discarded` take that has a file: Spytify saved it as "<title> (partial)". */
export const PARTIAL_TAKE = 'partial take';

/** A track's result in a run, as one line: "Recorded", "Skipped (duplicate)", "Failed · low volume". */
export function trackResultText(track: Pick<TrackResult, 'result' | 'reason' | 'path'>): string {
  if (track.result === 'skipped') return `Skipped (${skipReasonText(track.reason) ?? 'other'})`;
  if (track.result === 'recorded') return 'Recorded';
  // A failed `discarded` with a file is a partial take; with none, an older run's Stop now.
  const reason = track.reason === 'discarded' && track.path ? PARTIAL_TAKE : trackReasonText(track.reason);
  return reason ? `Failed · ${reason}` : 'Failed';
}

/**
 * The toast after Back up now, Record now, Record again or Retry failed (POST /api/runs with
 * `items`). web-ui.md § Running: during a run the item goes right after the current one, "with a
 * toast: Added to the current run", and "the toast must say so when nothing was added" (the
 * current item, or one that already ended in this run: `added` is empty). Ours: the wording for
 * a new run and for nothing added.
 */
export function runCreatedText(result: Pick<RunCreated, 'started' | 'added'>): string {
  if (result.started) return 'Backup started';
  if (result.added.length > 0) return 'Added to the current run';
  return 'Already in the current run: nothing added';
}
