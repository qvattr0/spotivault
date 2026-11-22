// The wizard's words: install phases and errors (step 2), the checklist hint (step 4) and step 9's
// summary lines.

import { describe, expect, it } from 'vitest';
import { checklistM1, clientLoggedIn, clientNotInstalled, connectionExpired, connectionNotConfigured, connectionOk, installFailed, installNotStarted, settingsDefault } from '@mock/fixtures.ts';
import type { ClientInstall } from '@/api';
import { formatDate } from '@/shell';
import { checklistHint } from './checklist-hint.ts';
import { accountLine, folderLine, formatLine, scheduleLine, trackingLine } from './done-summary.ts';
import { installErrorWords, installView, percentText, phaseText } from './install-words.ts';

const installing: ClientInstall = { ...installNotStarted, state: 'installing', phase: 'unpack', progress: 0.62, version: '1.3.4.258' };

describe('step 2: the install', () => {
  it('picks the screen: an install going on, then installed, then failed', () => {
    expect(installView(clientNotInstalled, installing)).toBe('installing');
    expect(installView(clientLoggedIn, clientLoggedIn.install)).toBe('installed');
    expect(installView(clientNotInstalled, installFailed)).toBe('failed');
    expect(installView(clientNotInstalled, installNotStarted)).toBe('not_started');
    expect(installView(null, null)).toBe('not_started');
    const installedRecord: ClientInstall = { ...installing, state: 'installed', progress: 1 };
    // The install has just ended well, and the client's status hasn't caught up yet: no Install screen.
    expect(installView(clientNotInstalled, installedRecord, true)).toBe('installed');
    // The last install ended well, but the client isn't there now: Install again, not a dead end.
    expect(installView(clientNotInstalled, installedRecord)).toBe('missing');
    expect(installView(clientLoggedIn, installedRecord)).toBe('installed');
  });

  it('says what it is doing, as h2Qgw does', () => {
    expect(phaseText(installing)).toBe('Unpacking spotify-client 1.3.4…');
    expect(phaseText({ phase: null, version: null })).toBe('Starting the install…');
    expect(percentText(0.62)).toBe('62%');
    expect(percentText(null)).toBeNull();
  });

  it('words a failure by its code', () => {
    expect(installErrorWords(installFailed).text).toBe('Check the NAS has internet access, then retry.');
    expect(installErrorWords({ ...installFailed, error: { code: 'missing_libraries', message: '' } }).title).toBe(
      'This image is too old for this client',
    );
  });
});

describe('step 4: why Continue waits', () => {
  it('names the first row that blocks it', () => {
    expect(checklistHint(checklistM1)).toBe('Volume normalization needs to be off');
    const gapless = { ...checklistM1, rows: checklistM1.rows.map((r) => (r.id === 'gapless' ? { ...r, confirmed: false } : r)) };
    expect(checklistHint(gapless)).toBe("Tick Gapless playback once it's off");
  });

  it('says nothing once every blocker is satisfied (Autoplay may stay unticked)', () => {
    const ready = {
      ...checklistM1,
      rows: checklistM1.rows.map((r) => (r.check === 'auto' ? { ...r, state: 'ok' as const } : r)),
    };
    expect(checklistHint(ready)).toBeNull();
  });
});

describe('step 9: the summary', () => {
  it('writes each line as web-ui.md § 9 does', () => {
    expect(accountLine(connectionOk)).toBe(`Lorne · expires ${formatDate(connectionOk.expires_at!)}`);
    expect(accountLine(connectionExpired)).toMatch(/^Lorne · expired /);
    expect(accountLine(connectionNotConfigured)).toBe('Not connected');
    expect(formatLine(settingsDefault)).toBe('AAC 256 · .m4a');
    expect(folderLine('/Music')).toBe('/music → /Music');
    expect(folderLine(null)).toBe('/music');
    expect(trackingLine({ tracked_count: 24, liked_tracked: true }, 42)).toBe('23 playlists + Liked Songs · 42 albums');
    expect(trackingLine({ tracked_count: 0, liked_tracked: false }, 0)).toBe('0 playlists · 0 albums');
    expect(trackingLine({ tracked_count: 1, liked_tracked: true }, null)).toBe('Liked Songs');
    expect(trackingLine({ tracked_count: 2, liked_tracked: false }, 1)).toBe('2 playlists · 1 album');
  });

  it('has no Schedule page to point at in M1', () => {
    expect(scheduleLine({ hours_per_week: 0, windows_per_week: 0 })).toBe('None yet');
    expect(scheduleLine({ hours_per_week: 42, windows_per_week: 7 })).toBe('7 windows a week, 42 h');
  });
});
