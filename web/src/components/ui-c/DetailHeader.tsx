import type { ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import { Link } from 'react-router';
import { Cover, type CoverKind } from '@/components/ui-b';
import { useDocumentTitle } from '@/shell/PageHeader.tsx';
import { cx } from '@/lib/cx.ts';
import styles from './DetailHeader.module.css';

export interface DetailHeaderProps {
  /** Where "‹ Library" goes back to: '/library', '/albums'. */
  backTo: string;
  /** "Library", "Albums". */
  backLabel: string;
  /** "Playlist", "Album", above the name. */
  typeLabel: string;
  /** The name, as the page's h1: "Late Night Drive". */
  title: string;
  /** The line under it: "by you · 120 tracks · 7 h 48 min · 118 recorded". */
  meta?: ReactNode;
  coverSrc?: string | null;
  /** 'liked' always shows Liked Songs' tile; 'album' an album's placeholder. */
  kind?: CoverKind;
  /** Something on the cover: the Library's "Change cover" hover (not in M1). */
  coverOverlay?: ReactNode;
  /** The row under the header: Back up now (PlayButton size "lg"), the tracking toggle, the status pill, ⋯. */
  actions?: ReactNode;
}

/**
 * The top of a detail view, "like a playlist page in the client" (web-ui.md § Detail view; Library ·
 * Detail, l9Wn7L): a back link, a 200 px cover, the type, the name in large type and a line of
 * facts, then a row of actions. Albums' detail view uses the same layout (web-ui.md § Albums,
 * Detail view; not drawn). Put it first inside <Page tint="library-detail"> (or "albums").
 */
export function DetailHeader({ backTo, backLabel, typeLabel, title, meta, coverSrc, kind = 'playlist', coverOverlay, actions }: DetailHeaderProps) {
  useDocumentTitle(title);
  return (
    <header className={styles.header}>
      <Link to={backTo} className={styles.back}>
        <ChevronLeft size={16} aria-hidden />
        {backLabel}
      </Link>
      <div className={styles.top}>
        <div className={styles.cover}>
          <Cover src={coverSrc} kind={kind} size={200} />
          {coverOverlay}
        </div>
        <div className={styles.texts}>
          <p className={styles.type}>{typeLabel}</p>
          <h1 className={cx(styles.title, title.length > 24 && styles.long)}>{title}</h1>
          {meta ? <p className={styles.meta}>{meta}</p> : null}
        </div>
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  );
}
