// The List view (web-ui.md § List view): a table with a header row, one LibraryRow per item.

import { ListTable, PlaylistHeader } from '@/components/ui-b';
import type { LibraryItem } from '@/api';
import { LibraryRow } from './LibraryRow.tsx';

export interface LibraryListProps {
  items: LibraryItem[];
  now: number;
  onChanged: (item: LibraryItem) => void;
  onRemoved: () => void;
}

export function LibraryList({ items, now, onChanged, onRemoved }: LibraryListProps) {
  return (
    <ListTable label="Library" header={<PlaylistHeader />}>
      {items.map((item) => (
        <LibraryRow key={item.id} item={item} now={now} onChanged={onChanged} onRemoved={onRemoved} />
      ))}
    </ListTable>
  );
}
