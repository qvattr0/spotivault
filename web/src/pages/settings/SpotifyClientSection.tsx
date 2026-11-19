// Settings › Spotify client (web-ui.md § Spotify client): the client's version and login state, the
// settings checklist (the same rows as wizard step 4) with Re-check, and Open Player. Read-only:
// changing a setting is done in the Player, as the page says.

import { MonitorPlay, RefreshCw } from 'lucide-react';
import { api, useApi, type ClientStatus } from '@/api';
import { Button, ButtonLink, Pill } from '@/components/ui-a';
import { useClientStatus } from '@/state';
import { useAction } from '@/lib/use-action.ts';
import { SettingRow, SettingsSection } from './SettingsSection.tsx';
import { ChecklistGrid } from './ChecklistGrid.tsx';

export function SpotifyClientSection() {
  const client = useClientStatus();
  const checklist = useApi((signal) => api.GET('/api/client/checklist', { signal }), []);
  // Re-check answers with the whole checklist again, so it replaces the rows on screen.
  const recheck = useAction(() => api.GET('/api/client/checklist'), {
    onDone: (answer) => checklist.setData(() => answer),
  });

  return (
    <SettingsSection title="Spotify client">
      <SettingRow
        title="Client"
        description={clientLine(client)}
        control={
          <>
            {client?.installed ? (
              client.logged_in ? (
                <Pill tone="green">Logged in</Pill>
              ) : (
                <Pill tone="neutral">Not logged in</Pill>
              )
            ) : null}
            <ButtonLink variant="secondary" icon={MonitorPlay} to="/player">
              Open Player
            </ButtonLink>
          </>
        }
      />
      <SettingRow
        title="Settings checklist"
        description="Re-checked before every run. A drifted Auto row fails the run with a clear message."
        control={
          <Button variant="secondary" icon={RefreshCw} busy={recheck.busy} onClick={() => void recheck.run()}>
            Re-check
          </Button>
        }
      >
        {checklist.data ? <ChecklistGrid rows={checklist.data.rows} /> : null}
      </SettingRow>
    </SettingsSection>
  );
}

/** "1.3.4.258", or what the client's state is when there's no version to show. */
function clientLine(client: ClientStatus | null): string {
  if (!client) return 'Checking…';
  if (!client.installed) return 'Not installed yet';
  return client.version ?? 'Installed';
}
