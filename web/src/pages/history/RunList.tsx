// The Runs table: its header row and one RunRow per run (web-ui.md § Runs tab, the columns).

import { Check, CornerUpRight, X } from 'lucide-react';
import type { HistoryRow } from '@/api';
import { ListTable } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { RunRow } from './RunRow.tsx';
import styles from './RunList.module.css';

export function RunList({ rows }: { rows: HistoryRow[] }) {
  return (
    <ListTable label="Runs" header={<RunListHeader />}>
      {rows.map((row) => (
        <RunRow key={`${row.kind}-${row.id}`} row={row} />
      ))}
    </ListTable>
  );
}

/** The column headings. The three counts are icons, so each one says its word for screen readers. */
function RunListHeader() {
  return (
    <div role="row" className={cx(styles.columns, styles.header)}>
      <span role="columnheader">When</span>
      <span role="columnheader">Trigger</span>
      <span role="columnheader">Duration</span>
      <span role="columnheader">Outcome</span>
      <span role="columnheader" className={styles.num}>
        <Check size={16} aria-hidden />
        <span className="visually-hidden">Recorded</span>
      </span>
      <span role="columnheader" className={styles.num}>
        <CornerUpRight size={16} aria-hidden />
        <span className="visually-hidden">Skipped</span>
      </span>
      <span role="columnheader" className={styles.num}>
        <X size={16} aria-hidden />
        <span className="visually-hidden">Failed</span>
      </span>
      <span role="columnheader" className={styles.num}>
        Size
      </span>
    </div>
  );
}
