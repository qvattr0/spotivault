// A run's page: the header (date, trigger, times, window, outcome, totals and the size added) and
// the items in the order they ran (web-ui.md § Run page). The run is read through
// GET /api/runs/{id}; it reloads when a run finishes, so a run still on screen gets its last numbers.
// A run still going (History lists it) shows Running, linking to the Dashboard, and no totals yet;
// it's read again as it changes: its queue is built after the pre-run check (run.queue, which may
// come with no item.state, when the run starts paused), its items move on (item.state), and its
// state changes (run.state; the ones sent once a second for counters alone are left out).

import { Link } from 'react-router';
import { ChevronLeft, CircleCheck, CircleX, CornerUpRight, HardDrive, RefreshCw } from 'lucide-react';
import { api, useApi, type HistoryRow } from '@/api';
import { Button } from '@/components/ui-a';
import { Alert, EmptyState } from '@/components/ui-b';
import { OutcomePill } from '@/components/ui-c';
import { errorText } from '@/lib/errors.ts';
import { failureText, noRunText, TRIGGER } from '@/lib/run-words.ts';
import { Page, useDocumentTitle, formatBytes, formatCount, formatDay, formatDayTime, formatRunLength, formatTime } from '@/shell';
import { useLiveEvent, useStatus, type EventType } from '@/state';
import { RunItemRow } from './RunItemRow.tsx';
import { isRunning, RunningPill } from './RunningPill.tsx';
import { useRetry } from './use-retry.ts';
import styles from './RunDetail.module.css';

/** The run going on: its queue and its items. A change of its state is handled below. */
const LIVE_RELOAD_ON: EventType[] = ['run.finished', 'run.queue', 'item.state'];
const ENDED_RELOAD_ON: EventType[] = ['run.finished'];

export function RunDetail({ runId }: { runId: number }) {
  // This run is the one going on: follow its items too.
  const current = useStatus()?.run?.id === runId;
  const detail = useApi((signal) => api.GET('/api/runs/{id}', { params: { path: { id: runId } }, signal }), [runId], {
    reloadOn: current ? LIVE_RELOAD_ON : ENDED_RELOAD_ON,
  });
  // run.state also comes once a second for the counters alone, which this page doesn't show while
  // the run goes on: only a change of state is read again.
  useLiveEvent('run.state', (event) => {
    if (current && event.data.state !== event.data.previous_state) detail.reload();
  });
  const retry = useRetry();
  const data = detail.data;
  useDocumentTitle(data ? titleOf(data.run) : undefined);

  if (detail.error?.code === 'not_found') return <RunMissing />;
  if (detail.error) {
    return (
      <Page tint="history">
        <BackLink />
        <Alert tone="danger" title={errorText(detail.error)} />
      </Page>
    );
  }
  if (!data) {
    return (
      <Page tint="history">
        <BackLink />
        <p className={styles.note}>Loading…</p>
      </Page>
    );
  }

  const { run, items } = data;
  const retryable = items.filter((item) => item.can_retry).map((item) => item.item_id);
  const running = isRunning(run);
  const counted = run.kind === 'run' && run.counters !== null && !running;

  return (
    <Page tint="history">
      <header className={styles.header}>
        <BackLink />
        <div className={styles.titleRow}>
          <h1 className={styles.title}>{titleOf(run)}</h1>
          {run.kind === 'run' && run.outcome ? <OutcomePill outcome={run.outcome} /> : null}
          {running ? <RunningPill /> : null}
          {run.kind === 'run' && run.reason ? <span className={styles.reason}>{failureText(run.reason)}</span> : null}
        </div>
        <p className={styles.summary}>{summaryOf(run)}</p>
        {run.kind !== 'run' ? <p className={styles.summary}>{noRunText(run)}</p> : null}
        {running ? (
          <p className={styles.summary}>
            This backup is still going. Its totals show here once it ends; the{' '}
            <Link to="/dashboard" className={styles.inlineLink}>
              Dashboard
            </Link>{' '}
            shows it live.
          </p>
        ) : null}
        <div className={styles.bar}>
          {counted && run.counters ? (
            <div className={styles.counts}>
              <span className={styles.count}>
                <CircleCheck size={16} aria-hidden className={run.counters.recorded > 0 ? styles.recorded : undefined} />
                {formatCount(run.counters.recorded)} recorded
              </span>
              <span className={styles.count}>
                <CornerUpRight size={16} aria-hidden />
                {formatCount(run.counters.skipped_duplicate)} skipped
              </span>
              <span className={styles.count}>
                <CircleX size={16} aria-hidden className={run.counters.failed > 0 ? styles.failed : undefined} />
                {formatCount(run.counters.failed)} failed
              </span>
              <span className={styles.count}>
                <HardDrive size={16} aria-hidden />+{formatBytes(run.counters.bytes_added)}
              </span>
            </div>
          ) : (
            <span />
          )}
          {retryable.length > 0 ? (
            <Button variant="secondary" icon={RefreshCw} busy={retry.busy} onClick={() => void retry.run(retryable)}>
              Retry all failed
            </Button>
          ) : null}
        </div>
      </header>

      {run.kind === 'run' && items.length === 0 ? (
        <p className={styles.note}>{running ? 'Building the queue…' : 'No items ran in this run.'}</p>
      ) : null}
      {items.length > 0 ? (
        <ol className={styles.items}>
          {items.map((item) => (
            <li key={item.item_id}>
              <RunItemRow runId={runId} item={item} live={current} />
            </li>
          ))}
        </ol>
      ) : null}
    </Page>
  );
}

/** A run number that isn't in History (or isn't a number at all). */
export function RunMissing() {
  useDocumentTitle('History');
  return (
    <Page tint="history">
      <BackLink />
      <EmptyState title="There's no run with that number." />
    </Page>
  );
}

function BackLink() {
  return (
    <Link to="/history/runs" className={styles.back}>
      <ChevronLeft size={18} aria-hidden />
      History · Runs
    </Link>
  );
}

/** "Tue 12 Nov · Scheduled" for a run; "Tue 12 Nov 01:00" for a row with no run. */
function titleOf(row: HistoryRow): string {
  return row.kind === 'run' ? `${formatDay(row.started_at)} · ${TRIGGER[row.trigger]}` : formatDayTime(row.started_at);
}

/** "01:00–06:12 · 5 h 12 m · window 01:00–07:00" (web-ui.md § Run page: the window, for scheduled runs). */
function summaryOf(row: HistoryRow): string {
  if (row.kind !== 'run') return '';
  const parts = [formatTime(row.started_at)];
  if (row.ended_at) parts[0] += `–${formatTime(row.ended_at)}`;
  if (row.duration_s !== null) parts.push(formatRunLength(row.duration_s));
  if (row.window && row.trigger !== 'run_now') parts.push(`window ${formatTime(row.window.start)}–${formatTime(row.window.end)}`);
  return parts.join(' · ');
}
