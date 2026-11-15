import { cx } from '@/lib/cx.ts';
import { RowTitle } from './RowTitle.tsx';
import { TrackStatus, type TrackStatusKind } from './TrackStatus.tsx';
import styles from './Row.module.css';

export interface TrackRowProps {
  /** The position in the Web API order; null for playlists without item access. */
  position: number | null;
  title: string;
  artist: string;
  album: string | null;
  /** "4:44", or "" when unknown. */
  duration: string;
  state: TrackStatusKind;
  /** "Recorded · 9.4 MB", "Failed · low volume". */
  stateText: string;
  /** Shown on hover over the state: the file path of a recorded track (web-ui.md § Detail view). */
  stateHint?: string;
  selected?: boolean;
  /** For the gallery: 'hover' draws the hover state without the mouse (ui-a's convention). */
  'data-state'?: 'hover';
}

/**
 * `Row/Track` (components.md § List row): # · Title + artist · Album · Duration · State.
 * Put it in a dense <ListTable> with a <TrackHeader>.
 */
export function TrackRow(props: TrackRowProps) {
  const { position, title, artist, album, duration, state, stateText, stateHint, selected } = props;
  const dataState = props['data-state'];

  return (
    <div role="row" className={cx(styles.row, styles.track, selected && styles.selected)} data-state={dataState}>
      <div role="cell" className={cx(styles.text, styles.number)}>
        {position ?? ''}
      </div>
      <div role="cell">
        <RowTitle title={title} sub={artist} medium />
      </div>
      <div role="cell" className={styles.text}>
        {album ?? ''}
      </div>
      <div role="cell" className={styles.text}>
        {duration}
      </div>
      {/* The path shows as the browser's own tooltip: a styled one would need a tab stop on every row. */}
      <div role="cell" title={stateHint}>
        <TrackStatus kind={state} text={stateText} />
      </div>
    </div>
  );
}
