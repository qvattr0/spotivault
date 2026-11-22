import { Check } from 'lucide-react';
import type { ComponentProps } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './TrackBadge.module.css';

export interface TrackBadgeProps extends Omit<ComponentProps<'button'>, 'onChange'> {
  tracked: boolean;
  onChange: (tracked: boolean) => void;
  /** Its accessible name: "Track Late Night Drive". */
  label: string;
  /** While the item records: how far it has got, 0 to 1. Draws the progress ring. */
  progress?: number | null;
  /**
   * On the page rather than on a cover: a list row's first column and the detail header. The
   * same check without the card's ring; not tracked, a hollow grey circle that turns white on hover.
   */
  inline?: boolean;
  /**
   * With `inline`: a word drawn beside the circle, inside the same button, so a click on the word
   * toggles too and the whole of it shows hover ("Tracked" in the detail header). The accessible
   * name stays `label`; `aria-checked` gives the state.
   */
  text?: string;
}

/**
 * Tracking an item, as a round check (components.md § Card, web-ui.md § Grid view and § List
 * view): a filled green check when tracked, a hollow circle when not. Clicking it toggles tracking,
 * so it's a checkbox: Space or Enter flips it, and `onChange` gets the new value. On a grid card's
 * cover by default, `inline` in a list row and the detail header. While the item records, a thin
 * ring around it shows its progress. ui-b's TrackCheck adds the tooltip that says what it means.
 */
export function TrackBadge({
  tracked,
  onChange,
  label,
  progress,
  inline = false,
  text,
  className,
  type = 'button',
  ...rest
}: TrackBadgeProps) {
  const recording = progress !== undefined && progress !== null;
  const percent = recording ? Math.min(100, Math.max(0, progress * 100)) : 0;
  const circle = cx(styles.badge, tracked ? styles.tracked : styles.untracked, inline && styles.inline);
  if (inline && text) {
    return (
      <button
        {...rest}
        type={type}
        role="checkbox"
        aria-checked={tracked}
        aria-label={label}
        className={cx(styles.labelled, className)}
        onClick={() => onChange(!tracked)}
      >
        <span className={circle} aria-hidden="true">
          {tracked && <Check size={14} />}
        </span>
        <span>{text}</span>
      </button>
    );
  }
  return (
    <button
      {...rest}
      type={type}
      role="checkbox"
      aria-checked={tracked}
      aria-label={label}
      className={cx(circle, className)}
      onClick={() => onChange(!tracked)}
    >
      {tracked && <Check size={14} />}
      {recording && (
        <svg className={styles.ring} viewBox="0 0 40 40" aria-hidden="true">
          <circle className={styles.ringTrack} cx="20" cy="20" r="18.5" />
          <circle
            className={styles.ringFill}
            cx="20"
            cy="20"
            r="18.5"
            pathLength={100}
            strokeDasharray={`${percent} 100`}
          />
        </svg>
      )}
    </button>
  );
}
