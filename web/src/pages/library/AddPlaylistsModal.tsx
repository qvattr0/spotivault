// The + modal, "Add playlists" (web-ui.md § Add playlists): a search box that filters the
// playlists you follow, or takes a pasted link and previews it. Each Add tracks the playlist at
// once; the modal stays open so you can add several (Done closes it).

import { useRef, useState } from 'react';
import { Check, CircleAlert, Link, Plus, Search } from 'lucide-react';
import { api, useApi, type PlaylistPreview } from '@/api';
import { Button, SearchInput } from '@/components/ui-a';
import { Alert, EmptyState, ItemRow, Modal } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { errorText, type ErrorWording } from '@/lib/errors.ts';
import { useDebouncedValue, SEARCH_DELAY_MS } from '@/lib/list-query.ts';
import { useAddedSet } from './use-added-set.ts';
import styles from './AddPlaylistsModal.module.css';

/** A pasted Spotify link (https://… or spotify:…): it's previewed, not searched for. */
const LINK = /^(https?:\/\/|spotify:)/i;

/** The words for the codes a pasted link can fail with (web-ui.md § Add playlists). Spotify-made playlists have the standing note above, so no inline error. */
const LINK_WORDS: ErrorWording = {
  invalid_url: "That isn't a Spotify playlist link.",
  not_found: 'Spotify has no playlist at that link.',
  private: "That playlist is private, so it can't be added.",
  spotify_owned: "Playlists made by Spotify aren't available through the API, so they can't be added.",
};

export function AddPlaylistsModal({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState('');
  const query = useDebouncedValue(text.trim(), SEARCH_DELAY_MS);
  const link = LINK.test(query);
  const added = useAddedSet();

  // The suggestions are the followed playlists, filtered by the words typed. A link isn't a search.
  const search = link ? '' : query;
  const suggestions = useApi(
    (signal) => api.GET('/api/library/suggestions', { params: { query: search ? { q: search } : {} }, signal }),
    [search],
    { keepData: true },
  );

  return (
    <Modal
      open
      title="Add playlists"
      width={600}
      onClose={onClose}
      footer={
        <>
          <Button variant="tertiary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={onClose}>
            Done
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <SearchInput
          autoFocus
          size="lg"
          className={styles.field}
          icon={LINK.test(text.trim()) ? Link : Search}
          label="Search followed playlists or paste a Spotify link"
          placeholder="Search followed playlists or paste a Spotify link"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onClear={() => setText('')}
          spellCheck={false}
        />
        {link && query ? <LinkPreview url={query} added={added} /> : null}
        <p className={styles.standing}>
          <CircleAlert size={16} aria-hidden />
          Playlists made by Spotify (Discover Weekly, Daily Mixes) aren&apos;t available through the API, so they can&apos;t be added.
        </p>

        <section aria-labelledby="follow-heading" className={styles.section}>
          <h3 id="follow-heading" className={styles.heading}>
            Playlists you follow
          </h3>
          {suggestions.error && !suggestions.data ? <Alert tone="danger" title={errorText(suggestions.error)} /> : null}
          {!suggestions.data && !suggestions.error ? <p className={styles.note}>Loading…</p> : null}
          {suggestions.data && suggestions.data.items.length === 0 ? (
            <EmptyState title="Nothing to suggest">
              {search ? 'No followed playlist matches. Clear the search to see them all.' : 'Playlists you follow in Spotify show up here.'}
            </EmptyState>
          ) : null}
          {suggestions.data?.items.map((playlist) => (
            <SuggestionRow key={playlist.id} playlist={playlist} added={added} />
          ))}
        </section>
      </div>
    </Modal>
  );
}

/** A pasted link as a preview row (cover, name, owner) with Add, or the reason it can't be used. */
function LinkPreview({ url, added }: { url: string; added: ReturnType<typeof useAddedSet> }) {
  const preview = useApi((signal) => api.POST('/api/library/resolve', { body: { url }, signal }), [url]);

  if (preview.error) {
    return <Alert tone="danger" title={errorText(preview.error, LINK_WORDS)} />;
  }
  if (!preview.data) return <p className={styles.note}>Looking up the link…</p>;
  return <PlaylistAddRow playlist={preview.data} added={added} sub={`by ${preview.data.owner} · from link`} preview />;
}

/** One followed playlist from the suggestions: its name, owner, and Add. */
function SuggestionRow({ playlist, added }: { playlist: PlaylistPreview; added: ReturnType<typeof useAddedSet> }) {
  return <PlaylistAddRow playlist={playlist} added={added} sub={`by ${playlist.owner}`} />;
}

/** The shared row of the modal: Add tracks the playlist (POST /api/library), then it reads Added. */
function PlaylistAddRow({
  playlist,
  added,
  sub,
  preview = false,
}: {
  playlist: PlaylistPreview;
  added: ReturnType<typeof useAddedSet>;
  sub: string;
  /** The pasted link's row: in a box, with a 48 px cover (w06M4n). */
  preview?: boolean;
}) {
  const button = useRef<HTMLButtonElement>(null);
  // Whether focus goes to "Added" when it replaces the Add button that had it. Otherwise focus
  // would fall out of the dialog, and Escape would stop closing it.
  const [focusAdded, setFocusAdded] = useState(false);
  const add = useAction(() => api.POST('/api/library', { body: { url: playlist.uri } }), {
    onDone: () => {
      setFocusAdded(button.current !== null && button.current === document.activeElement);
      added.mark(playlist.id);
    },
  });
  const done = playlist.already_added || added.has(playlist.id);

  return (
    <ItemRow
      className={preview ? styles.preview : styles.suggestion}
      coverSize={preview ? 48 : 40}
      title={playlist.name}
      sub={sub}
      coverSrc={playlist.cover}
      trailing={
        done ? (
          // Focusable from code only, so a screen reader reads "Added" where the button was.
          <span className={styles.added} tabIndex={focusAdded ? -1 : undefined} ref={focusAdded ? focusOnMount : undefined}>
            <Check size={16} aria-hidden />
            Added
          </span>
        ) : (
          <Button
            ref={button}
            variant="secondary"
            icon={Plus}
            busy={add.busy}
            aria-label={`Add ${playlist.name}`}
            onClick={() => void add.run()}
          >
            Add
          </Button>
        )
      }
    />
  );
}

/** A ref that focuses its element once it's on the page. */
function focusOnMount(element: HTMLElement | null) {
  element?.focus();
}
