// Step 5's checks (web-ui.md § 5, 4. Checks; j8m6AR): both must pass for the step to turn green.
// - The token works: "Connected as <name> · expires <date>".
// - The container's client is a playback device (GET /api/spotify/devices). If not: "Make sure the
//   client in step 3 is open and logged in", with Retry.

import { RotateCw } from 'lucide-react';
import { api, useApi, type Connection } from '@/api';
import { Button } from '@/components/ui-a';
import { errorText } from '@/lib/errors.ts';
import { useAction } from '@/lib/use-action.ts';
import { formatDate } from '@/shell';
import { CheckResult } from '../parts/CheckResult.tsx';
import parts from '../parts/Step.module.css';
import styles from './WebApi.module.css';

interface ChecksProps {
  connection: Connection | null;
  /** The Reconnect flow names the Player, not "step 3". */
  mode: 'wizard' | 'reconnect';
}

export function isConnected(connection: Connection | null): boolean {
  return connection?.state === 'ok' || connection?.state === 'expiring';
}

export function Checks({ connection, mode }: ChecksProps) {
  if (connection?.state === 'expired') {
    return (
      <CheckResult tone="fail" title={`The connection expired on ${connection.expires_at ? formatDate(connection.expires_at) : 'its date'}`}>
        Open Spotify&apos;s consent page again to reconnect. Reconnecting resets the 6-month clock.
      </CheckResult>
    );
  }
  if (!connection || !isConnected(connection)) {
    return <p className={parts.muted}>Both checks run once you&apos;ve connected.</p>;
  }
  return (
    <div className={styles.checks}>
      <CheckResult
        tone="ok"
        title={`Connected as ${connection.display_name ?? 'your account'}${connection.expires_at ? ` · expires ${formatDate(connection.expires_at)}` : ''}`}
      >
        Refresh tokens expire 6 months after you authorize. You&apos;ll see a banner 4 weeks before.
      </CheckResult>
      {/* Read again after each new authorization. */}
      <DeviceCheck key={connection.authorized_at ?? ''} mode={mode} />
    </div>
  );
}

function DeviceCheck({ mode }: { mode: ChecksProps['mode'] }) {
  // The client logging in or out changes the device list: read it again on `client.status`.
  const devices = useApi((signal) => api.GET('/api/spotify/devices', { signal }), [], { reloadOn: ['client.status'] });
  // A failed Retry says why in a toast, and the box keeps its last answer.
  const retry = useAction(() => api.GET('/api/spotify/devices'), {
    onDone: (data) => devices.setData(() => data),
  });
  const retryButton = (
    <Button variant="secondary" icon={RotateCw} busy={retry.busy} onClick={() => void retry.run()}>
      Retry
    </Button>
  );
  // web-ui.md § 5 gives the wizard's words; the Reconnect flow has no step 3 to point at.
  const advice =
    mode === 'wizard' ? 'Make sure the client in step 3 is open and logged in.' : 'Make sure the Spotify client is open and logged in. The Player shows its screen.';

  if (devices.error && !devices.data) {
    return (
      <CheckResult
        tone="fail"
        title="The playback devices couldn't be read"
        action={
          <Button variant="secondary" icon={RotateCw} onClick={devices.reload}>
            Retry
          </Button>
        }
      >
        {errorText(devices.error)}
      </CheckResult>
    );
  }
  if (!devices.data) return <CheckResult tone="pending" title="Looking for the container's client…" />;
  const ours = devices.data.ours;
  if (!ours) {
    return (
      <CheckResult tone="fail" title="The container's client isn't listed as a playback device" action={retryButton}>
        {advice}
      </CheckResult>
    );
  }
  return (
    <CheckResult tone="ok" title="The container's client is listed as a playback device">
      It&apos;s &ldquo;{ours.name}&rdquo; in Spotify&apos;s list of devices.
    </CheckResult>
  );
}
