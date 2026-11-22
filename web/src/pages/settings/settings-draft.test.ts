import { describe, expect, it } from 'vitest';
import type { Settings } from '@/api';
import { settingsDefault } from '../../../mock/fixtures.ts';
import { changesOf, draftOf } from './settings-draft.ts';

const saved: Settings = settingsDefault;

describe('draftOf', () => {
  it('puts the edits over the saved settings, and follows the extension from the format', () => {
    const draft = draftOf(saved, { format: 'flac', bitrate: null });
    expect(draft).toMatchObject({ format: 'flac', bitrate: null, extension: 'flac', write_m3u: true });
    expect(draftOf(saved, {}).extension).toBe('m4a');
  });
});

describe('changesOf', () => {
  it('is empty when nothing differs, even after an edit set back to its saved value', () => {
    expect(changesOf(saved, draftOf(saved, { write_m3u: true }))).toEqual({});
  });

  it('sends only the fields that differ', () => {
    expect(changesOf(saved, draftOf(saved, { write_m3u: false }))).toEqual({ write_m3u: false });
  });

  it('sends format and bitrate together', () => {
    expect(changesOf(saved, draftOf(saved, { format: 'aac', bitrate: 320 }))).toEqual({ format: 'aac', bitrate: 320 });
    expect(changesOf(saved, draftOf(saved, { format: 'wav', bitrate: null }))).toEqual({ format: 'wav', bitrate: null });
  });

  it('sends the whole layout when any part of it changes', () => {
    const layout = { ...saved.layout, underscores: true };
    expect(changesOf(saved, draftOf(saved, { layout }))).toEqual({ layout });
    expect(changesOf(saved, draftOf(saved, { layout: { ...saved.layout } }))).toEqual({});
  });
});
