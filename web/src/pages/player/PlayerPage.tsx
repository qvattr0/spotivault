import { useRef, useState } from 'react';
import { Lock } from 'lucide-react';
import { Banner, ConfirmDialog } from '@/components/ui-b';
import { VncView, type VncState } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { Page, useDocumentTitle } from '@/shell';
import { useStatus } from '@/state';
import { PlayerStatusStrip } from './PlayerStatusStrip.tsx';
import { PlayerToolbar } from './PlayerToolbar.tsx';
import { useFullscreen } from './use-fullscreen.ts';
import styles from './PlayerPage.module.css';

/**
 * /player (web-ui.md § Player; ZQChN, jh5YJ): the Spotify client's screen at full size, through
 * noVNC. A toolbar (scale, fullscreen, restart), a status strip (version, login, the VNC
 * connection), and the view. While a backup is recording the view is view-only, dimmed, with a
 * lock, under a banner with "Take control".
 */
export function PlayerPage() {
  useDocumentTitle('Player');
  const status = useStatus();
  const [scale, setScale] = useState<'fit' | 'actual'>('fit');
  const [vnc, setVnc] = useState<VncState>('connecting');
  const [retries, setRetries] = useState(0);
  const screen = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen(screen);

  // web-ui.md § During a run: view-only while a run is going (Status.view_only), until you take
  // control of that run. It lasts for that run only: when another run starts, the view locks again.
  const recording = status?.view_only === true;
  const runId = status?.run?.id ?? null;
  const [controlOf, setControlOf] = useState<number | null>(null);
  const [asking, setAsking] = useState(false);
  const tookControl = runId !== null && controlOf === runId;
  const viewOnly = recording && !tookControl;

  return (
    <Page flush>
      <div className={styles.player}>
        <PlayerToolbar
          scale={scale}
          onScale={setScale}
          fullscreen={fullscreen}
          recording={recording}
        />
        <PlayerStatusStrip vnc={vnc} onRetry={() => setRetries((n) => n + 1)} />
        {viewOnly ? (
          <Banner icon={Lock} action={{ label: 'Take control', onClick: () => setAsking(true) }}>
            A backup is recording. The view is read-only so a click doesn&apos;t spoil it.
          </Banner>
        ) : null}
        <div ref={screen} className={cx(styles.screen, viewOnly && styles.locked)}>
          <VncView viewOnly={viewOnly} scale={scale} onStateChange={setVnc} retryKey={retries} className={styles.vnc} />
          {viewOnly ? (
            <span className={styles.lock} title="View-only while a backup is recording">
              <Lock size={20} aria-hidden />
            </span>
          ) : null}
        </div>
      </div>
      {asking ? (
        <ConfirmDialog
          title="Take control anyway?"
          confirmLabel="Take control"
          tone="primary"
          onCancel={() => setAsking(false)}
          onConfirm={() => {
            // The run carries on; nothing is paused for you (web-ui.md § During a run).
            setControlOf(runId);
            setAsking(false);
          }}
        >
          Clicks in the client can pause or skip the track being recorded.
        </ConfirmDialog>
      ) : null}
    </Page>
  );
}
