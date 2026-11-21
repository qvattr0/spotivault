import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { Cover, type CoverKind } from './Cover.tsx';
import { rowClickHandler } from './row-open.ts';
import { TrackCheck } from './TrackCheck.tsx';
import styles from './Card.module.css';

export interface CardTracking {
  tracked: boolean;
  /** Gets the new value when the badge is clicked. */
  onChange: (tracked: boolean) => void;
  /** While the item records, from 0 to 1, for the ring around the badge. */
  progress?: number | null;
  /** Its request is on its way: aria-busy, not disabled, so keyboard focus stays. */
  busy?: boolean;
}

export interface CardProps {
  title: string;
  /** "by you · 64 tracks", "Radiohead · 1997". */
  sub?: string;
  coverSrc?: string | null;
  kind?: CoverKind;
  /** Playlists: the corner badge (TrackCheck), which toggles tracking. Albums have none. */
  tracking?: CardTracking;
  /** The status `Pill` under the text (playlists). */
  status?: ReactNode;
  /** A `Pill` with `onCover`, at the cover's top right (albums: Queued, Recording, Partial, Unavailable). */
  cornerStatus?: ReactNode;
  /** The round "Back up now" button (`Button/Play`), at the cover's bottom right on hover and focus. */
  action?: ReactNode;
  /** Opens the detail view: a click on the card or its title. */
  onOpen?: () => void;
  className?: string;
  /** For the gallery: 'hover' draws the hover state without the mouse (ui-a's convention). */
  'data-state'?: 'hover';
}

/**
 * `Card` (components.md § Card): cover art, title, a line below and a status pill. It fills its
 * grid column (200 wide on the sheet). Variants: tracked, not tracked and recording (by `tracking`),
 * hover (shows `action`), and album (`cornerStatus`, no badge; recorded albums pass no pill at all).
 */
export function Card(props: CardProps) {
  const { title, sub, coverSrc, kind, tracking, status, cornerStatus, action, onOpen, className } = props;
  const dataState = props['data-state'];

  return (
    <div
      className={cx(styles.card, onOpen && styles.clickable, className)}
      onClick={rowClickHandler(onOpen)}
      data-state={dataState}
    >
      <div className={styles.art}>
        <Cover src={coverSrc} kind={kind} size="fill" />
        {tracking ? (
          <div className={styles.badge}>
            <TrackCheck
              tracked={tracking.tracked}
              onChange={tracking.onChange}
              progress={tracking.progress}
              label={`Track ${title}`}
              aria-busy={tracking.busy || undefined}
              align="end"
            />
          </div>
        ) : null}
        {cornerStatus ? <div className={styles.corner}>{cornerStatus}</div> : null}
        {action ? <div className={styles.action}>{action}</div> : null}
      </div>
      {onOpen ? (
        <button type="button" className={styles.title} onClick={onOpen}>
          {title}
        </button>
      ) : (
        <p className={styles.title}>{title}</p>
      )}
      {sub ? <p className={styles.sub}>{sub}</p> : null}
      {status ? <div className={styles.status}>{status}</div> : null}
    </div>
  );
}
