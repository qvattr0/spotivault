import { describe, expect, it } from 'vitest';
import { connectionExpired, connectionExpiring, connectionOk } from '@mock/fixtures.ts';
import { expiryText } from './ExpiryBanner.tsx';

describe('expiryText', () => {
  const now = Date.now();

  it('warns 4 weeks ahead, with the date', () => {
    expect(expiryText(connectionExpiring, now)).toMatch(
      /^Spotify connection expires on \d{1,2} \w+ \d{4}\. Reconnect to keep backups running\.$/,
    );
  });

  it('says when it expired, and that runs are held', () => {
    expect(expiryText(connectionExpired, now)).toMatch(/^Spotify connection expired on .+\. Scheduled runs are held until you reconnect\.$/);
  });

  it('leaves the date out when Spotify refused the token early', () => {
    const refused = { ...connectionExpired, expires_at: new Date(now + 86_400_000).toISOString() };
    expect(expiryText(refused, now)).toBe('Spotify connection expired. Scheduled runs are held until you reconnect.');
  });

  it('shows no banner otherwise', () => {
    expect(expiryText(connectionOk, now)).toBeNull();
    expect(expiryText(null, now)).toBeNull();
  });
});
