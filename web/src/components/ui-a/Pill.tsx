import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { cx } from '@/lib/cx.ts';
import styles from './Pill.module.css';

/** components.md § Status pill, colour variants, and the labels drawn in each:
 *  green: Up to date, Recording, Completed, OK, Confirmed, Logged in
 *  blue: n new, Set for you, Window ended
 *  yellow: Partial, Paused, Interrupted, Completed with issues
 *  red: Unavailable, Needs change, Failed
 *  neutral: Not tracked, Never backed up, Queued, Stopped, Not confirmed */
export type PillTone = 'green' | 'blue' | 'yellow' | 'red' | 'neutral';

export interface PillProps {
  tone: PillTone;
  children: ReactNode;
  /** A 12 px icon in place of the dot: `CircleDotDashed` for Recording. */
  icon?: LucideIcon;
  /** On an album cover (Albums · Grid): the dark see-through background. */
  onCover?: boolean;
  /** Makes it a link: Recording and Queued link to the Dashboard (web-ui.md § Item states). */
  to?: string;
  className?: string;
  /** For the gallery: 'hover' or 'focus' draws that state. */
  'data-state'?: string;
}

/** A status pill: a dot or an icon and a short label, in one of five colours. */
export function Pill({
  tone,
  children,
  icon: Icon,
  onCover = false,
  to,
  className,
  'data-state': dataState,
}: PillProps) {
  const classes = cx(styles.pill, styles[tone], Icon && styles.withIcon, onCover && styles.onCover, className);
  const content = (
    <>
      {Icon ? <Icon size={12} /> : <span className={styles.dot} />}
      {children}
    </>
  );
  if (to !== undefined) {
    return (
      <Link to={to} className={classes} data-state={dataState}>
        {content}
      </Link>
    );
  }
  return (
    <span className={classes} data-state={dataState}>
      {content}
    </span>
  );
}
