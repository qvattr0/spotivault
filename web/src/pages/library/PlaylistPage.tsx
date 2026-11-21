// /library/:id: a playlist's detail view (web-ui.md § Detail view), like a playlist page in the
// client: the header with the cover and the actions, then the track table. Owner: the library builder.
//
// There is no GET for one item, so the page reads the whole Library and finds it there. The track
// list comes from GET /api/library/{id}/tracks, and is read again as the item records.

import { useNavigate, useParams } from 'react-router';
import { api, useApi, type LibraryItem } from '@/api';
import { Button, ButtonLink } from '@/components/ui-a';
import { Alert, EmptyState, ListTable, TrackCheck, TrackHeader, TrackRow } from '@/components/ui-b';
import { DetailHeader } from '@/components/ui-c';
import { errorText } from '@/lib/errors.ts';
import { Page, formatLength } from '@/shell';
import { useLiveEvent } from '@/state';
import { ItemMenu } from './ItemMenu.tsx';
import { ItemStatus } from './ItemStatus.tsx';
import { useRemove, useTracking } from './library-actions.ts';
import { BackUpButton } from './BackUpButton.tsx';
import { coverKindOf, detailMeta, trackLength, trackView } from './library-words.ts';
import styles from './PlaylistPage.module.css';

export function PlaylistPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();

  const everything = useApi((signal) => api.GET('/api/library', { params: { query: { filter: 'all' } }, signal }), []);
  const tracks = useApi((signal) => api.GET('/api/library/{id}/tracks', { params: { path: { id } }, signal }), [id], {
    reloadOn: ['run.finished'],
  });

  const item = everything.data?.items.find((i) => i.id === id) ?? null;

  // The header's status moves with the item's live event; the track list is read again with it.
  useLiveEvent('library.item', (event) => {
    if (event.data.id !== id) return;
    everything.setData((data) => ({ items: data.items.map((i) => (i.id === id ? event.data : i)) }));
    tracks.reload();
  });

  // Patched in place after a change of the item's own (the tracking check, Stop tracking).
  function changed(next: LibraryItem) {
    everything.setData((data) => ({ items: data.items.map((i) => (i.id === next.id ? next : i)) }));
  }

  if (!item) {
    return (
      <Page tint="library-detail">
        {everything.error ? <Alert tone="danger" title={errorText(everything.error)} /> : null}
        {everything.data ? (
          <EmptyState title="This playlist isn't in the Library">
            It may have been removed. The list is at the Library.
          </EmptyState>
        ) : null}
        {everything.data ? <ButtonLink variant="secondary" to="/library">Back to Library</ButtonLink> : null}
        {!everything.data && !everything.error ? <p className={styles.note}>Loading…</p> : null}
      </Page>
    );
  }

  const durationMs = tracks.data?.duration_ms ?? null;
  return (
    <Page tint="library-detail">
      <DetailHeader
        backTo="/library"
        backLabel="Library"
        typeLabel="Playlist"
        title={item.name}
        meta={detailMeta(item, durationMs, formatLength)}
        coverSrc={item.cover}
        kind={coverKindOf(item)}
        actions={<HeaderActions item={item} onChanged={changed} onRemoved={() => navigate('/library')} />}
      />

      <section aria-label="Tracks" className={styles.tracks}>
        {tracks.data && !tracks.data.item_access ? (
          <Alert tone="info" title="Spotify doesn't share this playlist's track list with the app; tracks appear here as they're recorded." />
        ) : null}
        {tracks.error ? <Alert tone="danger" title={errorText(tracks.error)} /> : null}
        {!tracks.data && !tracks.error ? <p className={styles.note}>Loading…</p> : null}
        {tracks.data && tracks.data.tracks.length === 0 ? (
          <EmptyState title="No tracks recorded yet" />
        ) : null}
        {tracks.data && tracks.data.tracks.length > 0 ? (
          <ListTable label="Tracks" header={<TrackHeader />} dense>
            {tracks.data.tracks.map((track, i) => {
              const view = trackView(track);
              return (
                <TrackRow
                  key={`${i}-${track.track_id ?? track.title}`}
                  position={track.position}
                  title={track.title}
                  artist={track.artists.join(', ')}
                  album={track.album}
                  duration={trackLength(track)}
                  state={view.kind}
                  stateText={view.text}
                  stateHint={view.hint}
                />
              );
            })}
          </ListTable>
        ) : null}
      </section>

      <footer className={styles.footer}>
        <FooterAction item={item} onChanged={changed} onRemoved={() => navigate('/library')} />
        <span className={styles.note}>Files are never deleted.</span>
      </footer>
    </Page>
  );
}

/**
 * The header's row: Back up now (the large round button), the tracking check with its word (one
 * control), the status, ⋯. web-ui.md § Detail view's "tracking toggle" is the grid card's round check here.
 */
function HeaderActions({
  item,
  onChanged,
  onRemoved,
}: {
  item: LibraryItem;
  onChanged: (item: LibraryItem) => void;
  onRemoved: () => void;
}) {
  const tracking = useTracking(item, onChanged);
  return (
    <>
      {/* Neither is disabled while its request runs, so keyboard focus stays; useAction ignores a
          second press meanwhile. */}
      {/* Tooltips start at their control: centred, the first would reach past the page's left edge. */}
      <BackUpButton item={item} size="lg" align="start" />
      {/* The word is part of the check's button, so a click on it toggles too. */}
      <span className={styles.tracking}>
        <TrackCheck
          inline
          align="start"
          tracked={item.tracked}
          text={item.tracked ? 'Tracked' : 'Not tracked'}
          label={`Track ${item.name}`}
          aria-busy={tracking.busy || undefined}
          onChange={(tracked) => void tracking.run(tracked)}
        />
      </span>
      <ItemStatus item={item} />
      <ItemMenu item={item} onRemoved={onRemoved} />
    </>
  );
}

/** The footer's action: Remove from Library for an added item, Stop tracking for your own. */
function FooterAction({
  item,
  onChanged,
  onRemoved,
}: {
  item: LibraryItem;
  onChanged: (item: LibraryItem) => void;
  onRemoved: () => void;
}) {
  const remove = useRemove(item, onRemoved);
  const tracking = useTracking(item, onChanged);
  if (item.removable) {
    return (
      <Button variant="tertiary" busy={remove.busy} onClick={() => void remove.run()}>
        Remove from Library
      </Button>
    );
  }
  return (
    <Button variant="tertiary" disabled={!item.tracked} busy={tracking.busy} onClick={() => void tracking.run(false)}>
      Stop tracking
    </Button>
  );
}
