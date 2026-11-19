import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { Cover } from './Cover.tsx';
import { rowClickHandler } from './row-open.ts';
import { RowTitle } from './RowTitle.tsx';
import styles from './Row.module.css';

export interface AlbumRowProps {
  name: string;
  artist: string;
  coverSrc?: string | null;
  /** The release year; null shows "—". */
  year: number | null;
  /** "12 / 12". */
  tracks: string;
  /** The date it was completed ("3 Nov 2026"), or "—". */
  recorded: string;
  /** The status `Pill`. */
  status?: ReactNode;
  /** The ⋯ row menu (ui-a's `MenuButton`). */
  menu?: ReactNode;
  /** A round button over the cover on hover and focus ("Record now"), if the page wants one. */
  action?: ReactNode;
  selected?: boolean;
  /** Opens the album's detail view. */
  onOpen?: () => void;
  /** For the gallery: 'hover' draws the hover state without the mouse (ui-a's convention). */
  'data-state'?: 'hover';
}

/**
 * `Row/Album` (components.md § List row): Cover + album · Year · Tracks · Recorded · Status · ⋯.
 * Put it in a <ListTable> with an <AlbumHeader>.
 */
export function AlbumRow(props: AlbumRowProps) {
  const { name, artist, coverSrc, year, tracks, recorded, status, menu, action, selected, onOpen } = props;
  const dataState = props['data-state'];

  return (
    <div
      role="row"
      className={cx(styles.row, styles.album, selected && styles.selected, onOpen && styles.clickable)}
      onClick={rowClickHandler(onOpen)}
      data-state={dataState}
    >
      <div role="cell" className={styles.item}>
        <div className={styles.coverBox}>
          <Cover src={coverSrc} kind="album" size={44} />
          {action ? <div className={styles.action}>{action}</div> : null}
        </div>
        <RowTitle title={name} sub={artist} onOpen={onOpen} />
      </div>
      <div role="cell" className={styles.text}>
        {year ?? '—'}
      </div>
      <div role="cell" className={styles.text}>
        {tracks}
      </div>
      <div role="cell" className={styles.text}>
        {recorded}
      </div>
      <div role="cell">{status}</div>
      <div role="cell" className={styles.end}>
        {menu}
      </div>
    </div>
  );
}
