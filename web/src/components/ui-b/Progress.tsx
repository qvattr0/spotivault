import { cx } from '@/lib/cx.ts';
import styles from './Progress.module.css';

export interface ProgressProps {
  /**
   * From 0 to 1. Null draws an indeterminate bar: Finishing (web-ui.md § Dashboard), or an install
   * with no progress yet. The Full backup card's Measuring is a skeleton instead (the approved mockup).
   */
  value: number | null;
  /** What it measures, for screen readers: "Track progress", "Full backup". */
  label: string;
  className?: string;
}

/** `Progress` (components.md § Progress bar): a 4 px track with a green fill. It fills its container's width. */
export function Progress({ value, label, className }: ProgressProps) {
  const percent = value === null ? null : Math.round(Math.min(Math.max(value, 0), 1) * 1000) / 10;

  return (
    <div
      className={cx(styles.track, className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
    >
      {percent === null ? (
        <div className={cx(styles.fill, styles.indeterminate)} />
      ) : (
        <div className={styles.fill} style={{ width: `${percent}%` }} />
      )}
    </div>
  );
}
