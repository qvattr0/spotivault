import { describe, expect, it } from 'vitest';
import type { ItemTrack, LibraryItem } from '@/api';
import { libraryItems } from '@mock/fixtures.ts';
import {
  detailMeta,
  hasTotalTooltip,
  librarySummaryText,
  ownerLine,
  progressOf,
  recordedText,
  refreshedText,
  statusView,
  trackView,
} from './library-words.ts';
import type { CatalogRefreshEvent } from '@/state';

const base = libraryItems[1] as LibraryItem;
const item = (over: Partial<LibraryItem>): LibraryItem => ({ ...base, ...over });

describe('statusView', () => {
  it('words every status the contract gives', () => {
    expect(statusView(item({ status: 'not_tracked' })).label).toBe('Not tracked');
    expect(statusView(item({ status: 'never_backed_up' })).label).toBe('Never backed up');
    expect(statusView(item({ status: 'up_to_date' })).label).toBe('Up to date');
    expect(statusView(item({ status: 'partial' })).tone).toBe('yellow');
    expect(statusView(item({ status: 'unavailable' })).tone).toBe('red');
  });

  it('says "n new" with the count, in blue', () => {
    expect(statusView(item({ status: 'new', new: 14 }))).toMatchObject({ label: '14 new', tone: 'blue' });
  });

  it('links Recording and Queued to the Dashboard', () => {
    expect(statusView(item({ status: 'recording' }))).toMatchObject({ label: 'Recording', to: '/dashboard' });
    expect(statusView(item({ status: 'queued' }))).toMatchObject({ label: 'Queued', to: '/dashboard' });
    expect(statusView(item({ status: 'up_to_date' })).to).toBeUndefined();
  });
});

describe('owner line and counts', () => {
  it('reads the kind: by you, by someone, added by link, Liked Songs', () => {
    expect(ownerLine(item({ kind: 'owned', owner: 'you' }))).toBe('by you');
    expect(ownerLine(item({ kind: 'followed', owner: 'Lorde' }))).toBe('by Lorde');
    expect(ownerLine(item({ kind: 'linked', owner: 'KEXP' }))).toBe('added by link');
    expect(ownerLine(item({ kind: 'liked', total: 412 }))).toBe('Playlist · pinned · 412 songs');
  });

  it('gives the recorded count with its total, or without one', () => {
    expect(recordedText(item({ total: 120, recorded: 84 }))).toBe('84 / 120 recorded');
    expect(recordedText(item({ total: null, recorded: 32 }))).toBe('32 recorded');
  });

  it('puts the tooltip on followed playlists only, the ones with a listed total', () => {
    expect(hasTotalTooltip(item({ kind: 'followed', item_access: false, total: 35 }))).toBe(true);
    expect(hasTotalTooltip(item({ kind: 'owned', item_access: true, total: 35 }))).toBe(false);
    expect(hasTotalTooltip(item({ kind: 'linked', item_access: false, total: null }))).toBe(false);
  });

  it('fills the ring from the run\'s progress', () => {
    expect(progressOf(item({ progress: null }))).toBeNull();
    expect(progressOf(item({ progress: { run_id: 1, state: 'playing', recorded: 3, planned: 12 } }))).toBeCloseTo(0.25);
    expect(progressOf(item({ progress: { run_id: 1, state: 'playing', recorded: 3, planned: null } }))).toBe(0);
  });
});

describe('librarySummaryText', () => {
  const now = new Date(2026, 10, 17, 14, 0).getTime();
  it('counts tracked over all, with the newest last backup', () => {
    const items = [
      item({ tracked: true, last_backup_at: new Date(2026, 10, 17, 3, 12).toISOString() }),
      item({ tracked: false, last_backup_at: null }),
      item({ tracked: true, last_backup_at: new Date(2026, 10, 16, 23, 0).toISOString() }),
    ];
    expect(librarySummaryText(items, now)).toBe('2 of 3 tracked · last backup 03:12 today');
  });

  it('leaves the backup out when there has never been one', () => {
    expect(librarySummaryText([item({ tracked: true, last_backup_at: null })], now)).toBe('1 of 1 tracked');
  });

  it('says yesterday for the day before', () => {
    const items = [item({ tracked: true, last_backup_at: new Date(2026, 10, 16, 1, 5).toISOString() })];
    expect(librarySummaryText(items, now)).toBe('1 of 1 tracked · last backup 01:05 yesterday');
  });
});

