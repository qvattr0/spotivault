// Settings › Spotify account (Web API) (web-ui.md § Spotify account (Web API)): the connection and
// its action, the Client ID (masked, with Change) and Disconnect. Reconnect and Change go to the
// wizard's /reconnect; Disconnect deletes the token, and the live connection event follows.

import { RefreshCw } from 'lucide-react';
import { api } from '@/api';
import { Button, ButtonLink } from '@/components/ui-a';
import { StatusButton } from '@/components/ui-c';
import { useSpotifyConnection } from '@/state';
import { useAction } from '@/lib/use-action.ts';
import { connectionView } from './connection-view.ts';
import { SettingRow, SettingsSection } from './SettingsSection.tsx';
import styles from './SpotifyAccountSection.module.css';

export function SpotifyAccountSection() {
  const connection = useSpotifyConnection();
  const disconnect = useAction(() => api.DELETE('/api/spotify/connection'));
  // Nothing to show until the live store has its first snapshot (the page waits for it anyway).
  if (!connection) return null;
  const view = connectionView(connection);
  return (
    <SettingsSection title="Spotify account (Web API)">
      <SettingRow
        title="Connection"
        description={view.summary}
        control={
          <StatusButton
            status={view.status}
            tone={view.tone}
            statusIcon={view.icon}
            actionLabel={view.hasToken ? 'Reconnect' : 'Connect'}
            actionIcon={RefreshCw}
            to="/reconnect"
          />
        }
      />
      <SettingRow
        title="Client ID"
        description="Changing it disconnects and reconnects."
        control={
          <>
            <span className={styles.masked}>{connection.client_id_masked ?? 'Not set'}</span>
            <ButtonLink variant="tertiary" to="/reconnect?change=client_id">
              Change
            </ButtonLink>
          </>
        }
      />
      {view.hasToken ? (
        <SettingRow
          title="Disconnect"
          description="Deletes the token. Scheduled runs are held until you reconnect."
          control={
            <Button variant="tertiary-danger" busy={disconnect.busy} onClick={() => void disconnect.run()}>
              Disconnect
            </Button>
          }
        />
      ) : null}
    </SettingsSection>
  );
}
