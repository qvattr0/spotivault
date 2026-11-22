import { useEffect, type ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import styles from './PageHeader.module.css';

export interface PageHeaderProps {
  /** The 32/800 page title, as the page's h1: "Library". It also names the browser tab. */
  title: string;
  /** The line under the title: "18 of 23 tracked · last backup 03:12 today". */
  summary?: ReactNode;
  /** At the right of the title: search, sort, view switch, + and ⋯ (Library · List, ZGPGu). */
  actions?: ReactNode;
  /** The row under the title, at the left: filter chips (Library) or tabs (History, PageTabs). */
  bar?: ReactNode;
  /** The same row, at the right: History's filter chips (o5vCh7). */
  barEnd?: ReactNode;
  className?: string;
}

/**
 * The top of an app page (Library, Albums, History, Settings, ...): the title and its summary,
 * the page's tools at the right, and a row of chips or tabs below. Put it first inside <Page>
 * (without Page's own `title`).
 */
export function PageHeader({ title, summary, actions, bar, barEnd, className }: PageHeaderProps) {
  useDocumentTitle(title);
  return (
    <header className={cx(styles.header, className)}>
      <div className={styles.top}>
        <div className={styles.titles}>
          <h1 className={styles.title}>{title}</h1>
          {summary ? <p className={styles.summary}>{summary}</p> : null}
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </div>
      {bar || barEnd ? (
        <div className={styles.bar}>
          {bar ? <div className={styles.barStart}>{bar}</div> : <span />}
          {barEnd ? <div className={styles.barEnd}>{barEnd}</div> : null}
        </div>
      ) : null}
    </header>
  );
}

/** Names the browser tab after the page: "Library · spotivault". */
export function useDocumentTitle(title: string | undefined): void {
  useEffect(() => {
    if (!title) return;
    document.title = `${title} · spotivault`;
    return () => {
      document.title = 'spotivault';
    };
  }, [title]);
}