describe('detailMeta', () => {
  it('reads: by you · 120 tracks · 7 h 48 min · 118 recorded', () => {
    const text = detailMeta(item({ kind: 'owned', total: 120, recorded: 118 }), 28_080_000, () => '7 h 48 min');
    expect(text).toBe('by you · 120 tracks · 7 h 48 min · 118 recorded');
  });

  it('leaves out what is unknown', () => {
    expect(detailMeta(item({ kind: 'linked', owner: 'KEXP', total: null, recorded: 12 }), null, () => '')).toBe('by KEXP · 12 recorded');
  });
});

describe('trackView', () => {
  const track = (over: Partial<ItemTrack>): ItemTrack => ({
    position: 1, track_id: null, title: 'T', artists: [], album: null, duration_ms: null, state: 'recorded',
    size_bytes: 9_400_000, path: 'A/B/01 - T.m4a', reason: null, recorded_at: null, ...over,
  });

  it('shows a recorded track with its size, and its path as the hover', () => {
    expect(trackView(track({}))).toEqual({ kind: 'recorded', text: 'Recorded · 9.4 MB', hint: 'A/B/01 - T.m4a' });
  });

  it('words failures with their reason', () => {
    expect(trackView(track({ state: 'failed', reason: 'low_volume' }))).toEqual({ kind: 'failed', text: 'Failed · low volume' });
    // A failed `discarded` row has no file: a take Stop now cut in an older run (run-words.ts).
    expect(trackView(track({ state: 'failed', reason: 'discarded' }))).toEqual({ kind: 'failed', text: 'Failed · discarded by Stop now' });
  });

  it('words the other states', () => {
    expect(trackView(track({ state: 'skipped_duplicate' })).text).toBe('Skipped (duplicate)');
    expect(trackView(track({ state: 'missing' })).text).toBe('Missing');
    expect(trackView(track({ state: 'new' })).text).toBe('New');
  });
});

describe('refreshedText', () => {
  const ended = (over: Partial<CatalogRefreshEvent>): CatalogRefreshEvent => ({
    refresh_id: 57,
    trigger: 'manual',
    state: 'ended',
    outcome: 'ok',
    items_changed: 0,
    items_added: 0,
    suggestions_added: 0,
    reason: null,
    ...over,
  });

  it('says what the refresh found, and where a followed playlist waits', () => {
    expect(refreshedText(ended({}))).toBe('Library refreshed');
    expect(refreshedText(ended({ items_added: 1 }))).toBe('Library refreshed · 1 new playlist');
    expect(refreshedText(ended({ suggestions_added: 1 }))).toBe('Library refreshed · 1 followed playlist to add with +');
    expect(refreshedText(ended({ items_added: 2, suggestions_added: 2 }))).toBe(
      'Library refreshed · 2 new playlists · 2 followed playlists to add with +',
    );
    expect(refreshedText(ended({ outcome: 'partial', items_changed: 3 }))).toBe(
      "Library refreshed · some playlists couldn't be read",
    );
  });

  it("says why it didn't refresh, from the event's reason", () => {
    const failed = (reason: CatalogRefreshEvent['reason']) => refreshedText(ended({ outcome: 'failed', reason }));
    const skipped = (reason: CatalogRefreshEvent['reason']) =>
      refreshedText(ended({ outcome: 'skipped', refresh_id: null, reason }));
    // Spotify's invalid_grant: reconnecting helps, trying again later doesn't.
    expect(failed('connection_expired')).toBe('The Spotify connection expired. Reconnect to refresh the Library.');
    expect(skipped('connection_expired')).toBe('The Spotify connection expired. Reconnect to refresh the Library.');
    expect(failed('rate_limited')).toBe(
      "The Library couldn't be refreshed: Spotify asked spotivault to wait. Try again in a few minutes.",
    );
    expect(failed('spotify_unavailable')).toBe("The Library couldn't be refreshed: Spotify didn't answer. Try again later.");
    expect(failed('internal')).toBe("The Library couldn't be refreshed. Try again later.");
    expect(failed(null)).toBe("The Library couldn't be refreshed. Try again later.");
    expect(skipped('run_active')).toBe(
      "The Library wasn't refreshed: a backup started, and each backup refreshes it first.",
    );
    expect(skipped('not_connected')).toBe("The Library wasn't refreshed: the Spotify Web API isn't connected.");
  });
});
