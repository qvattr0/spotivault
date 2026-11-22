// The settings page's unsaved changes (web-ui.md § Settings, "Saving"): the saved settings, the
// edits made since, and the PUT body that sends only what differs. Pure, so it's unit-tested.
//
// The page keeps `edits` (only the fields the user changed). The draft is the saved settings with
// those edits on top. Save sends `changesOf(saved, draft)`, which is empty when nothing differs
// (an edit set back to its saved value isn't a change).

import type { Format, Layout, Settings, SettingsUpdate } from '@/api';

/** The extension each format records to. Settings.extension is read-only: it follows the format. */
const EXTENSION: Record<Format, Settings['extension']> = { aac: 'm4a', mp3: 'mp3', flac: 'flac', wav: 'wav' };

/** The settings as the page shows them: the saved ones with the edits on top. */
export function draftOf(saved: Settings, edits: Partial<Settings>): Settings {
  const merged = { ...saved, ...edits };
  return { ...merged, extension: EXTENSION[merged.format] };
}

/** What differs from the saved settings, as a PUT body. Format and bitrate go together. */
export function changesOf(saved: Settings, draft: Settings): SettingsUpdate {
  const changes: SettingsUpdate = {};
  if (draft.format !== saved.format || draft.bitrate !== saved.bitrate) {
    changes.format = draft.format;
    changes.bitrate = draft.bitrate;
  }
  if (draft.write_m3u !== saved.write_m3u) changes.write_m3u = draft.write_m3u;
  if (draft.save_spotify_covers !== saved.save_spotify_covers) changes.save_spotify_covers = draft.save_spotify_covers;
  if (draft.auto_track_owned !== saved.auto_track_owned) changes.auto_track_owned = draft.auto_track_owned;
  if (!sameLayout(saved.layout, draft.layout)) changes.layout = draft.layout;
  return changes;
}

export function sameLayout(a: Layout, b: Layout): boolean {
  return a.pattern === b.pattern && a.prefix === b.prefix && a.underscores === b.underscores && a.strip_accents === b.strip_accents;
}
