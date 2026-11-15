import { useState, type ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './gallery.module.css';

// Small pieces for laying out ui-a's gallery entries like the component sheet. Gallery only.

/** One drawing on the sheet, with its spec label above it (or below, as in BRAND). */
export function Spec({ label, below = false, children }: { label: string; below?: boolean; children: ReactNode }) {
  return (
    <div className={cx(styles.item, below && styles.below)}>
      <span className={below ? styles.brandLabel : styles.spec}>{label}</span>
      {children}
    </div>
  );
}

/** A row of drawings, 40 apart and bottom-aligned. */
export function Row({ children }: { children: ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

/** Rows, 24 apart. */
export function Sheet({ children }: { children: ReactNode }) {
  return <div className={styles.sheet}>{children}</div>;
}

/** Keeps a value so a demo can be clicked: <Live initial={true}>{(on, set) => <Toggle checked={on} onChange={set} />}</Live> */
export function Live<T>({
  initial,
  children,
}: {
  initial: T;
  children: (value: T, set: (value: T) => void) => ReactNode;
}) {
  const [value, setValue] = useState(initial);
  return <>{children(value, setValue)}</>;
}

export function noop() {}
