import { Link } from 'react-router';
import { LoaderCircle, Package, PlugZap, Unplug, UserCheck, UserX } from 'lucide-react';
import type { VncState } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { useClientStatus } from '@/state';
import styles from './PlayerPage.module.css';

/** The VNC connection in words (web-ui.md § Status strip: Connected, Reconnecting… or Disconnected). */
const VNC_WORDS: Record<VncState, string> = {
  connecting: 'VNC connecting…',
  connected: 'VNC connected',
  reconnecting: 'VNC reconnecting…',
  disconnected: 'VNC disconnected',
};

interface PlayerStatusStripProps {
  vnc: VncState;
  /** Connect again at once, after the view gave up (Disconnected). */
  onRetry(): void;
}

/**
 * The line under the toolbar (web-ui.md § Status strip; ZQChN): the client version, "Logged in"
 * or "Not logged in" (a link to wizard step 3), and the VNC connection, with Retry once it gave up.
 */
export function PlayerStatusStrip({ vnc, onRetry }: PlayerStatusStripProps) {
  const client = useClientStatus();

  return (
    <div className={styles.strip} aria-label="Client status" role="group">
      {client ? (
        <span className={styles.fact}>
          <Package size={14} aria-hidden />
          {client.installed && client.version ? `Spotify ${client.version}` : 'Spotify client not installed'}
        </span>
      ) : null}

      {client?.installed ? (
        client.logged_in ? (
          <span className={cx(styles.fact, styles.ok)}>
            <UserCheck size={14} aria-hidden />
            <span className={styles.factText}>Logged in</span>
          </span>
        ) : (
          // The gate leaves /setup/<step> open after setup, so step 3 can be opened from here.
          <Link to="/setup/login" className={cx(styles.fact, styles.warnFact, styles.factLink)}>
            <UserX size={14} aria-hidden />
            Not logged in
          </Link>
        )
      ) : null}

      <span className={cx(styles.fact, vnc === 'connected' && styles.ok, vnc === 'disconnected' && styles.dangerFact)} data-testid="vnc-state">
        {vnc === 'connected' ? (
          <PlugZap size={14} aria-hidden />
        ) : vnc === 'disconnected' ? (
          <Unplug size={14} aria-hidden />
        ) : (
          <LoaderCircle size={14} aria-hidden className={styles.spin} />
        )}
        <span className={styles.factText}>{VNC_WORDS[vnc]}</span>
        {vnc === 'disconnected' ? (
          <button type="button" className={styles.retry} onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </span>
    </div>
  );
}
