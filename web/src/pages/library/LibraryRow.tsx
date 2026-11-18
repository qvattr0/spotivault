// One item in the List view (components.md § List row, Row/Playlist): tracking switch, cover and
// name, the count, the last backup, the status pill, the ⋯ menu. A click opens the detail view.

import { useNavigate } from 'react-router';
import { PlayButton, Toggle } from '@/components/ui-a';
import { PlaylistRow } from '@/components/ui-b';
import { formatAgo } from '@/shell/format.ts';
import type { LibraryItem } from '@/api';
import { useBackUp, useTracking } from './library-actions.ts';
import { ItemMenu } from './ItemMenu.tsx';
import { ItemStatus } from './ItemStatus.tsx';
import { RecordedCount } from './RecordedCount.tsx';
import { coverKindOf, ownerLine } from './library-words.ts';

export interface LibraryRowProps {
  item: LibraryItem;
  /** The time, for "3 hours ago" (it ticks once a minute, in the page). */
  now: number;
  /** The item as the controller now has it, after a change of its own. */
  onChanged: (item: LibraryItem) => void;
  onRemoved: () => void;
}

export function LibraryRow({ item, now, onChanged, onRemoved }: LibraryRowProps) {
  const navigate = useNavigate();
  const tracking = useTracking(item, onChanged);
  const backUp = useBackUp(item);
  const recording = item.status === 'recording';

  return (
    <PlaylistRow
      name={item.name}
      owner={ownerLine(item)}
      coverSrc={item.cover}
      kind={coverKindOf(item)}
      tracks={<RecordedCount item={item} />}
      lastBackup={recording ? 'Now' : formatAgo(item.last_backup_at, now)}
      recording={recording}
      muted={!item.tracked}
      toggle={
        // Not disabled while its request runs: that would drop keyboard focus. useAction ignores
        // a second press meanwhile.
        <Toggle
          checked={item.tracked}
          label={`Track ${item.name}`}
          aria-busy={tracking.busy || undefined}
          onChange={(tracked) => void tracking.run(tracked)}
        />
      }
      status={<ItemStatus item={item} />}
      menu={<ItemMenu item={item} onRemoved={onRemoved} />}
      action={<PlayButton aria-busy={backUp.busy || undefined} onClick={() => void backUp.run()} />}
      onOpen={() => navigate(`/library/${item.id}`)}
    />
  );
}
