// The Edit layout modal's live example (web-ui.md § Files: "a live path that updates as you type,
// for example Music/fakename/Elsewhere/05 - Last Hours.m4a"), and its words for a layout that isn't
// valid (src/lib/layout.ts gives the reason; web-ui.md § Files lists the rules).

import type { Layout } from '@/api';
import type { LayoutCheck, LayoutPlaceholder } from '@/lib/layout.ts';

/** The sample track: FINDINGS' "Elsewhere" by fakename, track 5. Spotify on Linux sends no year. */
const SAMPLE: Record<LayoutPlaceholder, string> = {
  album_artist: 'fakename',
  artists: 'fakename',
  title: 'Last Hours',
  album: 'Elsewhere',
  track: '05',
  year: '',
};

/** What the prefix adds before the file name, followed by " - " (web-ui.md § Files, Options). */
const PREFIX: Record<Layout['prefix'], string> = {
  none: '',
  counter: '001 - ',
  track_number: '05 - ',
};

/**
 * The sample track's path under a layout: `Music/` + the pattern filled in + `.extension`, with the
 * prefix before the file name, accents removed and spaces turned to underscores in the names when
 * those options are on. For a valid pattern only (checkLayout first).
 */
export function examplePath(layout: Layout, extension: string): string {
  const filled = layout.pattern.replace(/\{([a-z_]+)\}/g, (_match, name: string) => SAMPLE[name as LayoutPlaceholder] ?? '');
  const folders = filled.split('/');
  const file = folders.pop() ?? '';
  let names = [...folders, PREFIX[layout.prefix] + file];
  if (layout.strip_accents) names = names.map((name) => name.normalize('NFD').replace(/[̀-ͯ]/g, ''));
  if (layout.underscores) names = names.map((name) => name.replace(/ /g, '_'));
  return `Music/${names.join('/')}.${extension}`;
}

/** The red line that replaces the hint, by checkLayout's reason. */
export function layoutError(check: Extract<LayoutCheck, { valid: false }>): string {
  switch (check.reason) {
    case 'unknown_placeholder':
      return `${check.placeholder ?? 'That'} isn't a placeholder. Use one of the six below.`;
    case 'stray_brace':
      return 'A { or } is on its own. Placeholders look like {title}.';
    case 'backslash':
      return 'A \\ can’t be used. Use / between folders.';
    case 'control_character':
      return 'Tabs and line breaks can’t be used.';
    case 'bad_folder':
      return 'Folders can be none, {album_artist}, or {album_artist}/{album}.';
    case 'empty_file_name':
      return 'The file name, after the last /, can’t be empty.';
    case 'no_placeholder':
      return 'The file name needs a placeholder other than {year}, which is always empty.';
  }
}
