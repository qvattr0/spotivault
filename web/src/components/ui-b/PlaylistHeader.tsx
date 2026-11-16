import { cx } from '@/lib/cx.ts';
import styles from './Row.module.css';

/** The header row over PlaylistRows: Title · Tracks · Last backup · Status (as in ZGPGu). */
export function PlaylistHeader() {
  return (
    <div role="row" className={cx(styles.header, styles.playlist)}>
      <span role="columnheader">
        <span className="visually-hidden">Tracked</span>
      </span>
      <span role="columnheader">Title</span>
      <span role="columnheader">Tracks</span>
      <span role="columnheader">Last backup</span>
      <span role="columnheader">Status</span>
      <span role="columnheader">
        <span className="visually-hidden">Actions</span>
      </span>
    </div>
  );
}
