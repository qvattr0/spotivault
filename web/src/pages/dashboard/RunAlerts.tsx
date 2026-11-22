import { Play, Smartphone, Square } from 'lucide-react';
import { api, type RunSummary } from '@/api';
import { Button } from '@/components/ui-a';
import { Alert } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { useAlerts, type Alert as LiveAlert, type ErrorEvent } from '@/state';
import styles from './Dashboard.module.css';

/**
 * The warnings between the strip and the queue (web-ui.md § Warnings during a run; hJlHj).
 * - Playback moved: a yellow alert with Resume and Stop, while the run is paused.
 * - `error` events: a red alert with the message; the Web API one is a warning (yellow).
 * A failed track gets no alert: it shows in the track table and the counters.
 */
export function RunAlerts({ run }: { run: RunSummary }) {
  const alerts = useAlerts();
  const moved = alerts.find((a): a is Extract<LiveAlert, { kind: 'device_moved' }> => a.kind === 'device_moved');
  const errors = alerts.filter((a): a is Extract<LiveAlert, { kind: 'error' }> => a.kind === 'error');
  const paused = run.state === 'paused';

  if (!paused && errors.length === 0) return null;
  return (
    <div className={styles.alerts}>
      {paused ? <PausedAlert run={run} device={moved?.event.device.name ?? null} /> : null}
      {errors.map((alert) => (
        <ErrorAlert key={`${alert.event.source}:${alert.event.code}`} event={alert.event} />
      ))}
    </div>
  );
}

/**
 * Playback moved to another device, so the run paused (web-ui.md § Warnings): "Playback moved to
 * <device>. The backup is paused so it won't interrupt you." with Resume and Stop.
 * The device's name comes with the `device.moved` event; a page opened after it (the store can't
 * read alerts back through REST) says "another device". `device_busy` (another device was already
 * playing when the run started, D6) isn't worded in web-ui.md: ours says so the same way.
 */
function PausedAlert({ run, device }: { run: RunSummary; device: string | null }) {
  const resume = useAction(() => api.POST('/api/runs/current/resume'));
  // Nothing is playing while paused, so stopping "after this track" loses nothing and needs no confirm.
  const stop = useAction(() => api.POST('/api/runs/current/stop', { body: { mode: 'after_track' } }));
  const name = device ?? 'another device';
  const title = run.paused_reason === 'device_busy' ? `Spotify is playing on ${name}.` : `Playback moved to ${name}.`;

  return (
    <div className={styles.pausedAlert}>
      <Alert tone="warn" icon={Smartphone} title={title}>
        The backup is paused so it won&apos;t interrupt you.
      </Alert>
      <div className={styles.alertActions}>
        <Button variant="primary" size="sm" icon={Play} busy={resume.busy} onClick={() => void resume.run()}>
          Resume
        </Button>
        <Button variant="secondary" icon={Square} busy={stop.busy} onClick={() => void stop.run()}>
          Stop
        </Button>
      </div>
    </div>
  );
}

/**
 * An `error` event (contracts/events.md § Warnings): red, with the message. web-ui.md § Warnings
 * calls the Web API's failed jump a warning, so `controller`/`webapi` is yellow. When the item can't
 * go on (`fatal`), the line under it says what happens next (ours).
 */
function ErrorAlert({ event }: { event: ErrorEvent }) {
  const warning = event.source === 'controller' && event.code === 'webapi';
  return (
    <Alert tone={warning ? 'warn' : 'danger'} title={event.message}>
      {event.fatal ? 'This item ends Partial, and the backup goes on with the next one.' : null}
    </Alert>
  );
}
