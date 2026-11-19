import type { ReactNode } from 'react';
import { CircleCheck, CircleX, LoaderCircle } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './CheckResult.module.css';

interface CheckResultProps {
  /** `ok` green, `fail` red, `pending` grey with a spinner (the check is running). */
  tone: 'ok' | 'fail' | 'pending';
  title: string;
  /** The line under the title. */
  children?: ReactNode;
  /** A button under the text: Retry, Re-check. */
  action?: ReactNode;
}

/**
 * The result of a check the wizard runs: "/music is mounted and writable" (Mj5zE), "Connected as
 * Lorne · expires 12 May 2027" and the playback device (j8m6AR). Drawn as a tinted box with no
 * stroke, which is why it isn't ui-b's Alert (that one has a stroke and no green tone).
 */
export function CheckResult({ tone, title, children, action }: CheckResultProps) {
  const Icon = tone === 'ok' ? CircleCheck : tone === 'fail' ? CircleX : LoaderCircle;
  return (
    <div className={cx(styles.result, styles[tone])} role={tone === 'fail' ? 'alert' : 'status'}>
      <Icon size={20} aria-hidden className={styles.icon} />
      <div className={styles.body}>
        <p className={styles.title}>{title}</p>
        {children ? <div className={styles.text}>{children}</div> : null}
        {action ? <div className={styles.action}>{action}</div> : null}
      </div>
    </div>
  );
}
