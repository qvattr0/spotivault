import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './EmptyState.module.css';

export interface EmptyStateProps {
  /** "All your saved albums are already added", "Nothing to suggest". */
  title: string;
  /** What to do about it: "Save albums in Spotify first, then they show up here." */
  children?: ReactNode;
  icon?: LucideIcon;
  /** A button under the text, if the page has one. */
  action?: ReactNode;
  className?: string;
}

/**
 * An empty list's message, as drawn in Albums · Add albums (L3CNc7): a box with a subtle outline,
 * the title and one line of help, centred.
 */
export function EmptyState({ title, children, icon: Icon, action, className }: EmptyStateProps) {
  return (
    <div className={cx(styles.empty, className)}>
      {Icon ? <Icon size={24} aria-hidden className={styles.icon} /> : null}
      <p className={styles.title}>{title}</p>
      {children ? <div className={styles.text}>{children}</div> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
