// Settings › Spotify account (web-ui.md § Spotify account (Web API)): the connection's status pill,
// its summary line and whether there is a token to disconnect. Pure: the words are here, the
// component draws them.

import { CircleCheck, CircleX, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { Connection } from '@/api';
import { formatDate } from '@/shell';

export interface ConnectionView {
  /** The status pill: "OK", "Expiring", "Expired", "Not connected" or "Not set up". */
  status: string;
  /** Its colour, as a status pill's. */
  tone: 'green' | 'yellow' | 'red' | 'neutral';
  icon: LucideIcon | undefined;
  /** The line under "Connection". */
  summary: string;
  /** A token exists, so Disconnect has something to delete. */
  hasToken: boolean;
}

const WITH_TOKEN: Record<'ok' | 'expiring' | 'expired', Pick<ConnectionView, 'status' | 'tone' | 'icon'>> = {
  ok: { status: 'OK', tone: 'green', icon: CircleCheck },
  expiring: { status: 'Expiring', tone: 'yellow', icon: TriangleAlert },
  expired: { status: 'Expired', tone: 'red', icon: CircleX },
};

export function connectionView(connection: Connection): ConnectionView {
  if (connection.state === 'ok' || connection.state === 'expiring' || connection.state === 'expired') {
    // Same template in every state: the pill says which one it is (web-ui.md: "Connected as Lorne · authorized … · expires …").
    const parts = [connection.display_name ? `Connected as ${connection.display_name}` : 'Connected'];
    if (connection.authorized_at) parts.push(`authorized ${formatDate(connection.authorized_at)}`);
    if (connection.expires_at) parts.push(`expires ${formatDate(connection.expires_at)}`);
    return { ...WITH_TOKEN[connection.state], summary: parts.join(' · '), hasToken: true };
  }
  if (connection.state === 'disconnected') {
    return { status: 'Not connected', tone: 'neutral', icon: undefined, summary: 'Not connected to Spotify.', hasToken: false };
  }
  return { status: 'Not set up', tone: 'neutral', icon: undefined, summary: 'No Client ID yet.', hasToken: false };
}
