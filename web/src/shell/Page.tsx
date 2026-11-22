import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { useDocumentTitle } from './PageHeader.tsx';
import styles from './Page.module.css';

/** The page colours that tint the top of the panel (components.md § Page layout). */
export type PageTint = 'dashboard' | 'dashboard-running' | 'library-detail' | 'albums' | 'schedule' | 'history';

const TINTS: Record<PageTint, string> = {
  dashboard: styles.tintDashboard,
  'dashboard-running': styles.tintDashboardRunning,
  'library-detail': styles.tintLibraryDetail,
  albums: styles.tintAlbums,
  schedule: styles.tintSchedule,
  history: styles.tintHistory,
};

interface PageProps {
  /** The 32/800 page title, as an h1. Leave it out when the page draws a PageHeader. */
  title?: string;
  /** Dashboard idle and Library: 'dashboard'. Settings and Player have none. */
  tint?: PageTint;
  /** No padding or gap, for pages that draw edge to edge (the Player's toolbar). */
  flush?: boolean;
  /** As tall as the panel, not taller: for a page whose list scrolls by itself (History › Logs). */
  fill?: boolean;
  children: ReactNode;
}

/**
 * The frame of an app page, inside the shell's panel: padding 28 32, gap 16, and the page's tint
 * over the top (components.md § Page layout). Every S8 page draws itself inside one.
 */
export function Page({ title, tint, flush = false, fill = false, children }: PageProps) {
  useDocumentTitle(title);

  return (
    <div className={cx(styles.page, tint && styles.tinted, tint && TINTS[tint], flush && styles.flush, fill && styles.fill)}>
      {title && <h1 className={styles.title}>{title}</h1>}
      {children}
    </div>
  );
}
