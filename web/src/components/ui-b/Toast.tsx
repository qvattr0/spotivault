import { CircleCheck, type LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Toast.module.css';

export interface ToastProps {
  message: string;
  /** Defaults to `circle-check`, as drawn. */
  icon?: LucideIcon;
  className?: string;
}

/**
 * `Toast` (components.md § Toast): a blue box with an icon and one line of text.
 * This draws one. To show one, call `useToast()` (it's announced to screen readers and goes away
 * on its own); the shell places the `ToastViewport` where they appear.
 */
export function Toast({ message, icon: Icon = CircleCheck, className }: ToastProps) {
  return (
    <div className={cx(styles.toast, className)}>
      <Icon size={18} aria-hidden className={styles.icon} />
      <span>{message}</span>
    </div>
  );
}
