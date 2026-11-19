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
}

/**
 * The grid card's corner badge (components.md § Card): a filled green check when tracked, a
 * hollow circle when not. Clicking it toggles tracking (web-ui.md § Grid view), so it's a switch.
 * While the item records, a thin ring around it shows its progress.
 */
export function TrackBadge({
  tracked,
  onChange,
  label,
  progress,
  className,
  type = 'button',
  ...rest
}: TrackBadgeProps) {
  const recording = progress !== undefined && progress !== null;
  const percent = recording ? Math.min(100, Math.max(0, progress * 100)) : 0;
  return (
    <button
      {...rest}
      type={type}
      role="switch"
      aria-checked={tracked}
      aria-label={label}
      className={cx(styles.badge, tracked ? styles.tracked : styles.untracked, className)}
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
