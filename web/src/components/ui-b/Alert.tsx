import type { ReactNode } from 'react';
import { CircleX, Info, TriangleAlert, type LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Alert.module.css';

export type AlertTone = 'warn' | 'danger' | 'info';

export interface AlertProps {
  tone?: AlertTone;
  title: string;
  /** The text under the title. */
  children?: ReactNode;
  /** Defaults by tone: `triangle-alert`, `circle-x`, `info`. The drawings also use `smartphone` (playback moved). */
  icon?: LucideIcon;
  className?: string;
}

const ICONS: Record<AlertTone, LucideIcon> = { warn: TriangleAlert, danger: CircleX, info: Info };

/**
 * `Alert` (components.md § Inline alert). Buttons that go with it (Resume, Stop, Retry) sit outside
 * it, in their own row below, as drawn.
 *
 * Danger alerts are `role="alert"`, so a new one is read out at once; warn and info are polite
 * (`role="status"`). The info tone isn't drawn: it follows the other two with the info colours.
 */
export function Alert({ tone = 'warn', title, children, icon, className }: AlertProps) {
  const Icon = icon ?? ICONS[tone];

  return (
    <div className={cx(styles.alert, styles[tone], className)} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon size={20} aria-hidden className={styles.icon} />
      <div className={styles.body}>
        <p className={styles.title}>{title}</p>
        {children ? <div className={styles.text}>{children}</div> : null}
      </div>
    </div>
  );
}
