// The client settings checklist's words (web-ui.md § 4, the table): each row's setting, the
// section it's in, and the one-line reason. Wizard step 4 and Settings › Spotify client show the
// same rows; the API (GET /api/client/checklist) gives their state, not their words.

import type { ChecklistRow } from '@/api';

export type ChecklistRowId = ChecklistRow['id'];
export type ChecklistSection = ChecklistRow['section'];

export interface ChecklistWords {
  /** The setting, as the client's Settings names it: "Crossfade". */
  label: string;
  /** Why it matters, in one line. */
  reason: string;
}

/** web-ui.md § 4: Setting and Why, per row. */
export const CHECKLIST_WORDS: Record<ChecklistRowId, ChecklistWords> = {
  crossfade: { label: 'Crossfade', reason: "Overlapping tracks can't be split." },
  gapless: { label: 'Gapless playback', reason: 'A short gap gives clean cuts. Spytify trims the silence.' },
  automix: { label: 'Automix', reason: 'Blends and alters transitions.' },
  autoplay: {
    label: 'Autoplay',
    reason: 'Stops similar songs from playing after the playlist. It may be hidden for some accounts.',
  },
  normalization: {
    label: 'Volume normalization',
    reason: 'Alters levels, and "Loud" compresses. Use ReplayGain at playback instead.',
  },
  equalizer: { label: 'Equalizer', reason: 'Colours the recording.' },
  mono: { label: 'Mono audio', reason: 'Would record mono.' },
  streaming_quality: { label: 'Streaming quality', reason: 'It is the quality that gets recorded.' },
  auto_adjust_quality: { label: 'Auto adjust quality', reason: 'Spotify buffers instead of silently lowering quality.' },
  volume: { label: 'Volume', reason: 'Spytify marks takes below full volume as "(low volume)" and doesn\'t count them.' },
};

/** The sections, in the client's order, with their headings. */
export const CHECKLIST_SECTIONS: { id: ChecklistSection; label: string }[] = [
  { id: 'playback', label: 'Playback' },
  { id: 'audio_quality', label: 'Audio quality' },
  { id: 'player', label: 'Player' },
];

/** How a row is checked, as its pill names it (web-ui.md § 4: Auto, Confirm, Set for you). */
export const CHECK_LABEL: Record<ChecklistRow['check'], string> = {
  auto: 'Auto',
  confirm: 'Confirm',
  set_for_you: 'Set for you',
};

/** An Auto row's state pill (web-ui.md § 4: "OK, Needs change, or Unknown"). */
export const AUTO_STATE_LABEL: Record<NonNullable<ChecklistRow['state']>, string> = {
  ok: 'OK',
  needs_change: 'Needs change',
  unknown: 'Unknown',
};

/**
 * Whether the row is satisfied: an Auto row that's OK, a Confirm row that's ticked, and Set for
 * you always. Step 4's Continue needs every blocker satisfied (web-ui.md § 4: "Autoplay can be
 * left unticked").
 */
export function rowSatisfied(row: ChecklistRow): boolean {
  if (row.check === 'auto') return row.state === 'ok';
  if (row.check === 'confirm') return row.confirmed === true;
  return true;
}
