import { useRef, useState } from 'react';
import { Maximize2, Minimize2, Monitor } from 'lucide-react';
import { IconButton } from '@/components/ui-a';
import { Tooltip } from '@/components/ui-b';
import { VncView, type VncState, type VncViewHandle } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { useStatus } from '@/state';
import { useExpand } from './use-expand.ts';
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
  /** For its slot on the page: the panel itself leaves it while expanded. */
  className?: string;
}

/**
 * The client's screen, embedded in steps 3 and 4 (UzVcR, wNpTP): a bar with the title, the
 * connection state and Expand, over the noVNC view. View-only while a backup records, as on the
 * Player (web-ui.md § Player): a run can't start before setup, but one can be going after "Run
 * setup again".
 *
 * Expand (web-ui.md § 3; not drawn) grows the panel itself into a modal dialog, as large as the
 * window allows up to 100 %, over a dimmed and blurred page (use-expand.ts). The same noVNC view
 * stays connected throughout.
 */
export function VncPanel({ title, className }: VncPanelProps) {
  const [state, setState] = useState<VncState>('connecting');
  const viewOnly = useStatus()?.view_only ?? false;
  const slot = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const view = useRef<VncViewHandle>(null);
  const expand = useExpand({
    slot,
    panel,
    button,
    backdropClass: styles.backdrop,
    keysToScreen: !viewOnly,
    onResize: () => view.current?.rescale(),
  });

  return (
    <div ref={slot} className={cx(styles.slot, className)}>
      <section
        ref={panel}
        className={styles.panel}
        aria-label={title}
        role={expand.open ? 'dialog' : undefined}
        aria-modal={expand.open || undefined}
        tabIndex={expand.open ? -1 : undefined}
        onKeyDownCapture={expand.onKeyDownCapture}
        onKeyDown={expand.onKeyDown}
      >
        <div className={styles.bar}>
          <span className={styles.title}>
            <Monitor size={16} aria-hidden />
            {title}
          </span>
          <span className={styles.end}>
            <span className={styles.state}>
              <span className={cx(styles.dot, styles[state])} aria-hidden />
              {STATE_TEXT[state]}
            </span>
            {/* A tooltip, as the Player's Fullscreen has: maximize-2 alone doesn't say what it does. */}
            <Tooltip label={expand.open ? 'Collapse' : 'Expand'} align="end">
              <IconButton
                ref={button}
                icon={expand.open ? Minimize2 : Maximize2}
                label={expand.open ? 'Collapse' : 'Expand'}
                className={styles.expand}
                onClick={expand.toggle}
              />
            </Tooltip>
          </span>
        </div>
        <VncView ref={view} className={styles.view} viewOnly={viewOnly} onStateChange={setState} />
      </section>
    </div>
  );
}
