// One row of the Runs table: a run, with its counts, or a row for a run that didn't happen
// (missed, skipped, held: greyed, one line, no counts). web-ui.md § Runs tab.

import { Link } from 'react-router';
import { CircleSlash } from 'lucide-react';
import type { Counters, HistoryRow } from '@/api';
import { OutcomePill } from '@/components/ui-c';
import { cx } from '@/lib/cx.ts';
import { noRunText, TRIGGER } from '@/lib/run-words.ts';
import { formatBytes, formatCount, formatDay, formatDayTime, formatRunLength } from '@/shell';
import { isRunning, RunningPill } from './RunningPill.tsx';
import styles from './RunList.module.css';

const NO_COUNTS: Counters = { recorded: 0, skipped_duplicate: 0, skipped_other: 0, failed: 0, bytes_added: 0 };

export function RunRow({ row }: { row: HistoryRow }) {
  if (row.kind !== 'run') return <NoRunRow row={row} />;
  if (isRunning(row)) return <RunningRow row={row} />;
  const counts = row.counters ?? NO_COUNTS;
  // ↷ is "Tracks skipped as duplicates" (web-ui.md § Runs tab). Other skips, such as ads, are not counted here.

  return (
    <div role="row" className={cx(styles.columns, styles.row)}>
      <div role="cell">
        <Link to={`/history/runs/${row.id}`} className={styles.link}>
          {formatDayTime(row.started_at)}
        </Link>
      </div>
      <div role="cell" className={styles.text}>
        {TRIGGER[row.trigger]}
      </div>
      <div role="cell" className={styles.text}>
        {row.duration_s === null ? '' : formatRunLength(row.duration_s)}
      </div>
      <div role="cell">{row.outcome ? <OutcomePill outcome={row.outcome} /> : null}</div>
      <div role="cell" className={cx(styles.num, counts.recorded > 0 && styles.recorded)}>
        {formatCount(counts.recorded)}
      </div>
      <div role="cell" className={styles.num}>
        {formatCount(counts.skipped_duplicate)}
      </div>
      <div role="cell" className={cx(styles.num, counts.failed > 0 && styles.failed)}>
        {formatCount(counts.failed)}
      </div>
      <div role="cell" className={styles.num}>
        {counts.bytes_added > 0 ? `+${formatBytes(counts.bytes_added)}` : '—'}
      </div>
    </div>
  );
}

function RunningRow({ row }: { row: HistoryRow }) {
  return (
    <div role="row" className={cx(styles.columns, styles.row)}>
      <div role="cell">
        <Link to={`/history/runs/${row.id}`} className={styles.link}>
          {formatDayTime(row.started_at)}
        </Link>
      </div>
      <div role="cell" className={styles.text}>
        {TRIGGER[row.trigger]}
      </div>
      <div role="cell" />
      <div role="cell">
        <RunningPill />
      </div>
      <div role="cell" />
      <div role="cell" />
      <div role="cell" />
      <div role="cell" />
    </div>
  );
}

function NoRunRow({ row }: { row: HistoryRow }) {
  return (
    <div role="row" className={styles.noRun}>
      <div role="cell">{formatDay(row.started_at)}</div>
      <div role="cell" className={styles.noRunText}>
        <CircleSlash size={16} aria-hidden />
        <span>{noRunText(row)}</span>
      </div>
    </div>
  );
}
