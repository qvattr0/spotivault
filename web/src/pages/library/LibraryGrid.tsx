// The Grid view (web-ui.md § Grid view): cards in rows that fill the width.

import type { LibraryItem } from '@/api';
import { LibraryCard } from './LibraryCard.tsx';
import styles from './LibraryGrid.module.css';

export interface LibraryGridProps {
  items: LibraryItem[];
  onChanged: (item: LibraryItem) => void;
}

export function LibraryGrid({ items, onChanged }: LibraryGridProps) {
  return (
    <div className={styles.grid} role="list" aria-label="Library">
      {items.map((item) => (
        <div key={item.id} role="listitem" className={styles.cell}>
          <LibraryCard item={item} onChanged={onChanged} />
        </div>
      ))}
    </div>
  );
}
