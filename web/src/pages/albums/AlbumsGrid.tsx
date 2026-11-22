import { useNavigate } from 'react-router';
import type { Album } from '@/api';
import { Card } from '@/components/ui-b';
import { AlbumStatusPill } from './AlbumStatusPill.tsx';
import { albumSub } from './album-words.ts';
import styles from './AlbumsPage.module.css';

/**
 * The grid view (web-ui.md § Grid view, MX2OU): a square cover, the name, the artist and year. The
 * status pill sits on the cover; recorded albums have none, so a page of them stays clean.
 */
export function AlbumsGrid({ albums }: { albums: Album[] }) {
  const navigate = useNavigate();
  return (
    <div className={styles.grid}>
      {albums.map((album) => (
        <Card
          key={album.id}
          title={album.name}
          sub={albumSub(album)}
          coverSrc={album.cover}
          kind="album"
          cornerStatus={album.status === 'recorded' ? undefined : <AlbumStatusPill status={album.status} onCover />}
          onOpen={() => navigate(`/albums/${album.id}`)}
        />
      ))}
    </div>
  );
}
