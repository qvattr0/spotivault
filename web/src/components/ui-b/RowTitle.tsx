import { cx } from '@/lib/cx.ts';
import styles from './Row.module.css';

export interface RowTitleProps {
  title: string;
  /** The line below: owner, artist. */
  sub?: string;
  /** A 15/500 title (tracks, modal rows) instead of 15/600 (playlists, albums). */
  medium?: boolean;
  /** Makes the title a button, so keyboard users can open the item too. */
  onOpen?: () => void;
}

/** A row's title with its line below (gap 2). Used by the list rows and ItemRow. */
export function RowTitle({ title, sub, medium, onOpen }: RowTitleProps) {
  const className = cx(styles.title, medium && styles.medium);
  return (
    <div className={styles.names}>
      {onOpen ? (
        <button type="button" className={className} onClick={onOpen}>
          {title}
        </button>
      ) : (
        <span className={className}>{title}</span>
      )}
      {sub ? <span className={styles.sub}>{sub}</span> : null}
    </div>
  );
}
