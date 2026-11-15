import { Clock3 } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Row.module.css';

/** The header row over TrackRows: # · Title · Album · (clock) · State (as in l9Wn7L). */
export function TrackHeader() {
  return (
    <div role="row" className={cx(styles.header, styles.track)}>
      <span role="columnheader" className={styles.number}>
        #
      </span>
      <span role="columnheader">Title</span>
      <span role="columnheader">Album</span>
      <span role="columnheader" aria-label="Duration">
        <Clock3 size={16} aria-hidden />
      </span>
      <span role="columnheader">State</span>
    </div>
  );
}
