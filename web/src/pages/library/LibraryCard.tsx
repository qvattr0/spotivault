// One item in the Grid view (web-ui.md § Grid view): a card with its corner badge (the tracking
// switch, with the run's progress ring) and the round Back up now button on hover.

import { useNavigate } from 'react-router';
import { PlayButton } from '@/components/ui-a';
import { Card } from '@/components/ui-b';
import type { LibraryItem } from '@/api';
import { useBackUp, useTracking } from './library-actions.ts';
import { ItemStatus } from './ItemStatus.tsx';
import { coverKindOf, ownerLine, progressOf } from './library-words.ts';

export interface LibraryCardProps {
  item: LibraryItem;
  onChanged: (item: LibraryItem) => void;
}

export function LibraryCard({ item, onChanged }: LibraryCardProps) {
  const navigate = useNavigate();
  const tracking = useTracking(item, onChanged);
  const backUp = useBackUp(item);

  return (
    <Card
      title={item.name}
      sub={ownerLine(item)}
      coverSrc={item.cover}
      kind={coverKindOf(item)}
      tracking={{ tracked: item.tracked, onChange: (tracked) => void tracking.run(tracked), progress: progressOf(item) }}
      status={<ItemStatus item={item} />}
      // Not disabled while busy, so keyboard focus stays; useAction ignores a second press.
      action={<PlayButton aria-busy={backUp.busy || undefined} onClick={() => void backUp.run()} />}
      onOpen={() => navigate(`/library/${item.id}`)}
    />
  );
}
