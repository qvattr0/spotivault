import { useState } from 'react';
import { Maximize, Minimize, RotateCcw } from 'lucide-react';
import { api } from '@/api';
import { IconButton, SegmentedControl } from '@/components/ui-a';
import { ConfirmDialog, Tooltip, useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import type { Fullscreen } from './use-fullscreen.ts';
import styles from './PlayerPage.module.css';

const SCALES = [
  { value: 'fit' as const, label: 'Fit' },
  { value: 'actual' as const, label: '100%' },
];

/** web-ui.md § Toolbar: Restart is disabled during a run, with this tooltip. */
const NOT_DURING_RUN = 'Not available while a backup is recording';

interface PlayerToolbarProps {
  scale: 'fit' | 'actual';
  onScale(scale: 'fit' | 'actual'): void;
  fullscreen: Fullscreen;
  /** A backup is recording: Restart is disabled. */
  recording: boolean;
}

/**
 * The Player's toolbar (web-ui.md § Toolbar; ZQChN): the title, then Fit / 100%, Fullscreen and
 * Restart client, icon buttons with tooltips. Restart asks first; it's also how you get a fresh
 * login QR code.
 */
export function PlayerToolbar({ scale, onScale, fullscreen, recording }: PlayerToolbarProps) {
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const restart = useAction(() => api.POST('/api/client/restart'), {
    // Ours: web-ui.md gives no words for it. The screen comes back by itself.
    onDone: () => toast.show('Restarting the Spotify client'),
  });

  return (
    <header className={styles.toolbar}>
      <h1 className={styles.title}>Player</h1>
      <div className={styles.tools}>
        <SegmentedControl label="Scale" options={SCALES} value={scale} onChange={onScale} />
        <Tooltip label={fullscreen.active ? 'Exit fullscreen' : 'Fullscreen'}>
          <IconButton icon={fullscreen.active ? Minimize : Maximize} label="Fullscreen" aria-pressed={fullscreen.active} onClick={fullscreen.toggle} />
        </Tooltip>
        <Tooltip label={recording ? NOT_DURING_RUN : 'Restart client'} align="end">
          <IconButton
            icon={RotateCcw}
            label="Restart client"
            aria-disabled={recording || restart.busy}
            onClick={() => setAsking(true)}
          />
        </Tooltip>
      </div>
      {asking ? (
        <ConfirmDialog
          title="Restart the Spotify client?"
          confirmLabel="Restart"
          tone="primary"
          onCancel={() => setAsking(false)}
          onConfirm={() => {
            setAsking(false);
            void restart.run();
          }}
        >
          It comes back logged in.
        </ConfirmDialog>
      ) : null}
    </header>
  );
}
