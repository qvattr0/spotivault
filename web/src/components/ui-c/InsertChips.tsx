import { cx } from '@/lib/cx.ts';
import styles from './InsertChips.module.css';

export interface InsertChipsProps {
  /** What each chip types: '{album_artist}', '{artists}', ... */
  items: readonly string[];
  /** Called with the chip's text. Pair it with useInsertAtCursor. */
  onInsert: (text: string) => void;
  /** The label before the chips. Default "Insert:". */
  label?: string;
  className?: string;
}

/**
 * The Edit layout modal's "Insert:" chips (w1uXEY): small mono chips that type a placeholder at
 * the layout field's cursor. A press doesn't take the focus, so the field keeps its cursor.
 */
export function InsertChips({ items, onInsert, label = 'Insert:', className }: InsertChipsProps) {
  return (
    <div className={cx(styles.row, className)} role="group" aria-label={label.replace(/:$/, '')}>
      <span className={styles.label} aria-hidden="true">
        {label}
      </span>
      {items.map((item) => (
        <button
          key={item}
          type="button"
          className={styles.chip}
          aria-label={`Insert ${item}`}
          // Keep the focus (and the cursor) in the field.
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onInsert(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}
