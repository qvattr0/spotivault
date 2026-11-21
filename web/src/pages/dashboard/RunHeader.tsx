import { Fragment } from 'react';
import { CircleCheck, CircleX, Redo2 } from 'lucide-react';
import type { RunSummary } from '@/api';
import { Pill, type PillTone } from '@/components/ui-a';
import { StopButton, formatCount, useDocumentTitle, useNow } from '@/shell';
import { useBacklog } from '@/state';
import { runMetaParts, runTitle } from './words.ts';
import styles from './Dashboard.module.css';

/** The pill next to the title, by the run's state. */
const STATE_PILL: Record<RunSummary['state'], { label: string; tone: PillTone }> = {
  idle: { label: 'Idle', tone: 'neutral' },
  starting: { label: 'Starting', tone: 'neutral' },
  running: { label: 'Running', tone: 'green' },
  // Between items (~25–30 s): still running.
  finishing: { label: 'Running', tone: 'green' },
  paused: { label: 'Paused', tone: 'yellow' },
  stopping: { label: 'Stopping', tone: 'neutral' },
};

/**
 * The run header (web-ui.md § Run header; t4YEY): "Backing up" or "Paused", the run's line, the
 * live counters, and Stop. Stop is the shell's split button: "Stop after this track" (then the
 * header's button says "Stopping after this track…" until the run ends), and "Stop now", which asks.
 */
export function RunHeader({ run }: { run: RunSummary }) {
  // The browser tab stays "Dashboard"; the page's own title says what the run is doing.
  useDocumentTitle('Dashboard');
  const backlog = useBacklog();
  // "0:42 elapsed" counts minutes.
  const now = useNow(10_000);
  const pill = STATE_PILL[run.state];
  const { counters } = run;

  return (
    <header className={styles.runHeader}>
      <div className={styles.runTitles}>
        <div className={styles.runTitleRow}>
          <h1 className={styles.runTitle}>{runTitle(run)}</h1>
          <Pill tone={pill.tone}>{pill.label}</Pill>
        </div>
        {/* The text reads "started 01:00 · 0:42 elapsed · …" as before; the dots get room around them. */}
        <p className={styles.runMeta}>
          {runMetaParts(run, now, backlog).map((part, i) => (
            <Fragment key={i}>
              {i > 0 ? (
                <>
                  {' '}
                  <span className={styles.metaDot}>·</span>{' '}
                </>
              ) : null}
              {part}
            </Fragment>
          ))}
        </p>
        <div className={styles.counters} role="group" aria-label="Counters">
          <span className={styles.counter}>
            <CircleCheck size={14} aria-hidden className={styles.accent} />
            Recorded {formatCount(counters.recorded)}
          </span>
          <span className={styles.counter}>
            <Redo2 size={14} aria-hidden />
            Skipped {formatCount(counters.skipped_duplicate + counters.skipped_other)}
          </span>
          <span className={styles.counter}>
            <CircleX size={14} aria-hidden className={styles.danger} />
            Failed {formatCount(counters.failed)}
          </span>
        </div>
      </div>
      <StopButton run={run} />
    </header>
  );
}
