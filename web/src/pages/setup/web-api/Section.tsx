import type { ReactNode } from 'react';
import { Check } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './WebApi.module.css';

interface SectionProps {
  /** Its number, shown until it's done. */
  number: number;
  title: string;
  done: boolean;
  children?: ReactNode;
}

/** One numbered part of step 5 (j8m6AR): a 40 px disc, green with a tick once done, then the title and its content. */
export function Section({ number, title, done, children }: SectionProps) {
  return (
    <section className={styles.section}>
      <span className={cx(styles.marker, done && styles.markerDone)} aria-hidden>
        {done ? <Check size={16} strokeWidth={3} /> : number}
      </span>
      <div className={styles.sectionBody}>
        <h2 className={styles.sectionTitle}>
          {title}
          {done ? <span className="visually-hidden">, done</span> : null}
        </h2>
        {children}
      </div>
    </section>
  );
}
