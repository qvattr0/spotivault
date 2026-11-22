// The recording formats (web-ui.md § 6 Output, and Settings › Recording): the three offered, and
// FLAC and WAV under "More formats". Wizard step 6 and Settings show the same choices.

import type { Settings } from '@/api';

export type FormatChoiceId = 'aac256' | 'aac320' | 'mp3320' | 'flac' | 'wav';

export interface FormatChoice {
  id: FormatChoiceId;
  /** "AAC 256" */
  label: string;
  format: Settings['format'];
  /** Null for FLAC and WAV, which have no bitrate. */
  bitrate: 256 | 320 | null;
  extension: string;
  /** Under "More formats". */
  more: boolean;
}

export const FORMAT_CHOICES: FormatChoice[] = [
  { id: 'aac256', label: 'AAC 256', format: 'aac', bitrate: 256, extension: 'm4a', more: false },
  { id: 'aac320', label: 'AAC 320', format: 'aac', bitrate: 320, extension: 'm4a', more: false },
  { id: 'mp3320', label: 'MP3 320', format: 'mp3', bitrate: 320, extension: 'mp3', more: false },
  { id: 'flac', label: 'FLAC', format: 'flac', bitrate: null, extension: 'flac', more: true },
  { id: 'wav', label: 'WAV', format: 'wav', bitrate: null, extension: 'wav', more: true },
];

/** The default (web-ui.md § 6: "AAC 256 (default)"). */
export const DEFAULT_FORMAT: FormatChoiceId = 'aac256';

/** What "More formats" says of FLAC and WAV (web-ui.md § 6 and Settings › Recording). */
export const NO_BENEFIT = 'No benefit: the source is lossy. Bigger files, same quality.';
export const NO_BENEFIT_SETTINGS = 'No benefit: the source is lossy (Ogg Vorbis 320). Bigger files, same quality.';

/** The choice that matches saved settings. */
export function formatChoiceOf(settings: Pick<Settings, 'format' | 'bitrate'>): FormatChoice {
  return (
    FORMAT_CHOICES.find((c) => c.format === settings.format && (c.bitrate === null || c.bitrate === settings.bitrate)) ??
    FORMAT_CHOICES[0]!
  );
}

/** The PUT /api/settings body for a choice: `format` and `bitrate` go together (SettingsUpdate). */
export function formatUpdate(id: FormatChoiceId): Pick<Settings, 'format' | 'bitrate'> {
  const choice = FORMAT_CHOICES.find((c) => c.id === id) ?? FORMAT_CHOICES[0]!;
  return { format: choice.format, bitrate: choice.bitrate };
}
