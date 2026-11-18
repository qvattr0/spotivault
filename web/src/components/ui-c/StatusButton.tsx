import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router';
import { cx } from '@/lib/cx.ts';
import styles from './StatusButton.module.css';

export interface StatusButtonProps {
  /** The state: "OK", "Expiring", "Expired". */
  status: string;
  /** Its colour, as a status pill's (components.md § Status pill). */
  tone: 'green' | 'yellow' | 'red' | 'neutral';
  /** Before the state: `CircleCheck`. */
  statusIcon?: LucideIcon;
  /** The action: "Reconnect". */
  actionLabel: string;
  /** Before the action: `RefreshCw`. */
  actionIcon?: LucideIcon;
  /** A page of this app ('/reconnect'), or a click handler. */
  to?: string;
  onAction?: () => void;
  className?: string;
}

/**
 * A state and the action that goes with it, joined in one pill: Settings › Spotify account's
 * "✓ OK | ⟳ Reconnect" (t6RqK). The state is text, not a control; only the action is.
 */
export function StatusButton({ status, tone, statusIcon: StatusIcon, actionLabel, actionIcon: ActionIcon, to, onAction, className }: StatusButtonProps) {
  const action = (
    <>
      {ActionIcon ? <ActionIcon size={16} aria-hidden /> : null}
      {actionLabel}
    </>
  );
  return (
    <span className={cx(styles.joined, className)}>
      <span className={cx(styles.status, styles[tone])}>
        {StatusIcon ? <StatusIcon size={16} aria-hidden /> : null}
        {status}
      </span>
      <span className={styles.divider} aria-hidden="true" />
      {to !== undefined ? (
        <Link to={to} className={styles.action}>
          {action}
        </Link>
      ) : (
        <button type="button" className={styles.action} onClick={onAction}>
          {action}
        </button>
      )}
    </span>
  );
}
