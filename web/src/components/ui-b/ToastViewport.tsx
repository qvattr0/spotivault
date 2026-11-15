import { useContext } from 'react';
import { cx } from '@/lib/cx.ts';
import { Toast } from './Toast.tsx';
import { ToastListContext } from './toast-context.ts';
import styles from './ToastViewport.module.css';

export interface ToastViewportProps {
  className?: string;
}

/**
 * Where toasts appear: bottom centre of the nearest positioned box. The shell puts it in the page
 * panel, so toasts sit at the bottom centre of the content area (components.md § Toast).
 *
 * It's a polite live region that is always in the page, so screen readers announce each toast as
 * it's added (a live region added together with its text often isn't read).
 */
export function ToastViewport({ className }: ToastViewportProps) {
  const toasts = useContext(ToastListContext);

  return (
    <div className={cx(styles.viewport, className)} role="status" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <Toast key={toast.id} message={toast.message} icon={toast.icon} className={styles.item} />
      ))}
    </div>
  );
}
