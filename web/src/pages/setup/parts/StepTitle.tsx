import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { useDocumentTitle } from '@/shell';
import styles from './Step.module.css';

interface StepTitleProps {
  /** The step's heading (the page's h1, and the browser tab's name). */
  title: string;
  /** The line or two under it. */
  lead?: ReactNode;
  /** At the right of the heading: step 4's Re-check. */
  actions?: ReactNode;
  /** The first and last steps' larger title, 30 px (Oleh8, BAzX6). */
  hero?: boolean;
}

/** A wizard step's heading, 28/800 (30 for `hero`), with its lead text (Oleh8, h2Qgw, wNpTP). */
export function StepTitle({ title, lead, actions, hero = false }: StepTitleProps) {
  useDocumentTitle(title);
  return (
    <div className={styles.head}>
      <div className={cx(styles.headText, actions ? styles.headTextTight : null)}>
        <h1 className={cx(styles.title, hero && styles.titleHero)}>{title}</h1>
        {lead ? <p className={styles.lead}>{lead}</p> : null}
      </div>
      {actions}
    </div>
  );
}
