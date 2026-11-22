import { useRef } from 'react';
import { CircleAlert, Plus } from 'lucide-react';
import { api, type SavedAlbum } from '@/api';
import { Button } from '@/components/ui-a';
import { ItemRow, useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';

/** Why POST /api/albums skipped an album (its `skipped[].reason`), in the toast's words. */
const SKIPPED_WORDS: Record<'already_added' | 'not_saved' | 'not_found', (name: string) => string> = {
  already_added: (name) => `${name} was already added.`,
  not_saved: (name) => `${name} is no longer in your saved albums.`,
  not_found: (name) => `Spotify no longer has ${name}.`,
};

export interface AddAlbumRowProps {
  album: SavedAlbum;
  /**
   * The album leaves the list. `added`: it's on the page now (the page reloads). `hadFocus`: its
   * Add button had keyboard focus, so the modal moves focus on before the row goes.
   */
  onDone: (id: string, result: { added: boolean; hadFocus: boolean }) => void;
}

/**
 * One saved album in the + modal (L3CNc7): cover, name, artist · year · tracks, and Add. Adding
 * makes it Queued and it leaves the list; each row has its own busy state. An album the answer
 * skipped leaves the list too, with a toast saying why: it no longer belongs there.
 */
export function AddAlbumRow({ album, onDone }: AddAlbumRowProps) {
  const toast = useToast();
  const button = useRef<HTMLButtonElement>(null);
  const add = useAction((id: string) => api.POST('/api/albums', { body: { ids: [id] } }), {
    onDone: (data) => {
      const hadFocus = button.current !== null && button.current === document.activeElement;
      const skipped = data.skipped.find((entry) => entry.id === album.id);
      if (skipped) toast.show(SKIPPED_WORDS[skipped.reason](album.name), { icon: CircleAlert });
      onDone(album.id, { added: !skipped || skipped.reason === 'already_added', hadFocus });
    },
  });
  const sub = [album.artist, album.year === null ? null : String(album.year), `${album.total} tracks`].filter(Boolean).join(' · ');
  return (
    <ItemRow
      title={album.name}
      sub={sub}
      coverSrc={album.cover}
      kind="album"
      trailing={
        <Button
          ref={button}
          variant="secondary"
          icon={Plus}
          busy={add.busy}
          aria-label={`Add ${album.name}`}
          onClick={() => void add.run(album.id)}
        >
          Add
        </Button>
      }
    />
  );
}
