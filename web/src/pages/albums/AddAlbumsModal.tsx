import { useMemo, useRef, useState } from 'react';
import { ListFilter } from 'lucide-react';
import { api, useApi, type SavedAlbum } from '@/api';
import { Alert, EmptyState, Modal } from '@/components/ui-b';
import { Button, SearchInput } from '@/components/ui-a';
import { errorText } from '@/lib/errors.ts';
import { filterSaved } from './album-data.ts';
import { AddAlbumRow } from './AddAlbumRow.tsx';
import styles from './AddAlbumsModal.module.css';

/**
 * The + modal, "Add albums" (web-ui.md § Albums, Add albums; L3CNc7). The saved albums not yet
 * added are loaded in full when it opens, so filtering by name is instant. Adding several is fine:
 * the modal stays open until Done. Only Done: an add can't be undone from here, so Cancel would
 * promise what it can't do.
 */
export function AddAlbumsModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [text, setText] = useState('');
  const saved = useApi((signal) => api.GET('/api/albums/saved', { signal }), []);
  const matches = useMemo(() => filterSaved(saved.data?.items ?? [], text), [saved.data, text]);
  const list = useRef<HTMLDivElement>(null);
  const filter = useRef<HTMLInputElement>(null);

  /** An added album leaves the list at once; the page behind reloads to show it as Queued. */
  function done(id: string, result: { added: boolean; hadFocus: boolean }) {
    // Its Add button is about to go: give focus to the next row's (or the one before, or the
    // filter), so Escape still reaches the dialog and a keyboard user can add the next one.
    if (result.hadFocus) {
      const buttons = Array.from(list.current?.querySelectorAll('button') ?? []);
      const at = buttons.findIndex((b) => b === document.activeElement);
      const next = buttons[at + 1] ?? buttons[at - 1];
      if (next) next.focus();
      else filter.current?.focus();
    }
    saved.setData((data) => ({ ...data, items: data.items.filter((album: SavedAlbum) => album.id !== id) }));
    if (result.added) onAdded();
  }

  return (
    <Modal
      open
      title="Add albums"
      onClose={onClose}
      width={600}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          Done
        </Button>
      }
    >
      <SearchInput
        size="lg"
        icon={ListFilter}
        className={styles.filter}
        label="Filter by album name"
        placeholder="Filter by album name"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onClear={() => setText('')}
        autoFocus
        ref={filter}
      />
      {saved.error ? <Alert tone="danger" title={errorText(saved.error)} /> : null}
      {saved.data ? (
        <>
          <p className={styles.heading}>Your saved albums · most recently saved first</p>
          {matches.length > 0 ? (
            <div className={styles.list} ref={list}>
              {matches.map((album) => (
                <AddAlbumRow key={album.id} album={album} onDone={done} />
              ))}
            </div>
          ) : text.trim() ? (
            <EmptyState title={`No saved album matches “${text.trim()}”`}>Try another name.</EmptyState>
          ) : (
            <EmptyState title="All your saved albums are already added">Save albums in Spotify first, then they show up here.</EmptyState>
          )}
        </>
      ) : null}
    </Modal>
  );
}
