import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './ListTable.module.css';

export interface ListTableProps {
  /** Names the table for screen readers: "Playlists", "Tracks". */
  label: string;
  /** The column headings: <PlaylistHeader />, <AlbumHeader /> or <TrackHeader />. */
  header?: ReactNode;
  /** The rows: PlaylistRow, AlbumRow or TrackRow. */
  children: ReactNode;
  /** Space between rows: 2 px for playlist and album rows (as drawn), none for track rows. */
  dense?: boolean;
  className?: string;
}

/**
 * A Spotify-style table of rows, with a header line above. The rows are a grid, not a <table>, but
 * carry table roles, so screen readers can move by row and column.
 */
export function ListTable({ label, header, children, dense, className }: ListTableProps) {
  return (
    <div role="table" aria-label={label} className={cx(styles.table, className)}>
      {header ? (
        <div role="rowgroup" className={styles.head}>
          {header}
        </div>
      ) : null}
      <div role="rowgroup" className={cx(styles.rows, dense && styles.dense)}>
        {children}
      </div>
    </div>
  );
}
