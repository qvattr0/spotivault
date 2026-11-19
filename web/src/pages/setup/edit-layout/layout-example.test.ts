import { describe, expect, it } from 'vitest';
import { checkLayout, DEFAULT_LAYOUT_PATTERN } from '@/lib/layout.ts';
import type { Layout } from '@/api';
import { examplePath, layoutError } from './layout-example.ts';

const DEFAULT: Layout = { pattern: DEFAULT_LAYOUT_PATTERN, prefix: 'none', underscores: false, strip_accents: false };

function errorFor(pattern: string): string {
  const check = checkLayout(pattern);
  if (check.valid) throw new Error(`${pattern} is valid`);
  return layoutError(check);
}

describe('examplePath', () => {
  it('fills in the sample track, as web-ui.md § Files writes it', () => {
    expect(examplePath(DEFAULT, 'm4a')).toBe('Music/fakename/Elsewhere/05 - Last Hours.m4a');
  });

  it('follows the format, the folders and the options', () => {
    expect(examplePath({ ...DEFAULT, pattern: '{title}' }, 'mp3')).toBe('Music/Last Hours.mp3');
    expect(examplePath({ ...DEFAULT, prefix: 'counter' }, 'm4a')).toBe('Music/fakename/Elsewhere/001 - 05 - Last Hours.m4a');
    expect(examplePath({ ...DEFAULT, pattern: '{album_artist}/{title}', prefix: 'track_number' }, 'flac')).toBe(
      'Music/fakename/05 - Last Hours.flac',
    );
    expect(examplePath({ ...DEFAULT, underscores: true }, 'm4a')).toBe('Music/fakename/Elsewhere/05_-_Last_Hours.m4a');
  });

  it('leaves {year} empty', () => {
    expect(examplePath({ ...DEFAULT, pattern: '{year}{title}' }, 'm4a')).toBe('Music/Last Hours.m4a');
  });
});

describe('layoutError', () => {
  it('names an unknown placeholder', () => {
    expect(errorFor('{album_artist}/{genre} {title}')).toBe("{genre} isn't a placeholder. Use one of the six below.");
  });

  it('words every rule of web-ui.md § Files', () => {
    expect(errorFor('{title')).toMatch(/on its own/);
    expect(errorFor('{album_artist}\\{title}')).toMatch(/can’t be used/);
    expect(errorFor('{title}\t')).toMatch(/Tabs and line breaks/);
    expect(errorFor('{album}/{title}')).toMatch(/^Folders can be none/);
    expect(errorFor('{album_artist}/')).toMatch(/can’t be empty/);
    expect(errorFor('{album_artist}/{year}')).toMatch(/other than \{year\}/);
  });
});
