import { describe, expect, it } from 'vitest';
import { errorText } from './errors.ts';
import { formatChoiceOf, formatUpdate } from './formats.ts';
import { failureText, noRunText, runCreatedText, trackResultText } from './run-words.ts';
import { spotifyWebUrl } from './spotify.ts';

describe('run words', () => {
  it('words the rows with no run as web-ui.md does', () => {
    expect(noRunText({ kind: 'missed', reason: 'not_running' })).toBe('Missed: spotivault was not running');
    expect(noRunText({ kind: 'skipped', reason: 'previous_paused' })).toBe('Skipped: the previous run was paused');
    expect(noRunText({ kind: 'held', reason: 'connection_expired' })).toBe('Held: Spotify connection expired');
  });

  it('words track results and failure reasons', () => {
    expect(trackResultText({ result: 'skipped', reason: 'duplicate', path: null })).toBe('Skipped (duplicate)');
    expect(trackResultText({ result: 'skipped', reason: 'ad', path: null })).toBe('Skipped (ad)');
    // A take Stop now (or the container stopping) cut short is skipped, not failed.
    expect(trackResultText({ result: 'skipped', reason: 'discarded', path: null })).toBe('Skipped (backup stopped mid-track)');
    // A failed `discarded` with a file is a partial take; with none, an older run's Stop now
    // (openapi.yaml TrackResult.reason).
    expect(trackResultText({ result: 'failed', reason: 'discarded', path: 'Mix/a (partial).m4a' })).toBe('Failed · partial take');
    expect(trackResultText({ result: 'failed', reason: 'discarded', path: null })).toBe('Failed · discarded by Stop now');
    expect(trackResultText({ result: 'failed', reason: 'low_volume', path: 'Mix/a.m4a' })).toBe('Failed · low volume');
    expect(trackResultText({ result: 'recorded', reason: null, path: 'Mix/a.m4a' })).toBe('Recorded');
    expect(failureText('container_restarted')).toBe('container restarted');
    // The client restarted for a run, and its device never showed up (web-ui.md § Warnings).
    expect(failureText('device_missing')).toBe("the container's client isn't listed as a playback device");
    expect(failureText('something_new')).toBe('something new');
  });
});

describe('runCreatedText', () => {
  it('says whether the item joined the run, as web-ui.md asks', () => {
    expect(runCreatedText({ started: false, added: ['liked'] })).toBe('Added to the current run');
    expect(runCreatedText({ started: false, added: [] })).toMatch(/nothing added/);
    expect(runCreatedText({ started: true, added: ['liked'] })).toBe('Backup started');
  });
});

describe('errorText', () => {
  it("prefers the page's wording, and falls back to the general line", () => {
    expect(errorText({ code: 'not_found' }, { not_found: 'Spotify has no such playlist.' })).toBe('Spotify has no such playlist.');
    expect(errorText({ code: 'network' })).toMatch(/^Can't reach spotivault/);
  });
});

describe('formats', () => {
  it('maps settings to choices and back', () => {
    expect(formatChoiceOf({ format: 'aac', bitrate: 320 }).label).toBe('AAC 320');
    expect(formatChoiceOf({ format: 'flac', bitrate: null }).label).toBe('FLAC');
    expect(formatUpdate('mp3320')).toEqual({ format: 'mp3', bitrate: 320 });
  });
});

describe('spotifyWebUrl', () => {
  it('opens playlists, albums and Liked Songs on open.spotify.com', () => {
    expect(spotifyWebUrl('spotify:playlist:3cEYpjA9oz9GiPac4AsH4n')).toBe('https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsH4n');
    expect(spotifyWebUrl('spotify:album:4glBZ0bZMgkmFyi6TD4h69')).toBe('https://open.spotify.com/album/4glBZ0bZMgkmFyi6TD4h69');
    expect(spotifyWebUrl('spotify:user:lorne:collection')).toBe('https://open.spotify.com/collection/tracks');
  });
});
