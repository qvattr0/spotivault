import { useState } from 'react';
import { Monitor } from 'lucide-react';
import { VncView, type VncState } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { useStatus } from '@/state';
import styles from './VncPanel.module.css';

const STATE_TEXT: Record<VncState, string> = {
  connecting: 'Connecting…',
  connected: 'Connected',
  reconnecting: 'Reconnecting…',
  disconnected: 'Disconnected',
};

interface VncPanelProps {
  /** The bar's title: "Spotify Client" (step 3), "Spotify client · Settings" (step 4). */
  title: string;
  className?: string;
}

/**
 * The client's screen, embedded in steps 3 and 4 (UzVcR, wNpTP): a bar with the title and the
 * connection state, over the noVNC view. View-only while a backup records, as on the Player
 * (web-ui.md § Player): a run can't start before setup, but one can be going after "Run setup again".
 */
export function VncPanel({ title, className }: VncPanelProps) {
  const [state, setState] = useState<VncState>('connecting');
  const viewOnly = useStatus()?.view_only ?? false;
  return (
    <section className={cx(styles.panel, className)} aria-label={title}>
      <div className={styles.bar}>
        <span className={styles.title}>
          <Monitor size={16} aria-hidden />
          {title}
        </span>
        <span className={styles.state}>
          <span className={cx(styles.dot, styles[state])} aria-hidden />
          {STATE_TEXT[state]}
        </span>
      </div>
      <VncView className={styles.view} viewOnly={viewOnly} onStateChange={setState} />
    </section>
  );
}
