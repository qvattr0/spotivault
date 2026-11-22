import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './gallery.module.css';

// Small layout pieces for ui-b's gallery entries. Gallery only.

/** One drawing with its spec label above it, as on the component sheet. */
export function Spec({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={cx(styles.spec, className)}>
      <span className={styles.specLabel}>{label}</span>
      {children}
    </div>
  );
}

/** Drawings side by side, 40 apart, bottom-aligned. */
export function Row({ children }: { children: ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

/** Drawings one under the other, 8 apart. */
export function Stack({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx(styles.stack, className)}>{children}</div>;
}

/** A short explanation under a drawing. */
export function Note({ children }: { children: ReactNode }) {
  return <p className={styles.note}>{children}</p>;
}

export function noop() {}
