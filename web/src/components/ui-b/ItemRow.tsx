import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { Cover, type CoverKind } from './Cover.tsx';
import { RowTitle } from './RowTitle.tsx';
import styles from './ItemRow.module.css';

export interface ItemRowProps {
  title: string;
  /** "Tyler, The Creator · 2019 · 12 tracks", "by Lorde". */
  sub?: string;
  coverSrc?: string | null;
  kind?: CoverKind;
  /** 44 in the add modals (as drawn), 36 in the Dashboard's Up next list. */
  coverSize?: number;
  /** What sits at the right: an Add button, "12 tracks", a pill, a menu. */
  trailing?: ReactNode;
  /** A 14 px title (the Dashboard's Up next, t4YEY) instead of 15. */
  small?: boolean;
  className?: string;
}

/**
 * A simple list row: cover, title and a line below, and something at the right. Not a component
 * in the drawings, but drawn the same way in Library · Add playlists (w06M4n), Albums · Add albums
 * (L3CNc7) and the Dashboard's Up next list (t4YEY).
 */
export function ItemRow({ title, sub, coverSrc, kind, coverSize = 44, trailing, small, className }: ItemRowProps) {
  return (
    <div className={cx(styles.row, className)}>
      <Cover src={coverSrc} kind={kind} size={coverSize} />
      <div className={styles.names}>
        <RowTitle title={title} sub={sub} medium small={small} />
      </div>
      {trailing ? <div className={styles.trailing}>{trailing}</div> : null}
    </div>
  );
}
