import { cx } from '@/lib/cx.ts';
import styles from './Row.module.css';

/** The header row over AlbumRows: Album · Year · Tracks · Recorded · Status (as in wwJXz). */
export function AlbumHeader() {
  return (
    <div role="row" className={cx(styles.header, styles.album)}>
      <span role="columnheader" className={styles.pastCover}>
        Album
      </span>
      <span role="columnheader">Year</span>
      <span role="columnheader">Tracks</span>
      <span role="columnheader">Recorded</span>
      <span role="columnheader">Status</span>
      <span role="columnheader">
        <span className="visually-hidden">Actions</span>
      </span>
    </div>
  );
}
