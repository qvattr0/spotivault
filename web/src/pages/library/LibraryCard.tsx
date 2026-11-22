// One item in the Grid view (web-ui.md § Grid view): a card with its corner badge (the tracking
// check, with the run's progress ring) and the round Back up now button on hover.

import { useNavigate } from 'react-router';
import { Card } from '@/components/ui-b';
import type { LibraryItem } from '@/api';
import { useTracking } from './library-actions.ts';
import { BackUpButton } from './BackUpButton.tsx';
import { ItemStatus } from './ItemStatus.tsx';
import { coverKindOf, ownerLine, progressOf } from './library-words.ts';

export interface LibraryCardProps {
  item: LibraryItem;
  onChanged: (item: LibraryItem) => void;
}

export function LibraryCard({ item, onChanged }: LibraryCardProps) {
  const navigate = useNavigate();
  const tracking = useTracking(item, onChanged);

  return (
    <Card
      title={item.name}
      sub={ownerLine(item)}
      coverSrc={item.cover}
      kind={coverKindOf(item)}
      tracking={{
        tracked: item.tracked,
        onChange: (tracked) => void tracking.run(tracked),
        progress: progressOf(item),
        busy: tracking.busy,
      }}
      status={<ItemStatus item={item} />}
      action={<BackUpButton item={item} align="end" />}
      onOpen={() => navigate(`/library/${item.id}`)}
    />
  );
}
