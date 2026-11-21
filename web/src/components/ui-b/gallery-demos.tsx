import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui-a';
import { createLiveStore, LiveStoreProvider } from '@/state';
import { envelope } from '@/test/live.ts';
import { Card, type CardProps } from './Card.tsx';
import { ConfirmDialog } from './ConfirmDialog.tsx';
import { ItemRow } from './ItemRow.tsx';
import { LiveLevelMeter } from './LiveLevelMeter.tsx';
import { Modal } from './Modal.tsx';
import { ToastProvider } from './ToastProvider.tsx';
import { ToastViewport } from './ToastViewport.tsx';
import { TrackCheck } from './TrackCheck.tsx';
import { useToast } from './use-toast.ts';
import { Row } from './gallery-kit.tsx';
import styles from './gallery.module.css';

// The gallery's clickable demos: each keeps its own state. Gallery only.

/** The live meter, fed 10 readings a second by a local store; Stop shows it falling to silence. */
export function LiveLevelDemo() {
  const [store] = useState(() => createLiveStore());
  const [running, setRunning] = useState(true);

  useEffect(() => {
    if (!running) return;
    let peak = -12;
    const timer = setInterval(() => {
      // A random walk between -30 and -1 dBFS, like music.
      peak = Math.min(-1, Math.max(-30, peak + (Math.random() - 0.5) * 8));
      store.dispatch(envelope('level', { peak_dbfs: peak, rms_dbfs: peak - 12, channels: [] }));
    }, 100);
    return () => clearInterval(timer);
  }, [store, running]);

  return (
    <LiveStoreProvider store={store}>
      <Row>
        <LiveLevelMeter />
        <Button variant="secondary" onClick={() => setRunning(!running)}>
          {running ? 'Stop the readings' : 'Start the readings'}
        </Button>
      </Row>
    </LiveStoreProvider>
  );
}

function ShowToast() {
  const toast = useToast();
  return (
    <Button variant="secondary" onClick={() => toast.show('Added to the current run')}>
      Show a toast
    </Button>
  );
}

/** A toast in a stand-in content area: it rises at the bottom centre and goes after 5 s. */
export function ToastDemo() {
  return (
    <ToastProvider>
      <div className={styles.toastStage}>
        <ShowToast />
        <ToastViewport />
      </div>
    </ToastProvider>
  );
}

/** Opens a real modal: focus moves in, Tab stays inside, Escape closes. */
export function ModalDemo() {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Open the modal
      </Button>
      <Modal
        open={open}
        title="Add playlists"
        onClose={close}
        footer={
          <>
            <Button variant="tertiary" onClick={close}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={close}>
              Done
            </Button>
          </>
        }
      >
        <p>Playlists you follow that aren't in the Library yet.</p>
        <ItemRow
          title="Best New Tracks"
          sub="Pitchfork · 50 tracks"
          trailing={
            <Button variant="secondary" icon={Plus}>
              Add
            </Button>
          }
        />
      </Modal>
    </>
  );
}

/** The Stop now confirm (web-ui.md § Running), not drawn. */
export function ConfirmDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="danger" onClick={() => setOpen(true)}>
        Stop now
      </Button>
      {open ? (
        <ConfirmDialog title="Stop now?" confirmLabel="Stop now" onConfirm={() => setOpen(false)} onCancel={() => setOpen(false)}>
          The current track will be discarded and recorded next time.
        </ConfirmDialog>
      ) : null}
    </>
  );
}

/** A row's tracking check that can be clicked. */
export function TrackedCheck({ name, initial = true }: { name: string; initial?: boolean }) {
  const [on, setOn] = useState(initial);
  return <TrackCheck inline tracked={on} onChange={setOn} label={`Track ${name}`} align="start" />;
}

/** A card whose badge can be clicked. */
export function TrackingCard({ initial, progress, ...props }: Omit<CardProps, 'tracking'> & { initial: boolean; progress?: number }) {
  const [tracked, setTracked] = useState(initial);
  return <Card {...props} tracking={{ tracked, onChange: setTracked, progress }} />;
}
