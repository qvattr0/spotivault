// The file layout's rules (web-ui.md § Files, Edit layout modal): which patterns are valid, and
// why one isn't. The same rules as the controller's (contracts/vectors/layouts.json, which
// layout.test.ts runs), so the modal can say what's wrong as you type, before PUT /api/settings
// would refuse it with 422 `invalid_layout`.
//
//   const check = checkLayout('{album_artist}/{album}/{track} - {title}');
//   if (!check.valid) showError(check.reason, check.placeholder);
//
// Browser-safe and pure: the mock backend uses it too.

/** The placeholders the Insert chips type, in the order web-ui.md lists them. */
export const LAYOUT_PLACEHOLDERS = ['album_artist', 'artists', 'title', 'album', 'track', 'year'] as const;

export type LayoutPlaceholder = (typeof LAYOUT_PLACEHOLDERS)[number];

/** The default pattern, between the fixed `Music/` and the extension. */
export const DEFAULT_LAYOUT_PATTERN = '{album_artist}/{album}/{track} - {title}';

/**
 * Why a pattern is refused: `details.reason` of the 422, in the order the checks run.
 * - `unknown_placeholder`: a `{…}` that isn't one of the six (`placeholder` names it).
 * - `stray_brace`: a `{` or `}` that isn't part of a placeholder.
 * - `backslash`, `control_character`: a `\`, or a tab, a line break or another control character.
 * - `bad_folder`: the folder part isn't none, `{album_artist}` or `{album_artist}/{album}`.
 * - `empty_file_name`: nothing (or only spaces) after the last `/`.
 * - `no_placeholder`: the file name has no placeholder other than `{year}`.
 */
export type LayoutProblem =
  | 'unknown_placeholder'
  | 'stray_brace'
  | 'backslash'
  | 'control_character'
  | 'bad_folder'
  | 'empty_file_name'
  | 'no_placeholder';

export type LayoutCheck =
  | { valid: true }
  | { valid: false; reason: LayoutProblem; /** The unknown placeholder, with its braces. */ placeholder: string | null };

const BRACED = /\{[^{}]*\}/g;
// Control characters are exactly what this rule is about.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\x00-\x1f\x7f]/;
const FOLDERS = ['{album_artist}', '{album_artist}/{album}'];
/** Spytify needs one of these in the file name; {year} is always empty on Linux. */
const NAMING = ['album_artist', 'artists', 'title', 'album', 'track'];

/** Checks a pattern; the first rule that fails is the reason. */
export function checkLayout(pattern: string): LayoutCheck {
  const fail = (reason: LayoutProblem, placeholder: string | null = null): LayoutCheck => ({ valid: false, reason, placeholder });
  const braced = pattern.match(BRACED) ?? [];
  const unknown = braced.find((m) => !(LAYOUT_PLACEHOLDERS as readonly string[]).includes(m.slice(1, -1)));
  if (unknown) return fail('unknown_placeholder', unknown);
  const rest = pattern.replace(BRACED, '');
  if (rest.includes('{') || rest.includes('}')) return fail('stray_brace');
  if (pattern.includes('\\')) return fail('backslash');
  if (CONTROL.test(pattern)) return fail('control_character');
  const slash = pattern.lastIndexOf('/');
  const folder = slash === -1 ? null : pattern.slice(0, slash);
  const name = slash === -1 ? pattern : pattern.slice(slash + 1);
  if (folder !== null && !FOLDERS.includes(folder)) return fail('bad_folder');
  if (!name.trim()) return fail('empty_file_name');
  const named = (name.match(BRACED) ?? []).some((m) => NAMING.includes(m.slice(1, -1)));
  if (!named) return fail('no_placeholder');
  return { valid: true };
}
