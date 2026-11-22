// The sticky bar at the foot of Settings, shown while there are unsaved changes (web-ui.md §
// Settings, "Saving"): "Unsaved changes", then Discard and Save. It sticks to the bottom of the
// page panel, which scrolls.

import { useLayoutEffect } from 'react';
import { CircleDot } from 'lucide-react';
import { Button } from '@/components/ui-a';
import styles from './SaveBar.module.css';

export interface SaveBarProps {
  busy: boolean;
  onDiscard: () => void;
  onSave: () => void;
}

export function SaveBar({ busy, onDiscard, onSave }: SaveBarProps) {
  // The bar comes up over the panel's foot, where the control whose change brought it up may sit
  // (the browser doesn't scroll to a control already in view). Bring that control clear of it: the
  // panel keeps room for the bar when it scrolls (AppLayout.module.css, data-settings), so the bar
  // never covers the focused control (WCAG 2.4.11).
  useLayoutEffect(() => {
    const focused = document.activeElement;
    if (focused instanceof HTMLElement && focused !== document.body) focused.scrollIntoView({ block: 'nearest' });
  }, []);

  return (
    <div className={styles.bar} role="region" aria-label="Unsaved changes">
      <span className={styles.label}>
        <CircleDot size={18} aria-hidden />
        Unsaved changes
      </span>
      <div className={styles.actions}>
        <Button variant="tertiary" disabled={busy} onClick={onDiscard}>
          Discard
        </Button>
        <Button variant="primary" busy={busy} onClick={onSave}>
          Save
        </Button>
      </div>
    </div>
  );
}
