import { ArrowDownToLine, ExternalLink, FolderOpen } from 'lucide-react';
import { useNavigate, useParams } from 'react-router';
import { api, useApi } from '@/api';
import { Button, ButtonLink, MenuButton, type MenuItem } from '@/components/ui-a';
import { Alert, EmptyState } from '@/components/ui-b';
import { DetailHeader } from '@/components/ui-c';
import { useLiveEvent } from '@/state';
import { errorText } from '@/lib/errors.ts';
import { Page, formatLength } from '@/shell';
import { openInSpotify, useAlbumActions } from './album-actions.ts';
import { replaceAlbum } from './album-data.ts';
import { AlbumStatusPill } from './AlbumStatusPill.tsx';
import { AlbumTracks } from './AlbumTracks.tsx';
import styles from './AlbumPage.module.css';

/**
 * /albums/:id: an album's detail view (web-ui.md § Albums, Detail view). Not drawn: it's Library's
 * detail layout (l9Wn7L), with DetailHeader. The contract has no GET for one album, so the page
 * reads the added albums and finds its own.
 */
export function AlbumPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const albums = useApi((signal) => api.GET('/api/albums', { signal }), [], { reloadOn: ['run.finished'] });
  const tracks = useApi((signal) => api.GET('/api/albums/{id}/tracks', { params: { path: { id } }, signal }), [id], {
    reloadOn: ['run.finished'],
  });
  const actions = useAlbumActions(() => navigate('/albums'));

  // The header moves with the album's live event; the track table is read again with it, as the
  // Library's detail does (album.item comes at most once a second per album while it records).
  useLiveEvent('album.item', (event) => {
    albums.setData((data) => replaceAlbum(data, event.data));
    if (event.data.id === id) tracks.reload();
  });

  const album = albums.data?.items.find((item) => item.id === id);

  if (albums.data && !album) {
    return (
      <Page tint="albums">
        <EmptyState title={errorText({ code: 'not_found' })} action={<ButtonLink variant="secondary" to="/albums">Back to Albums</ButtonLink>} />
      </Page>
    );
  }
  if (!album) {
    return <Page tint="albums">{albums.error ? <Alert tone="danger" title={errorText(albums.error)} /> : null}</Page>;
  }

  const length = tracks.data?.duration_ms;
  const meta = [
    album.artist,
    album.year === null ? null : String(album.year),
    `${album.total} tracks`,
    length === null || length === undefined ? null : formatLength(length),
    `${album.recorded} recorded`,
  ]
    .filter(Boolean)
    .join(' · ');

  const menu: MenuItem[] = [
    { label: 'Open in Spotify', icon: ExternalLink, onSelect: () => openInSpotify(album) },
    { label: 'Show files path', icon: FolderOpen, onSelect: () => void actions.files.run(album.id) },
  ];

  return (
    <Page tint="albums">
      <DetailHeader
        backTo="/albums"
        backLabel="Albums"
        typeLabel="Album"
        title={album.name}
        meta={meta}
        coverSrc={album.cover}
        kind="album"
        actions={
          <>
            <Button variant="primary" icon={ArrowDownToLine} busy={actions.record.busy} onClick={() => void actions.record.run(album.id)}>
              Record now
            </Button>
            <AlbumStatusPill status={album.status} />
            <MenuButton label={`More for ${album.name}`} items={menu} />
          </>
        }
      />

      {tracks.error && !tracks.data ? <Alert tone="danger" title={errorText(tracks.error)} /> : null}
      {tracks.data ? <AlbumTracks list={tracks.data} /> : null}

      <footer className={styles.footer}>
        <Button variant="tertiary" onClick={() => void actions.remove.run(album.id)} busy={actions.remove.busy}>
          Remove from Albums
        </Button>
        <span className={`type-small ${styles.note}`}>Files are never deleted.</span>
      </footer>
    </Page>
  );
}
