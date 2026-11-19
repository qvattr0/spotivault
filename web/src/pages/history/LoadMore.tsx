// The older runs, loaded as you scroll (web-ui.md § Runs tab). The sentinel under the list asks for
// the next page when it comes into view; the button does the same for keyboard and screen-reader
// users, and for browsers with no IntersectionObserver. Nothing shows when there are no more pages.

import { useEffect, useEffectEvent, useRef } from 'react';
import { Button } from '@/components/ui-a';
import styles from './RunsPage.module.css';

interface LoadMoreProps {
  /** The next page's cursor, or null when the list is complete. */
  cursor: string | null;
  busy: boolean;
  onLoad: () => void;
}

export function LoadMore({ cursor, busy, onLoad }: LoadMoreProps) {
  const sentinel = useRef<HTMLDivElement>(null);
  // An effect event: the observer keeps the latest onLoad without being set up again each render.
  const loadNext = useEffectEvent(() => onLoad());
  const more = cursor !== null;

  useEffect(() => {
    const node = sentinel.current;
    if (!more || !node || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadNext();
      },
      { rootMargin: '240px 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [more]);

  if (!more) return null;
  return (
    <div ref={sentinel} className={styles.more}>
      <Button variant="secondary" busy={busy} onClick={onLoad}>
        Load older runs
      </Button>
    </div>
  );
}
