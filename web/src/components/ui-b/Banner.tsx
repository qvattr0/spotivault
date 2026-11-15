import type { ReactNode } from 'react';
import { CircleX, ClockAlert, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router';
import { cx } from '@/lib/cx.ts';
import styles from './Banner.module.css';

export type BannerTone = 'warn' | 'danger';

/** The pill at the right: a link inside the app ("Reconnect"), or a button ("Take control"). */
export type BannerAction = { label: string; to: string } | { label: string; onClick: () => void };

export interface BannerProps {
  /** Yellow (the default) or red: the expiry banner before and after the connection expires. */
  tone?: BannerTone;
  children: ReactNode;
  /** Defaults by tone: `clock-alert` or `circle-x`. The Player's view-only banner uses `lock`. */
  icon?: LucideIcon;
  action?: BannerAction;
  className?: string;
}

/**
 * `Banner` (components.md § Expiry banner): a full-width strip with an icon, one line of text and a
 * pill. The shell's expiry banner and the Player's view-only banner are both this.
 * The red one is `role="alert"`; the yellow one is polite (`role="status"`).
 */
export function Banner({ tone = 'warn', children, icon, action, className }: BannerProps) {
  const Icon = icon ?? (tone === 'danger' ? CircleX : ClockAlert);

  return (
    <div className={cx(styles.banner, styles[tone], className)} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon size={18} aria-hidden className={styles.icon} />
      <p className={styles.text}>{children}</p>
      {action && 'to' in action ? (
        <Link to={action.to} className={styles.action}>
          {action.label}
        </Link>
      ) : action ? (
        <button type="button" className={styles.action} onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
