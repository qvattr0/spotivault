// "84 / 120 recorded" (web-ui.md § List view, Tracks). A followed playlist's total comes from
// Spotify's listing, not a track list, so it gets an info tooltip.

import { Info } from 'lucide-react';
import type { LibraryItem } from '@/api';
import { Tooltip } from '@/components/ui-b';
import { hasTotalTooltip, recordedText } from './library-words.ts';
import styles from './RecordedCount.module.css';

export function RecordedCount({ item }: { item: LibraryItem }) {
  const text = recordedText(item);
  if (!hasTotalTooltip(item)) return text;
  return (
    <Tooltip label="Spotify counts every track in this playlist, playable or not. The app can't see the track list, so it can't tell which ones play.">
      <span className={styles.counted} tabIndex={0}>
        {text}
        <Info size={14} aria-hidden />
      </span>
    </Tooltip>
  );
}
