import { useCallback, useState } from 'react';
import { api, errorCode, type RunSummary } from '@/api';
import { SplitButton } from '@/components/ui-a';
import { ConfirmDialog } from '@/components/ui-b';

type StopMode = 'after_track' | 'now';

interface StopButtonProps {
  run: RunSummary | null;
  /** Open the menu above the button: in the global bottom bar, at the foot of the screen. */
  menuAbove?: boolean;
}

/**
 * Stop, as a split button (web-ui.md § Running): "Stop after this track" loses nothing; "Stop now",
 * from the arrow, asks first. The live store shows the result; the run ends as Stopped.
 * openapi.yaml: "Sending `now` after `after_track` upgrades the stop". So once "after this track"
 * is asked for (by you, or by the end of a window), Stop now is still there. After Stop now, nothing is.
 */
export function StopButton({ run, menuAbove = false }: StopButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const cancel = useCallback(() => setConfirming(false), []);

  async function stop(mode: StopMode) {
    setConfirming(false);
    setSending(true);
    try {
      const { error } = await api.POST('/api/runs/current/stop', { body: { mode } });
      // `no_run`: it ended meanwhile. The live state catches up on its own either way.
      if (error) console.warn('stop:', errorCode(error));
    } catch (e) {
      console.warn('stop:', e);
    } finally {
      setSending(false);
    }
  }

  const requested = run?.stop_mode ?? null;

  return (
    <>
      <SplitButton
        menuPlacement={menuAbove ? 'above' : 'below'}
        label={requested === 'after_track' ? 'Stopping after this track…' : 'Stop after this track'}
        onClick={() => stop('after_track')}
        disabled={sending || requested === 'now'}
        mainDisabled={requested !== null}
        menuLabel="More ways to stop"
        items={[{ label: 'Stop now', danger: true, onSelect: () => setConfirming(true) }]}
      />
      {confirming && (
        <ConfirmDialog title="Stop now?" confirmLabel="Stop now" onConfirm={() => stop('now')} onCancel={cancel}>
          The current track will be discarded and recorded next time.
        </ConfirmDialog>
      )}
    </>
  );
}
