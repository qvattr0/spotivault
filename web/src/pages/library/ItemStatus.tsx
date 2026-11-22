// An item's status pill (web-ui.md § Item states): the words and colour from library-words.ts.

import type { LibraryItem } from '@/api';
import { Pill } from '@/components/ui-a';
import { statusView } from './library-words.ts';

export function ItemStatus({ item }: { item: LibraryItem }) {
  const view = statusView(item);
  return (
    <Pill tone={view.tone} icon={view.icon} to={view.to}>
      {view.label}
    </Pill>
  );
}
