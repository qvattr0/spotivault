import { CircleMinus } from 'lucide-react';
import { api, type QueueItem } from '@/api';
import { MenuButton, Pill } from '@/components/ui-a';
import { ItemRow, type CoverKind } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { expectText } from './words.ts';
import styles from './Dashboard.module.css';

/**
 * An Up next row (web-ui.md § Queue; t4YEY): cover, name and what to expect ("84 new", "11 tracks",
 * "checking"), or the "Interrupted · will retry" pill. Its ⋯ menu has "Remove from this run".
 */
export function UpNextRow({ item }: { item: QueueItem }) {
  // The live store shows the result (run.queue): the row goes.
  const remove = useAction(() => api.DELETE('/api/runs/current/items/{id}', { params: { path: { id: item.item_id } } }), {
    errors: { not_found: "It isn't waiting in this run any more." },
  });

  return (
    <ItemRow
      title={item.name}
      coverSrc={item.cover}
      kind={coverKind(item.kind)}
      coverSize={36}
      small
      className={styles.upNextRow}
      trailing={
        <>
          <WhatToExpect item={item} />
          <MenuButton
            label={`Options for ${item.name}`}
            items={[{ label: 'Remove from this run', icon: CircleMinus, disabled: remove.busy, onSelect: () => void remove.run() }]}
          />
        </>
      }
    />
  );
}

function WhatToExpect({ item }: { item: QueueItem }) {
  if (item.state === 'interrupted') return <Pill tone="yellow">Interrupted · will retry</Pill>;
  // Cut off by the last window: it runs first in this one (web-ui.md § Queue, Carried over).
  if (item.badges.includes('carried_over_in')) {
    return (
      <>
        <Pill tone="neutral">Carried over</Pill>
        <span className={styles.expect}>{expectText(item)}</span>
      </>
    );
  }
  return <span className={styles.expect}>{expectText(item)}</span>;
}

function coverKind(kind: QueueItem['kind']): CoverKind {
  return kind === 'liked' ? 'liked' : kind === 'album' ? 'album' : 'playlist';
}
