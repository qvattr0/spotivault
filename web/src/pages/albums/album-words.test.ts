import { describe, expect, it } from 'vitest';
import type { ItemTrack } from '@/api';
import { albumSub, filesText, recordedText, summaryText, trackView, tracksText } from './album-words.ts';
import { filterSaved, replaceAlbum } from './album-data.ts';

function track(over: Partial<ItemTrack>): ItemTrack {
  return {
    position: 1,
    track_id: null,
    title: 'Airbag',
    artists: ['Radiohead'],
    album: 'OK Computer',
    duration_ms: 284_000,
    state: 'recorded',
    size_bytes: 9_400_000,
    path: null,
    reason: null,
    recorded_at: null,
    ...over,
  };
}

describe('the albums page words', () => {
  it('sums the header line, in the singular for one album', () => {
    expect(summaryText({ total: 42, recorded: 39, queued: 3, partial: 0 })).toBe('42 albums · 39 recorded · 3 queued');
    expect(summaryText({ total: 1, recorded: 0, queued: 1, partial: 0 })).toBe('1 album · 0 recorded · 1 queued');
  });

  it('writes the artist and year, and only the artist when the year is unknown', () => {
    expect(albumSub({ artist: 'Radiohead', year: 1997 })).toBe('Radiohead · 1997');
    expect(albumSub({ artist: 'Radiohead', year: null })).toBe('Radiohead');
  });

  it('shows recorded tracks over the total, and the completion date or a dash', () => {
    expect(tracksText({ recorded: 9, total: 13 })).toBe('9 / 13');
    expect(recordedText({ completed_at: null })).toBe('—');
    expect(recordedText({ completed_at: '2026-11-03T10:00:00Z' })).toMatch(/Nov 2026$/);
  });

  it('words each track state as the table does', () => {
    expect(trackView(track({}))).toEqual({ kind: 'recorded', text: 'Recorded · 9.4 MB' });
    expect(trackView(track({ state: 'skipped_duplicate', size_bytes: null }))).toEqual({ kind: 'skipped', text: 'Skipped (duplicate)' });
    expect(trackView(track({ state: 'failed', reason: 'low_volume' }))).toEqual({ kind: 'failed', text: 'Failed · low volume' });
    // A failed `discarded` row has no file: a take Stop now cut in an older run (run-words.ts).
    expect(trackView(track({ state: 'failed', reason: 'discarded' }))).toEqual({ kind: 'failed', text: 'Failed · discarded by Stop now' });
    expect(trackView(track({ state: 'missing', size_bytes: null }))).toEqual({ kind: 'missing', text: 'Missing' });
    expect(trackView(track({ state: 'new', size_bytes: null }))).toEqual({ kind: 'new', text: 'New' });
  });

  it('says where the files are, from the first recorded track', () => {
    const tracks = [
      track({ path: null }),
      track({ path: 'Radiohead/OK Computer/01 - Airbag.m4a' }),
      track({ path: 'Radiohead/OK Computer/02 - Paranoid.m4a' }),
    ];
    expect(filesText({ tracks })).toBe('Recorded in Radiohead/OK Computer');
    expect(filesText({ tracks: [track({})] })).toBe('Nothing is recorded yet, so there are no files.');
    expect(filesText({ tracks: [track({ path: 'Song.m4a' })] })).toBe('Recorded in the music folder');
  });
});

describe('the albums page data', () => {
  const data = {
    items: [
      { id: 'a', name: 'A', artist: 'X', year: 1, cover: null, uri: 'spotify:album:a', total: 2, recorded: 0, status: 'queued' as const, added_at: '', completed_at: null, progress: null },
      { id: 'b', name: 'B', artist: 'Y', year: 2, cover: null, uri: 'spotify:album:b', total: 2, recorded: 0, status: 'queued' as const, added_at: '', completed_at: null, progress: null },
    ],
    summary: { total: 2, recorded: 0, queued: 2, partial: 0 },
  };

  it('replaces one album when it changes, and leaves the others', () => {
    const next = replaceAlbum(data, { ...data.items[1]!, status: 'recording' });
    expect(next.items.map((item) => item.status)).toEqual(['queued', 'recording']);
    expect(next.summary).toBe(data.summary);
  });

  it('filters the + modal by name, ignoring case and spaces at the ends', () => {
    const saved = [
      { id: '1', uri: '', name: 'Currents', artist: 'Tame Impala', year: 2015, cover: null, total: 13, saved_at: '' },
      { id: '2', uri: '', name: 'Punisher', artist: 'Phoebe Bridgers', year: 2020, cover: null, total: 11, saved_at: '' },
    ];
    expect(filterSaved(saved, '  cur ').map((a) => a.id)).toEqual(['1']);
    expect(filterSaved(saved, '').length).toBe(2);
    expect(filterSaved(saved, 'zzz')).toEqual([]);
  });
});
