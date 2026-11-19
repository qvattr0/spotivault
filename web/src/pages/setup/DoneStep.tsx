// Wizard step 9, "Done" (web-ui.md § 9; BAzX6): a summary, then two buttons that both finish setup
// (POST /api/setup/complete, refused with 409 setup_incomplete while a step from 1 to 6 isn't done):
// - Open Library (primary).
// - Back up now (secondary): starts a first run of everything tracked (POST /api/runs, Run now) and
//   opens the Dashboard.
//
// Not yet (plan D8, waiting for the user's review): the backup-length line ("About 298 h of music to
// record", "Measuring…"). It's left out until then.

import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { ArrowDownToLine, Check, CircleAlert } from 'lucide-react';
import { api, callApi, useApi, type ApiError, type SetupStepId } from '@/api';
import { Button } from '@/components/ui-a';
import { Alert, useToast } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { runCreatedText } from '@/lib/run-words.ts';
import { setupPath } from '@/shell';
import { useSetup, useSpotifyConnection } from '@/state';
import { accountLine, folderLine, formatLine, scheduleLine, trackingLine } from './done-summary.ts';
import { stepLabel } from './parts/step-nav.ts';
import { StepTitle } from './parts/StepTitle.tsx';
import styles from './DoneStep.module.css';

/** The words for Back up now's run, when it can't start (POST /api/runs's 409s). */
const RUN_ERRORS = {
  run_active: 'A backup is already running.',
  client_logged_out: 'The backup couldn’t start: the Spotify client is logged out. Log in again in the Player.',
  connection_expired: 'The backup couldn’t start: the Spotify connection has expired. Reconnect in Settings.',
  not_connected: 'The backup couldn’t start: spotivault isn’t connected to Spotify.',
  client_not_installed: 'The backup couldn’t start: the Spotify client isn’t installed.',
} as const;

export function DoneStep() {
  const navigate = useNavigate();
  const toast = useToast();
  const connection = useSpotifyConnection();
  const settings = useApi((signal) => api.GET('/api/settings', { signal }), []);
  const container = useApi((signal) => api.GET('/api/container', { signal }), []);
  const summary = useApi((signal) => api.GET('/api/library/summary', { signal }), []);
  const albums = useApi((signal) => api.GET('/api/albums', { signal }), []);
  const schedule = useApi((signal) => api.GET('/api/schedule', { signal }), []);
  const [busy, setBusy] = useState<'library' | 'backup' | null>(null);
  const [missing, setMissing] = useState<SetupStepId[] | null>(null);
  // Where to go once setup is complete. The setup gate reads the live store, and the answer to
  // POST /api/setup/complete can come before its setup.state event: leaving earlier would send
  // the gate back here. So the page goes once the store says `completed`.
  const [leaveTo, setLeaveTo] = useState<string | null>(null);
  const completed = useSetup()?.completed ?? false;
  useEffect(() => {
    if (leaveTo && completed) navigate(leaveTo);
  }, [leaveTo, completed, navigate]);

  function failed(error: ApiError) {
    setBusy(null);
    if (error.code === 'setup_incomplete') {
      const steps = error.details?.steps;
      setMissing(Array.isArray(steps) ? (steps as SetupStepId[]) : []);
    } else {
      toast.show(errorText(error), { icon: CircleAlert });
    }
  }

  async function finish(then: 'library' | 'backup') {
    if (busy) return;
    setBusy(then);
    setMissing(null);
    const completed = await callApi(api.POST('/api/setup/complete'));
    if (completed.error) return failed(completed.error);
    if (then === 'library') {
      setLeaveTo('/library');
      return;
    }
    // Run now: everything due, which right after setup is everything tracked.
    const run = await callApi(api.POST('/api/runs', { body: {} }));
    if (run.error) toast.show(errorText(run.error, RUN_ERRORS), { icon: CircleAlert });
    else toast.show(runCreatedText(run.data));
    setLeaveTo('/dashboard');
  }

  const rows: [string, string | null][] = [
    ['Account', accountLine(connection)],
    ['Format', settings.data ? formatLine(settings.data) : null],
    ['Folder', container.data ? folderLine(container.data.music_source) : null],
    ['Tracking', summary.data ? trackingLine(summary.data, albums.data?.summary.total ?? null) : null],
    ['Schedule', schedule.data ? scheduleLine(schedule.data) : null],
  ];

  return (
    <>
      <div className={styles.top}>
        <span className={styles.badge} aria-hidden>
          <Check size={48} strokeWidth={2.5} />
        </span>
        <StepTitle hero title="You're all set" />
      </div>
      <dl className={styles.summary}>
        {rows.map(([label, value]) => (
          <div key={label} className={styles.row}>
            <dt>{label}</dt>
            <dd>{value ?? '…'}</dd>
          </div>
        ))}
      </dl>
      {missing ? (
        <Alert tone="danger" title="Finish setup first">
          {missing.length > 0 ? (
            <>
              These steps aren&apos;t done yet:{' '}
              {missing.map((id, i) => (
                <span key={id}>
                  {i > 0 ? ', ' : null}
                  <Link className={styles.link} to={setupPath(id)}>
                    {stepLabel(id)}
                  </Link>
                </span>
              ))}
              .
            </>
          ) : (
            'A step before this one isn’t done yet.'
          )}
        </Alert>
      ) : null}
      <div className={styles.actions}>
        <Button variant="secondary" icon={ArrowDownToLine} busy={busy === 'backup'} onClick={() => void finish('backup')}>
          Back up now
        </Button>
        <Button variant="primary" busy={busy === 'library'} onClick={() => void finish('library')}>
          Open Library
        </Button>
      </div>
    </>
  );
}
