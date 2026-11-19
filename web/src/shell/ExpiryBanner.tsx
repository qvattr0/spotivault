import type { Connection } from '@/api';
import { Banner } from '@/components/ui-b';
import { useSpotifyConnection } from '@/state';
import { formatDate } from './format.ts';
import { useNow } from './use-now.ts';

/**
 * The expiry banner across the top of every app page (web-ui.md § Navigation; components.md §
 * Expiry banner). Yellow from 4 weeks before the Web API connection expires, red once it has.
 * Reconnect opens wizard step 5 on its own (/reconnect).
 */
export function ExpiryBanner() {
  const connection = useSpotifyConnection();
  const now = useNow(60 * 60_000);
  const text = expiryText(connection, now);
  if (!text) return null;

  return (
    <Banner tone={connection?.state === 'expired' ? 'danger' : 'warn'} action={{ label: 'Reconnect', to: '/reconnect' }}>
      {text}
    </Banner>
  );
}

/** The banner's words, as on the component sheet, or null when there's no banner. */
export function expiryText(connection: Connection | null, now: number): string | null {
  if (connection?.state === 'expiring') {
    const date = connection.expires_at ? ` on ${formatDate(connection.expires_at)}` : ' soon';
    return `Spotify connection expires${date}. Reconnect to keep backups running.`;
  }
  if (connection?.state === 'expired') {
    // Spotify can also refuse the token early (invalid_grant): then the date hasn't come yet.
    const passed = connection.expires_at && Date.parse(connection.expires_at) <= now;
    const date = passed ? ` on ${formatDate(connection.expires_at!)}` : '';
    return `Spotify connection expired${date}. Scheduled runs are held until you reconnect.`;
  }
  return null;
}
