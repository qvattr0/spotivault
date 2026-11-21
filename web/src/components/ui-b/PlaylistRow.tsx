import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { Cover, type CoverKind } from './Cover.tsx';
import { rowClickHandler } from './row-open.ts';
import { RowTitle } from './RowTitle.tsx';
import styles from './Row.module.css';

export interface PlaylistRowProps {
  name: string;
  /** The line under the name: "by you", "by Lorde", "added by link", "Playlist · pinned · 412 songs". */
  owner: string;
  coverSrc?: string | null;
  /** 'liked' shows Liked Songs' tile. */
  kind?: CoverKind;
  /** "84 / 120 recorded", "32 recorded" or "—". A node, so the page can add an info tooltip. */
  tracks: ReactNode;
  /** "2 days ago", "Never", or "Now" while it records. */
  lastBackup: string;
  /** Recording now: the last-backup text turns green. */
  recording?: boolean;
  /** Not tracked: the cover and text are dimmed. */
  muted?: boolean;
  /** The tracking check (`TrackCheck`, `inline`). */
  tracking?: ReactNode;
  /** The status `Pill`. */
  status?: ReactNode;
  /** The ⋯ row menu (ui-a's `MenuButton`). The row stays highlighted while it's open. */
  menu?: ReactNode;
  /** The round "Back up now" button (`Button/Play`), shown over the cover on hover and focus. */
  action?: ReactNode;
  /** Highlighted like a hovered row. */
  selected?: boolean;
  /** Opens the detail view: a click on the row or its name. */
  onOpen?: () => void;
  /** For the gallery: 'hover' draws the hover state without the mouse (ui-a's convention). */
  'data-state'?: 'hover';
}

/**
 * `Row/Playlist` (components.md § List row): Toggle · Cover + name · Tracks · Last backup · Status · ⋯.
 * Put it in a <ListTable> with a <PlaylistHeader>. The drawing's Toggle is a round check in the UI
 * (TrackCheck, as on a grid card), so it can't be mistaken for Back up now.
 *
 * Where "Back up now" sits on hover isn't drawn (components.md § Differences, row 6): we put it over
 * the cover, where the client puts its play button in list rows.
 */
export function PlaylistRow(props: PlaylistRowProps) {
  const { name, owner, coverSrc, kind, tracks, lastBackup, recording, muted, tracking, status, menu, action, selected, onOpen } =
    props;
  const dataState = props['data-state'];

  return (
    <div
      role="row"
      className={cx(
        styles.row,
        styles.playlist,
        selected && styles.selected,
        muted && styles.muted,
        onOpen && styles.clickable,
      )}
      onClick={rowClickHandler(onOpen)}
      data-state={dataState}
    >
      <div role="cell">{tracking}</div>
      <div role="cell" className={styles.item}>
        <div className={styles.coverBox}>
          <Cover src={coverSrc} kind={kind} size={44} />
          {action ? <div className={styles.action}>{action}</div> : null}
        </div>
        <RowTitle title={name} sub={owner} onOpen={onOpen} />
      </div>
      <div role="cell" className={styles.text}>
        {tracks}
      </div>
      <div role="cell" className={cx(styles.text, recording && styles.now)}>
        {lastBackup}
      </div>
      <div role="cell">{status}</div>
      <div role="cell" className={styles.end}>
        {menu}
      </div>
    </div>
  );
}
