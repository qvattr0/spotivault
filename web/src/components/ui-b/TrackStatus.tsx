import {
  Circle,
  CircleCheck,
  CircleDashed,
  CircleDotDashed,
  CircleSlash,
  CircleX,
  Redo2,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './TrackStatus.module.css';

/**
 * A track's state, with its icon and colour (components.md § Row/Track). `recording` and `pending`
 * are the Dashboard's live table; `unplayable` is the contract's (a local file), not drawn.
 */
export type TrackStatusKind =
  | 'recorded'
  | 'skipped'
  | 'failed'
  | 'missing'
  | 'new'
  | 'recording'
  | 'pending'
  | 'unplayable';

export interface TrackStatusProps {
  kind: TrackStatusKind;
  /** What it says: "Recorded · 9.4 MB", "Failed · low volume", "Skipped (duplicate)". */
  text: string;
  /** 'md' (16 px icon, 13/500) in track tables; 'sm' (15 px, 12/500) in the Dashboard's live table. */
  size?: 'md' | 'sm';
  className?: string;
}

const ICONS: Record<TrackStatusKind, LucideIcon> = {
  recorded: CircleCheck,
  skipped: Redo2,
  failed: CircleX,
  missing: CircleDashed,
  new: Sparkles,
  recording: CircleDotDashed,
  pending: Circle,
  unplayable: CircleSlash,
};

/** An icon and a short text for a track's state. */
export function TrackStatus({ kind, text, size = 'md', className }: TrackStatusProps) {
  const Icon = ICONS[kind];
  return (
    <span className={cx(styles.status, styles[kind], styles[size], className)}>
      <Icon size={size === 'sm' ? 15 : 16} aria-hidden className={styles.icon} />
      <span className={styles.text}>{text}</span>
    </span>
  );
}
